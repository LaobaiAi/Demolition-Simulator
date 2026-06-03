"""Blender Build CAIAO Server — procedural frame structure generation via Blender."""

import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from blender_pipeline.common import find_blender, run_blender_script, get_pipeline_paths, write_runtime_config

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("blender_build")

_paths = get_pipeline_paths()
OUTPUT_DIR = _paths["output_dir"]

server = Server("blender-build")


TOOLS = [
    Tool(
        name="build_frame_model",
        description=(
            "Generate a parametric reinforced concrete frame structure in Blender. "
            "Creates 139 individual elements (columns, beams, slabs, foundations) each with "
            "8 metadata properties (element_type, floor, grid_x/y, bay_x/y, importance, label_cn). "
            "Output: scene_base.blend. Config is read from blender_pipeline/data/project_config.json "
            "and can be partially overridden."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "config_override": {
                    "type": "object",
                    "description": "Override specific building parameters (stories, bays_x, bays_y, bay_width_x, bay_width_y, story_height, column_size, beam_width, beam_height, slab_thickness). Only specify what you want to change.",
                    "properties": {
                        "stories": {"type": "integer"},
                        "bays_x": {"type": "integer"},
                        "bays_y": {"type": "integer"},
                        "bay_width_x": {"type": "number"},
                        "bay_width_y": {"type": "number"},
                        "story_height": {"type": "number"},
                        "column_size": {"type": "number"},
                        "beam_width": {"type": "number"},
                        "beam_height": {"type": "number"},
                        "slab_thickness": {"type": "number"},
                    },
                },
                "output_dir": {
                    "type": "string",
                    "description": "Custom output directory for the .blend file. Defaults to blender_pipeline/output/blend/",
                },
            },
            "required": [],
        },
    ),
]


def _handle_build_frame_model(arguments):
    output_dir = arguments.get("output_dir", os.path.join(OUTPUT_DIR, "blend"))
    os.makedirs(output_dir, exist_ok=True)

    config_override = arguments.get("config_override")
    if config_override:
        env_extra = {"BLENDER_OUTPUT_DIR": output_dir}
        env_extra.update(write_runtime_config(config_override, output_dir))
    else:
        env_extra = {"BLENDER_OUTPUT_DIR": output_dir}

    result = run_blender_script("generate_building.py", env_extra=env_extra, timeout=120)

    if result.get("success"):
        blend_path = os.path.join(output_dir, "scene_base.blend")
        result["blend_file"] = blend_path if os.path.exists(blend_path) else None
        result["output_dir"] = output_dir

    return result


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "build_frame_model":
            result = await asyncio.wait_for(
                asyncio.to_thread(_handle_build_frame_model, arguments),
                timeout=180.0,
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except asyncio.TimeoutError:
        return [TextContent(type="text", text=json.dumps({"error": "Build timed out (>180s)"}))]
    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
