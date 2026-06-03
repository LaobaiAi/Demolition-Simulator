"""Blender Pipeline CAIAO Server — full demolition animation pipeline orchestrator.

Chains the 4 pipeline stages (build → animate → machinery → render) into a single
end-to-end workflow. Each stage can also be run independently.
"""

import asyncio
import json
import logging
import os
import subprocess
import time
from datetime import datetime

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("blender_pipeline")

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SERVER_DIR))
BLENDER_PIPELINE_DIR = os.path.join(PROJECT_ROOT, "blender_pipeline")
SCRIPTS_DIR = os.path.join(BLENDER_PIPELINE_DIR, "scripts")
OUTPUT_BASE = os.path.join(BLENDER_PIPELINE_DIR, "output")
DATA_DIR = os.path.join(BLENDER_PIPELINE_DIR, "data")

server = Server("blender-pipeline")


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


def _run_blender(script_name, blend_input=None, env_extra=None, timeout=300, background=True):
    blender_exe = _find_blender()
    if not blender_exe:
        return False, {"error": "Blender not found. Set BLENDER_EXE env var or install Blender."}

    script_path = os.path.join(SCRIPTS_DIR, script_name)
    if not os.path.exists(script_path):
        return False, {"error": f"Script not found: {script_path}"}

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
            return False, {"error": f"Blender exited with code {r.returncode}", "stderr": error_lines, "stdout": output_lines[-20:]}
        return True, {"status": "ok", "output": output_lines}
    except subprocess.TimeoutExpired:
        return False, {"error": f"Blender script timed out ({timeout}s)"}
    except Exception as e:
        return False, {"error": str(e)}


def _make_project_dir(project_name):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = project_name.replace(" ", "_")
    proj_dir = os.path.join(OUTPUT_BASE, f"{name}_{ts}")
    blend_dir = os.path.join(proj_dir, "blend")
    os.makedirs(blend_dir, exist_ok=True)
    return proj_dir, blend_dir


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


def _handle_run_full_pipeline(arguments):
    with_machinery = arguments.get("with_machinery", True)
    with_render = arguments.get("with_render", True)
    config_override = arguments.get("config_override")

    custom_out = arguments.get("output_dir")
    if custom_out:
        proj_dir = custom_out
        blend_dir = os.path.join(proj_dir, "blend")
        os.makedirs(blend_dir, exist_ok=True)
    else:
        config_path = os.path.join(DATA_DIR, "project_config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        proj_name = config.get("project_name", "demolition")
        proj_dir, blend_dir = _make_project_dir(proj_name)

    results = {"pipeline": "full", "project_dir": proj_dir, "stages": {}}
    start_time = time.time()

    if config_override:
        config_path = os.path.join(DATA_DIR, "project_config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        config["building"].update(config_override)
        tmp_config = os.path.join(blend_dir, "_runtime_config.json")
        with open(tmp_config, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        env_build = {"BLENDER_OUTPUT_DIR": blend_dir, "BLENDER_CONFIG_OVERRIDE": tmp_config}
    else:
        env_build = {"BLENDER_OUTPUT_DIR": blend_dir}

    logger.info("Stage 1/4: Building frame model...")
    ok, r = _run_blender("generate_building.py", env_extra=env_build, timeout=120)
    blend_base = os.path.join(blend_dir, "scene_base.blend")
    results["stages"]["build"] = {
        "success": ok,
        "blend_file": blend_base if os.path.exists(blend_base) else None,
        **r,
    }
    if not ok:
        results["duration_s"] = round(time.time() - start_time, 1)
        return results

    logger.info("Stage 2/4: Applying demolition animation...")
    ok, r = _run_blender("apply_demolition.py", blend_input=blend_base, env_extra={"BLENDER_OUTPUT_DIR": blend_dir}, timeout=300)
    blend_animated = os.path.join(blend_dir, "scene_animated.blend")
    csv_path = os.path.join(proj_dir, "computed_demolition_schedule.csv")
    results["stages"]["animate"] = {
        "success": ok,
        "blend_file": blend_animated if os.path.exists(blend_animated) else None,
        "schedule_csv": csv_path if os.path.exists(csv_path) else None,
        **r,
    }
    if not ok:
        results["duration_s"] = round(time.time() - start_time, 1)
        return results

    if with_machinery:
        logger.info("Stage 3/4: Adding machinery...")
        env_mach = {"BLENDER_OUTPUT_DIR": blend_dir}
        ok, r = _run_blender("add_machinery.py", blend_input=blend_animated, env_extra=env_mach, timeout=120)
    else:
        import shutil
        blend_final = os.path.join(blend_dir, "scene_final.blend")
        shutil.copy2(blend_animated, blend_final)
        ok, r = True, {"status": "ok", "output": ["Machinery skipped, copied scene_animated to scene_final"]}
    blend_final = os.path.join(blend_dir, "scene_final.blend")
    results["stages"]["machinery"] = {
        "success": ok,
        "blend_file": blend_final if os.path.exists(blend_final) else None,
        **r,
    }

    if with_render and ok:
        logger.info("Stage 4/4: Rendering animation...")
        ok, r = _run_blender("render.py", blend_input=blend_final, env_extra={"BLENDER_OUTPUT_DIR": blend_dir}, timeout=1200, background=False)
        video_file = None
        for root, dirs, files in os.walk(proj_dir):
            for fn in files:
                if fn.endswith('.mp4'):
                    video_file = os.path.join(root, fn)
                    break
        results["stages"]["render"] = {
            "success": ok,
            "video_file": video_file,
            **r,
        }

    results["duration_s"] = round(time.time() - start_time, 1)
    all_ok = all(s["success"] for s in results["stages"].values())
    results["status"] = "completed" if all_ok else "partial_failure"
    return results


def _handle_run_pipeline_stage(arguments):
    stage = arguments["stage"]
    blend_input = arguments.get("blend_input")
    output_dir = arguments.get("output_dir")

    stage_map = {
        "build": ("generate_building.py", None, 120, True),
        "animate": ("apply_demolition.py", blend_input, 300, True),
        "machinery": ("add_machinery.py", blend_input, 120, True),
        "render": ("render.py", blend_input, 1200, False),
        "preview": ("preview_render.py", blend_input, 600, True),
    }

    if stage not in stage_map:
        return {"error": f"Unknown stage: {stage}. Choose from: {list(stage_map.keys())}"}

    script, blend, timeout, bg = stage_map[stage]
    if stage in ("animate", "machinery", "render", "preview") and not blend:
        return {"error": f"blend_input is required for stage '{stage}'"}

    if not output_dir:
        output_dir = os.path.dirname(blend) if blend else os.path.join(OUTPUT_BASE, "blend")
    os.makedirs(output_dir, exist_ok=True)

    env = {"BLENDER_OUTPUT_DIR": output_dir}
    ok, r = _run_blender(script, blend_input=blend, env_extra=env, timeout=timeout, background=bg)

    result = {"stage": stage, "success": ok, "output_dir": output_dir, **r}

    blend_files = {
        "build": "scene_base.blend",
        "animate": "scene_animated.blend",
        "machinery": "scene_final.blend",
    }
    if stage in blend_files:
        path = os.path.join(output_dir, blend_files[stage])
        if os.path.exists(path):
            result["blend_file"] = path

    return result


def _handle_check_environment():
    blender_exe = _find_blender()
    result = {
        "blender_found": blender_exe is not None,
        "blender_path": blender_exe,
    }

    if blender_exe:
        try:
            r = subprocess.run([blender_exe, "--version"], capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace')
            result["blender_version"] = r.stdout.strip().split('\n')[0] if r.returncode == 0 else None
        except Exception:
            result["blender_version"] = None

    result["pipeline_dir"] = BLENDER_PIPELINE_DIR
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
