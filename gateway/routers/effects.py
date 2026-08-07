"""Effects Video pipeline REST endpoints."""

import base64
import datetime
import json
import logging
import os
from typing import Any
import uuid

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
# Save project artifacts under caiao_servers/exports/effects/ (served by main.py at /exports)
_BASE_EXPORTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "caiao_servers", "exports", "effects",
)
os.makedirs(_BASE_EXPORTS, exist_ok=True)


def _project_dir(task_id: str) -> str:
    """Get or create a project directory for a given task."""
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_id)[:64]
    d = os.path.join(_BASE_EXPORTS, safe_name)
    os.makedirs(d, exist_ok=True)
    return d


def _save_frame_images(frames: list[str], project_dir: str) -> list[str]:
    """Save base64 frame images to disk and return public URLs.

    Each frame is a data URL like 'data:image/png;base64,...'
    Returns list of URLs like '/exports/effects/{project}/{filename}'
    """
    project_name = os.path.basename(project_dir)
    urls = []
    for i, frame in enumerate(frames):
        if "base64," in frame:
            b64 = frame.split("base64,")[1]
        else:
            b64 = frame
        try:
            img_data = base64.b64decode(b64)
            filename = f"{uuid.uuid4().hex}_{i}.png"
            filepath = os.path.join(project_dir, filename)
            with open(filepath, "wb") as f:
                f.write(img_data)
            urls.append(f"/exports/effects/{project_name}/{filename}")
        except Exception as e:
            logger.warning(f"Failed to save frame {i}: {e}")
    return urls


def _download_and_save_image(image_url: str) -> str | None:
    """Download a generated image from a URL and save it to the images project folder.

    Returns local URL path like '/exports/effects/images/{name}/rendering.png'
    """
    folder_name = f"img_{uuid.uuid4().hex[:12]}"
    img_dir = os.path.join(_BASE_EXPORTS, folder_name)
    os.makedirs(img_dir, exist_ok=True)

    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(image_url)
            resp.raise_for_status()
        content = resp.content
        ext = "png"
        content_type = resp.headers.get("content-type", "")
        if "jpeg" in content_type or "jpg" in content_type:
            ext = "jpg"
        elif "webp" in content_type:
            ext = "webp"

        filename = f"rendering.{ext}"
        filepath = os.path.join(img_dir, filename)
        with open(filepath, "wb") as f:
            f.write(content)
        return f"/exports/effects/{folder_name}/{filename}"
    except Exception as e:
        logger.warning(f"Failed to save generated image: {e}")
        return None


router = APIRouter(prefix="/api/effects", tags=["effects"])


@router.post("/generate-frame")
async def generate_frame(request: Request):
    """Generate a 3D steel frame via the steel_frame_3d_generator CAIAO Server."""
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)

    body = await request.json()

    result = await hub.call_tool("generate_3d_frame", body)
    if isinstance(result, dict):
        # Propagate server errors explicitly
        if "error" in result:
            return JSONResponse({"error": result["error"]}, status_code=502)
        raw = result.get("result", "")
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
                return JSONResponse(data)
            except json.JSONDecodeError:
                return JSONResponse({"error": "Invalid JSON in result"}, status_code=500)
        return JSONResponse(raw)
    if isinstance(result, list):
        for item in result:
            if hasattr(item, "text"):
                try:
                    data = json.loads(item.text)
                    return JSONResponse(data)
                except json.JSONDecodeError:
                    return JSONResponse({"error": "Invalid response from server"}, status_code=500)

    return JSONResponse({"error": "Unexpected response format"}, status_code=500)


QUALITY_PRESETS = {
    "low": {"width": 384, "height": 256, "num_frames": 65, "frame_rate": 16},
    "medium": {"width": 768, "height": 512, "num_frames": 81, "frame_rate": 20},
    "high": {"width": 1152, "height": 768, "num_frames": 121, "frame_rate": 24},
    "cinematic": {"width": 1920, "height": 1080, "num_frames": 161, "frame_rate": 24},
}
DEFAULT_PROMPT = (
    "Photorealistic architectural steel structure demolition simulation. "
    "Wide establishing shot of a multi-story steel frame building. "
    "Specific columns on the ground floor are visually marked for demolition. "
    "Hydraulic breakers smash into the marked columns. "
    "Steel yields, concrete cracks, debris bursts. "
    "The frame loses support, tilts, then collapses floor by floor. "
    "Huge dust clouds roll outward. "
    "Real gravity and momentum physics. "
    "After main collapse, dust slowly settles, sunlight filters through haze."
)


@router.post("/export-video")
async def export_video(request: Request):
    """Export video endpoint — triggers Agnes AI video generation pipeline."""
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)

    body = await request.json()
    model_data = body.get("modelData")
    marked_columns = body.get("markedColumns", [])
    scene = body.get("scene", "mechanical_demolition")
    prompt = body.get("prompt", "")
    frames = body.get("frames", [])
    quality = body.get("quality", "high")
    num_frames = body.get("num_frames", 0)

    if not model_data:
        return JSONResponse({"error": "No model data provided"}, status_code=400)

    q = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["high"])
    width = q["width"]
    height = q["height"]
    frame_rate = q["frame_rate"]
    if num_frames and num_frames > 0:
        nf = num_frames
    else:
        nf = q["num_frames"]

    # Build Agnes API payload — pass base64 data URIs from frontend captures
    agnes_payload = {
        "prompt": prompt or DEFAULT_PROMPT,
        "width": width,
        "height": height,
        "num_frames": nf,
        "frame_rate": frame_rate,
    }
    if frames:
        agnes_payload["image_urls"] = frames

    agnes_result = await hub.call_tool("generate_video", agnes_payload)

    # Parse Agnes response
    agnes_data = None
    if isinstance(agnes_result, dict):
        if "error" in agnes_result:
            return JSONResponse({"error": agnes_result["error"]}, status_code=502)
        raw = agnes_result.get("result", "{}")
        if isinstance(raw, str):
            try:
                agnes_data = json.loads(raw)
            except json.JSONDecodeError:
                pass
    elif isinstance(agnes_result, list):
        for item in agnes_result:
            if hasattr(item, "text"):
                try:
                    agnes_data = json.loads(item.text)
                except json.JSONDecodeError:
                    pass
                break

    task_id = ""
    if agnes_data:
        if "error" in agnes_data and agnes_data["error"]:
            raw_err = agnes_data["error"]
            err_str = raw_err if isinstance(raw_err, str) else json.dumps(raw_err, ensure_ascii=False)
            raw_detail = agnes_data.get("detail", raw_err)
            detail_str = raw_detail if isinstance(raw_detail, str) else json.dumps(raw_detail, ensure_ascii=False)
            return JSONResponse({
                "status": "error",
                "error": err_str,
                "detail": detail_str,
                "message": f"Video API error: {err_str[:200]}",
            }, status_code=502)
        task_id = agnes_data.get("id", agnes_data.get("task_id", ""))

    if not task_id:
        return JSONResponse({
            "status": "error",
            "task_id": "",
            "error": "No task ID from Agnes API",
            "message": "Video server did not return a valid task ID",
        }, status_code=502)

    # Project directory: save all artifacts in one folder
    proj_dir = _project_dir(task_id)
    frame_urls = _save_frame_images(frames, proj_dir) if frames else []

    # Save project metadata
    meta = {
        "task_id": task_id,
        "created_at": datetime.datetime.utcnow().isoformat(),
        "quality": quality,
        "width": width,
        "height": height,
        "num_frames": nf,
        "frame_rate": frame_rate,
        "prompt": prompt,
        "marked_columns": marked_columns,
        "scene": scene,
        "frames_saved": len(frame_urls),
        "status": agnes_data.get("status", "queued") if agnes_data else "queued",
        "video_url": agnes_data.get("remixed_from_video_id", "") if agnes_data else "",
    }
    try:
        with open(os.path.join(proj_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save metadata: {e}")

    logger.info(
        f"Export video: task={task_id[:16]}..., quality={quality} ({width}x{height}), "
        f"frames={nf}, ref_images={len(frame_urls)}, columns={len(marked_columns)}"
    )

    return JSONResponse({
        "status": meta["status"],
        "task_id": task_id,
        "video_url": meta["video_url"],
        "frame_count": len(frame_urls),
        "project": os.path.basename(proj_dir),
    })


DEFAULT_IMAGE_PROMPT = (
    "Convert this structural engineering wireframe model into a photorealistic architectural rendering. "
    "Strictly preserve the original building structure: all column positions, beam layout, number of stories, "
    "floor levels, overall proportions, camera angle, and composition exactly as shown. "
    "Add realistic steel material with metallic reflections, concrete floor slabs, glass curtain walls, "
    "natural overcast sky lighting, precise geometric details, "
    "high resolution, cinematic quality, architectural visualization style."
)


@router.post("/generate-image")
async def generate_image(request: Request):
    """Generate a realistic rendered image from a model screenshot using Agnes Image 2.1 Flash."""
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)

    body = await request.json()
    image_data = body.get("image", "")
    prompt = body.get("prompt", "")
    project_id = body.get("project_id", "")

    if not image_data:
        return JSONResponse({"error": "No image data provided"}, status_code=400)

    # Use the base64 data URI directly
    result = await hub.call_tool("generate_image", {
        "image": image_data,
        "prompt": prompt or DEFAULT_IMAGE_PROMPT,
        "size": "1024x768",
        "response_format": "url",
    })

    # Parse result
    agnes_data = None
    if isinstance(result, dict):
        if "error" in result:
            return JSONResponse({"error": result["error"]}, status_code=502)
        raw = result.get("result", "{}")
        if isinstance(raw, str):
            try:
                agnes_data = json.loads(raw)
            except json.JSONDecodeError:
                pass
    elif isinstance(result, list):
        for item in result:
            if hasattr(item, "text"):
                try:
                    agnes_data = json.loads(item.text)
                except json.JSONDecodeError:
                    pass
                break

    if not agnes_data:
        return JSONResponse({"error": "No response from image server"}, status_code=502)

    if "error" in agnes_data and agnes_data["error"]:
        raw_err = agnes_data["error"]
        err_str = raw_err if isinstance(raw_err, str) else json.dumps(raw_err, ensure_ascii=False)
        return JSONResponse({
            "status": "error",
            "error": err_str,
            "detail": agnes_data.get("detail", ""),
        }, status_code=502)

    # Extract image URL from response (OpenAI-compatible format)
    image_url = ""
    image_data_b64 = ""
    if "data" in agnes_data and isinstance(agnes_data["data"], list) and len(agnes_data["data"]) > 0:
        item = agnes_data["data"][0]
        image_url = item.get("url", "")
        if "b64_json" in item:
            image_data_b64 = item["b64_json"]

    logger.info(f"Generated image: url={'yes' if image_url else 'no'}, b64={'yes' if image_data_b64 else 'no'}")

    # Auto-save to project folder (use existing project or create new one)
    if image_url:
        if project_id:
            proj_dir = _project_dir(project_id)
            folder_name = os.path.basename(proj_dir)
            try:
                with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                    resp = client.get(image_url)
                    resp.raise_for_status()
                content = resp.content
                ext = "png"
                ct = resp.headers.get("content-type", "")
                if "jpeg" in ct or "jpg" in ct:
                    ext = "jpg"
                elif "webp" in ct:
                    ext = "webp"
                filename = f"rendering.{ext}"
                filepath = os.path.join(proj_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(content)
                local_url = f"/exports/effects/{folder_name}/{filename}"
                # Update metadata.json with image info
                meta_path = os.path.join(proj_dir, "metadata.json")
                meta = {}
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception:
                        pass
                images = meta.get("images", [])
                images.append({
                    "url": local_url,
                    "prompt": prompt,
                    "created_at": datetime.datetime.utcnow().isoformat(),
                })
                meta["images"] = images
                try:
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
                logger.info(f"Image saved to project {folder_name}: {local_url}")
            except Exception as e:
                logger.warning(f"Failed to save image to project {project_id}: {e}")
                local_url = None
        else:
            local_url = _download_and_save_image(image_url)
            if local_url:
                logger.info(f"Image saved locally: {local_url}")

    return JSONResponse({
        "status": "ok",
        "image_url": image_url or "",
        "image_data": image_data_b64 or "",
        "local_url": local_url or "",
    })


@router.get("/download/{task_id}")
async def download_video(task_id: str, request: Request):
    """Proxy-download the Agnes-generated video file to avoid CORS issues."""
    import httpx as _httpx

    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)

    result = await hub.call_tool("check_video_status", {"task_id": task_id})
    agnes_data = None
    if isinstance(result, dict):
        raw = result.get("result", "{}")
        if isinstance(raw, str):
            try:
                agnes_data = json.loads(raw)
            except json.JSONDecodeError:
                pass
    elif isinstance(result, list):
        for item in result:
            if hasattr(item, "text"):
                try:
                    agnes_data = json.loads(item.text)
                except json.JSONDecodeError:
                    pass
                break

    if not agnes_data:
        return JSONResponse({"error": "No status data"}, status_code=404)

    video_url = agnes_data.get("remixed_from_video_id") or agnes_data.get("video_url", "")
    if not video_url:
        return JSONResponse({"error": "Video not ready or no URL"}, status_code=404)

    try:
        async with _httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(video_url, follow_redirects=True)
            resp.raise_for_status()
        from fastapi.responses import Response as _Response
        return _Response(
            content=resp.content,
            media_type=resp.headers.get("content-type", "video/mp4"),
            headers={"Content-Disposition": f'attachment; filename="demolition_{task_id[:12]}.mp4"'},
        )
    except Exception as e:
        logger.warning(f"Video proxy download failed for {task_id}: {e}")
        return JSONResponse({"error": "Download failed", "detail": str(e)}, status_code=502)


@router.get("/status/{task_id}")
async def video_status(task_id: str, request: Request):
    """Check video generation status."""
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)

    result = await hub.call_tool("check_video_status", {"task_id": task_id})
    if isinstance(result, dict):
        raw = result.get("result", "{}")
        if isinstance(raw, str):
            try:
                return JSONResponse(json.loads(raw))
            except json.JSONDecodeError:
                pass
    elif isinstance(result, list):
        for item in result:
            if hasattr(item, "text"):
                try:
                    return JSONResponse(json.loads(item.text))
                except json.JSONDecodeError:
                    pass
                break
    return JSONResponse({"status": "unknown", "task_id": task_id})
