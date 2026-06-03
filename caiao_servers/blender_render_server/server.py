"""Blender Render CAIAO Server — animation rendering and preview via Blender."""

import asyncio
import json
import logging
import os
import subprocess

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("blender_render")

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SERVER_DIR))
BLENDER_PIPELINE_DIR = os.path.join(PROJECT_ROOT, "blender_pipeline")
SCRIPTS_DIR = os.path.join(BLENDER_PIPELINE_DIR, "scripts")
OUTPUT_DIR = os.path.join(BLENDER_PIPELINE_DIR, "output")

server = Server("blender-render")


def _find_blender():
    exe = os.environ.get("BLENDER_EXE", "")
    if exe and os.path.exists(exe):
        return exe
    portable = os.path.join(BLENDER_PIPELINE_DIR, "blender_portable", "blender-4.2.8-windows-x64", "blender.exe")
    if os.path.exists(portable):
        return portable
    for p in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(p, "blender.exe")
        if os.path.exists(candidate):
            return candidate
    return None


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


def _run_blender_script(script_name, blend_input=None, env_extra=None, timeout=1200, background=True):
    blender_exe = _find_blender()
    if not blender_exe:
        return {"error": "Blender not found. Set BLENDER_EXE env var or install Blender."}

    script_path = os.path.join(SCRIPTS_DIR, script_name)
    if not os.path.exists(script_path):
        return {"error": f"Script not found: {script_path}"}

    cmd = [blender_exe]
    if background:
        cmd.append("--background")
    if blend_input and os.path.exists(blend_input):
        cmd.append(blend_input)
    cmd.extend(["--python", script_path])

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace', env=env)
        output_lines = [l.strip() for l in r.stdout.split('\n') if l.strip()]
        if r.returncode != 0:
            error_lines = [l.strip() for l in r.stderr.split('\n') if l.strip()][:10]
            return {"error": f"Blender exited with code {r.returncode}", "stderr": error_lines, "stdout": output_lines[-20:]}
        return {"status": "ok", "returncode": 0, "output": output_lines}
    except subprocess.TimeoutExpired:
        return {"error": f"Blender script timed out ({timeout}s)"}
    except Exception as e:
        return {"error": str(e)}


def _handle_render_animation(arguments):
    blend_input = arguments["blend_input"]
    output_dir = arguments.get("output_dir", os.path.dirname(blend_input))
    os.makedirs(output_dir, exist_ok=True)

    env_extra = {"BLENDER_OUTPUT_DIR": output_dir}
    result = _run_blender_script("render.py", blend_input=blend_input, env_extra=env_extra, timeout=1200, background=False)

    if result.get("status") == "ok":
        for root, dirs, files in os.walk(output_dir):
            for fn in files:
                if fn.endswith('.mp4'):
                    result["video_file"] = os.path.join(root, fn)
                    result["video_size_mb"] = round(os.path.getsize(os.path.join(root, fn)) / 1024 / 1024, 1)
                    break

    return result


def _handle_render_preview(arguments):
    blend_input = arguments["blend_input"]
    output_dir = arguments.get("output_dir", os.path.join(OUTPUT_DIR, "preview"))
    os.makedirs(output_dir, exist_ok=True)

    env_extra = {"BLENDER_OUTPUT_DIR": output_dir}
    result = _run_blender_script("preview_render.py", blend_input=blend_input, env_extra=env_extra, timeout=600, background=True)

    if result.get("status") == "ok":
        for root, dirs, files in os.walk(output_dir):
            for fn in files:
                if fn.endswith('.mp4'):
                    result["video_file"] = os.path.join(root, fn)
                    result["video_size_mb"] = round(os.path.getsize(os.path.join(root, fn)) / 1024 / 1024, 1)
                    break

    return result


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
