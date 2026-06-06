"""Blender Build CAIAO Server — procedural frame/structure generation via Blender.

Supports standard RC frames (generate_building.py) and steam turbine buildings
(build_steam_turbine_model.py) based on the building_type parameter.
"""

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
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

server = Server("blender-build")


TOOLS = [
    Tool(
        name="build_frame_model",
        description=(
            "Generate a parametric reinforced concrete frame structure in Blender, "
            "or a steam turbine building (building_type=steam_turbine). "
            "Output: scene_base.blend."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "building_type": {
                    "type": "string",
                    "description": "Building type: 'standard' (RC frame) or 'steam_turbine' (industrial turbine building with trusses and AB/BC bays)",
                    "enum": ["standard", "steam_turbine"],
                },
                "config_override": {
                    "type": "object",
                    "description": "Override specific building parameters for standard frame.",
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
    building_type = arguments.get("building_type", "standard")
    output_dir = arguments.get("output_dir", os.path.join(OUTPUT_DIR, "blend"))
    os.makedirs(output_dir, exist_ok=True)

    if building_type == "steam_turbine":
        # Path to the steam turbine default config
        steam_cfg = os.path.join(
            _BASE_DIR, "blender_pipeline", "projects", "steam_turbine_building", "data", "config.json"
        )
        env_extra = {
            "BLENDER_OUTPUT_DIR": output_dir,
            "BLENDER_CONFIG_PATH": steam_cfg,
        }
        result = run_blender_script("build_steam_turbine_model.py", env_extra=env_extra, timeout=300)
    else:
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
        result["building_type"] = building_type
        # Extract base64 preview image from Blender output
        output_lines = result.get("output", [])
        capturing, b64_parts = False, []
        for line in output_lines:
            if line.startswith("[PREVIEW_BASE64] "):
                capturing = True
                b64_parts.append(line[len("[PREVIEW_BASE64] "):])
            elif capturing:
                if line == "[PREVIEW_END]":
                    capturing = False
                else:
                    b64_parts.append(line)
        if b64_parts:
            result["preview_image"] = "".join(b64_parts)

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
                timeout=300.0,
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except asyncio.TimeoutError:
        return [TextContent(type="text", text=json.dumps({"error": "Build timed out (>300s)"}))]
    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
