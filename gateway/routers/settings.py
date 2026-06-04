"""Settings REST endpoints — LLM config + memory management."""

import json
import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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
    return {
        "model": llm.model,
        "base_url": llm.base_url or "",
        "has_api_key": bool(llm.api_key),
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
