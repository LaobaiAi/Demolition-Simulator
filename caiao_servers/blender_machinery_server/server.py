"""Blender Machinery CAIAO Server — construction machinery addition via Blender."""

import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from blender_pipeline.common import find_blender, run_blender_script, get_pipeline_paths

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("blender_machinery")

_paths = get_pipeline_paths()
OUTPUT_DIR = _paths["output_dir"]

server = Server("blender-machinery")


TOOLS = [
    Tool(
        name="add_construction_machinery",
        description=(
            "Add construction machinery (excavator with breaker hammer, dump truck) "
            "to an existing demolition animation scene. The machinery can optionally be animated "
            "with movement keyframes. If machinery is disabled, simply copies scene_animated.blend "
            "to scene_final.blend. Output: scene_final.blend."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "blend_input": {
                    "type": "string",
                    "description": "Path to the input scene_animated.blend file. Required.",
                },
                "enable_machinery": {
                    "type": "boolean",
                    "description": "Whether to add machinery models (default true). Set false to skip.",
                    "default": True,
                },
                "excavator_position": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Excavator start position [x, y, z]. Default [8, -5, 0].",
                },
                "truck_position": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Dump truck start position [x, y, z]. Default [-10, -5, 0].",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Custom output directory. Defaults to same dir as blend_input.",
                },
            },
            "required": ["blend_input"],
        },
    ),
]


def _handle_add_machinery(arguments):
    blend_input = arguments["blend_input"]
    output_dir = arguments.get("output_dir", os.path.dirname(blend_input))
    os.makedirs(output_dir, exist_ok=True)

    env_extra = {"BLENDER_OUTPUT_DIR": output_dir}
    result = run_blender_script("add_machinery.py", blend_input=blend_input, env_extra=env_extra, timeout=120)

    if result.get("success"):
        blend_path = os.path.join(output_dir, "scene_final.blend")
        result["blend_file"] = blend_path if os.path.exists(blend_path) else None
        result["output_dir"] = output_dir

    return result


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "add_construction_machinery":
            result = await asyncio.wait_for(
                asyncio.to_thread(_handle_add_machinery, arguments),
                timeout=180.0,
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except asyncio.TimeoutError:
        return [TextContent(type="text", text=json.dumps({"error": "Machinery addition timed out (>180s)"}))]
    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
