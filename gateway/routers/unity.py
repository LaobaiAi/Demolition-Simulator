"""Unity process management + WebRTC signaling REST endpoints."""

import logging
import os
import socket
import subprocess
import platform
import glob as _glob
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["unity"])


UNITY_PROJECT_DIR: str | None = None


def _init_unity_project_dir() -> None:
    global UNITY_PROJECT_DIR
    if UNITY_PROJECT_DIR is None:
        gateway_dir = os.path.dirname(os.path.abspath(__file__))
        project_dir = os.path.dirname(gateway_dir)
        UNITY_PROJECT_DIR = os.path.join(project_dir, "unity_project")


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


def _detect_running_unity() -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        result = sock.connect_ex(("127.0.0.1", 5005))
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

    flag_dir = os.path.join(UNITY_PROJECT_DIR, "Temp")
    os.makedirs(flag_dir, exist_ok=True)
    flag_path = os.path.join(flag_dir, "auto_play.flag")
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
        return {"status": "launching", "pid": proc.pid, "unity_path": unity_exe, "project": UNITY_PROJECT_DIR}
    except Exception as e:
        if os.path.exists(flag_path):
            os.remove(flag_path)
        logger.exception("Failed to launch Unity")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/unity/reconnect")
async def reconnect_unity(request: Request):
    tcp_result = _send_tcp_command({"action": "restart_webrtc"})
    if tcp_result["status"] == "ok":
        request.app.state.webrtc_offer = None
        request.app.state.webrtc_answer = None
        return {
            "status": "ok",
            "message": "WebRTC restart command sent to Unity. A fresh SDP offer should arrive shortly.",
        }
    unity_exe = _find_unity_exe()
    if unity_exe:
        return {"status": "launch_required", "message": "Unity not responding on TCP. Click Launch Unity to start fresh."}
    return {"status": "error", "message": "Unity not found and not running."}


@router.get("/unity/status")
async def unity_status(request: Request):
    _init_unity_project_dir()
    unity_proc = request.app.state.unity_process
    running = unity_proc is not None and unity_proc.poll() is None

    tcp_ok = _detect_running_unity()

    unity_alive = running or tcp_ok

    return {
        "process_running": running,
        "unity_alive": unity_alive,
        "pid": unity_proc.pid if running else None,
        "tcp_ready": tcp_ok,
        "webrtc_offer_available": request.app.state.webrtc_offer is not None,
        "unity_path": _find_unity_exe(),
    }


# ── WebRTC Signaling ──────────────────────────────────────────────────────────

class SdpPayload(BaseModel):
    sdp: str


@router.post("/webrtc/offer")
async def post_webrtc_offer(payload: SdpPayload, request: Request):
    request.app.state.webrtc_offer = payload.sdp
    request.app.state.webrtc_answer = None
    logger.info(f"WebRTC offer received ({len(payload.sdp)} chars)")
    return {"status": "ok"}


@router.get("/webrtc/offer")
async def get_webrtc_offer(request: Request):
    if request.app.state.webrtc_offer is None:
        return JSONResponse({"sdp": None}, status_code=404)
    return {"sdp": request.app.state.webrtc_offer}


@router.delete("/webrtc/offer")
async def delete_webrtc_offer(request: Request):
    request.app.state.webrtc_offer = None
    return {"status": "ok"}


@router.post("/webrtc/answer")
async def post_webrtc_answer(payload: SdpPayload, request: Request):
    request.app.state.webrtc_answer = payload.sdp
    logger.info(f"WebRTC answer received ({len(payload.sdp)} chars)")
    return {"status": "ok"}


@router.get("/webrtc/answer")
async def get_webrtc_answer(request: Request):
    if request.app.state.webrtc_answer is None:
        return JSONResponse({"sdp": None}, status_code=404)
    return {"sdp": request.app.state.webrtc_answer}
