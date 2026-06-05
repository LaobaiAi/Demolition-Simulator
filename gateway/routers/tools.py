"""Tools & scenarios REST endpoints."""

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tools"])

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent
CAIAO_SERVERS_DIR = PROJECT_DIR / "caiao_servers"
FRONTEND_DIR = PROJECT_DIR / "frontend"

_system_prompt_cache: str | None = None
_frontend_identifiers_cache: set[str] | None = None
_pipeline_tool_names_cache: set[str] | None = None


def _get_system_prompt() -> str:
    global _system_prompt_cache
    if _system_prompt_cache is None:
        from llm_engine import SYSTEM_PROMPT
        _system_prompt_cache = SYSTEM_PROMPT
    return _system_prompt_cache


def _tool_in_system_prompt(name: str) -> bool:
    prompt = _get_system_prompt()
    return bool(re.search(r'\b' + re.escape(name) + r'\b', prompt))


def _build_frontend_identifiers() -> set[str]:
    identifiers: set[str] = set()

    if not FRONTEND_DIR.exists():
        return identifiers

    try:
        result = subprocess.run(
            ["git", "grep", "-oh", r'\b[a-z][a-z0-9_]{2,60}\b', "--", "*.tsx", "*.ts"],
            cwd=str(FRONTEND_DIR),
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "PAGER": ""},
        )
        if result.returncode == 0 and result.stdout:
            for word in result.stdout.strip().split("\n"):
                word = word.strip()
                if word and len(word) > 3:
                    identifiers.add(word)
            return identifiers
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        logger.warning("git grep failed for frontend scan, using Python fallback")

    for root, _dirs, files in os.walk(str(FRONTEND_DIR)):
        for fname in files:
            if not (fname.endswith(".tsx") or fname.endswith(".ts")):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue
            for match in re.finditer(r'\b[a-z][a-z0-9_]{3,60}\b', content):
                identifiers.add(match.group(0))

    return identifiers


def _build_pipeline_cache() -> set[str]:
    names: set[str] = set()
    if not CAIAO_SERVERS_DIR.exists():
        return names

    for yaml_path in CAIAO_SERVERS_DIR.rglob("caiao.yaml"):
        try:
            content = yaml_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        in_pipeline = False
        pipeline_indent: int | None = None

        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue

            current_indent = len(line) - len(line.lstrip(" "))

            if stripped == "pipeline:" or stripped.startswith("pipeline:"):
                in_pipeline = True
                pipeline_indent = current_indent
                continue

            if in_pipeline:
                if pipeline_indent is not None and current_indent <= pipeline_indent and stripped:
                    in_pipeline = False
                    pipeline_indent = None
                    continue

                if stripped.startswith("tool:"):
                    tool_name = stripped.split(":", 1)[1].strip()
                    if tool_name:
                        names.add(tool_name)

    return names


class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any]


@router.get("/tools")
async def list_tools(request: Request):
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    tools = await hub.list_tools()
    return {"tools": tools}


@router.get("/tools/orphans")
async def find_orphan_tools(request: Request):
    global _frontend_identifiers_cache, _pipeline_tool_names_cache

    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)

    if _frontend_identifiers_cache is None:
        _frontend_identifiers_cache = _build_frontend_identifiers()
    if _pipeline_tool_names_cache is None:
        _pipeline_tool_names_cache = _build_pipeline_cache()

    tools = await hub.list_tools()

    orphans: list[dict] = []
    fragile: list[dict] = []
    robust: list[dict] = []

    for tool in tools:
        name = tool.get("name", "")
        llm_hit = _tool_in_system_prompt(name)
        frontend_hit = name in _frontend_identifiers_cache
        pipeline_hit = name in _pipeline_tool_names_cache

        reachability = {
            "llm_path": llm_hit,
            "frontend_path": frontend_hit,
            "pipeline_path": pipeline_hit,
        }
        path_count = sum([llm_hit, frontend_hit, pipeline_hit])

        entry = {
            "name": name,
            "server": tool.get("server", ""),
            "description": tool.get("description", ""),
            "input_schema": tool.get("input_schema", {}),
            "reachability": reachability,
            "paths": path_count,
        }

        if path_count == 0:
            orphans.append(entry)
        elif path_count == 1:
            fragile.append(entry)
        else:
            robust.append(entry)

    return {
        "orphans": orphans,
        "fragile": fragile,
        "robust": robust,
        "summary": {
            "total_tools": len(tools),
            "orphan_count": len(orphans),
            "fragile_count": len(fragile),
            "robust_count": len(robust),
        },
    }


@router.post("/tools/call")
async def call_tool(req: ToolCallRequest, request: Request):
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    result = await hub.call_tool(req.tool_name, req.arguments)
    return result


@router.get("/scenarios")
async def list_scenarios(request: Request, category: str | None = None, tag: str | None = None):
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    args: dict[str, Any] = {}
    if category:
        args["category"] = category
    if tag:
        args["tag"] = tag
    result = await hub.call_tool("list_scenarios", args)
    return result


@router.get("/scenarios/{name}")
async def get_scenario(name: str, request: Request):
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    result = await hub.call_tool("get_scenario", {"name": name})
    return result
