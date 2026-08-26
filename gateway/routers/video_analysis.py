"""Video calibration analysis — upload a real collapse video, run the
scripts/video_calibration/analyze_video.py pipeline, and return the
extracted measurements plus generated mark-up images.

Endpoints
---------
POST /api/abaqus/analyze-video   (multipart: file, tower_h, base_d)
    Runs the analysis synchronously (a few seconds) and returns:
    { job_id, output_dir, summary, video_url, images: [{url, name, group}] }
"""

import asyncio
import os
import subprocess
import sys
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router = APIRouter(prefix="/api/abaqus", tags=["video-analysis"])

# scripts/video_calibration/analyze_video.py  (absolute path, stable under gateway/)
_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "video_calibration", "analyze_video.py",
)
# scripts/video_calibration/runs/<job_id>/  — each analysis gets its own folder
RUNS_DIR = os.path.join(os.path.dirname(_SCRIPT), "runs")
os.makedirs(RUNS_DIR, exist_ok=True)

# Mounted at /video-analysis in main.py — public URL prefix for result files.
_PUBLIC_PREFIX = "/video-analysis"

_MAX_VIDEO_BYTES = 300 * 1024 * 1024  # hard safety cap (gateway middleware allows more)


async def _run_analysis(video_path: str, out_dir: str, tower_h: float, base_d: float,
                        tower_x0: int | None = None, tower_x1: int | None = None) -> str:
    """Run analyze_video.py in a thread; returns combined stdout+stderr."""
    cmd = [sys.executable, _SCRIPT,
           "--video", video_path,
           "--out", out_dir,
           "--tower-h", str(tower_h),
           "--base-d", str(base_d)]
    if tower_x0 is not None and tower_x1 is not None:
        cmd += ["--tower-x0", str(tower_x0), "--tower-x1", str(tower_x1)]
    proc = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True, timeout=180
    )
    log = proc.stdout + "\n" + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"analysis failed (exit {proc.returncode}):\n{log[-2000:]}")
    return log


def _clean_nan(obj):
    """Recursively convert NaN/Inf floats to None (FastAPI JSONResponse uses
    allow_nan=False, so NaN values would make the response 500)."""
    if isinstance(obj, float) and obj != obj:
        return None
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_nan(v) for v in obj]
    return obj


def _collect_images(job_dir: str, job_id: str) -> list[dict[str, str]]:
    """List result PNGs relative to the /video-analysis mount, with groups."""
    images: list[dict[str, str]] = []

    def _walk(folder: str, group: str) -> None:
        if not os.path.isdir(folder):
            return
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(".png"):
                rel = os.path.relpath(os.path.join(folder, name), RUNS_DIR)
                images.append({"url": f"{_PUBLIC_PREFIX}/{rel}", "name": name, "group": group})

    _walk(job_dir, "plot")                 # real_tower_top_trace.png, sim_vs_real_trace.png
    _walk(os.path.join(job_dir, "frames"), "frame")   # mark_*.png, timeline_*.png, frame_*.png
    return images


@router.post("/analyze-video")
async def analyze_video(
    file: UploadFile = File(...),
    tower_h: float = Form(70.0),
    base_d: float = Form(57.0),
    tower_x0: int | None = Form(None),
    tower_x1: int | None = Form(None),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No video file provided")
    job_id = uuid.uuid4().hex[:8]
    job_dir = os.path.join(RUNS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    video_path = os.path.join(job_dir, "input.mp4")
    size = 0
    try:
        with open(video_path, "wb") as f:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > _MAX_VIDEO_BYTES:
                    raise HTTPException(status_code=413, detail="Video too large (max 300 MB)")
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save video: {e}")

    try:
        await _run_analysis(video_path, job_dir, tower_h, base_d, tower_x0, tower_x1)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Analysis timed out (180 s)")

    summary = {}
    summary_path = os.path.join(job_dir, "analysis_summary.json")
    if os.path.exists(summary_path):
        import json
        with open(summary_path, "rb") as f:
            raw = f.read()
        for _enc in ("utf-8", "gbk", "cp936"):
            try:
                summary = _clean_nan(json.loads(raw.decode(_enc)))
                break
            except (UnicodeDecodeError, ValueError):
                continue

    return {
        "job_id": job_id,
        "output_dir": job_dir,           # absolute folder the user can browse
        "summary": summary,
        "video_url": f"{_PUBLIC_PREFIX}/{job_id}/input.mp4",
        "images": _collect_images(job_dir, job_id),
    }
