"""Blender Build CAIAO Server — procedural frame structure generation via Blender."""

import asyncio
import json
import logging
import os
import subprocess

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("blender_build")

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SERVER_DIR))
BLENDER_PIPELINE_DIR = os.path.join(PROJECT_ROOT, "blender_pipeline")
SCRIPTS_DIR = os.path.join(BLENDER_PIPELINE_DIR, "scripts")
OUTPUT_DIR = os.path.join(BLENDER_PIPELINE_DIR, "output")

server = Server("blender-build")


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


def _handle_build_frame_model(arguments):
    output_dir = arguments.get("output_dir", os.path.join(OUTPUT_DIR, "blend"))
    os.makedirs(output_dir, exist_ok=True)

    config_override = arguments.get("config_override")
    if config_override:
        config_path = os.path.join(BLENDER_PIPELINE_DIR, "data", "project_config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        config["building"].update(config_override)
        tmp_config_path = os.path.join(output_dir, "_runtime_config.json")
        with open(tmp_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        env_extra = {"BLENDER_OUTPUT_DIR": output_dir, "BLENDER_CONFIG_OVERRIDE": tmp_config_path}
    else:
        env_extra = {"BLENDER_OUTPUT_DIR": output_dir}

    result = _run_blender_script("generate_building.py", env_extra=env_extra, timeout=120)

    if result.get("status") == "ok":
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
