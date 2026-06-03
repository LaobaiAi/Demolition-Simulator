"""Blender Environment CAIAO Server — infrastructure provider for all Blender pipeline servers.

Does NOT call Blender subprocesses (except --version for metadata).
Provides environment info that functional servers consume at startup.
Marked kind: infrastructure, start_mode: eager — starts before any Blender functional server.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from blender_pipeline.common import find_blender, get_pipeline_paths, load_project_config

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("blender_environment")

_paths = get_pipeline_paths()
SCRIPTS_DIR = _paths["scripts_dir"]
DATA_DIR = _paths["data_dir"]

server = Server("blender-environment")

TOOLS = [
    Tool(
        name="resolve_blender_path",
        description=(
            "Find and return the Blender executable path, version, and discovery method. "
            "Searches: BLENDER_EXE env var → portable install → system PATH. "
            "Result is cached for the server process lifetime."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="validate_environment",
        description=(
            "Run a comprehensive environment health check. "
            "Verifies: Blender binary exists and can run, all pipeline scripts are present, "
            "all required data files exist. Returns pass/fail per check with details."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="provide_pipeline_paths",
        description=(
            "Return the standardized pipeline directory structure. "
            "Single source of truth for: pipeline_dir, scripts_dir, data_dir, output_dir. "
            "All Blender functional servers should get their paths from here."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="provide_config",
        description=(
            "Load and return the project_config.json content. "
            "Includes building parameters, demolition strategy, machinery settings, "
            "and render configuration. Functional servers can override specific fields."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
]

REQUIRED_SCRIPTS = [
    "generate_building.py", "apply_demolition.py",
    "add_machinery.py", "render.py", "preview_render.py",
]

REQUIRED_DATA_FILES = [
    "project_config.json", "building_description.txt",
    "demolition_schedule.csv", "machines.json",
]


def _handle_resolve_blender_path(_arguments):
    blender_exe = find_blender()
    result = {
        "blender_found": blender_exe is not None,
        "blender_path": blender_exe,
        "discovery_source": None,
    }

    if blender_exe:
        if blender_exe == os.environ.get("BLENDER_EXE", ""):
            result["discovery_source"] = "env:BLENDER_EXE"
        elif "blender_portable" in blender_exe:
            result["discovery_source"] = "portable_install"
        else:
            result["discovery_source"] = "system_path"

        try:
            r = subprocess.run([blender_exe, "--version"], capture_output=True, text=True,
                               timeout=30, encoding='utf-8', errors='replace')
            if r.returncode == 0:
                result["blender_version"] = r.stdout.strip().split('\n')[0]
        except Exception:
            result["blender_version"] = None

    return result


def _handle_validate_environment(_arguments):
    checks = {}

    blender_exe = find_blender()
    checks["blender_binary"] = {
        "pass": blender_exe is not None and os.path.exists(blender_exe),
        "path": blender_exe,
    }

    if blender_exe:
        try:
            r = subprocess.run([blender_exe, "--version"], capture_output=True, text=True,
                               timeout=30, encoding='utf-8', errors='replace')
            checks["blender_version"] = {
                "pass": r.returncode == 0,
                "version": r.stdout.strip().split('\n')[0] if r.returncode == 0 else None,
            }
        except Exception as e:
            checks["blender_version"] = {"pass": False, "error": str(e)}
    else:
        checks["blender_version"] = {"pass": False, "error": "Blender binary not found"}

    checks["scripts"] = {}
    for fn in REQUIRED_SCRIPTS:
        path = os.path.join(SCRIPTS_DIR, fn)
        checks["scripts"][fn] = {"pass": os.path.exists(path), "path": path}

    checks["data_files"] = {}
    for fn in REQUIRED_DATA_FILES:
        path = os.path.join(DATA_DIR, fn)
        checks["data_files"][fn] = {"pass": os.path.exists(path), "path": path}

    all_pass = (
        checks["blender_binary"]["pass"]
        and checks["blender_version"]["pass"]
        and all(v["pass"] for v in checks["scripts"].values())
        and all(v["pass"] for v in checks["data_files"].values())
    )

    return {
        "all_pass": all_pass,
        "checks": checks,
        "summary": "All checks passed" if all_pass else "Some checks failed — see details",
    }


def _handle_provide_pipeline_paths(_arguments):
    return get_pipeline_paths()


def _handle_provide_config(_arguments):
    config = load_project_config()
    return {
        "project_name": config.get("project_name", "demolition"),
        "building": config.get("building", {}),
        "demolition_strategy": config.get("demolition_strategy", {}),
        "machinery": config.get("machinery", {}),
        "render_enabled": config.get("render_enabled", False),
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    handlers = {
        "resolve_blender_path": _handle_resolve_blender_path,
        "validate_environment": _handle_validate_environment,
        "provide_pipeline_paths": _handle_provide_pipeline_paths,
        "provide_config": _handle_provide_config,
    }

    try:
        handler = handlers.get(name)
        if handler:
            result = handler(arguments)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
