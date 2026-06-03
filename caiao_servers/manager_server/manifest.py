"""CAIAO manifest engine — read/write/validate caiao.yaml files.

The manifest is the single source of truth for every CAIAO Server.
It bridges the gap between:
  - MCP-based servers (main project pattern: mcp.server.Server + stdio)
  - Class-based servers (Steel Frame pattern: CAIAOServer + @tool decorator)

All file operations happen through this module. No server code is modified.
"""

import os
import re
import logging
from datetime import date
from typing import Any

import yaml

logger = logging.getLogger(__name__)

VALID_KINDS = {"atomic-mcp", "atomic-class", "merged", "composite", "bridge"}
VALID_STATUSES = {"active", "deprecated", "experimental", "maintenance"}
VALID_START_MODES = {"eager", "lazy"}

_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def read_manifest(server_dir: str) -> dict[str, Any] | None:
    """Read and parse a caiao.yaml manifest from a server directory.

    Returns None if the file doesn't exist or can't be parsed.
    """
    path = os.path.join(server_dir, "caiao.yaml")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            logger.warning(f"Invalid manifest (not a dict): {path}")
            return None
        return data
    except yaml.YAMLError as e:
        logger.warning(f"YAML parse error in {path}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Failed to read {path}: {e}")
        return None


def write_manifest(server_dir: str, data: dict[str, Any]) -> None:
    """Write a caiao.yaml manifest to a server directory."""
    os.makedirs(server_dir, exist_ok=True)
    path = os.path.join(server_dir, "caiao.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    logger.info(f"Manifest written: {path}")


def validate_manifest(data: dict[str, Any]) -> list[str]:
    """Validate a caiao.yaml manifest dict. Returns list of error messages (empty = valid)."""
    errors = []

    if not isinstance(data, dict):
        return ["Manifest must be a dict"]

    name = data.get("name")
    if not name or not isinstance(name, str):
        errors.append("name is required (string)")

    kind = data.get("kind", "")
    if kind not in VALID_KINDS:
        errors.append(f"kind must be one of {VALID_KINDS}, got '{kind}'")

    status = data.get("status", "active")
    if status not in VALID_STATUSES:
        errors.append(f"status must be one of {VALID_STATUSES}, got '{status}'")

    if kind != "composite":
        start_mode = data.get("start_mode", "")
        if start_mode not in VALID_START_MODES:
            errors.append(f"start_mode must be one of {VALID_START_MODES}, got '{start_mode}'")

    tools = data.get("tools", [])
    if isinstance(tools, list):
        for i, tool in enumerate(tools):
            if not isinstance(tool, dict):
                errors.append(f"tools[{i}] must be a dict")
                continue
            tname = tool.get("name", "")
            if not tname:
                errors.append(f"tools[{i}]: name is required")
            elif not _TOOL_NAME_RE.match(tname):
                errors.append(f"tools[{i}]: '{tname}' is not valid snake_case")

    if kind == "merged":
        imports = data.get("imports", [])
        if not imports:
            errors.append("merged server must declare imports")

    if kind == "composite":
        pipeline = data.get("pipeline", [])
        if not pipeline:
            errors.append("composite server must declare a pipeline")

    return errors


def validate_manifest_file(server_dir: str) -> list[str]:
    """Validate a caiao.yaml file on disk. Returns list of error messages."""
    path = os.path.join(server_dir, "caiao.yaml")
    if not os.path.exists(path):
        return [f"No caiao.yaml found in {server_dir}"]
    data = read_manifest(server_dir)
    if data is None:
        return [f"Failed to parse {path}"]
    return validate_manifest(data)


def manifest_to_config(data: dict[str, Any], server_dir: str) -> dict[str, Any]:
    """Convert a caiao.yaml manifest dict to a SERVER_CONFIGS entry.

    This produces the format that CAIAOClientHub expects.
    """
    name = data["name"]
    kind = data.get("kind", "atomic-mcp")

    if kind == "composite":
        return {
            "name": name,
            "composite": True,
            "description": data.get("description", ""),
            "input_schema": data.get("input_schema", {}),
            "pipeline": data.get("pipeline", []),
            "tools": [t["name"] for t in data.get("tools", [])],
        }

    cmd = data.get("command", {})
    config: dict[str, Any] = {
        "name": name,
        "tools": [t["name"] for t in data.get("tools", [])],
    }

    python_path = _resolve_python(cmd.get("python", "auto"))
    config["command"] = python_path

    args = cmd.get("args", ["server.py"])
    config["args"] = args

    cwd = os.path.join(server_dir, cmd.get("cwd", "."))
    config["cwd"] = os.path.normpath(cwd)

    if data.get("start_mode") == "lazy":
        config["lazy"] = True

    env = cmd.get("env")
    if env and isinstance(env, dict) and env:
        config["env"] = env

    return config


def discover_manifests(servers_dir: str) -> list[dict[str, Any]]:
    """Walk a servers directory and return all valid caiao.yaml manifests.

    Skips directories starting with '_' or '.'.
    Each returned dict has an added '_dir' key with the full path.
    """
    manifests = []
    if not os.path.isdir(servers_dir):
        return manifests

    for entry in os.scandir(servers_dir):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue

        data = read_manifest(entry.path)
        if data is None:
            continue

        errors = validate_manifest(data)
        if errors:
            logger.warning(f"Invalid manifest in {entry.name}: {errors}")
            continue

        data["_dir"] = entry.path
        manifests.append(data)

    return manifests


def generate_manifest_from_server(server_dir: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate a caiao.yaml manifest dict from an existing server directory.

    If config is provided (from SERVER_CONFIGS), use it to fill in fields.
    Otherwise, scan the directory and make best guesses.
    """
    dir_name = os.path.basename(os.path.normpath(server_dir))

    data: dict[str, Any] = {
        "name": dir_name,
        "version": "0.1.0",
        "kind": "atomic-mcp",
        "description": "",
        "status": "active",
        "since": date.today().isoformat(),
        "start_mode": "eager",
        "command": {
            "python": "auto",
            "args": ["server.py"],
            "cwd": ".",
            "env": {},
        },
        "health": {
            "timeout_ms": 5000,
            "restart_on_crash": False,
            "max_restarts": 3,
            "health_check_interval_s": 0,
        },
        "tools": [],
        "capabilities": [],
        "dependencies": {"python": [], "system": []},
    }

    if config is None:
        data["start_mode"] = "lazy"
        return data

    data["start_mode"] = "lazy" if config.get("lazy") else "eager"

    if config.get("composite"):
        data["kind"] = "composite"
        data.pop("command", None)
        data.pop("start_mode", None)
        data["description"] = config.get("description", "")
        data["pipeline"] = config.get("pipeline", [])
    else:
        cmd = config.get("command", "")
        if cmd:
            data["command"]["python"] = "auto"
        args_list = config.get("args", ["server.py"])
        data["command"]["args"] = list(args_list)

    for tool_name in config.get("tools", []):
        data["tools"].append({"name": tool_name, "description": "", "tags": []})

    return data


def _resolve_python(python_spec: str) -> str:
    """Resolve the python spec from the manifest to an actual executable path."""
    if python_spec == "auto":
        import sys
        return sys.executable
    return python_spec
