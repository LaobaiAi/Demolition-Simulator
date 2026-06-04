"""Server management REST endpoints."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/servers", tags=["servers"])


@router.get("")
async def list_servers_status(request: Request):
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    return {"servers": hub.get_all_status()}


@router.get("/health")
async def servers_health(request: Request):
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    return {"health": hub.get_all_health()}


@router.get("/metrics")
async def servers_metrics(request: Request):
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    return {"metrics": hub._metrics}


@router.post("/{server_name}/restart")
async def restart_server(server_name: str, request: Request):
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    success = await hub.restart_server(server_name)
    return {"status": "ok" if success else "error"}


@router.post("/{server_name}/pause")
async def pause_server(server_name: str, request: Request):
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    await hub.pause_server(server_name)
    return {"status": "ok"}


@router.post("/{server_name}/resume")
async def resume_server(server_name: str, request: Request):
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    success = await hub.restart_server(server_name)
    return {"status": "ok" if success else "error"}


@router.post("/{server_name}/stop")
async def stop_server(server_name: str, request: Request):
    hub = request.app.state.hub
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    await hub.stop_server(server_name)
    return {"status": "ok"}
