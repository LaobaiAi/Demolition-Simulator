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
            "Remove structural elements and trigger collapse animation in the frontend. "
            "Pass the full current structure to get back a modified version (without failed elements) "
            "for progressive re-analysis. Specify which elements fail and the force multiplier."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "failed_elements": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of element IDs to demolish. At least one required.",
                },
                "force_multiplier": {
                    "type": "number",
                    "description": "Multiplier for demolition forces (default 1.5).",
                    "default": 1.5,
                },
                "structure": {
                    "type": "object",
                    "description": "The full current structure including nodes, elements, loads, supports. Required for progressive re-analysis.",
                    "properties": {
                        "nodes": {"type": "array"},
                        "elements": {"type": "array"},
                        "loads": {"type": "array"},
                        "supports": {"type": "array"},
                    },
                },
                "round": {
                    "type": "integer",
                    "description": "Current demolition round number (1-based).",
                    "default": 1,
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

            round_num = arguments.get("round", 1)
            structure = arguments.get("structure")

            # Compute modified structure (without failed elements) for progressive re-analysis
            modified_structure = None
            collapsed = False
            remaining_columns = 0
            total_columns_original = 0
            if structure and "elements" in structure:
                orig_elements = structure.get("elements", [])
                # Filter out failed elements
                failed_set = set(failed_elements)
                modified_elements = [e for e in orig_elements if e.get("id") not in failed_set]
                modified_structure = {
                    "nodes": structure.get("nodes", []),
                    "elements": modified_elements,
                    "loads": structure.get("loads", []),
                    "supports": structure.get("supports", []),
                }
                # Count remaining columns and detect collapse
                if modified_structure["nodes"] and modified_elements:
                    nodes_by_id = {n["id"]: n for n in modified_structure["nodes"]}
                    total_columns_original = sum(1 for e in orig_elements
                        if abs(nodes_by_id.get(e.get("node_i"), {}).get("x", -999) -
                               nodes_by_id.get(e.get("node_j"), {}).get("x", 999)) < 0.01)
                    for elem in modified_elements:
                        ni = nodes_by_id.get(elem.get("node_i"))
                        nj = nodes_by_id.get(elem.get("node_j"))
                        if ni and nj and abs(ni.get("x", 0) - nj.get("x", 0)) < 0.01:
                            remaining_columns += 1
                # Collapse detection: no columns left, or >2/3 columns lost (progressive collapse threshold)
                if remaining_columns == 0 or (total_columns_original > 0 and remaining_columns < total_columns_original * 0.34):
                    collapsed = True

            # Try Unity, fall back to simulated
            command = {
                "action": "demolish",
                "failed_elements": failed_elements,
                "force_multiplier": arguments.get("force_multiplier", 1.5),
            }
            unity_result = _send_to_unity(command)

            result = {
                "status": "completed",
                "round": round_num,
                "failed_elements": failed_elements,
                "force_multiplier": arguments.get("force_multiplier", 1.5),
                "collapsed": collapsed,
                "remaining_columns": remaining_columns,
                "note": f"Round {round_num}: {len(failed_elements)} element(s) removed. {remaining_columns} columns remaining." + (" STRUCTURE COLLAPSED!" if collapsed else ""),
            }
            if modified_structure:
                result["modified_structure"] = modified_structure

            if "error" in unity_result:
                result["status"] = "simulated"

            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "reset_simulation":
            command = {"action": "reset"}
            result = _send_to_unity(command)
            if "error" in result:
                result = {"status": "simulated", "action": "reset", "note": "Scene reset in browser."}
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
