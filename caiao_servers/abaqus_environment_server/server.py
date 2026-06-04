"""Abaqus Environment CAIAO Server — infrastructure provider for Abaqus pipeline servers.

Reads abaqus_env.json to provide Abaqus path resolution, environment validation,
and configuration. Does NOT import abaqus module (runs in system Python).
Marked kind: infrastructure, start_mode: eager — starts before any Abaqus functional server.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("abaqus_environment")

_ENV_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "abaqus_env.json")

server = Server("abaqus-environment")

TOOLS = [
    Tool(
        name="resolve_abaqus_path",
        description=(
            "Find and return the Abaqus commands directory, Python executable path, "
            "product root, and version from abaqus_env.json. "
            "This is the single source of truth for Abaqus paths used by all other Abaqus servers."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="validate_environment",
        description=(
            "Run a comprehensive environment health check. "
            "Verifies: Abaqus commands directory exists, Abaqus Python interpreter exists, "
            "license server is configured. Returns pass/fail per check with details."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="get_abaqus_config",
        description=(
            "Return the complete loaded abaqus_env.json content — "
            "paths, license configuration, hardware specs, software versions."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
]


def _load_env():
    if not os.path.exists(_ENV_JSON):
        return {}
    with open(_ENV_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def _handle_resolve_abaqus_path(_arguments):
    env = _load_env()
    paths = env.get("paths", {})

    commands_dir = paths.get("commands")
    product_root = paths.get("product_root")
    python_dir = paths.get("python")
    abaqus_python = os.path.join(python_dir, "python.exe") if python_dir else None

    result = {
        "abaqus_command": os.path.join(commands_dir, "abaqus.bat") if commands_dir else None,
        "abaqus_python": abaqus_python,
        "commands_dir": commands_dir,
        "product_root": product_root,
        "python_dir": python_dir,
        "version": env.get("product", {}).get("version"),
    }

    if abaqus_python and os.path.exists(abaqus_python):
        result["python_exists"] = True
    else:
        result["python_exists"] = False

    if commands_dir and os.path.isdir(commands_dir):
        abaqus_bat = os.path.join(commands_dir, "abaqus.bat")
        result["command_exists"] = os.path.exists(abaqus_bat)
    else:
        result["command_exists"] = False

    return result


def _handle_validate_environment(_arguments):
    env = _load_env()
    paths = env.get("paths", {})
    checks = {}

    commands_dir = paths.get("commands")
    checks["commands_dir"] = {
        "pass": commands_dir is not None and os.path.isdir(commands_dir),
        "path": commands_dir,
    }

    abaqus_bat = os.path.join(commands_dir, "abaqus.bat") if commands_dir else None
    checks["abaqus_bat"] = {
        "pass": abaqus_bat is not None and os.path.exists(abaqus_bat),
        "path": abaqus_bat,
    }

    python_dir = paths.get("python")
    checks["python_dir"] = {
        "pass": python_dir is not None and os.path.isdir(python_dir),
        "path": python_dir,
    }

    abaqus_python = os.path.join(python_dir, "python.exe") if python_dir else None
    checks["abaqus_python"] = {
        "pass": abaqus_python is not None and os.path.exists(abaqus_python),
        "path": abaqus_python,
    }

    license_server = env.get("license", {}).get("server")
    checks["license"] = {
        "pass": bool(license_server),
        "server": license_server,
    }

    cpus = env.get("hardware", {}).get("cpu_cores")
    ram = env.get("hardware", {}).get("ram_gb")
    checks["hardware"] = {
        "pass": bool(cpus and ram),
        "cpu_cores": cpus,
        "ram_gb": ram,
    }

    all_pass = all(v["pass"] for v in checks.values())

    return {
        "all_pass": all_pass,
        "checks": checks,
        "summary": "All checks passed" if all_pass else "Some checks failed — see details",
    }


def _handle_get_abaqus_config(_arguments):
    return _load_env()


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    handlers = {
        "resolve_abaqus_path": _handle_resolve_abaqus_path,
        "validate_environment": _handle_validate_environment,
        "get_abaqus_config": _handle_get_abaqus_config,
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
