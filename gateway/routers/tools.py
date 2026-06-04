"""Tools & scenarios REST endpoints."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any

router = APIRouter(tags=["tools"])


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
