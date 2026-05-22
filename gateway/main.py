"""XuanwuAI Gateway — FastAPI application entry point."""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mcp_hub import MCPClientHub
from llm_engine import LLMEngine
from agent_loop import AgentLoop
from memory import SessionMemory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")

# --- MCP Server configurations ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MCP_SERVERS_DIR = os.path.join(os.path.dirname(BASE_DIR), "mcp_servers")
VENV_PYTHON = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")

SERVER_CONFIGS = [
    {
        "name": "demo_calculator",
        "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
        "args": ["server.py"],
        "cwd": os.path.join(MCP_SERVERS_DIR, "demo_calculator"),
    },
    {
        "name": "anastruct_server",
        "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
        "args": ["server.py"],
        "cwd": os.path.join(MCP_SERVERS_DIR, "anastruct_server"),
    },
    {
        "name": "opensees_server",
        "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
        "args": ["server.py"],
        "cwd": os.path.join(MCP_SERVERS_DIR, "opensees_server"),
    },
    {
        "name": "unity_simulator",
        "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
        "args": ["server.py"],
        "cwd": os.path.join(MCP_SERVERS_DIR, "unity_simulator"),
    },
]

hub: MCPClientHub | None = None
agent: AgentLoop | None = None
memory: SessionMemory | None = None
llm_engine: LLMEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global hub, agent, memory, llm_engine
    logger.info("Starting MCP servers...")
    hub = MCPClientHub(SERVER_CONFIGS)
    await hub.start_all()
    llm_engine = LLMEngine()
    agent = AgentLoop(llm_engine, hub)
    memory = SessionMemory()
    logger.info("Gateway ready (LLM + Agent loop + Memory active)")
    yield
    logger.info("Shutting down MCP servers...")
    if hub:
        await hub.stop_all()
    logger.info("Gateway stopped")


app = FastAPI(title="XuanwuAI Gateway", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- REST Endpoints ---

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/tools")
async def list_tools():
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    tools = await hub.list_tools()
    return {"tools": tools}


class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any]


@app.post("/tools/call")
async def call_tool(req: ToolCallRequest):
    if hub is None:
        return JSONResponse({"error": "Hub not initialized"}, status_code=503)
    result = await hub.call_tool(req.tool_name, req.arguments)
    return result


class VerifyRequest(BaseModel):
    fast_result: dict[str, Any]  # anaStruct analysis result
    structure: dict[str, Any] | None = None  # optional: frame structure for OpenSees comparison


@app.post("/verify")
async def verify_analysis(req: VerifyRequest):
    """Compare fast analysis with high-fidelity OpenSees analysis.

    If structure is provided and OpenSees is available, runs real comparison.
    Otherwise returns a clear status indicating high-fidelity is not available.
    """
    fast = req.fast_result
    max_disp_fast = fast.get("max_displacement", 0)
    max_axial_fast = fast.get("max_axial_force", 0)

    # Attempt high-fidelity comparison if structure is provided
    if hub and req.structure:
        try:
            hf_result = await hub.call_tool("high_fidelity_analysis", {"structure": req.structure})
            if hf_result and "result" in hf_result:
                import json
                hf_data = json.loads(hf_result["result"]) if isinstance(hf_result["result"], str) else hf_result["result"]
                if "error" not in hf_data:
                    max_disp_hf = hf_data.get("max_displacement", 0)
                    max_axial_hf = hf_data.get("max_axial_force", 0)
                    disp_diff = abs(max_disp_fast - max_disp_hf) / max(max_disp_fast, 1e-12) * 100
                    axial_diff = abs(max_axial_fast - max_axial_hf) / max(max_axial_fast, 1e-12) * 100
                    status = "verified" if max(disp_diff, axial_diff) < 5.0 else "warning"
                    return {
                        "status": status,
                        "demo_mode": False,
                        "comparison": {
                            "max_displacement": {"fast": round(max_disp_fast, 10), "high_fidelity": round(max_disp_hf, 10), "diff_percent": round(disp_diff, 2)},
                            "max_axial_force": {"fast": round(max_axial_fast, 2), "high_fidelity": round(max_axial_hf, 2), "diff_percent": round(axial_diff, 2)},
                        },
                    }
        except Exception:
            pass

    return {
        "status": "unavailable",
        "demo_mode": True,
        "comparison": {
            "max_displacement": {"fast": round(max_disp_fast, 10), "high_fidelity": 0, "diff_percent": 0},
            "max_axial_force": {"fast": round(max_axial_fast, 2), "high_fidelity": 0, "diff_percent": 0},
        },
        "message": "High-fidelity verification (OpenSees) is not available on this platform. The fast analysis values above are computed by anaStruct linear elastic solver.",
    }


class LLMSettingsRequest(BaseModel):
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None


@app.post("/settings/llm")
async def configure_llm(req: LLMSettingsRequest):
    """Update LLM configuration at runtime from the frontend."""
    global llm_engine
    if llm_engine is None:
        return JSONResponse({"status": "error", "message": "LLM engine not initialized"}, status_code=503)
    llm_engine.configure(
        model=req.model,
        api_key=req.api_key,
        base_url=req.base_url,
    )
    return {
        "status": "ok",
        "config": {
            "model": llm_engine.model,
            "base_url": llm_engine.base_url or "default (OpenAI)",
            "has_api_key": bool(llm_engine.api_key),
        },
    }


@app.get("/settings/llm")
async def get_llm_config():
    """Get current LLM configuration (no secrets)."""
    global llm_engine
    if llm_engine is None:
        return JSONResponse({"status": "error", "message": "LLM engine not initialized"}, status_code=503)
    return {
        "model": llm_engine.model,
        "base_url": llm_engine.base_url or "",
        "has_api_key": bool(llm_engine.api_key),
    }


# --- WebSocket for Chat ---

@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    history: list[dict[str, Any]] = []
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "message")

            if msg_type == "message":
                user_message = msg.get("content", "").strip()
                if not user_message:
                    continue

                # Echo user message back so frontend can display it
                await websocket.send_json({
                    "type": "user_echo",
                    "content": user_message,
                })

                if agent and hub:
                    # Retrieve relevant memories
                    memory_context = ""
                    if memory:
                        memory_context = memory.get_memory_context(user_message)
                        if memory_context:
                            await websocket.send_json({
                                "type": "memory",
                                "content": memory_context,
                            })

                    # Run the agent loop with memory context
                    try:
                        steps = await agent.run(user_message, history, memory_context)
                        for step in steps:
                            await websocket.send_json(step)
                            await asyncio.sleep(0.05)

                        # Update conversation history
                        history.append({"role": "user", "content": user_message})
                        final_content = ""
                        for step in steps:
                            if step["type"] == "response":
                                final_content = step["content"]
                        if final_content:
                            history.append({"role": "assistant", "content": final_content})

                        # Store exchange in persistent memory
                        if memory:
                            memory.add(f"User: {user_message}")
                            if final_content:
                                memory.add(f"Assistant: {final_content}")

                        # Trim history to prevent context overflow (keep last 20)
                        if len(history) > 20:
                            history = history[-20:]

                    except Exception as e:
                        logger.exception("Agent loop error")
                        await websocket.send_json({
                            "type": "error",
                            "content": f"Agent error: {e}",
                        })
                else:
                    await websocket.send_json({
                        "type": "response",
                        "content": "Agent not initialized. Check server configuration.",
                    })

            elif msg_type == "tool_call" and hub:
                tool_name = msg.get("tool_name", "")
                arguments = msg.get("arguments", {})
                result = await hub.call_tool(tool_name, arguments)
                await websocket.send_json({
                    "type": "tool_result",
                    "tool": tool_name,
                    "result": result,
                })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.exception("WebSocket error")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
