"""Abaqus solve status + control REST endpoints — proxy to the
abaqus_session_server tools (get_collapse_status / stop_collapse)."""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["abaqus"])

TOWER_JOB_ID = "tower_job_run"


def _parse_tool_result(result) -> tuple[dict | None, str | None]:
    if not isinstance(result, dict):
        return None, "unexpected response from server"
    if "error" in result:
        return None, str(result["error"])
    raw = result.get("result", "{}")
    if isinstance(raw, dict):
        return raw, None
    if isinstance(raw, str):
        try:
            return json.loads(raw), None
        except json.JSONDecodeError:
            return None, "invalid JSON from server"
    return None, "unexpected response from server"


@router.get("/api/abaqus/solve-status")
async def abaqus_solve_status(request: Request):
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    result = await hub.call_tool(
        "get_collapse_status", {"job_id": TOWER_JOB_ID, "wait_seconds": 0})
    data, err = _parse_tool_result(result)
    if err:
        return JSONResponse({"error": err}, status_code=502)
    return data


@router.post("/api/abaqus/solve-stop")
async def abaqus_solve_stop(request: Request):
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    result = await hub.call_tool("stop_collapse", {"job_id": TOWER_JOB_ID})
    data, err = _parse_tool_result(result)
    if err:
        return JSONResponse({"error": err}, status_code=502)
    return data
