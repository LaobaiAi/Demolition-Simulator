"""XuanwuAI Gateway — FastAPI application entry point."""

import asyncio
import json
import logging
import os
import platform
import subprocess
from contextlib import asynccontextmanager
from typing import Any

# ---------------------------------------------------------------------------
# Monkey-patch json.dumps to silently convert non-serializable objects
# (TextContent, etc.) into strings.  Must run before anything that calls
# json.dumps, including FastAPI's websocket.send_json.
# ---------------------------------------------------------------------------
_original_dumps = json.dumps


def _patched_dumps(obj: Any, **kwargs: Any) -> str:
    def _walk(o: Any) -> Any:
        if o is None or isinstance(o, (bool, int, float, str)):
            return o
        if isinstance(o, (list, tuple)):
            return [_walk(i) for i in o]
        if isinstance(o, dict):
            return {str(k): _walk(v) for k, v in o.items()}
        if hasattr(o, "text"):
            return str(o.text)
        if hasattr(o, "model_dump"):
            return _walk(o.model_dump())
        return str(o)

    return _original_dumps(_walk(obj), **kwargs)


json.dumps = _patched_dumps

# ---------------------------------------------------------------------------

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from caiao import CAIAOClientHub
from llm_engine import LLMEngine
from agent_loop import AgentLoop
from memory import SessionMemory
from routers import routers as _all_routers
from services.pipeline_executor import execute_pipeline_streaming

# LLM config persistence file (survives gateway restarts)
LLM_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm_config.json")


def _load_llm_config() -> dict[str, Any]:
    try:
        if os.path.exists(LLM_CONFIG_FILE):
            with open(LLM_CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_llm_config(config: dict[str, Any]) -> None:
    try:
        with open(LLM_CONFIG_FILE, "w") as f:
            json.dump(config, f)
    except Exception as e:
        logger.warning(f"Failed to save LLM config: {e}")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")
logger.info("JSON monkey-patch applied — all json.dumps calls are now TextContent-safe")


from caiao_config import discover_server_configs

SERVER_CONFIGS = discover_server_configs()

hub: CAIAOClientHub | None = None
agent: AgentLoop | None = None
memory: SessionMemory | None = None
llm_engine: LLMEngine | None = None
_unity_process: subprocess.Popen | None = None


def _detect_running_unity() -> bool:
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        result = sock.connect_ex(("127.0.0.1", 5005))
        sock.close()
        if result == 0:
            logger.info("Detected running Unity instance on port 5005.")
            return True
    except Exception:
        pass
    return False



def _system_load_checker() -> float:
    if platform.system() == "Linux" and os.path.exists("/proc/loadavg"):
        with open("/proc/loadavg") as f:
            return float(f.read().split()[0])
    try:
        import psutil
        cpu_pct = psutil.cpu_percent(interval=0.1) / 100.0
        mem_pct = psutil.virtual_memory().percent / 100.0
        return max(cpu_pct, mem_pct)
    except Exception:
        try:
            return 1.0 / (os.cpu_count() or 4)
        except Exception:
            return 0.5


_TRIM_BLACKLIST = {
    "chain_rounds", "animation_sequence", "body_states", "keyframes",
    "steps", "nodes", "elements", "element_forces",
}


# --- No local tool handlers needed — composite pipelines are auto-registered
# via SERVER_CONFIGS composite entries. See caiao.CAIAOClientHub.


@asynccontextmanager
async def lifespan(app: FastAPI):
    global hub, agent, memory, llm_engine
    logger.info("Starting CAIAO servers...")
    hub = CAIAOClientHub(
        SERVER_CONFIGS,
        trim_field_blacklist=_TRIM_BLACKLIST,
        load_checker=_system_load_checker,
    )
    await hub.start_all()
    saved = _load_llm_config()
    llm_engine = LLMEngine(
        model=saved.get("model", "gpt-4o"),
        api_key=saved.get("api_key"),
        base_url=saved.get("base_url"),
    )
    agent = AgentLoop(llm_engine, hub)
    memory = SessionMemory()

    # Expose singletons via app.state for router access
    app.state.hub = hub
    app.state.llm_engine = llm_engine
    app.state.agent = agent
    app.state.memory = memory
    app.state.unity_process = None
    app.state.webrtc_offer = None
    app.state.webrtc_answer = None

    # Register all routers
    for router in _all_routers:
        app.include_router(router)

    if saved.get("api_key"):
        logger.info(f"Gateway ready — LLM config restored (model={saved.get('model')})")
    else:
        logger.info("Gateway ready — no saved LLM config, configure via /settings/llm")

    _detect_running_unity()
    yield
    logger.info("Shutting down...")
    unity_proc = app.state.unity_process
    if unity_proc and unity_proc.poll() is None:
        logger.info("Terminating Unity process...")
        unity_proc.terminate()
        try:
            unity_proc.wait(timeout=5)
        except Exception:
            unity_proc.kill()
    if hub:
        await hub.stop_all()
    logger.info("Gateway stopped")


app = FastAPI(title="XuanwuAI Gateway", version="0.2.4", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request body size limit (10 MB) ───────────────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse as _JSONResponse


class _BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        cl = request.headers.get("content-length")
        if cl and int(cl) > 10 * 1024 * 1024:
            return _JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)


app.add_middleware(_BodySizeLimitMiddleware)

# ── All REST endpoints are defined in gateway/routers/ ────────────────────
# Routers are registered in lifespan() via app.include_router().
# Pipeline helpers are in gateway/services/pipeline_service.py.
# WebSocket handler + pipeline execution remain below.


# --- WebSocket for Chat ---

@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()

    async def _safe_send(data: dict[str, Any]) -> None:
        try:
            await websocket.send_json(data)
        except Exception:
            pass  # connection likely lost

    # Heartbeat task — keeps connection alive during long LLM silences
    async def _heartbeat():
        try:
            while True:
                await asyncio.sleep(15)
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    heartbeat_task = asyncio.create_task(_heartbeat())

    history: list[dict[str, Any]] = []
    agent_task: asyncio.Task | None = None

    async def _run_agent(user_message: str, memory_context: str) -> None:
        """Run the agent loop as a background task, sending steps to frontend."""
        nonlocal history
        try:
            final_content = ""
            new_history: list[dict[str, Any]] = []
            async for step in agent.run(user_message, history, memory_context):
                if step["type"] == "history":
                    new_history = step["messages"]
                    continue
                await _safe_send(step)
                if step["type"] == "response":
                    final_content = step["content"]

            if new_history:
                history = new_history
            else:
                history.append({"role": "user", "content": user_message})
                if final_content:
                    history.append({"role": "assistant", "content": final_content})

            if memory:
                memory.add(f"User: {user_message}")
                if final_content:
                    memory.add(f"Assistant: {final_content}")

            if len(history) > 20:
                history = history[-20:]
            while history and history[0].get("role") == "tool":
                history.pop(0)

        except asyncio.CancelledError:
            await _safe_send({
                "type": "response",
                "content": "Task cancelled by user.",
                "cancelled": True,
            })
        except Exception as e:
            logger.exception("Agent loop error")
            await _safe_send({
                "type": "error",
                "content": f"Agent error: {e}",
            })

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "message")

            if msg_type == "message":
                user_message = msg.get("content", "").strip()
                if not user_message:
                    continue

                await _safe_send({
                    "type": "user_echo",
                    "content": user_message,
                })

                if agent and hub:
                    memory_context = ""
                    if memory:
                        memory_context = memory.get_memory_context(user_message)
                        if memory_context:
                            await _safe_send({
                                "type": "memory",
                                "content": memory_context,
                            })

                    agent.reset_signals()
                    if agent_task and not agent_task.done():
                        agent.cancel()
                        agent_task.cancel()
                        try:
                            await agent_task
                        except asyncio.CancelledError:
                            pass

                    agent_task = asyncio.create_task(_run_agent(user_message, memory_context))
                else:
                    await _safe_send({
                        "type": "response",
                        "content": "Agent not initialized. Check server configuration.",
                    })

            elif msg_type == "cancel":
                if agent:
                    agent.cancel()
                if agent_task and not agent_task.done():
                    agent_task.cancel()
                    try:
                        await agent_task
                    except asyncio.CancelledError:
                        pass
                    agent_task = None

            elif msg_type == "pause":
                if agent:
                    agent.pause()
                await _safe_send({"type": "status", "content": "paused"})

            elif msg_type == "resume":
                if agent:
                    agent.resume()
                await _safe_send({"type": "status", "content": "resumed"})

            elif msg_type == "tool_call" and hub:
                tool_name = msg.get("tool_name", "")
                arguments = msg.get("arguments", {})
                result = await hub.call_tool(tool_name, arguments)
                await _safe_send({
                    "type": "tool_result",
                    "tool": tool_name,
                    "result": result,
                })

            elif msg_type == "launch_pipeline":
                pipeline_name = msg.get("pipeline", "visual_demolition")
                mode = msg.get("params", {}).get("mode", "mechanics")
                params = msg.get("params", {})

                try:
                    async for event in execute_pipeline_streaming(
                        hub,
                        pipeline_name=pipeline_name,
                        mode=mode,
                        structure=params.get("structure"),
                        strategy=params.get("strategy", "top_down"),
                        effects_preset=params.get("effects_preset", "standard"),
                        speed=params.get("speed", 1.0),
                        structure_params=params.get("structure_params", {}),
                    ):
                        await _safe_send(event)
                except Exception as e:
                    logger.exception("Pipeline execution error")
                    await _safe_send({
                        "type": "pipeline_error",
                        "content": f"Pipeline execution error: {e}",
                    })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.exception("WebSocket error")
    finally:
        if agent_task and not agent_task.done():
            agent.cancel() if agent else None
            agent_task.cancel()
        heartbeat_task.cancel()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False,
                ws_ping_interval=25, ws_ping_timeout=10)
