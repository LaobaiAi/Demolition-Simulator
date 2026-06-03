"""Shared utilities for Blender CAIAO servers and pipeline scripts.

Importable by CAIAO servers (system Python) — add PROJECT_ROOT to sys.path first.
Also importable by Blender scripts running inside Blender's embedded Python.
"""

import json
import os
import subprocess
from datetime import datetime
from typing import Optional

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
_BLENDER_EXE = None  # cached after first find_blender() call


def get_pipeline_paths():
    """Standardized pipeline directory paths. Single source of truth."""
    return {
        "pipeline_dir": _PIPELINE_DIR,
        "data_dir": os.path.join(_PIPELINE_DIR, "data"),
        "scripts_dir": os.path.join(_PIPELINE_DIR, "scripts"),
        "output_dir": os.path.join(_PIPELINE_DIR, "output"),
    }


def find_blender():
    """Locate Blender executable. Cached after first successful lookup."""
    global _BLENDER_EXE
    if _BLENDER_EXE and os.path.exists(_BLENDER_EXE):
        return _BLENDER_EXE

    exe = os.environ.get("BLENDER_EXE", "")
    if exe and os.path.exists(exe):
        _BLENDER_EXE = exe
        return exe

    portable = os.path.join(_PIPELINE_DIR, "blender_portable", "blender-4.2.8-windows-x64", "blender.exe")
    if os.path.exists(portable):
        _BLENDER_EXE = portable
        return portable

    for p in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(p, "blender.exe")
        if os.path.exists(candidate):
            _BLENDER_EXE = candidate
            return candidate

    return None


def run_blender_script(script_name, blend_input=None, env_extra=None, timeout=300, background=True):
    """Run a Blender Python script via subprocess.

    Returns dict with at least 'success' (bool). On success includes 'output' lines.
    On failure includes 'error' and optionally 'stderr'/'stdout'.
    """
    blender_exe = find_blender()
    if not blender_exe:
        return {"success": False, "error": "Blender not found. Set BLENDER_EXE env var or install Blender."}

    paths = get_pipeline_paths()
    script_path = os.path.join(paths["scripts_dir"], script_name)
    if not os.path.exists(script_path):
        return {"success": False, "error": f"Script not found: {script_path}"}

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
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding='utf-8', errors='replace', env=env)
        output_lines = [l.strip() for l in r.stdout.split('\n') if l.strip()]
        if r.returncode != 0:
            error_lines = [l.strip() for l in r.stderr.split('\n') if l.strip()][:10]
            return {"success": False, "error": f"Blender exited with code {r.returncode}",
                    "stderr": error_lines, "stdout": output_lines[-20:]}
        return {"success": True, "returncode": 0, "output": output_lines}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Blender script timed out ({timeout}s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def load_project_config():
    """Load project_config.json from the data directory."""
    config_path = os.path.join(_PIPELINE_DIR, "data", "project_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def make_project_dir(project_name=None):
    """Create a timestamped project output directory.

    Returns (project_dir, blend_dir) tuple.
    If project_name is None, reads it from project_config.json.
    """
    if project_name is None:
        config = load_project_config()
        project_name = config.get("project_name", "demolition")
    name = project_name.replace(" ", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = os.path.join(_PIPELINE_DIR, "output")
    proj_dir = os.path.join(output_base, f"{name}_{ts}")
    blend_dir = os.path.join(proj_dir, "blend")
    os.makedirs(blend_dir, exist_ok=True)
    return proj_dir, blend_dir


def find_video_file(search_dir):
    """Find the first .mp4 file in a directory tree.

    Returns (path, size_mb) or (None, None).
    """
    for root, dirs, files in os.walk(search_dir):
        for fn in files:
            if fn.endswith('.mp4'):
                path = os.path.join(root, fn)
                size_mb = round(os.path.getsize(path) / 1024 / 1024, 1)
                return path, size_mb
    return None, None


def write_runtime_config(config_override, output_dir):
    """Merge config_override into project_config, write to _runtime_config.json.

    Returns the env_extra dict to pass to run_blender_script.
    """
    config = load_project_config()
    config["building"].update(config_override)
    tmp_path = os.path.join(output_dir, "_runtime_config.json")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return {"BLENDER_CONFIG_OVERRIDE": tmp_path}
