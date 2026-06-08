"""Unity process management + MJPEG frame server status REST endpoints."""

import logging
import os
import socket
import subprocess
import platform
import glob as _glob
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["unity"])


UNITY_PROJECT_DIR: str | None = None


def _init_unity_project_dir() -> None:
    global UNITY_PROJECT_DIR
    if UNITY_PROJECT_DIR is None:
        file_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(os.path.dirname(file_dir))
        UNITY_PROJECT_DIR = os.path.join(repo_root, "unity_project")


def _find_unity_exe() -> str | None:
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
    else:
        for p in _glob.glob(os.path.expanduser("~/Unity/Hub/Editor/*/Editor/Unity")):
            if os.path.isfile(p):
                candidates.append(p)

    env = os.environ.get("UNITY_PATH")
    if env and os.path.isfile(env):
        candidates.insert(0, env)

    return candidates[0] if candidates else None


def _check_port(port: int) -> bool:
    """Check if a TCP port is open on localhost."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _send_tcp_command(command: dict) -> dict:
    import json as _json
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


@router.post("/unity/launch")
async def launch_unity(request: Request):
    _init_unity_project_dir()
    unity_exe = _find_unity_exe()
    if not unity_exe:
        return JSONResponse(
            {"status": "error", "message": "Unity Editor not found. Install Unity 2021.3 LTS+ or set UNITY_PATH env var."},
            status_code=404,
        )

    unity_proc = request.app.state.unity_process
    if unity_proc is not None and unity_proc.poll() is None:
        return {"status": "ok", "message": "Unity is already running", "pid": unity_proc.pid}

    flag_path = os.path.join(UNITY_PROJECT_DIR, "auto_play.flag")
    with open(flag_path, "w") as f:
        f.write("1")
    logger.info(f"Auto-play flag created: {flag_path}")

    try:
        cmd = [unity_exe, "-projectPath", UNITY_PROJECT_DIR]
        logger.info(f"Launching Unity: {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(unity_exe),
        )
        request.app.state.unity_process = proc
        request.app.state.unity_restart_backoff = 0
        request.app.state.unity_auto_restart = True
        return {"status": "launching", "pid": proc.pid, "unity_path": unity_exe, "project": UNITY_PROJECT_DIR}
    except Exception as e:
        if os.path.exists(flag_path):
            os.remove(flag_path)
        logger.exception("Failed to launch Unity")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/unity/status")
async def unity_status(request: Request):
    _init_unity_project_dir()
    unity_proc = request.app.state.unity_process
    running = unity_proc is not None and unity_proc.poll() is None

    tcp_5005 = _check_port(5005)
    frame_server_ok = _check_port(5006)

    unity_alive = running or tcp_5005

    return {
        "process_running": running,
        "unity_alive": unity_alive,
        "pid": unity_proc.pid if running else None,
        "tcp_ready": tcp_5005,
        "frame_server_ready": frame_server_ok,
        "unity_path": _find_unity_exe(),
    }


@router.post("/unity/reconnect")
async def reconnect_unity(request: Request):
    """Reconnect to Unity's frame server (port 5006)."""
    frame_server_ok = _check_port(5006)
    if frame_server_ok:
        return {"status": "ok", "message": "Frame server is running on port 5006."}
    unity_alive = _check_port(5005)
    if unity_alive:
        return {"status": "waiting", "message": "Unity TCP is alive, frame server not yet ready on port 5006."}
    unity_exe = _find_unity_exe()
    if unity_exe:
        return {"status": "launch_required", "message": "Unity not responding. Click Launch Unity to start."}
    return {"status": "error", "message": "Unity not found and not running."}


@router.post("/unity/build-frame")
async def build_frame(request: Request):
    body = await request.json()
    structure = body.get("structure") or body
    nodes = structure.get("nodes", [])
    elements = structure.get("elements", [])

    if not nodes or not elements:
        return JSONResponse({"status": "error", "message": "nodes and elements required"}, status_code=400)

    command = {
        "action": "build_frame",
        "nodes": nodes,
        "elements": elements,
    }
    result = _send_tcp_command(command)
    return result
