"""XuanwuAI Gateway — FastAPI application entry point."""

import asyncio
import json
import logging
import os
import platform
import re
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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

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
    try:
        llm_engine = LLMEngine(
            model=saved.get("model", "gpt-4o"),
            api_key=saved.get("api_key"),
            base_url=saved.get("base_url"),
            thinking_enabled=saved.get("thinking_enabled", False),
        )
        agent = AgentLoop(llm_engine, hub)
    except Exception as e:
        logger.warning(f"LLM engine not available (no API key configured): {e}")
        llm_engine = None
        agent = None
    memory = SessionMemory()

    # Expose singletons via app.state for router access
    app.state.hub = hub
    app.state.llm_engine = llm_engine
    app.state.agent = agent
    app.state.memory = memory
    app.state.unity_process = None
    app.state.unity_monitor_task = None
    app.state.unity_restart_backoff = 0
    app.state.unity_auto_restart = True
    app.state.blender_process = None
    app.state.blender_monitor_task = None
    app.state.blender_restart_backoff = 0
    app.state.blender_auto_restart = True

    # Register all routers
    for router in _all_routers:
        app.include_router(router)

    if saved.get("api_key"):
        logger.info(f"Gateway ready — LLM config restored (model={saved.get('model')})")
    else:
        logger.info("Gateway ready — no saved LLM config, configure via /settings/llm")

    # Auto-launch Unity if installed and not running
    if not _detect_running_unity():
        try:
            from routers.unity import _find_unity_exe, _init_unity_project_dir, UNITY_PROJECT_DIR
            _init_unity_project_dir()
            unity_exe = _find_unity_exe()
            if unity_exe and UNITY_PROJECT_DIR:
                import os as _os
                import subprocess as _sp
                flag_path = _os.path.join(UNITY_PROJECT_DIR, "auto_play.flag")
                with open(flag_path, "w") as f:
                    f.write("1")
                proc = _sp.Popen(
                    [unity_exe, "-projectPath", UNITY_PROJECT_DIR],
                    stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                )
                app.state.unity_process = proc
                logger.info(f"Auto-launched Unity (PID {proc.pid})")
        except Exception as e:
            logger.warning(f"Auto-launch Unity failed: {e}")

    # Auto-launch Blender if installed and not running
    def _port_open(port: int) -> bool:
        import socket as _sock
        try:
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.settimeout(1.0)
            r = s.connect_ex(("127.0.0.1", port)) == 0
            s.close()
            return r
        except Exception:
            return False

    if not _port_open(5007):
        try:
            from routers.blender import _build_frame_server_cmd
            cmd = _build_frame_server_cmd()
            if cmd:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
                app.state.blender_process = proc
                logger.info(f"Auto-launched Blender (PID {proc.pid})")
        except Exception as e:
            logger.warning(f"Auto-launch Blender failed: {e}")

    # Start Unity process health monitor
    async def _monitor_unity():
        while True:
            await asyncio.sleep(10)
            try:
                proc = app.state.unity_process
                if proc is None:
                    app.state.unity_restart_backoff = 0
                    continue

                if proc.poll() is not None:
                    exit_code = proc.returncode
                    logger.warning(f"Unity process exited (code={exit_code})")
                    app.state.unity_process = None

                    if not app.state.unity_auto_restart:
                        continue

                    backoff = app.state.unity_restart_backoff
                    if backoff > 5:
                        logger.error("Unity restart backoff limit reached — giving up")
                        continue

                    delay = min(10 * (2 ** backoff), 300)
                    app.state.unity_restart_backoff = backoff + 1
                    logger.info(f"Restarting Unity in {delay}s (attempt {backoff + 1})")
                    await asyncio.sleep(delay)

                    from routers.unity import _find_unity_exe, _init_unity_project_dir, UNITY_PROJECT_DIR
                    _init_unity_project_dir()
                    unity_exe = _find_unity_exe()
                    if unity_exe and UNITY_PROJECT_DIR:
                        import os as _os
                        import subprocess as _sp
                        flag_path = _os.path.join(UNITY_PROJECT_DIR, "auto_play.flag")
                        with open(flag_path, "w") as f:
                            f.write("1")
                        proc = _sp.Popen(
                            [unity_exe, "-projectPath", UNITY_PROJECT_DIR],
                            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                        )
                        app.state.unity_process = proc
                        logger.info(f"Auto-restarted Unity (PID {proc.pid})")
            except Exception as e:
                logger.warning(f"Unity monitor error: {e}")

    monitor_task = asyncio.create_task(_monitor_unity())
    app.state.unity_monitor_task = monitor_task

    # Start Blender process health monitor
    async def _monitor_blender():
        _consecutive_dead = 0
        while True:
            await asyncio.sleep(10)
            try:
                proc = app.state.blender_process
                port_alive = _port_open(5007)

                if port_alive:
                    _consecutive_dead = 0
                    if proc is None:
                        app.state.blender_restart_backoff = 0
                    continue

                if proc is not None and proc.poll() is None:
                    _consecutive_dead += 1
                    if _consecutive_dead < 3:
                        continue
                    logger.warning("Blender process alive but TCP dead for 30s — killing stale process")
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    app.state.blender_process = None
                else:
                    _consecutive_dead += 1
                    app.state.blender_process = None

                if not app.state.blender_auto_restart:
                    _consecutive_dead = 0
                    continue

                backoff = app.state.blender_restart_backoff
                if backoff > 5:
                    if _consecutive_dead < 10:
                        continue
                    logger.error("Blender restart backoff limit reached — giving up")
                    continue

                delay = min(10 * (2 ** backoff), 300)
                app.state.blender_restart_backoff = backoff + 1
                logger.info(f"Restarting Blender in {delay}s (attempt {backoff + 1})")
                await asyncio.sleep(delay)

                if _port_open(5007):
                    logger.info("Blender already running on port 5007 — skipping restart")
                    app.state.blender_restart_backoff = 0
                    _consecutive_dead = 0
                    continue

                from routers.blender import _build_frame_server_cmd
                cmd = _build_frame_server_cmd()
                if cmd:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                    )
                    app.state.blender_process = proc
                    _consecutive_dead = 0
                    logger.info(f"Auto-restarted Blender (PID {proc.pid})")
            except Exception as e:
                logger.warning(f"Blender monitor error: {e}")

    blender_monitor_task = asyncio.create_task(_monitor_blender())
    app.state.blender_monitor_task = blender_monitor_task

    yield
    logger.info("Shutting down...")
    app.state.unity_auto_restart = False
    app.state.blender_auto_restart = False
    if app.state.unity_monitor_task:
        app.state.unity_monitor_task.cancel()
    if app.state.blender_monitor_task:
        app.state.blender_monitor_task.cancel()
    unity_proc = app.state.unity_process
    if unity_proc and unity_proc.poll() is None:
        logger.info("Terminating Unity process...")
        unity_proc.terminate()
        try:
            unity_proc.wait(timeout=5)
        except Exception:
            unity_proc.kill()
    blender_proc = app.state.blender_process
    if blender_proc and blender_proc.poll() is None:
        logger.info("Terminating Blender process...")
        blender_proc.terminate()
        try:
            blender_proc.wait(timeout=5)
        except Exception:
            blender_proc.kill()
    if hub:
        await hub.stop_all()
    logger.info("Gateway stopped")


app = FastAPI(title="XuanwuAI Gateway", version="0.2.4", lifespan=lifespan)

# ── Pure-ASGI middleware (avoids Starlette BaseHTTPMiddleware's collapsing
# task group, which conflicts with long-running MCP tool calls and crashes
# with "Attempted to exit a cancel scope ..." on slow tools like Blender). ──


class _CORSPureMiddleware:
    """CORS replacement implemented as pure ASGI."""

    def __init__(self, app, allow_origins=None, allow_credentials=True,
                 allow_methods=None, allow_headers=None):
        self.app = app
        self.allow_origins = allow_origins or ["*"]
        self.allow_credentials = allow_credentials
        self.allow_methods = allow_methods or ["*"]
        self.allow_headers = allow_headers or ["*"]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        origin = next((v.decode("latin-1") for k, v in headers if k == b"origin"), None)
        # Preflight request
        if scope["method"] == "OPTIONS" and origin and any(
            k == b"access-control-request-method" for k, _ in headers
        ):
            resp_headers = [
                (b"access-control-allow-origin", origin.encode("latin-1")),
                (b"access-control-allow-methods", ", ".join(self.allow_methods).encode()),
                (b"access-control-allow-headers", ", ".join(self.allow_headers).encode()),
                (b"access-control-max-age", b"600"),
                (b"content-length", b"0"),
            ]
            if self.allow_credentials:
                resp_headers.append((b"access-control-allow-credentials", b"true"))
            await send({"type": "http.response.start", "status": 200, "headers": resp_headers})
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and origin:
                if self.allow_origins == ["*"] or origin in self.allow_origins:
                    new_headers = list(message.get("headers", []))
                    if not any(k == b"access-control-allow-origin" for k, _ in new_headers):
                        new_headers.append((b"access-control-allow-origin", origin.encode("latin-1")))
                        if self.allow_credentials:
                            new_headers.append((b"access-control-allow-credentials", b"true"))
                    message["headers"] = new_headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class _BodySizeLimitPureMiddleware:
    """Request body size limit (10 MB) as pure ASGI."""

    MAX_BODY = 10 * 1024 * 1024

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            cl = next((int(v) for k, v in scope.get("headers", []) if k == b"content-length"), 0)
            if cl > self.MAX_BODY:
                body = b'{"detail": "Request body too large"}'
                await send({
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                })
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


app.add_middleware(
    _CORSPureMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(_BodySizeLimitPureMiddleware)

# ── Serve exported IFC files (from bim_model_server) ─────────────────────
_exports_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "caiao_servers", "exports")
os.makedirs(_exports_dir, exist_ok=True)
app.mount("/exports", StaticFiles(directory=_exports_dir), name="exports")

# ── All REST endpoints are defined in gateway/routers/ ────────────────────
# Routers are registered in lifespan() via app.include_router().
# Pipeline helpers are in gateway/services/pipeline_service.py.
# WebSocket handler + pipeline execution remain below.


@app.get("/health")
async def health():
    return {"status": "ok"}


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

    async def _run_agent(user_message: str, memory_context: str, analysis_mode: str = "analysis") -> None:
        """Run the agent loop as a background task, sending steps to frontend."""
        nonlocal history
        try:
            final_content = ""
            new_history: list[dict[str, Any]] = []
            async for step in agent.run(user_message, history, memory_context, analysis_mode):
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
                analysis_mode = msg.get("analysisMode", "analysis")
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

                    if analysis_mode == "simulation":
                        user_message = (
                            "[Simulation mode is active: ONLY Abaqus tools are available. "
                            "Abaqus is a heavy FEM package and may not be installed, so launch it "
                            "ONLY when the user explicitly requests simulation / collapse analysis "
                            "(e.g. 仿真/倒塌模拟/collapse/FEM); otherwise answer directly without "
                            "calling any Abaqus tool.] " + user_message
                        )

                    agent_task = asyncio.create_task(_run_agent(user_message, memory_context, analysis_mode))
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


def _ps_run(script: str, capture: bool = False) -> str:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=capture, text=True, timeout=30,
        )
        return result.stdout.strip() if capture else ""
    except Exception:
        return ""


def _startup_self_heal() -> None:
    # NOTE: Do NOT kill watchdog.py processes here — that previously ended up
    # killing this gateway's own parent watchdog (taskkill /F /T kills the
    # whole tree), which made the gateway unable to start under the watchdog.
    # Port cleanup below is sufficient for stale-instance conflicts.
    killed = _ps_run(
        "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue "
        "| ForEach-Object { $_.OwningProcess; taskkill /F /T /PID $_.OwningProcess 2>$null }",
        capture=True,
    )
    if killed:
        print("[startup] killed stale process on port 8000")
    else:
        print("[startup] port 8000 free")


if __name__ == "__main__":
    import uvicorn
    _startup_self_heal()
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False,
                ws_ping_interval=25, ws_ping_timeout=10)
