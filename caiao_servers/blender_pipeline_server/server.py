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
import tempfile
import time
from datetime import datetime

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


_STEAM_TURBINE_ANIMATE = os.path.join(
    _paths["pipeline_dir"], "projects", "steam_turbine_building", "scripts", "animate_demolition.py"
)

STAGES = [
    ("build", "generate_building.py", None, 120, True),
    ("animate", "apply_demolition.py", None, 300, True),
    ("turbine_animate", _STEAM_TURBINE_ANIMATE, None, 300, True),
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
                    "enum": ["build", "animate", "turbine_animate", "machinery", "render", "preview"],
                    "description": "Pipeline stage to run. turbine_animate applies the steam-turbine-specific demolition keyframes (projects/steam_turbine_building/scripts/animate_demolition.py).",
                },
                "blend_input": {
                    "type": "string",
                    "description": "Path to input .blend file. Required for animate/machinery/render/preview stages.",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Custom output directory.",
                },
                "config_override": {
                    "type": "object",
                    "description": "Override project_config.json parameters. For build stage: building + demolition_strategy. For animate stage: demolition_strategy.",
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
    "turbine_animate": "scene_animated.blend",
    "machinery": "scene_final.blend",
}

STAGE_REQUIRES_INPUT = {"animate", "turbine_animate", "machinery", "render", "preview"}


def _mux_render_output(result, output_dir, meta_path=None):
    """Mux per-frame PNGs (written by render.py) into an MP4 via bundled ffmpeg.

    render.py renders one PNG per frame (write_still loop — the opengl animation
    operator does not evaluate object animation in this environment), then this
    helper combines them into the final video. Returns mp4 path or None.
    """
    frame_dir = None
    if meta_path and os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                frame_dir = json.load(f).get("frame_dir")
        except Exception as e:
            logger.warning(f"render: read meta failed: {e}")
    if not frame_dir:
        for line in result.get("output", []):
            line = line.strip()
            if line.startswith("[FRAME_DIR] "):
                frame_dir = line[len("[FRAME_DIR] "):].strip()
                break
    if not frame_dir or not os.path.isdir(frame_dir):
        logger.warning("render: no [FRAME_DIR] marker / meta file, cannot mux")
        return None
    proj_dir = os.path.dirname(frame_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    mp4_path = os.path.join(proj_dir, f"animation_{ts}.mp4")
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        logger.warning(f"render: ffmpeg unavailable: {e}")
        return None
    try:
        cfg = load_project_config()
        fps = int(cfg.get("fps", 24))
    except Exception:
        fps = 24
    # Mux to an ASCII temp path first, then move into place — avoids any
    # path-encoding edge cases and leaves a complete file at the final path.
    tmp_mp4 = os.path.join(tempfile.gettempdir(), f"ds_mux_{ts}.mp4")
    err_log = os.path.join(tempfile.gettempdir(), f"ds_mux_{ts}.err.log")
    cmd = [ffmpeg_exe, "-loglevel", "error", "-y", "-framerate", str(fps),
           "-i", os.path.join(frame_dir, "frame_%05d.png"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
           tmp_mp4]
    try:
        # stdin=DEVNULL is critical: a child of the MCP stdio server that
        # inherits the JSON-RPC pipe as stdin can block indefinitely. stderr
        # goes to a file so diagnostics survive even when the pipe path hangs.
        with open(err_log, "wb") as ef:
            r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=ef, timeout=300)
    except subprocess.TimeoutExpired:
        logger.warning(f"render: mux timed out after 300s (stderr: {err_log})")
        return None
    except Exception as e:
        logger.warning(f"render: mux failed: {e}")
        return None
    if r.returncode != 0 or not os.path.exists(tmp_mp4) or os.path.getsize(tmp_mp4) < 100000:
        try:
            tail = open(err_log, "rb").read().decode(errors="replace")[-300:]
        except Exception:
            tail = ""
        logger.warning("render: mux failed: " + tail)
        return None
    try:
        # shutil.move handles cross-drive moves (os.replace raises WinError 17
        # when Temp is on C: and the output dir on another drive).
        shutil.move(tmp_mp4, mp4_path)
    except Exception as e:
        logger.warning(f"render: mux move failed: {e}")
        return None
    logger.info(f"render: muxed {mp4_path}")
    return mp4_path


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
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        env_base["BLENDER_RUN_ID"] = run_id
        result = run_blender_script("render.py", blend_input=blend_final, env_extra=env_base, timeout=1200, background=False)
        video_path = None
        if result.get("success"):
            meta_path = os.path.join(blend_dir, f"_render_meta_{run_id}.json")
            video_path = _mux_render_output(result, proj_dir, meta_path)
        if not video_path:
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
    config_override = arguments.get("config_override")

    stage_config = _get_stage_config(stage)
    if not stage_config:
        return {"error": f"Unknown stage: {stage}. Choose from: build, animate, machinery, render, preview"}

    _, script, _, timeout, bg = stage_config

    if stage in STAGE_REQUIRES_INPUT and not blend_input:
        return {"error": f"blend_input is required for stage '{stage}'"}

    if not output_dir:
        if blend_input:
            output_dir = os.path.dirname(blend_input)
        else:
            config = load_project_config()
            proj_name = config.get("project_name", "demolition") if config else None
            proj_dir, blend_dir = make_project_dir(proj_name)
            output_dir = blend_dir
    os.makedirs(output_dir, exist_ok=True)

    env = {"BLENDER_OUTPUT_DIR": output_dir}
    run_id = None
    if stage == "render":
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        env["BLENDER_RUN_ID"] = run_id
    if config_override and stage == "build":
        config = load_project_config()
        config["building"].update(config_override.get("building", {}))
        if "demolition_strategy" in config_override:
            config["demolition_strategy"].update(config_override["demolition_strategy"])
        tmp_path = os.path.join(output_dir, "_runtime_config.json")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        env["BLENDER_CONFIG_OVERRIDE"] = tmp_path
    elif config_override and stage == "animate":
        tmp_path = os.path.join(output_dir, "_runtime_anim_config.json")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config_override, f, ensure_ascii=False, indent=2)
        env["BLENDER_ANIM_OVERRIDE"] = tmp_path

    result = run_blender_script(script, blend_input=blend_input, env_extra=env, timeout=timeout, background=bg)

    stage_result = {"stage": stage, "success": result.get("success", False), "output_dir": output_dir}
    stage_result.update({k: v for k, v in result.items() if k != "success"})

    if stage == "build":
        progress = result.get("progress", [])
        if progress:
            stage_result["build_progress"] = progress
            stage_result["progress_summary"] = f"建模完成：共{len(progress)}个步骤"
        # Extract element counts from output
        output_lines = result.get("output", [])
        for line in output_lines:
            if "总计:" in line:
                stage_result["element_total"] = line.split("总计:")[-1].strip()

    if stage in STAGE_BLEND_FILES:
        path = os.path.join(output_dir, STAGE_BLEND_FILES[stage])
        if os.path.exists(path):
            stage_result["blend_file"] = path

    if stage == "render":
        # Always mux the freshly rendered frames — find_video_file may return a
        # stale MP4 from an earlier run in the same output_dir.
        if result.get("success"):
            meta_path = os.path.join(output_dir, f"_render_meta_{run_id}.json") if run_id else None
            muxed = _mux_render_output(result, output_dir, meta_path)
            if muxed:
                stage_result["video_file"] = muxed

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
