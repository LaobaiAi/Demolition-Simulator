"""Blender Animate CAIAO Server — demolition animation keyframing via Blender."""

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
logger = logging.getLogger("blender_animate")

_paths = get_pipeline_paths()
OUTPUT_DIR = _paths["output_dir"]

server = Server("blender-animate")


TOOLS = [
    Tool(
        name="apply_demolition_sequence",
        description=(
            "Apply demolition animation keyframes to a frame structure scene. "
            "Scans all elements' metadata, sorts by demolition strategy "
            "(floor→importance→type→position), groups them, and sets visibility/scale/location "
            "keyframes for progressive collapse animation. "
            "Output: scene_animated.blend + computed_demolition_schedule.csv."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "blend_input": {
                    "type": "string",
                    "description": "Path to the input scene_base.blend file. Required.",
                },
                "demolition_mode": {
                    "type": "string",
                    "enum": ["by_floor_type", "single", "by_type", "by_floor"],
                    "description": "Grouping mode: by_floor_type (default, slabs→beams→columns per floor), single (one by one), by_type (all slabs→all beams→all columns), by_floor (entire floor at once).",
                    "default": "by_floor_type",
                },
                "frame_per_step": {
                    "type": "integer",
                    "description": "Frames per demolition step group (default 24). Higher = slower animation.",
                    "default": 24,
                },
                "transition_frames": {
                    "type": "integer",
                    "description": "Frames for the scale+drop transition effect (default 8).",
                    "default": 8,
                },
                "overlap_frames": {
                    "type": "integer",
                    "description": "Overlap frames between consecutive groups (default 4).",
                    "default": 4,
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


def _handle_apply_demolition(arguments):
    blend_input = arguments["blend_input"]
    output_dir = arguments.get("output_dir", os.path.dirname(blend_input))
    os.makedirs(output_dir, exist_ok=True)

    env_extra = {"BLENDER_OUTPUT_DIR": output_dir}
    result = run_blender_script("apply_demolition.py", blend_input=blend_input, env_extra=env_extra, timeout=300)

    if result.get("success"):
        blend_path = os.path.join(output_dir, "scene_animated.blend")
        csv_path = os.path.join(os.path.dirname(output_dir), "computed_demolition_schedule.csv")
        result["blend_file"] = blend_path if os.path.exists(blend_path) else None
        result["schedule_csv"] = csv_path if os.path.exists(csv_path) else None
        result["output_dir"] = output_dir

    return result


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "apply_demolition_sequence":
            result = await asyncio.wait_for(
                asyncio.to_thread(_handle_apply_demolition, arguments),
                timeout=360.0,
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except asyncio.TimeoutError:
        return [TextContent(type="text", text=json.dumps({"error": "Animation timed out (>360s)"}))]
    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
