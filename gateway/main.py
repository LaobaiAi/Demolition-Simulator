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

from caiao import CAIAOClientHub, get_parallel_limit
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

from caiao_config import discover_server_configs, PROJECT_DIR

SERVER_CONFIGS = discover_server_configs()

hub: CAIAOClientHub | None = None
agent: AgentLoop | None = None
memory: SessionMemory | None = None
llm_engine: LLMEngine | None = None


# --- No local tool handlers needed — composite pipelines are auto-registered
# via SERVER_CONFIGS composite entries. See caiao.CAIAOClientHub.


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

    # Composite pipelines are auto-registered from SERVER_CONFIGS in hub.__init__
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


@app.get("/scenarios")
async def list_scenarios(category: str | None = None, tag: str | None = None):
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    args: dict[str, Any] = {}
    if category:
        args["category"] = category
    if tag:
        args["tag"] = tag
    result = await hub.call_tool("list_scenarios", args)
    return result


@app.get("/scenarios/{name}")
async def get_scenario(name: str):
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    result = await hub.call_tool("get_scenario", {"name": name})
    return result


# ── Server management endpoints (for manager_server + frontend) ──────────────

@app.get("/servers")
async def list_servers_status():
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    return {"servers": hub.get_all_status()}


@app.get("/servers/health")
async def servers_health():
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    return {"health": hub.get_all_health()}


@app.get("/servers/metrics")
async def servers_metrics():
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    return {"metrics": hub._metrics}


@app.post("/servers/{server_name}/restart")
async def restart_server(server_name: str):
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    success = await hub.restart_server(server_name)
    return {"status": "ok" if success else "error"}


@app.post("/servers/{server_name}/pause")
async def pause_server(server_name: str):
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    await hub.pause_server(server_name)
    return {"status": "ok"}


@app.post("/servers/{server_name}/resume")
async def resume_server(server_name: str):
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    success = await hub.restart_server(server_name)
    return {"status": "ok" if success else "error"}


@app.post("/servers/{server_name}/stop")
async def stop_server(server_name: str):
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    await hub.stop_server(server_name)
    return {"status": "ok"}


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


async def _run_solvers(
    structure: dict,
    solver_order: list[tuple[str, str]],
) -> tuple[dict | None, str | None]:
    """Run solvers with resource-aware parallelization.

    When CPU/memory allows, runs all solvers in parallel and picks the first
    successful result. When resources are tight, runs serially.
    Returns (result_data, solver_label) or (None, None) if all fail.
    """
    if not hub or not structure:
        return None, None

    total = len(solver_order)
    limit = get_parallel_limit(total)

    if limit >= 2:
        # Parallel: run all at once, pick first success
        logger.info(f"Running {total} solvers in parallel (limit={limit})")
        tasks = []
        for tool_name, solver_label in solver_order:
            tasks.append(_try_solver(tool_name, structure))
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, (tool_name, solver_label) in enumerate(solver_order):
            result = all_results[i]
            if isinstance(result, dict) and result is not None:
                logger.info(f"{solver_label} returned valid result in parallel mode")
                return result, solver_label
        return None, None
    else:
        # Serial: try each in order
        logger.info(f"Running {total} solvers serially (limited resources)")
        for tool_name, solver_label in solver_order:
            result = await _try_solver(tool_name, structure)
            if result:
                return result, solver_label
        return None, None


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
    """Compare fast analysis with high-fidelity solvers in parallel.

    Uses resource-aware parallelization — runs all solvers concurrently
    when CPU/memory allows, falls back to serial when loaded.
    Returns first successful result, or 'unavailable' if ALL solvers fail.
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
        hf_data, solver_label = await _run_solvers(req.structure, solver_order)
        if hf_data and solver_label:
            max_disp_hf = hf_data.get("max_displacement", 0)
            max_axial_hf = hf_data.get("max_axial_force", 0)
            disp_diff = _safe_pct_diff(max_disp_fast, max_disp_hf)
            axial_diff = _safe_pct_diff(max_axial_fast, max_axial_hf)
            status = "verified" if max(disp_diff, axial_diff) < 5.0 else "warning"

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


# Dimension groups for consensus comparison
DIMENSION_GROUPS: dict[str, set[str]] = {
    "2D": {"anastruct", "opensees"},
    "3D": {"pynite", "fapp"},
}

SOLVER_DIMENSION: dict[str, str] = {}
for dim, solvers in DIMENSION_GROUPS.items():
    for s in solvers:
        SOLVER_DIMENSION[s] = dim


def _extract_solver_result(raw: dict | Any, results: dict, key: str) -> None:
    """Parse a solver raw result into the results dict."""
    if isinstance(raw, dict) and "result" in raw:
        data = json.loads(raw["result"]) if isinstance(raw["result"], str) else raw["result"]
        if "error" in data:
            results[key] = {"error": str(data["error"])}
        else:
            results[key] = {
                "max_displacement": data.get("max_displacement", 0),
                "max_axial_force": data.get("max_axial_force", 0),
            }
    elif isinstance(raw, dict) and "error" in raw:
        results[key] = {"error": str(raw["error"])}
    else:
        results[key] = {"error": "Solver returned no result"}


@app.post("/verify/multi")
async def verify_multi(req: MultiVerifyRequest):
    """Run all available solvers on the same structure in parallel and compute consensus.

    Uses resource-aware parallelization — runs solvers concurrently
    when CPU/memory allows, falls back to serial when loaded.

    Returns per-solver results plus consensus (median) and outlier flags.
    Deviations are computed per dimension group (2D vs 3D) so that e.g.
    anaStruct is compared against other 2D solvers, not against 3D solvers
    whose Iy/Iz stiffness properties may differ.
    """
    results: dict[str, dict[str, Any]] = {}

    solver_map = [
        ("analyze_frame", "anastruct"),
        ("high_fidelity_analysis", "opensees"),
        ("pynite_analysis", "pynite"),
        ("fapp_analysis", "fapp"),
    ]

    total = len(solver_map)
    limit = get_parallel_limit(total)
    logger.info(f"Multi-verify: {total} solvers, parallel_limit={limit}")

    if limit >= 2:
        # Parallel execution via hub
        tool_calls = [(tn, {"structure": req.structure}) for tn, _ in solver_map]
        parallel_results = await hub.call_tools_parallel(tool_calls)
        for i, (tool_name, key) in enumerate(solver_map):
            raw = parallel_results[i] if i < len(parallel_results) else {"error": "No result"}
            _extract_solver_result(raw, results, key)
    else:
        # Serial fallback
        for tool_name, key in solver_map:
            try:
                raw = await hub.call_tool(tool_name, {"structure": req.structure})
                _extract_solver_result(raw, results, key)
            except Exception as e:
                logger.warning(f"Multi-verify: {key} failed: {e}")
                results[key] = {"error": str(e)}

    available_disp = [r["max_displacement"] for r in results.values() if "max_displacement" in r]
    available_axial = [r["max_axial_force"] for r in results.values() if "max_axial_force" in r]

    # Overall consensus (median of all solvers, kept for backward compat)
    consensus_disp = _median(available_disp)
    consensus_axial = _median(available_axial)

    # Per-dimension-group consensus
    consensus_by_dimension: dict[str, dict[str, Any]] = {}
    for dim, members in DIMENSION_GROUPS.items():
        group_disp = [results[m]["max_displacement"] for m in members if m in results and "max_displacement" in results[m]]
        group_axial = [results[m]["max_axial_force"] for m in members if m in results and "max_axial_force" in results[m]]
        if group_disp:
            consensus_by_dimension[dim] = {
                "solver_count": len(group_disp),
                "solvers": [m for m in members if m in results and "max_displacement" in results[m]],
                "max_displacement": round(_median(group_disp), 10),
                "max_axial_force": round(_median(group_axial), 2),
            }

    # Cross-dimension discrepancy detection
    dimension_discrepancy: dict[str, Any] = {"detected": False}
    if "2D" in consensus_by_dimension and "3D" in consensus_by_dimension:
        disp_2d = consensus_by_dimension["2D"]["max_displacement"]
        disp_3d = consensus_by_dimension["3D"]["max_displacement"]
        axial_2d = consensus_by_dimension["2D"]["max_axial_force"]
        axial_3d = consensus_by_dimension["3D"]["max_axial_force"]
        d_disp = _safe_pct_diff(disp_2d, disp_3d)
        d_axial = _safe_pct_diff(axial_2d, axial_3d)
        dimension_discrepancy = {
            "detected": d_disp > 5.0 or d_axial > 5.0,
            "displacement_diff_pct": round(d_disp, 2),
            "axial_diff_pct": round(d_axial, 2),
        }

    # Deviation analysis: compare each solver against its own dimension group
    solver_count = len(available_disp)
    deviations = {}
    for name, r in results.items():
        if "max_displacement" not in r:
            continue
        group = SOLVER_DIMENSION.get(name)
        if group and group in consensus_by_dimension:
            ref_disp = consensus_by_dimension[group]["max_displacement"]
            ref_axial = consensus_by_dimension[group]["max_axial_force"]
        else:
            ref_disp = consensus_disp
            ref_axial = consensus_axial

        d_disp = _safe_pct_diff(r["max_displacement"], ref_disp)
        d_axial = _safe_pct_diff(r["max_axial_force"], ref_axial)
        deviations[name] = {
            "displacement_diff_pct": round(d_disp, 2),
            "axial_diff_pct": round(d_axial, 2),
            "is_outlier": d_disp > 5.0 or d_axial > 5.0,
            "group": group or "all",
        }

    return {
        "solvers": results,
        "consensus": {
            "max_displacement": round(consensus_disp, 10),
            "max_axial_force": round(consensus_axial, 2),
        },
        "consensus_by_dimension": consensus_by_dimension,
        "dimension_discrepancy": dimension_discrepancy,
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

UNITY_PROJECT_DIR = os.path.join(PROJECT_DIR, "unity_project")
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


def _detect_running_unity() -> bool:
    """Check if Unity is already running on TCP port 5005 (from a previous gateway session)."""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        result = sock.connect_ex(("127.0.0.1", 5005))
        sock.close()
        if result == 0:
            logger.info("Detected running Unity instance on port 5005 (from previous session).")
            return True
    except Exception:
        pass
    return False


def _send_tcp_command(command: dict) -> dict:
    """Send a JSON command to Unity via TCP port 5005 and return the response."""
    import json as _json
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(("127.0.0.1", 5005))
        payload = _json.dumps(command) + "\n"
        sock.sendall(payload.encode())
        response = sock.recv(4096).decode().strip()
        sock.close()
        return {"status": "ok", "response": response}
    except Exception as e:
        return {"status": "error", "error": str(e)}


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


@app.post("/unity/reconnect")
async def reconnect_unity():
    """Send a restart_webrtc command to Unity via TCP to re-establish WebRTC signaling.
    Use this after a gateway restart where the SDP offer was lost."""
    # First try TCP command to restart WebRTC
    tcp_result = _send_tcp_command({"action": "restart_webrtc"})
    if tcp_result["status"] == "ok":
        global _webrtc_offer, _webrtc_answer
        _webrtc_offer = None
        _webrtc_answer = None
        return {
            "status": "ok",
            "message": "WebRTC restart command sent to Unity. A fresh SDP offer should arrive shortly.",
        }
    # If TCP failed, check if we can launch Unity
    unity_exe = _find_unity_exe()
    if unity_exe:
        return {"status": "launch_required", "message": "Unity not responding on TCP. Click Launch Unity to start fresh."}
    return {"status": "error", "message": "Unity not found and not running."}


@app.get("/unity/status")
async def unity_status():
    global _unity_process, _webrtc_offer
    running = _unity_process is not None and _unity_process.poll() is None

    # Always check TCP — Unity may be running from a previous gateway session
    tcp_ok = False
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        tcp_ok = sock.connect_ex(("127.0.0.1", 5005)) == 0
        sock.close()
    except Exception:
        pass

    # Unity is considered alive if either tracked process OR TCP port responds
    unity_alive = running or tcp_ok

    return {
        "process_running": running,
        "unity_alive": unity_alive,
        "pid": _unity_process.pid if running else None,
        "tcp_ready": tcp_ok,
        "webrtc_offer_available": _webrtc_offer is not None,
        "unity_path": _find_unity_exe(),
    }


# --- Visual Demolition Pipeline Definitions ---

PIPELINE_VISUAL_DEMOLITION_TOPOLOGY: list[dict[str, Any]] = [
    {
        "server": "frame_generator",
        "tool": "generate_frame",
        "label": "Generating structural frame",
        "skip_if_structure": True,
    },
    {
        "server": "planning_server",
        "tool": "plan_demolition_sequence",
        "label": "Planning demolition sequence",
    },
    {
        "server": "animation_control_server",
        "tool": "create_timeline",
        "label": "Creating animation timeline",
    },
    {
        "server": "animation_control_server",
        "tool": "sequence_to_animation_data",
        "label": "Building animation data",
    },
    {
        "server": "animation_control_server",
        "tool": "generate_effects_config",
        "label": "Configuring visual effects",
    },
    {
        "server": "physics_server",
        "tool": "init_physics_scene",
        "label": "Initializing physics engine",
    },
]

PIPELINE_VISUAL_DEMOLITION_MECHANICS: list[dict[str, Any]] = [
    {
        "server": "frame_generator",
        "tool": "generate_frame",
        "label": "Generating structural frame",
    },
    {
        "server": "anastruct_server",
        "tool": "analyze_frame",
        "label": "Running structural analysis",
    },
    {
        "server": "anastruct_server",
        "tool": "select_critical_element",
        "label": "Identifying critical elements",
    },
    {
        "server": "planning_server",
        "tool": "plan_demolition_sequence",
        "label": "Planning demolition sequence",
    },
    {
        "server": "animation_control_server",
        "tool": "create_timeline",
        "label": "Creating animation timeline",
    },
    {
        "server": "animation_control_server",
        "tool": "sequence_to_animation_data",
        "label": "Building animation data",
    },
    {
        "server": "animation_control_server",
        "tool": "generate_effects_config",
        "label": "Configuring visual effects",
    },
    {
        "server": "physics_server",
        "tool": "init_physics_scene",
        "label": "Initializing physics engine",
    },
]


def _resolve_pipeline_args(
    tool_name: str,
    structure: dict[str, Any] | None,
    strategy: str,
    effects_preset: str,
    speed: float,
    structure_params: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """Build arguments for a pipeline step, using prior results from ctx."""
    # Resolve effective structure: prefer ctx (from generate_frame) over param
    effective_structure = structure
    gen_result = _parse_step_result(ctx.get("generate_frame", {}))
    if gen_result.get("nodes") and gen_result.get("elements"):
        effective_structure = gen_result

    if tool_name == "plan_demolition_sequence":
        return {"structure": effective_structure or structure_params, "strategy": strategy}
    if tool_name == "create_timeline":
        return {
            "demolition_plan": _parse_step_result(ctx.get("plan_demolition_sequence", {})),
            "effects_preset": effects_preset,
        }
    if tool_name == "sequence_to_animation_data":
        return {
            "demolition_sequence": _parse_step_result(ctx.get("create_timeline", {})),
            "speed": speed,
        }
    if tool_name == "generate_effects_config":
        return {"preset": effects_preset, "structure": effective_structure or structure_params}
    if tool_name == "init_physics_scene":
        return {
            "structure": effective_structure or structure_params,
            "animation_data": _parse_step_result(ctx.get("sequence_to_animation_data", {})),
        }
    if tool_name == "generate_frame":
        return {
            "num_bays_x": structure_params.get("num_bays_x", 3),
            "num_stories": structure_params.get("num_stories", 4),
            "span_x_m": structure_params.get("span_x_m", 6.0),
            "story_height_m": structure_params.get("story_height_m", 3.0),
            "steel_grade": structure_params.get("steel_grade", "Q355"),
        }
    if tool_name == "analyze_frame":
        return {"structure": effective_structure or structure_params}
    if tool_name == "select_critical_element":
        analysis = _parse_step_result(ctx.get("analyze_frame", {}))
        return {
            "structure": effective_structure or structure_params,
            "analysis_result": analysis,
        }
    return {}


def _parse_step_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Unwrap CAIAO tool result: if raw has a 'result' key with a JSON string, parse it."""
    result_val = raw.get("result")
    if isinstance(result_val, str):
        try:
            return json.loads(result_val)
        except (json.JSONDecodeError, TypeError):
            return {"raw": result_val}
    if isinstance(result_val, dict):
        return result_val
    return raw


def _trim_for_pipeline(result: dict[str, Any]) -> dict[str, Any]:
    """Trim verbose fields from a pipeline step result for progress messages.

    Preserves the 'result' key (the actual tool output) intact — the frontend
    parses it to extract structures, plans, and animation data.
    """
    trimmed: dict[str, Any] = {}
    for k, v in result.items():
        if k == "result":
            trimmed[k] = v
        elif k in ("steps", "chain_rounds", "animation_sequence", "body_states", "keyframes"):
            trimmed[k] = f"[{len(v)} items]" if isinstance(v, list) else str(v)[:200]
        elif k == "error":
            trimmed[k] = str(v)[:300]
        elif isinstance(v, str) and len(v) > 500:
            trimmed[k] = v[:500] + "..."
        else:
            trimmed[k] = v
    return trimmed


def _extract_timeline_steps(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract a simplified timeline step list from pipeline context for the frontend."""
    plan_raw = _parse_step_result(ctx.get("plan_demolition_sequence", {}))
    timeline_raw = _parse_step_result(ctx.get("create_timeline", {}))

    steps = plan_raw.get("steps") or timeline_raw.get("steps") or []
    if isinstance(steps, list) and len(steps) > 0 and isinstance(steps[0], dict):
        return [
            {
                "id": s.get("step", i),
                "elementId": s.get("element_id", 0),
                "elementType": s.get("element_type", "unknown"),
                "phase": s.get("action", "remove"),
                "durationMs": s.get("duration_ms", 2000),
            }
            for i, s in enumerate(steps)
        ][:50]  # cap at 50 for message size
    return []


# --- WebSocket for Chat ---

@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()

    async def _safe_send(data: dict[str, Any]) -> None:
        try:
            await websocket.send_json(_sanitize_for_json(data))
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
                pipeline_name = msg.get("pipeline", "visual_demolition_topology")
                params = msg.get("params", {})

                if pipeline_name == "visual_demolition_topology":
                    pipeline_def = PIPELINE_VISUAL_DEMOLITION_TOPOLOGY
                elif pipeline_name == "visual_demolition_mechanics":
                    pipeline_def = PIPELINE_VISUAL_DEMOLITION_MECHANICS
                else:
                    await _safe_send({
                        "type": "pipeline_error",
                        "content": f"Unknown pipeline: {pipeline_name}",
                    })
                    continue

                structure = params.get("structure")
                strategy = params.get("strategy", "top_down")
                effects_preset = params.get("effects_preset", "standard")
                speed = params.get("speed", 1.0)
                structure_params = params.get("structure_params", {})

                has_structure = structure and structure.get("nodes") and structure.get("elements")
                has_generator = any(s.get("tool") == "generate_frame" for s in pipeline_def)

                if not has_structure and not has_generator:
                    await _safe_send({
                        "type": "pipeline_error",
                        "content": "Pipeline requires a valid structure — none provided and no generator step in pipeline",
                    })
                    continue

                await _safe_send({
                    "type": "pipeline_start",
                    "pipeline": pipeline_name,
                    "total_steps": len(pipeline_def),
                    "strategy": strategy,
                })

                try:
                    pipeline_ctx: dict[str, Any] = {}
                    has_structure = structure and structure.get("nodes") and structure.get("elements")
                    for i, step in enumerate(pipeline_def):
                        if step.get("skip_if_structure") and has_structure:
                            logger.info(f"Pipeline skipping {step['tool']} — structure already provided")
                            pipeline_ctx[step["tool"]] = {"nodes": structure["nodes"], "elements": structure["elements"], "loads": structure.get("loads", []), "supports": structure.get("supports", [])}
                            await _safe_send({
                                "type": "pipeline_step",
                                "phase": step.get("label", step["tool"]),
                                "progress": round((i + 1) / len(pipeline_def), 2),
                                "step_index": i,
                                "total_steps": len(pipeline_def),
                                "tool": step["tool"],
                                "data": {"status": "skipped", "reason": "structure already provided"},
                            })
                            continue
                        tool_name = step["tool"]
                        label = step.get("label", tool_name)
                        server_hint = step.get("server")

                        # Resolve arguments at execution time (may depend on earlier results)
                        arguments = _resolve_pipeline_args(
                            tool_name, structure, strategy, effects_preset,
                            speed, structure_params, pipeline_ctx,
                        )

                        if server_hint:
                            await hub._ensure_server(tool_name, server_hint)

                        result = await hub.call_tool(tool_name, arguments)
                        pipeline_ctx[tool_name] = result

                        progress = round((i + 1) / len(pipeline_def), 2)

                        if "error" in result:
                            await _safe_send({
                                "type": "pipeline_step",
                                "phase": label,
                                "progress": progress,
                                "step_index": i,
                                "total_steps": len(pipeline_def),
                                "tool": tool_name,
                                "error": str(result.get("error", "Unknown error")),
                            })
                            await _safe_send({
                                "type": "pipeline_error",
                                "content": f"Pipeline failed at step {i+1}/{len(pipeline_def)} ({label}): {result.get('error', 'Unknown error')}",
                            })
                            break

                        await _safe_send({
                            "type": "pipeline_step",
                            "phase": label,
                            "progress": progress,
                            "step_index": i,
                            "total_steps": len(pipeline_def),
                            "tool": tool_name,
                            "data": _trim_for_pipeline(result),
                        })
                    else:
                        plan_result = _parse_step_result(pipeline_ctx.get("plan_demolition_sequence", {}))
                        step_count = plan_result.get("total_steps", 0) if isinstance(plan_result, dict) else 0
                        timeline_steps = _extract_timeline_steps(pipeline_ctx)
                        await _safe_send({
                            "type": "pipeline_complete",
                            "pipeline": pipeline_name,
                            "timeline_steps": timeline_steps,
                            "strategy": strategy,
                            "step_count": step_count,
                        })
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
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False,
                ws_ping_interval=25, ws_ping_timeout=10)
