"""Blender Pipeline CAIAO Server — full demolition animation pipeline orchestrator.

Chains the 4 pipeline stages (build → animate → machinery → render) into a single
end-to-end workflow. Each stage can also be run independently.
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from blender_pipeline.common import (
    find_blender, run_blender_script, get_pipeline_paths,
    load_project_config, make_project_dir, find_video_file,
)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("blender_pipeline")

_paths = get_pipeline_paths()
SCRIPTS_DIR = _paths["scripts_dir"]
OUTPUT_BASE = _paths["output_dir"]
DATA_DIR = _paths["data_dir"]

server = Server("blender-pipeline")


STAGES = [
    ("build", "generate_building.py", None, 120, True),
    ("animate", "apply_demolition.py", None, 300, True),
    ("machinery", "add_machinery.py", None, 120, True),
    ("render", "render.py", None, 1200, False),
    ("preview", "preview_render.py", None, 600, True),
]


TOOLS = [
    Tool(
        name="run_full_pipeline",
        description=(
            "Run the complete Blender demolition animation pipeline end-to-end: "
            "build frame model → apply demolition animation → add machinery → render video. "
            "Returns paths to all intermediate and final output files."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "with_machinery": {
                    "type": "boolean",
                    "description": "Include construction machinery in the scene (default true).",
                    "default": True,
                },
                "with_render": {
                    "type": "boolean",
                    "description": "Render the final animation to MP4 video (default true). Set false to stop after animation.",
                    "default": True,
                },
                "demolition_mode": {
                    "type": "string",
                    "enum": ["by_floor_type", "single", "by_type", "by_floor"],
                    "description": "Demolition grouping mode (default by_floor_type).",
                    "default": "by_floor_type",
                },
                "config_override": {
                    "type": "object",
                    "description": "Override building parameters (stories, bays_x, bays_y, bay_width_x, etc.).",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Custom output base directory. Default creates timestamped dir under blender_pipeline/output/.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="run_pipeline_stage",
        description=(
            "Run a single stage of the Blender demolition animation pipeline. "
            "Stages: build (generate frame model), animate (apply demolition keyframes), "
            "machinery (add construction equipment), render (output MP4 video), "
            "preview (fast white-model preview)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "enum": ["build", "animate", "machinery", "render", "preview"],
                    "description": "Pipeline stage to run.",
                },
                "blend_input": {
                    "type": "string",
                    "description": "Path to input .blend file. Required for animate/machinery/render/preview stages.",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Custom output directory.",
                },
            },
            "required": ["stage"],
        },
    ),
    Tool(
        name="check_blender_environment",
        description=(
            "Check if Blender is installed and accessible. Returns Blender version "
            "and paths to pipeline scripts and data files."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
]

STAGE_BLEND_FILES = {
    "build": "scene_base.blend",
    "animate": "scene_animated.blend",
    "machinery": "scene_final.blend",
}

STAGE_REQUIRES_INPUT = {"animate", "machinery", "render", "preview"}


def _get_stage_config(stage_name):
    for s in STAGES:
        if s[0] == stage_name:
            return s
    return None


def _handle_run_full_pipeline(arguments):
    with_machinery = arguments.get("with_machinery", True)
    with_render = arguments.get("with_render", True)
    config_override = arguments.get("config_override")

    custom_out = arguments.get("output_dir")
    config = load_project_config() if (not custom_out or config_override) else None

    if custom_out:
        proj_dir = custom_out
        blend_dir = os.path.join(proj_dir, "blend")
        os.makedirs(blend_dir, exist_ok=True)
    else:
        if config_override:
            config["building"].update(config_override)
        proj_name = config.get("project_name", "demolition") if config else None
        proj_dir, blend_dir = make_project_dir(proj_name)

    results = {"pipeline": "full", "project_dir": proj_dir, "stages": {}}
    start_time = time.time()

    env_base = {"BLENDER_OUTPUT_DIR": blend_dir}
    if config_override and config:
        tmp_config = os.path.join(blend_dir, "_runtime_config.json")
        with open(tmp_config, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        env_base["BLENDER_CONFIG_OVERRIDE"] = tmp_config

    pipeline_stages = [
        ("build", "generate_building.py", None, 120, True, "scene_base.blend", "blend_file"),
        ("animate", "apply_demolition.py", None, 300, True, "scene_animated.blend", "blend_file"),
    ]

    blend_base = None
    blend_animated = None

    for stage_name, script, _, timeout, bg, blend_name, result_key in pipeline_stages:
        logger.info(f"Stage: {stage_name}...")
        blend_input = blend_base if stage_name == "animate" else None
        result = run_blender_script(script, blend_input=blend_input, env_extra=env_base, timeout=timeout, background=bg)
        ok = result.get("success", False)
        blend_path = os.path.join(blend_dir, blend_name)
        stage_result = {"success": ok, result_key: blend_path if os.path.exists(blend_path) else None}
        stage_result.update({k: v for k, v in result.items() if k != "success"})

        if stage_name == "build":
            blend_base = blend_path
            if not ok:
                results["stages"]["build"] = stage_result
                results["duration_s"] = round(time.time() - start_time, 1)
                return results
        elif stage_name == "animate":
            blend_animated = blend_path
            csv_path = os.path.join(proj_dir, "computed_demolition_schedule.csv")
            stage_result["schedule_csv"] = csv_path if os.path.exists(csv_path) else None

        results["stages"][stage_name] = stage_result
        if not ok:
            results["duration_s"] = round(time.time() - start_time, 1)
            return results

    if with_machinery:
        logger.info("Stage: machinery...")
        result = run_blender_script("add_machinery.py", blend_input=blend_animated, env_extra=env_base, timeout=120, background=True)
    else:
        blend_final = os.path.join(blend_dir, "scene_final.blend")
        shutil.copy2(blend_animated, blend_final)
        result = {"success": True, "output": ["Machinery skipped, copied scene_animated to scene_final"]}
    blend_final = os.path.join(blend_dir, "scene_final.blend")
    results["stages"]["machinery"] = {
        "success": result.get("success", False),
        "blend_file": blend_final if os.path.exists(blend_final) else None,
        **{k: v for k, v in result.items() if k != "success"},
    }

    if with_render and result.get("success"):
        logger.info("Stage: render...")
        result = run_blender_script("render.py", blend_input=blend_final, env_extra=env_base, timeout=1200, background=False)
        video_path, _ = find_video_file(proj_dir)
        results["stages"]["render"] = {
            "success": result.get("success", False),
            "video_file": video_path,
            **{k: v for k, v in result.items() if k != "success"},
        }

    results["duration_s"] = round(time.time() - start_time, 1)
    all_ok = all(s["success"] for s in results["stages"].values())
    results["status"] = "completed" if all_ok else "partial_failure"
    return results


def _handle_run_pipeline_stage(arguments):
    stage = arguments["stage"]
    blend_input = arguments.get("blend_input")
    output_dir = arguments.get("output_dir")

    stage_config = _get_stage_config(stage)
    if not stage_config:
        return {"error": f"Unknown stage: {stage}. Choose from: build, animate, machinery, render, preview"}

    _, script, _, timeout, bg = stage_config

    if stage in STAGE_REQUIRES_INPUT and not blend_input:
        return {"error": f"blend_input is required for stage '{stage}'"}

    if not output_dir:
        output_dir = os.path.dirname(blend_input) if blend_input else os.path.join(OUTPUT_BASE, "blend")
    os.makedirs(output_dir, exist_ok=True)

    env = {"BLENDER_OUTPUT_DIR": output_dir}
    result = run_blender_script(script, blend_input=blend_input, env_extra=env, timeout=timeout, background=bg)

    stage_result = {"stage": stage, "success": result.get("success", False), "output_dir": output_dir}
    stage_result.update({k: v for k, v in result.items() if k != "success"})

    if stage in STAGE_BLEND_FILES:
        path = os.path.join(output_dir, STAGE_BLEND_FILES[stage])
        if os.path.exists(path):
            stage_result["blend_file"] = path

    if stage == "render":
        video_path, _ = find_video_file(output_dir)
        if video_path:
            stage_result["video_file"] = video_path

    return stage_result


def _handle_check_environment():
    blender_exe = find_blender()
    result = {
        "blender_found": blender_exe is not None,
        "blender_path": blender_exe,
    }

    if blender_exe:
        try:
            r = subprocess.run([blender_exe, "--version"], capture_output=True, text=True,
                               timeout=30, encoding='utf-8', errors='replace')
            result["blender_version"] = r.stdout.strip().split('\n')[0] if r.returncode == 0 else None
        except Exception:
            result["blender_version"] = None

    result["pipeline_dir"] = _paths["pipeline_dir"]
    result["scripts"] = {}
    for fn in ["generate_building.py", "apply_demolition.py", "add_machinery.py", "render.py", "preview_render.py"]:
        path = os.path.join(SCRIPTS_DIR, fn)
        result["scripts"][fn] = os.path.exists(path)

    result["data_files"] = {}
    for fn in ["project_config.json", "building_description.txt", "demolition_schedule.csv", "machines.json"]:
        path = os.path.join(DATA_DIR, fn)
        result["data_files"][fn] = os.path.exists(path)

    return result


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "run_full_pipeline":
            result = await asyncio.wait_for(
                asyncio.to_thread(_handle_run_full_pipeline, arguments),
                timeout=2400.0,
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "run_pipeline_stage":
            result = await asyncio.wait_for(
                asyncio.to_thread(_handle_run_pipeline_stage, arguments),
                timeout=1500.0,
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

        elif name == "check_blender_environment":
            result = _handle_check_environment()
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except asyncio.TimeoutError:
        return [TextContent(type="text", text=json.dumps({"error": "Pipeline stage timed out"}))]
    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
