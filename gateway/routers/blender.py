"""Blender process management + frame server status REST endpoints."""

import logging
import os
import socket
import subprocess
import sys
from typing import Any

_file_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.dirname(os.path.dirname(_file_dir))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from blender_pipeline.common import find_blender

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["blender"])

BLENDER_PIPELINE_DIR: str | None = None


def _init_blender_pipeline_dir() -> None:
    global BLENDER_PIPELINE_DIR
    if BLENDER_PIPELINE_DIR is None:
        file_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(os.path.dirname(file_dir))
        BLENDER_PIPELINE_DIR = os.path.join(repo_root, "blender_pipeline")


def _get_frame_server_script() -> str | None:
    _init_blender_pipeline_dir()
    path = os.path.join(BLENDER_PIPELINE_DIR, "scripts", "frame_server.py")
    if os.path.isfile(path):
        return path
    return None


def _find_blender_exe() -> str | None:
    return find_blender()


def _check_port(port: int) -> bool:
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
        sock.connect(("127.0.0.1", 5007))
        payload = _json.dumps(command) + "\n"
        sock.sendall(payload.encode())
        response = sock.recv(65536).decode().strip()
        sock.close()
        if response:
            return {"status": "ok", "response": _json.loads(response)}
        return {"status": "ok", "response": {}}
    except socket.timeout:
        return {"status": "error", "error": "Blender TCP command timed out (5s)"}
    except ConnectionRefusedError:
        return {"status": "error", "error": "Blender TCP server not reachable on :5007"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/blender/launch")
async def launch_blender(request: Request):
    _init_blender_pipeline_dir()
    blender_exe = _find_blender_exe()
    if not blender_exe:
        return JSONResponse(
            {"status": "error", "message": "Blender not found. Set BLENDER_EXE env var or install Blender 4.2+."},
            status_code=404,
        )

    blender_proc = getattr(request.app.state, "blender_process", None)
    if blender_proc is not None and blender_proc.poll() is None:
        return {"status": "ok", "message": "Blender is already running", "pid": blender_proc.pid}

    if _check_port(5007):
        return {"status": "ok", "message": "Blender is already running (detected on port 5007)", "pid": None}

    script = _get_frame_server_script()
    if not script:
        return JSONResponse(
            {"status": "error", "message": "frame_server.py not found in blender_pipeline/scripts/"},
            status_code=500,
        )

    try:
        cmd = [blender_exe, "--python", script]
        logger.info(f"Launching Blender: {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(blender_exe),
        )
        request.app.state.blender_process = proc
        request.app.state.blender_restart_backoff = 0
        request.app.state.blender_auto_restart = True
        return {"status": "launching", "pid": proc.pid, "blender_path": blender_exe}
    except Exception as e:
        logger.exception("Failed to launch Blender")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/blender/status")
async def blender_status(request: Request):
    _init_blender_pipeline_dir()
    blender_proc = getattr(request.app.state, "blender_process", None)
    running = blender_proc is not None and blender_proc.poll() is None

    tcp_5007 = _check_port(5007)
    frame_server_ok = _check_port(5008)

    blender_alive = running or tcp_5007

    return {
        "process_running": running,
        "blender_alive": blender_alive,
        "pid": blender_proc.pid if running else None,
        "tcp_ready": tcp_5007,
        "frame_server_ready": frame_server_ok,
        "blender_path": _find_blender_exe(),
    }


@router.post("/blender/reconnect")
async def reconnect_blender(request: Request):
    frame_server_ok = _check_port(5008)
    if frame_server_ok:
        return {"status": "ok", "message": "Frame server is running on port 5008."}
    tcp_alive = _check_port(5007)
    if tcp_alive:
        return {"status": "waiting", "message": "Blender TCP is alive, frame server not yet ready on port 5008."}
    blender_exe = _find_blender_exe()
    if blender_exe:
        return {"status": "launch_required", "message": "Blender not responding. Click Launch Blender to start."}
    return {"status": "error", "message": "Blender not found and not running."}


@router.post("/blender/build-frame")
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
