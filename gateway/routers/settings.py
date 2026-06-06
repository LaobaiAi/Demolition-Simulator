"""Settings REST endpoints — LLM config + memory management."""

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


class LLMSettingsRequest(BaseModel):
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None


@router.get("/llm")
async def get_llm_config(request: Request):
    llm = request.app.state.llm_engine
    if llm is None:
        return JSONResponse({"status": "error", "message": "LLM engine not initialized"}, status_code=503)
    masked = ""
    key = llm.api_key or ""
    if key and len(key) > 4:
        masked = "*" * (len(key) - 4) + key[-4:]
    return {
        "model": llm.model,
        "base_url": llm.base_url or "",
        "has_api_key": bool(llm.api_key),
        "api_key_masked": masked,
    }


@router.post("/llm")
async def configure_llm(req: LLMSettingsRequest, request: Request):
    llm = request.app.state.llm_engine
    memory = request.app.state.memory
    if llm is None:
        return JSONResponse({"status": "error", "message": "LLM engine not initialized"}, status_code=503)
    llm.configure(model=req.model, api_key=req.api_key, base_url=req.base_url)

    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "llm_config.json")
    try:
        with open(config_file, "w") as f:
            json.dump({"model": llm.model, "api_key": llm.api_key, "base_url": llm.base_url}, f)
    except Exception as e:
        logger.warning(f"Failed to save LLM config: {e}")

    if memory and (req.api_key or req.base_url):
        memory.reconfigure(api_key=req.api_key, base_url=req.base_url)
    return {
        "status": "ok",
        "config": {
            "model": llm.model,
            "base_url": llm.base_url or "default (OpenAI)",
            "has_api_key": bool(llm.api_key),
        },
    }


@router.post("/llm/test")
async def test_llm_connection(req: LLMSettingsRequest, request: Request):
    llm = request.app.state.llm_engine
    if llm is None:
        return JSONResponse({"status": "error", "message": "LLM engine not initialized"}, status_code=503)

    key = req.api_key or llm.api_key or ""
    base_url = (req.base_url or llm.base_url or "https://api.openai.com/v1").rstrip("/")
    model = req.model or llm.model or "gpt-4o"

    if not key:
        return JSONResponse({"status": "error", "message": "No API key configured"}, status_code=400)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
                json={"model": model, "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]},
            )
            if resp.is_success:
                return {"status": "ok", "message": "Connection successful"}
            detail = resp.text[:200]
            return JSONResponse(
                {"status": "error", "message": f"HTTP {resp.status_code}: {detail}"},
                status_code=502,
            )
    except httpx.TimeoutException:
        return JSONResponse({"status": "error", "message": "Connection timed out"}, status_code=504)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)[:200]}, status_code=502)


@router.get("/memory/status")
async def memory_status(request: Request):
    memory = request.app.state.memory
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


@router.post("/memory/clear")
async def clear_memory(request: Request):
    import os as _os
    memory_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "local_memory.json")
    try:
        if _os.path.exists(memory_file):
            _os.remove(memory_file)
            logger.info("Local memory file cleared")
        memory = request.app.state.memory
        if memory:
            memory._local = []
        return {"status": "ok", "message": "Memory cleared"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
