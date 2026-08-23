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


def _decode_blender_output(data: bytes) -> str:
    """Decode Blender subprocess output bytes robustly.

    Blender's embedded Python emits text using the OS console codepage (GBK on
    Chinese Windows) regardless of PYTHONIOENCODING, so strict UTF-8 decoding
    corrupts CJK text. Try UTF-8 first, fall back to the local codepage.
    """
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("gbk", errors="replace")
        except (LookupError, UnicodeDecodeError):
            return data.decode("latin-1", errors="replace")


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

    # Blender --python does NOT add the script's dir (nor the pipeline dir) to sys.path,
    # so scripts that `from _common import ...` would fail with ModuleNotFoundError.
    # Inject both dirs via --python-expr before running the script, and force the
    # embedded Python's stdout/stderr to UTF-8 (PYTHONIOENCODING is ignored by Blender
    # on Windows, whose console defaults to the local codepage e.g. GBK).
    # NOTE: --python-expr accepts a SINGLE line only (multi-line/indented code is a
    # SyntaxError). Use a list comprehension for the reconfigure attempts.
    pyexpr = (
        "import sys;"
        "sys.path.insert(0, %r); sys.path.insert(0, %r);"
        "[getattr(_s, 'reconfigure', lambda **k: None)(encoding='utf-8', errors='replace') "
        "for _s in (sys.stdout, sys.stderr)]"
    ) % (paths["scripts_dir"], paths["pipeline_dir"])

    cmd = [blender_exe]
    if background:
        cmd.append("--background")
    if blend_input and os.path.exists(blend_input):
        cmd.append(blend_input)
    cmd.extend(["--python-expr", pyexpr, "--python", script_path])

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    # Force Blender's embedded Python to emit UTF-8 on stdout/stderr (Windows console
    # otherwise uses the local codepage, e.g. GBK, producing mojibake when decoded).
    env.setdefault("PYTHONIOENCODING", "utf-8")

    proc = None
    try:
        # stdin=DEVNULL is critical: when invoked from a long-lived server (e.g. MCP
        # stdio transport), Blender inherits the pipe as stdin and, if the script
        # errors, blocks waiting for input -> spurious timeout.
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, env=env)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # communicate() timeout does NOT kill the child; do it explicitly so we
            # don't leak a hung Blender process.
            proc.kill()
            out, err = proc.communicate()
            return {"success": False, "error": f"Blender script timed out ({timeout}s)",
                    "stderr": [l.strip() for l in _decode_blender_output(err).split('\n') if l.strip()][:10],
                    "stdout": [l.strip() for l in _decode_blender_output(out).split('\n') if l.strip()][-20:]}

        stdout_text = _decode_blender_output(out)
        stderr_text = _decode_blender_output(err)
        output_lines = [l.strip() for l in stdout_text.split('\n') if l.strip()]
        progress_lines = [l for l in output_lines if l.startswith("[BUILD_STEP]") or l.startswith("[ANIM_STEP]")]

        # Blender exits 0 even when the script raised; detect failure via stderr.
        failed = proc.returncode != 0 or "Traceback" in stderr_text or "Error:" in stderr_text
        if failed:
            error_lines = [l.strip() for l in stderr_text.split('\n') if l.strip()][:10]
            return {"success": False, "error": f"Blender script failed (code {proc.returncode})",
                    "stderr": error_lines, "stdout": output_lines[-20:], "progress": progress_lines}
        return {"success": True, "returncode": proc.returncode, "output": output_lines, "progress": progress_lines}
    except Exception as e:
        if proc is not None and proc.poll() is None:
            proc.kill()
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
