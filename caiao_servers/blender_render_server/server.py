"""Blender Render CAIAO Server — animation rendering and preview via Blender."""

import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from blender_pipeline.common import find_blender, run_blender_script, get_pipeline_paths, find_video_file

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("blender_render")

_paths = get_pipeline_paths()
OUTPUT_DIR = _paths["output_dir"]

server = Server("blender-render")


TOOLS = [
    Tool(
        name="render_animation",
        description=(
            "Render the demolition animation to MP4 video using Blender's OpenGL viewport rendering. "
            "Requires a scene_final.blend with animation keyframes already applied. "
            "Renders in UI mode (no --background) for GPU-accelerated color output. "
            "Output: MP4 video file (H.264, default 1280x720, 24fps)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "blend_input": {
                    "type": "string",
                    "description": "Path to the input scene_final.blend file. Required.",
                },
                "resolution_x": {
                    "type": "integer",
                    "description": "Output width in pixels (default 1280).",
                    "default": 1280,
                },
                "resolution_y": {
                    "type": "integer",
                    "description": "Output height in pixels (default 720).",
                    "default": 720,
                },
                "fps": {
                    "type": "integer",
                    "description": "Frames per second (default 24).",
                    "default": 24,
                },
                "output_dir": {
                    "type": "string",
                    "description": "Custom output directory for the video file.",
                },
            },
            "required": ["blend_input"],
        },
    ),
    Tool(
        name="render_preview",
        description=(
            "Render a fast white-model preview video using Blender's Workbench engine (~0.1s/frame). "
            "Low resolution (640x360), for verifying camera framing and animation timing before "
            "committing to a full-quality render. Works in background mode."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "blend_input": {
                    "type": "string",
                    "description": "Path to the input .blend file (scene_animated or scene_final). Required.",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Custom output directory for the preview video.",
                },
            },
            "required": ["blend_input"],
        },
    ),
]


def _attach_video_info(result, output_dir):
    path, size_mb = find_video_file(output_dir)
    if path:
        result["video_file"] = path
        result["video_size_mb"] = size_mb
    return result


def _handle_render_animation(arguments):
    blend_input = arguments["blend_input"]
    output_dir = arguments.get("output_dir", os.path.dirname(blend_input))
    os.makedirs(output_dir, exist_ok=True)

    env_extra = {"BLENDER_OUTPUT_DIR": output_dir}
    result = run_blender_script("render.py", blend_input=blend_input, env_extra=env_extra, timeout=1200, background=False)
    return _attach_video_info(result, output_dir)


def _handle_render_preview(arguments):
    blend_input = arguments["blend_input"]
    output_dir = arguments.get("output_dir", os.path.join(OUTPUT_DIR, "preview"))
    os.makedirs(output_dir, exist_ok=True)

    env_extra = {"BLENDER_OUTPUT_DIR": output_dir}
    result = run_blender_script("preview_render.py", blend_input=blend_input, env_extra=env_extra, timeout=600, background=True)
    return _attach_video_info(result, output_dir)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "render_animation":
            result = await asyncio.wait_for(
                asyncio.to_thread(_handle_render_animation, arguments),
                timeout=1500.0,
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

        elif name == "render_preview":
            result = await asyncio.wait_for(
                asyncio.to_thread(_handle_render_preview, arguments),
                timeout=900.0,
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except asyncio.TimeoutError:
        return [TextContent(type="text", text=json.dumps({"error": "Render timed out"}))]
    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
