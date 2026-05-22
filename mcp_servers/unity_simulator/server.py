"""Unity Simulator MCP Server — sends demolition commands to Unity via TCP."""

import asyncio
import json
import logging
import socket
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("unity_simulator")

UNITY_HOST = "127.0.0.1"
UNITY_PORT = 5005

app = Server("unity-simulator")

TOOLS = [
    Tool(
        name="apply_demolition_action",
        description=(
            "Trigger a demolition animation in the Unity simulation. "
            "Specify which structural elements should fail and the force multiplier "
            "to control the collapse intensity."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "failed_elements": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of element IDs to demolish (0-based). At least one required.",
                },
                "force_multiplier": {
                    "type": "number",
                    "description": "Multiplier for demolition forces (default 1.5). Higher = more dramatic collapse.",
                    "default": 1.5,
                },
                "structure_summary": {
                    "type": "object",
                    "description": "Optional structure metadata for context display in Unity",
                    "properties": {
                        "spans": {"type": "integer"},
                        "stories": {"type": "integer"},
                        "max_displacement": {"type": "number"},
                        "max_axial_force": {"type": "number"},
                    },
                },
            },
            "required": ["failed_elements"],
        },
    ),
    Tool(
        name="reset_simulation",
        description="Reset the Unity simulation scene to its initial state.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
]


def _send_to_unity(command: dict[str, Any]) -> dict[str, Any]:
    """Send a JSON command to Unity via TCP socket."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((UNITY_HOST, UNITY_PORT))
        payload = json.dumps(command)
        sock.sendall(payload.encode("utf-8"))
        # Read response (Unity echoes back status)
        response_data = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b"\n" in response_data:
                    break
        except socket.timeout:
            pass
        sock.close()

        if response_data:
            return json.loads(response_data.decode("utf-8").strip())
        return {"status": "sent", "command": command}
    except ConnectionRefusedError:
        return {"error": f"Unity not reachable at {UNITY_HOST}:{UNITY_PORT}. Start the Unity simulation first."}
    except socket.timeout:
        return {"error": "Unity connection timed out"}
    except Exception as e:
        return {"error": str(e)}


@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "apply_demolition_action":
            failed_elements = arguments.get("failed_elements", [])
            if not failed_elements:
                return [TextContent(type="text", text=json.dumps({"error": "At least one failed_element ID is required"}))]

            command = {
                "action": "demolish",
                "failed_elements": failed_elements,
                "force_multiplier": arguments.get("force_multiplier", 1.5),
            }
            if "structure_summary" in arguments:
                command["structure_summary"] = arguments["structure_summary"]

            result = _send_to_unity(command)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "reset_simulation":
            command = {"action": "reset"}
            result = _send_to_unity(command)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        else:
            return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]

    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
