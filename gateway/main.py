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

from caiao_hub import CAIAOClientHub
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

# --- CAIAO Server configurations ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
CAIAO_SERVERS_DIR = os.path.join(PROJECT_DIR, "caiao_servers")
# Check multiple possible venv locations (uv may create it at project root)
_VENV_CANDIDATES = [
    os.path.join(BASE_DIR, "venv", "Scripts", "python.exe"),
    os.path.join(PROJECT_DIR, ".venv", "Scripts", "python.exe"),
    os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe"),
]
VENV_PYTHON = next((p for p in _VENV_CANDIDATES if os.path.exists(p)), "python")

SERVER_CONFIGS = [
    {
        "name": "anastruct_server",
        "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
        "args": [os.path.join(CAIAO_SERVERS_DIR, "anastruct_server", "server.py")],
        "cwd": os.path.join(CAIAO_SERVERS_DIR, "anastruct_server"),
    },
    {
        "name": "opensees_server",
        "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
        "args": ["server.py"],
        "cwd": os.path.join(CAIAO_SERVERS_DIR, "opensees_server"),
        "lazy": True,
    },
    {
        "name": "pynite_server",
        "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
        "args": ["server.py"],
        "cwd": os.path.join(CAIAO_SERVERS_DIR, "pynite_server"),
        "lazy": True,
    },
    {
        "name": "fapp_server",
        "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
        "args": ["server.py"],
        "cwd": os.path.join(CAIAO_SERVERS_DIR, "fapp_server"),
        "lazy": True,
    },
    {
        "name": "unity_simulator",
        "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
        "args": ["server.py"],
        "cwd": os.path.join(CAIAO_SERVERS_DIR, "unity_simulator"),
        "lazy": True,
    },
]

hub: CAIAOClientHub | None = None
agent: AgentLoop | None = None
memory: SessionMemory | None = None
llm_engine: LLMEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global hub, agent, memory, llm_engine
    logger.info("Starting CAIAO servers...")
    hub = CAIAOClientHub(SERVER_CONFIGS)
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

    # Auto-detect: if TCP port 5005 is open, Unity is running from a previous session
    _detect_running_unity()
    yield
    logger.info("Shutting down...")
    global _unity_process
    if _unity_process and _unity_process.poll() is None:
        logger.info("Terminating Unity process...")
        _unity_process.terminate()
        try:
            _unity_process.wait(timeout=5)
        except Exception:
            _unity_process.kill()
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


async def _try_solver(tool_name: str, structure: dict) -> dict | None:
    """Call a solver tool and return parsed result dict, or None on failure."""
    try:
        raw = await hub.call_tool(tool_name, {"structure": structure})
        if raw and "result" in raw:
            data = json.loads(raw["result"]) if isinstance(raw["result"], str) else raw["result"]
            if "error" not in data and data.get("max_displacement") is not None:
                return data
            logger.warning(f"{tool_name} returned error: {data.get('error', 'unknown')}")
        return None
    except Exception as e:
        logger.warning(f"{tool_name} call failed: {e}")
        return None


def _safe_pct_diff(a: float, b: float) -> float:
    """Safe percentage difference between two values.

    - Returns 0% when both are effectively zero (within tolerance).
    - Uses the larger absolute value as denominator to avoid division by near-zero.
    """
    if abs(a) < 1e-9 and abs(b) < 1e-9:
        return 0.0
    denom = max(abs(a), abs(b))
    return abs(a - b) / denom * 100


@app.post("/verify")
async def verify_analysis(req: VerifyRequest):
    """Compare fast analysis with high-fidelity solvers (OpenSees > PyNite > FAPP).

    Tries solvers in order. Falls back to the next if one is unavailable.
    Only returns 'unavailable' if ALL solvers fail.
    """
    fast = req.fast_result
    max_disp_fast = fast.get("max_displacement", 0)
    max_axial_fast = fast.get("max_axial_force", 0)

    if hub and req.structure:
        solver_order = [
            ("high_fidelity_analysis", "OpenSees"),
            ("pynite_analysis", "PyNite"),
            ("fapp_analysis", "FAPP"),
        ]
        for tool_name, solver_label in solver_order:
            hf_data = await _try_solver(tool_name, req.structure)
            if hf_data is None:
                continue
            max_disp_hf = hf_data.get("max_displacement", 0)
            max_axial_hf = hf_data.get("max_axial_force", 0)
            disp_diff = _safe_pct_diff(max_disp_fast, max_disp_hf)
            axial_diff = _safe_pct_diff(max_axial_fast, max_axial_hf)
            status = "verified" if max(disp_diff, axial_diff) < 5.0 else "warning"

            # Detect when fast analysis likely failed (returned near-zero while hi-fi has real values)
            message = None
            if abs(max_disp_fast) < 1e-9 and abs(max_disp_hf) > 1e-9:
                message = (
                    "Fast analysis returned effectively zero displacement. This usually means the structure "
                    "was not correctly passed to the fast solver (anaStruct). The high-fidelity result is "
                    "likely correct. Consider re-running the analysis."
                )

            logger.info(f"{solver_label} comparison: disp_diff={disp_diff:.1f}%, axial_diff={axial_diff:.1f}%, status={status}")
            return {
                "status": status,
                "demo_mode": False,
                "solver": solver_label,
                "message": message,
                "comparison": {
                    "max_displacement": {"fast": round(max_disp_fast, 10), "high_fidelity": round(max_disp_hf, 10), "diff_percent": round(disp_diff, 2)},
                    "max_axial_force": {"fast": round(max_axial_fast, 2), "high_fidelity": round(max_axial_hf, 2), "diff_percent": round(axial_diff, 2)},
                },
            }

    return {
        "status": "unavailable",
        "demo_mode": True,
        "comparison": {
            "max_displacement": {"fast": round(max_disp_fast, 10), "high_fidelity": 0, "diff_percent": 0},
            "max_axial_force": {"fast": round(max_axial_fast, 2), "high_fidelity": 0, "diff_percent": 0},
        },
        "message": "No high-fidelity solver is available on this platform. Install OpenSees, PyNite, or FAPP for comparison verification.",
    }


class MultiVerifyRequest(BaseModel):
    fast_result: dict[str, Any]
    structure: dict[str, Any]


def _median(vals: list[float]) -> float:
    if not vals:
        return 0
    s = sorted(vals)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


@app.post("/verify/multi")
async def verify_multi(req: MultiVerifyRequest):
    """Run all available solvers on the same structure and compute consensus.

    Returns per-solver results plus consensus (median) and outlier flags.
    """
    fast = req.fast_result
    results: dict[str, dict[str, Any]] = {
        "anastruct": {
            "max_displacement": fast.get("max_displacement", 0),
            "max_axial_force": fast.get("max_axial_force", 0),
        }
    }

    solver_map = [
        ("high_fidelity_analysis", "opensees"),
        ("pynite_analysis", "pynite"),
        ("fapp_analysis", "fapp"),
    ]

    for tool_name, key in solver_map:
        try:
            raw = await hub.call_tool(tool_name, {"structure": req.structure})
            if raw and "result" in raw:
                data = json.loads(raw["result"]) if isinstance(raw["result"], str) else raw["result"]
                if "error" in data:
                    results[key] = {"error": str(data["error"])}
                else:
                    results[key] = {
                        "max_displacement": data.get("max_displacement", 0),
                        "max_axial_force": data.get("max_axial_force", 0),
                    }
            else:
                results[key] = {"error": "Solver returned no result"}
        except Exception as e:
            logger.warning(f"Multi-verify: {key} failed: {e}")
            results[key] = {"error": str(e)}

    available_disp = [r["max_displacement"] for r in results.values() if "max_displacement" in r]
    available_axial = [r["max_axial_force"] for r in results.values() if "max_axial_force" in r]

    consensus_disp = _median(available_disp)
    consensus_axial = _median(available_axial)

    solver_count = len(available_disp)
    deviations = {}
    for name, r in results.items():
        if "max_displacement" not in r:
            continue
        d_disp = _safe_pct_diff(r["max_displacement"], consensus_disp)
        d_axial = _safe_pct_diff(r["max_axial_force"], consensus_axial)
        deviations[name] = {
            "displacement_diff_pct": round(d_disp, 2),
            "axial_diff_pct": round(d_axial, 2),
            "is_outlier": d_disp > 5.0 or d_axial > 5.0,
        }

    return {
        "solvers": results,
        "consensus": {
            "max_displacement": round(consensus_disp, 10),
            "max_axial_force": round(consensus_axial, 2),
        },
        "solver_count": solver_count,
        "deviations": deviations,
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

# --- WebRTC Signaling (Unity ↔ Frontend) ---

_webrtc_offer: str | None = None
_webrtc_answer: str | None = None


class SdpPayload(BaseModel):
    sdp: str


@app.post("/webrtc/offer")
async def post_webrtc_offer(payload: SdpPayload):
    global _webrtc_offer, _webrtc_answer
    _webrtc_offer = payload.sdp
    _webrtc_answer = None
    logger.info(f"WebRTC offer received ({len(payload.sdp)} chars)")
    return {"status": "ok"}


@app.get("/webrtc/offer")
async def get_webrtc_offer():
    if _webrtc_offer is None:
        return JSONResponse({"sdp": None}, status_code=404)
    return {"sdp": _webrtc_offer}


@app.delete("/webrtc/offer")
async def delete_webrtc_offer():
    global _webrtc_offer
    _webrtc_offer = None
    return {"status": "ok"}


@app.post("/webrtc/answer")
async def post_webrtc_answer(payload: SdpPayload):
    global _webrtc_answer
    _webrtc_answer = payload.sdp
    logger.info(f"WebRTC answer received ({len(payload.sdp)} chars)")
    return {"status": "ok"}


@app.get("/webrtc/answer")
async def get_webrtc_answer():
    if _webrtc_answer is None:
        return JSONResponse({"sdp": None}, status_code=404)
    return {"sdp": _webrtc_answer}


# --- Unity Process Management ---

import subprocess
import platform
import glob as _glob

UNITY_PROJECT_DIR = os.path.join(os.path.dirname(BASE_DIR), "unity_project")
_unity_process: subprocess.Popen | None = None


def _find_unity_exe() -> str | None:
    """Scan common Unity install locations. Returns path to Unity.exe or None."""
    candidates: list[str] = []

    if platform.system() == "Windows":
        hub_base = r"C:\Program Files\Unity\Hub\Editor"
        if os.path.isdir(hub_base):
            for ver in sorted(os.listdir(hub_base), reverse=True):
                exe = os.path.join(hub_base, ver, "Editor", "Unity.exe")
                if os.path.isfile(exe):
                    candidates.append(exe)
        legacy = r"C:\Program Files\Unity"
        if os.path.isdir(legacy):
            for ver in sorted(os.listdir(legacy), reverse=True):
                exe = os.path.join(legacy, ver, "Editor", "Unity.exe")
                if os.path.isfile(exe):
                    candidates.append(exe)
    elif platform.system() == "Darwin":
        for p in _glob.glob("/Applications/Unity/Hub/Editor/*/Unity.app/Contents/MacOS/Unity"):
            candidates.append(p)
    else:  # Linux
        for p in _glob.glob(os.path.expanduser("~/Unity/Hub/Editor/*/Editor/Unity")):
            if os.path.isfile(p):
                candidates.append(p)

    env = os.environ.get("UNITY_PATH")
    if env and os.path.isfile(env):
        candidates.insert(0, env)

    return candidates[0] if candidates else None


@app.post("/unity/launch")
async def launch_unity():
    global _unity_process
    unity_exe = _find_unity_exe()
    if not unity_exe:
        return JSONResponse(
            {"status": "error", "message": "Unity Editor not found. Install Unity 2021.3 LTS+ or set UNITY_PATH env var."},
            status_code=404,
        )

    if _unity_process is not None and _unity_process.poll() is None:
        return {"status": "ok", "message": "Unity is already running", "pid": _unity_process.pid}

    # Create auto-play flag so Unity sets up scene + enters Play mode on load
    flag_dir = os.path.join(UNITY_PROJECT_DIR, "Temp")
    os.makedirs(flag_dir, exist_ok=True)
    flag_path = os.path.join(flag_dir, "auto_play.flag")
    with open(flag_path, "w") as f:
        f.write("1")
    logger.info(f"Auto-play flag created: {flag_path} (exists={os.path.exists(flag_path)})")

    try:
        cmd = [unity_exe, "-projectPath", UNITY_PROJECT_DIR]
        logger.info(f"Launching Unity: {' '.join(cmd)}")
        _unity_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(unity_exe),
        )
        return {"status": "launching", "pid": _unity_process.pid, "unity_path": unity_exe, "project": UNITY_PROJECT_DIR}
    except Exception as e:
        # Clean up flag on failure
        if os.path.exists(flag_path):
            os.remove(flag_path)
        logger.exception("Failed to launch Unity")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/unity/status")
async def unity_status():
    global _unity_process, _webrtc_offer
    running = _unity_process is not None and _unity_process.poll() is None

    tcp_ok = False
    if running:
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            tcp_ok = sock.connect_ex(("127.0.0.1", 5005)) == 0
            sock.close()
        except Exception:
            pass

    return {
        "process_running": running,
        "pid": _unity_process.pid if running else None,
        "tcp_ready": tcp_ok,
        "webrtc_offer_available": _webrtc_offer is not None,
        "unity_path": _find_unity_exe(),
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

                    # Run the agent loop with memory context (streaming)
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

                        # Use full message history from agent (preserving reasoning_content, tool_calls)
                        if new_history:
                            history = new_history
                        else:
                            history.append({"role": "user", "content": user_message})
                            if final_content:
                                history.append({"role": "assistant", "content": final_content})

                        # Store exchange in persistent memory
                        if memory:
                            memory.add(f"User: {user_message}")
                            if final_content:
                                memory.add(f"Assistant: {final_content}")

                        # Trim history to prevent context overflow (keep last 20)
                        # Ensure we don't orphan tool messages from their tool_calls
                        if len(history) > 20:
                            history = history[-20:]
                        while history and history[0].get("role") == "tool":
                            history.pop(0)

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
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
