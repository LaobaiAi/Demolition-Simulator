"""Blender Machinery CAIAO Server — construction machinery addition via Blender."""

import asyncio
import json
import logging
import os
import subprocess

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("blender_machinery")

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SERVER_DIR))
BLENDER_PIPELINE_DIR = os.path.join(PROJECT_ROOT, "blender_pipeline")
SCRIPTS_DIR = os.path.join(BLENDER_PIPELINE_DIR, "scripts")
OUTPUT_DIR = os.path.join(BLENDER_PIPELINE_DIR, "output")

server = Server("blender-machinery")


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


def _run_blender_script(script_name, blend_input=None, env_extra=None, timeout=120):
    blender_exe = _find_blender()
    if not blender_exe:
        return {"error": "Blender not found. Set BLENDER_EXE env var or install Blender."}

    script_path = os.path.join(SCRIPTS_DIR, script_name)
    if not os.path.exists(script_path):
        return {"error": f"Script not found: {script_path}"}

    cmd = [blender_exe, "--background"]
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


def _handle_add_machinery(arguments):
    blend_input = arguments["blend_input"]
    output_dir = arguments.get("output_dir", os.path.dirname(blend_input))
    os.makedirs(output_dir, exist_ok=True)

    env_extra = {"BLENDER_OUTPUT_DIR": output_dir}

    result = _run_blender_script("add_machinery.py", blend_input=blend_input, env_extra=env_extra, timeout=120)

    if result.get("status") == "ok":
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
