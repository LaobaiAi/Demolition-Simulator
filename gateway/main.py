"""XuanwuAI Gateway — FastAPI application entry point."""

import asyncio
import json
import logging
import os
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
from pydantic import BaseModel

from mcp_hub import MCPClientHub
from llm_engine import LLMEngine
from agent_loop import AgentLoop
from memory import SessionMemory

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


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert non-JSON-serializable objects to safe primitives."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    # Anything else (TextContent, objects, etc.) → string representation
    try:
        if hasattr(obj, "text"):
            return str(obj.text)
    except Exception:
        pass
    return str(obj)

# --- MCP Server configurations ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MCP_SERVERS_DIR = os.path.join(os.path.dirname(BASE_DIR), "mcp_servers")
VENV_PYTHON = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")

SERVER_CONFIGS = [
    {
        "name": "anastruct_server",
        "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
        "args": [os.path.join(MCP_SERVERS_DIR, "anastruct_server", "server.py")],
        "cwd": os.path.join(MCP_SERVERS_DIR, "anastruct_server"),
    },
    {
        "name": "opensees_server",
        "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
        "args": ["server.py"],
        "cwd": os.path.join(MCP_SERVERS_DIR, "opensees_server"),
    },
    {
        "name": "unity_simulator",
        "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
        "args": ["server.py"],
        "cwd": os.path.join(MCP_SERVERS_DIR, "unity_simulator"),
    },
]

hub: MCPClientHub | None = None
agent: AgentLoop | None = None
memory: SessionMemory | None = None
llm_engine: LLMEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global hub, agent, memory, llm_engine
    logger.info("Starting MCP servers...")
    hub = MCPClientHub(SERVER_CONFIGS)
    await hub.start_all()
    saved = _load_llm_config()
    llm_engine = LLMEngine(
        model=saved.get("model", "gpt-4o"),
        api_key=saved.get("api_key"),
        base_url=saved.get("base_url"),
    )
    agent = AgentLoop(llm_engine, hub)
    memory = SessionMemory()
    if saved.get("api_key"):
        logger.info(f"Gateway ready — LLM config restored (model={saved.get('model')})")
    else:
        logger.info("Gateway ready — no saved LLM config, configure via /settings/llm")
    yield
    logger.info("Shutting down MCP servers...")
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


# --- REST Endpoints ---

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/tools")
async def list_tools():
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    tools = await hub.list_tools()
    return {"tools": tools}


class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any]


@app.post("/tools/call")
async def call_tool(req: ToolCallRequest):
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    result = await hub.call_tool(req.tool_name, req.arguments)
    return result


class VerifyRequest(BaseModel):
    fast_result: dict[str, Any]  # anaStruct analysis result
    structure: dict[str, Any] | None = None  # optional: frame structure for OpenSees comparison


@app.post("/verify")
async def verify_analysis(req: VerifyRequest):
    """Compare fast analysis with high-fidelity OpenSees analysis.

    If structure is provided and OpenSees is available, runs real comparison.
    Otherwise returns a clear status indicating high-fidelity is not available.
    """
    fast = req.fast_result
    max_disp_fast = fast.get("max_displacement", 0)
    max_axial_fast = fast.get("max_axial_force", 0)

    # Attempt high-fidelity comparison if structure is provided
    if hub and req.structure:
        try:
            logger.info("Running high-fidelity verification with OpenSees...")
            hf_result = await hub.call_tool("high_fidelity_analysis", {"structure": req.structure})
            logger.info(f"OpenSees raw result: {str(hf_result)[:200]}")
            if hf_result and "result" in hf_result:
                import json
                result_str = hf_result["result"]
                hf_data = json.loads(result_str) if isinstance(result_str, str) else result_str
                if "error" in hf_data:
                    logger.warning(f"OpenSees analysis error: {hf_data['error']}")
                else:
                    max_disp_hf = hf_data.get("max_displacement", 0)
                    max_axial_hf = hf_data.get("max_axial_force", 0)
                    disp_diff = abs(max_disp_fast - max_disp_hf) / max(max_disp_fast, 1e-12) * 100
                    axial_diff = abs(max_axial_fast - max_axial_hf) / max(max_axial_fast, 1e-12) * 100
                    status = "verified" if max(disp_diff, axial_diff) < 5.0 else "warning"
                    logger.info(f"OpenSees comparison: disp_diff={disp_diff:.1f}%, axial_diff={axial_diff:.1f}%, status={status}")
                    return {
                        "status": status,
                        "demo_mode": False,
                        "comparison": {
                            "max_displacement": {"fast": round(max_disp_fast, 10), "high_fidelity": round(max_disp_hf, 10), "diff_percent": round(disp_diff, 2)},
                            "max_axial_force": {"fast": round(max_axial_fast, 2), "high_fidelity": round(max_axial_hf, 2), "diff_percent": round(axial_diff, 2)},
                        },
                    }
        except Exception as e:
            logger.exception(f"High-fidelity verification failed: {e}")

    return {
        "status": "unavailable",
        "demo_mode": True,
        "comparison": {
            "max_displacement": {"fast": round(max_disp_fast, 10), "high_fidelity": 0, "diff_percent": 0},
            "max_axial_force": {"fast": round(max_axial_fast, 2), "high_fidelity": 0, "diff_percent": 0},
        },
        "message": "High-fidelity verification (OpenSees) is not available on this platform. The fast analysis values above are computed by anaStruct linear elastic solver.",
    }


class LLMSettingsRequest(BaseModel):
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None


@app.post("/settings/llm")
async def configure_llm(req: LLMSettingsRequest):
    """Update LLM configuration at runtime from the frontend."""
    global llm_engine, memory
    if llm_engine is None:
        return JSONResponse({"status": "error", "message": "LLM engine not initialized"}, status_code=503)
    llm_engine.configure(
        model=req.model,
        api_key=req.api_key,
        base_url=req.base_url,
    )
    # Persist config to survive gateway restarts
    _save_llm_config({
        "model": llm_engine.model,
        "api_key": llm_engine.api_key,
        "base_url": llm_engine.base_url,
    })
    # Also set env vars for mem0 and try to reinitialize memory
    if memory and (req.api_key or req.base_url):
        memory.reconfigure(api_key=req.api_key, base_url=req.base_url)
    return {
        "status": "ok",
        "config": {
            "model": llm_engine.model,
            "base_url": llm_engine.base_url or "default (OpenAI)",
            "has_api_key": bool(llm_engine.api_key),
        },
    }


@app.get("/settings/llm")
async def get_llm_config():
    """Get current LLM configuration (no secrets)."""
    global llm_engine
    if llm_engine is None:
        return JSONResponse({"status": "error", "message": "LLM engine not initialized"}, status_code=503)
    return {
        "model": llm_engine.model,
        "base_url": llm_engine.base_url or "",
        "has_api_key": bool(llm_engine.api_key),
    }


@app.post("/settings/memory/clear")
async def clear_memory():
    """Clear the local memory file (resets agent context)."""
    import os as _os
    memory_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "local_memory.json")
    try:
        if _os.path.exists(memory_file):
            _os.remove(memory_file)
            logger.info("Local memory file cleared")
        # Also reset in-memory local cache
        if memory:
            memory._local = []
        return {"status": "ok", "message": "Memory cleared"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/settings/memory/status")
async def memory_status():
    """Get current memory stats."""
    if memory is None:
        return {"status": "unavailable", "entries": 0}
    mem0_ok = memory._memory is not None
    local_count = len(memory._local) if memory._local else 0
    return {
        "status": "ok",
        "provider": "mem0" if mem0_ok else "local_json",
        "entries": local_count,
        "storage_file": "gateway/local_memory.json",
    }

# --- WebSocket for Chat ---

@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()

    async def _safe_send(data: dict[str, Any]) -> None:
        await websocket.send_json(_sanitize_for_json(data))

    history: list[dict[str, Any]] = []
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "message")

            if msg_type == "message":
                user_message = msg.get("content", "").strip()
                if not user_message:
                    continue

                # Echo user message back so frontend can display it
                await _safe_send({
                    "type": "user_echo",
                    "content": user_message,
                })

                if agent and hub:
                    # Retrieve relevant memories
                    memory_context = ""
                    if memory:
                        memory_context = memory.get_memory_context(user_message)
                        if memory_context:
                            await _safe_send({
                                "type": "memory",
                                "content": memory_context,
                            })

                    # Run the agent loop with memory context
                    try:
                        steps = await agent.run(user_message, history, memory_context)
                        for step in steps:
                            await _safe_send(step)
                            await asyncio.sleep(0.05)

                        # Update conversation history
                        history.append({"role": "user", "content": user_message})
                        final_content = ""
                        for step in steps:
                            if step["type"] == "response":
                                final_content = step["content"]
                        if final_content:
                            history.append({"role": "assistant", "content": final_content})

                        # Store exchange in persistent memory
                        if memory:
                            memory.add(f"User: {user_message}")
                            if final_content:
                                memory.add(f"Assistant: {final_content}")

                        # Trim history to prevent context overflow (keep last 20)
                        if len(history) > 20:
                            history = history[-20:]

                    except Exception as e:
                        logger.exception("Agent loop error")
                        await _safe_send({
                            "type": "error",
                            "content": f"Agent error: {e}",
                        })
                else:
                    await _safe_send({
                        "type": "response",
                        "content": "Agent not initialized. Check server configuration.",
                    })

            elif msg_type == "tool_call" and hub:
                tool_name = msg.get("tool_name", "")
                arguments = msg.get("arguments", {})
                result = await hub.call_tool(tool_name, arguments)
                await _safe_send({
                    "type": "tool_result",
                    "tool": tool_name,
                    "result": result,
                })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.exception("WebSocket error")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
