"""CAIAO config discovery — delegates to the caiao package.

All server configs are discovered from caiao.yaml manifests in caiao_servers/.
No hardcoded legacy fallback — every server must have a manifest.
"""

import os
import sys
import logging

from caiao.discovery import discover_server_configs as _caiao_discover

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
CAIAO_SERVERS_DIR = os.path.join(PROJECT_DIR, "caiao_servers")

_VENV_CANDIDATES = [
    os.path.join(BASE_DIR, "venv", "Scripts", "python.exe"),
    os.path.join(PROJECT_DIR, ".venv", "Scripts", "python.exe"),
    os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe"),
]
VENV_PYTHON = next((p for p in _VENV_CANDIDATES if os.path.exists(p)), sys.executable)


def _resolve_abaqus_python() -> str:
    env_json_path = os.path.join(
        PROJECT_DIR, "caiao_servers", "abaqus_environment_server", "abaqus_env.json"
    )
    try:
        import json
        with open(env_json_path, "r", encoding="utf-8") as f:
            env_data = json.load(f)
        python_dir = env_data.get("paths", {}).get("python")
        if python_dir:
            python_exe = os.path.join(python_dir, "python.exe")
            if os.path.exists(python_exe):
                return python_exe
            return python_exe
        logger.warning(f"@abaqus_python@ sentinel used but paths.python not found in {env_json_path}")
    except Exception as e:
        logger.warning(f"Failed to resolve @abaqus_python@ from {env_json_path}: {e}")
    return sys.executable


def discover_server_configs() -> list[dict]:
    configs = _caiao_discover(
        servers_dir=CAIAO_SERVERS_DIR,
        sentinel_resolvers={"@abaqus_python@": _resolve_abaqus_python},
        venv_python=VENV_PYTHON,
    )
    return [c for c in configs if c.get("status") != "deprecated"]
