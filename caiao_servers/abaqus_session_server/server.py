"""Abaqus Session CAIAO Server — MCP wrapper managing a persistent Abaqus CAE session.

Runs in system Python. On first tool call, spawns an Abaqus Python subprocess
running abaqus_session.py, then forwards all tool calls via stdin/stdout JSON-RPC.
The single Abaqus process persists across tool calls, sharing one model database.

Server-side tools (no Abaqus kernel needed) run directly in this process:
  render_collapse_video  — pure Python rendering via scripts/render_tower_frames.py
  get_collapse_status    — .sta file polling for async solve progress

Environment variables (all optional):
  ABAQUS_TOOL_TIMEOUT_S          default 900  — per-kernel-call protection net
  ABAQUS_KERNEL_BOOT_TIMEOUT_S   default 180  — kernel ready.flag wait
  ABAQUS_POLL_INTERVAL_S         default 0.5  — task-file poll interval
  ABAQUS_RENDER_TIMEOUT_S        default 900  — server-side tool call timeout
"""

import asyncio
import contextlib
import glob
import json
import logging
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid

import numpy as np

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("abaqus_session")

_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(os.path.dirname(_SERVER_DIR))

TOWER_JOB_NAME = "tower_job_run"
TOTAL_SIM_TIME = 13.0  # settle 1s + collapse 12s for the default tower job
_SERVER_ONLY_TOOLS = {"render_collapse_video", "get_collapse_status"}

server = Server("abaqus-session")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default

TOOLS = [
    Tool(
        name="create_rectangular_column",
        description="Create rectangular RC column part in Abaqus — concrete solid extruded from rectangular profile, plus rebar wireframe at four corners",
        inputSchema={
            "type": "object",
            "required": ["name", "length", "width", "depth"],
            "properties": {
                "name": {"type": "string", "description": "Part name prefix"},
                "length": {"type": "number", "description": "Column height (m)"},
                "width": {"type": "number", "description": "Section width (m)"},
                "depth": {"type": "number", "description": "Section depth (m)"},
                "rebar_dia": {"type": "number", "description": "Rebar diameter (m)", "default": 0.012},
                "cover": {"type": "number", "description": "Concrete cover thickness (m)", "default": 0.05},
            },
        },
    ),
    Tool(
        name="create_truss",
        description="Create triangular steel truss as wireframe in Abaqus — top chord, bottom chord, verticals, and diagonal web members",
        inputSchema={
            "type": "object",
            "required": ["name", "span", "height"],
            "properties": {
                "name": {"type": "string", "description": "Part name"},
                "span": {"type": "number", "description": "Truss span length (m)"},
                "height": {"type": "number", "description": "Truss height (m)"},
                "n_panels": {"type": "integer", "description": "Number of panels", "default": 4},
            },
        },
    ),
    Tool(
        name="create_slab",
        description="Create precast concrete roof slab — shell extrusion from rectangular sketch",
        inputSchema={
            "type": "object",
            "required": ["name", "length", "width", "thickness"],
            "properties": {
                "name": {"type": "string", "description": "Part name"},
                "length": {"type": "number", "description": "Slab length (m)"},
                "width": {"type": "number", "description": "Slab width (m)"},
                "thickness": {"type": "number", "description": "Slab thickness (m)"},
            },
        },
    ),
    Tool(
        name="assign_concrete_cdp",
        description="Assign C30 Concrete Damaged Plasticity material to a part with compression hardening and tension stiffening",
        inputSchema={
            "type": "object",
            "required": ["part_name"],
            "properties": {
                "part_name": {"type": "string", "description": "Target part name"},
                "material_name": {"type": "string", "description": "Material name", "default": "C30"},
                "density": {"type": "number", "description": "Density kg/m3", "default": 2500.0},
                "E": {"type": "number", "description": "Young's modulus Pa", "default": 3e10},
                "nu": {"type": "number", "description": "Poisson's ratio", "default": 0.2},
                "fc": {"type": "number", "description": "Compressive strength MPa", "default": 30.0},
            },
        },
    ),
    Tool(
        name="mesh_part",
        description="Seed and mesh a part with C3D8R explicit elements, with fallback strategies for the Abaqus 2026 API",
        inputSchema={
            "type": "object",
            "required": ["part_name"],
            "properties": {
                "part_name": {"type": "string", "description": "Part to mesh"},
                "element_type": {"type": "string", "description": "Element type code", "default": "C3D8R"},
                "global_size": {"type": "number", "description": "Seed size (m)", "default": 0.2},
            },
        },
    ),
    Tool(
        name="create_explicit_step",
        description="Create Explicit Dynamics step with field output (S, E, U, V, A, STATUS, PEEQ)",
        inputSchema={
            "type": "object",
            "required": ["step_name", "time_period"],
            "properties": {
                "step_name": {"type": "string", "description": "Step name"},
                "time_period": {"type": "number", "description": "Simulation duration (s)"},
                "nlgeom": {"type": "boolean", "description": "Nonlinear geometry", "default": True},
            },
        },
    ),
    Tool(
        name="apply_gravity",
        description="Apply gravity load to the model in the Collapse step",
        inputSchema={
            "type": "object",
            "properties": {
                "magnitude": {"type": "number", "description": "Gravity magnitude m/s2", "default": 9.8},
            },
        },
    ),
    Tool(
        name="create_rigid_ground",
        description="Create horizontal rigid ground part with mesh, fixed boundary, and general contact for impact simulation",
        inputSchema={
            "type": "object",
            "properties": {
                "max_coord": {"type": "number", "description": "Ground half-extent X (m)", "default": 60.0},
                "half_span": {"type": "number", "description": "Ground half-extent Z (m)", "default": 20.0},
            },
        },
    ),
    Tool(
        name="submit_job",
        description="Submit Abaqus job and wait for completion. Returns job status when done.",
        inputSchema={
            "type": "object",
            "required": ["job_name"],
            "properties": {
                "job_name": {"type": "string", "description": "Job name"},
                "cpus": {"type": "integer", "description": "CPU cores", "default": 4},
                "memory_percent": {"type": "integer", "description": "Memory limit (%)", "default": 80},
            },
        },
    ),
    Tool(
        name="get_max_displacement",
        description="Extract maximum displacement magnitude from an ODB file",
        inputSchema={
            "type": "object",
            "required": ["odb_path"],
            "properties": {
                "odb_path": {"type": "string", "description": "Path to .odb file"},
                "instance_name": {"type": "string", "description": "Optional filter by instance name"},
            },
        },
    ),
    Tool(
        name="plot_displacement_curve",
        description="Plot displacement vs time curve as PNG using matplotlib (Agg backend)",
        inputSchema={
            "type": "object",
            "required": ["time_values", "disp_values", "output_path"],
            "properties": {
                "time_values": {"type": "array", "items": {"type": "number"}, "description": "Time values"},
                "disp_values": {"type": "array", "items": {"type": "number"}, "description": "Displacement values"},
                "output_path": {"type": "string", "description": "Path for output PNG image"},
            },
        },
    ),
    Tool(
        name="create_cut_zone",
        description="Identify elements at a given height in all column instances and create part-level element sets for demolition simulation",
        inputSchema={
            "type": "object",
            "required": ["cut_height"],
            "properties": {
                "cut_height": {"type": "number", "description": "Height (m) at which to cut columns"},
            },
        },
    ),
    Tool(
        name="inject_cut_zone_inp",
        description="Inject WEAK_C30 material, SECTION CONTROLS with element deletion, and STATUS/SDEG output into an existing INP file",
        inputSchema={
            "type": "object",
            "required": ["inp_path", "cut_zone_refs"],
            "properties": {
                "inp_path": {"type": "string", "description": "Path to INP file to modify"},
                "cut_zone_refs": {"type": "array", "items": {"type": "array"}, "description": "List of [inst_name, set_name, n_elem] tuples from create_cut_zone"},
                "step_name": {"type": "string", "description": "Step name for section controls", "default": "Collapse"},
            },
        },
    ),
    Tool(
        name="build_factory",
        description="Build complete factory model — all columns, trusses, roof slab with mesh, CDP materials, and assembly in a single call",
        inputSchema={
            "type": "object",
            "required": ["num_bays", "span", "bay_length", "total_height"],
            "properties": {
                "num_bays": {"type": "integer", "description": "Number of bays"},
                "span": {"type": "number", "description": "Span width (m)"},
                "bay_length": {"type": "number", "description": "Bay length along columns (m)"},
                "total_height": {"type": "number", "description": "Column total height (m)"},
                "column_width": {"type": "number", "description": "Column section width (m)", "default": 0.5},
                "column_depth": {"type": "number", "description": "Column section depth (m)", "default": 0.5},
                "mesh_size": {"type": "number", "description": "Mesh seed size (m)", "default": 0.3},
                "truss_height": {"type": "number", "description": "Truss height (m)", "default": 2.0},
                "slab_thickness": {"type": "number", "description": "Roof slab thickness (m)", "default": 0.15},
            },
        },
    ),
    Tool(
        name="setup_collapse",
        description="Full end-to-end collapse simulation — build factory, create step, ground/contact, gravity, cut zone, submit job, wait for completion",
        inputSchema={
            "type": "object",
            "required": ["config"],
            "properties": {
                "config": {
                    "type": "object",
                    "description": "Full config with building, collapse, job, materials sections (see project_config.json)",
                },
                "project_dir": {
                    "type": "string",
                    "description": "Output directory for INP and result files",
                },
            },
        },
    ),
    Tool(
        name="create_cooling_tower",
        description="Create hyperboloid cooling tower shell part with S4R mesh built at creation — two-segment hyperbola meridian (base-throat-top), 70m tower defaults. Opening is NOT cut here; it is handled post-mesh by mesh_tower + INP write exclusion.",
        inputSchema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Part name"},
                "height": {"type": "number", "description": "Tower height (m)", "default": 70.0},
                "base_radius": {"type": "number", "description": "Base radius (m)", "default": 25.5},
                "throat_radius": {"type": "number", "description": "Throat radius (m)", "default": 14.5},
                "throat_elevation": {"type": "number", "description": "Throat elevation (m)", "default": 55.0},
                "top_radius": {"type": "number", "description": "Top radius (m)", "default": 15.599},
                "wall_thickness": {"type": "number", "description": "Shell wall thickness (m), used by section assignment", "default": 0.12},
                "opening_bottom_elevation": {"type": "number", "description": "Opening bottom elevation (m), sets the refined mesh band", "default": 11.0},
                "opening_height": {"type": "number", "description": "Opening height (m)", "default": 3.0},
            },
        },
    ),
    Tool(
        name="assign_tower_materials",
        description="Assign C30 CDP (full GB50010 hardening/stiffening tables) + rebar steel to a tower part with composite shell section (2 concrete layers + 1 rebar layer)",
        inputSchema={
            "type": "object",
            "required": ["part_name"],
            "properties": {
                "part_name": {"type": "string", "description": "Tower part name"},
                "wall_thickness": {"type": "number", "description": "Total wall thickness (m), split into 2 concrete layers", "default": 0.12},
                "rebar_thickness": {"type": "number", "description": "Rebar smeared layer thickness (m)", "default": 0.0005},
            },
        },
    ),
    Tool(
        name="mesh_tower",
        description="Collect tower opening-band elements (centroid criterion: elevation + azimuth range) into the OpeningHole element set; actual element removal happens when the INP is written",
        inputSchema={
            "type": "object",
            "required": ["part_name"],
            "properties": {
                "part_name": {"type": "string", "description": "Tower part name"},
                "opening_bottom_elevation": {"type": "number", "description": "Opening bottom elevation (m)", "default": 11.0},
                "opening_height": {"type": "number", "description": "Opening height (m)", "default": 3.0},
                "opening_angle_deg": {"type": "number", "description": "Opening central angle (degrees)", "default": 98.0},
                "opening_center_angle_deg": {"type": "number", "description": "Opening center azimuth (degrees, 0 = +X)", "default": 0.0},
            },
        },
    ),
    Tool(
        name="setup_tower_collapse",
        description="Submit a cooling tower collapse solve ASYNCHRONOUSLY: generates the full INP directly from parameters (composite shell, CDP+rebar, fixed mass scaling dt=4e-4, ENCASTRE base, gravity ramp, general contact, full output — same cards as the validated run), submits the job and returns immediately with job_id, status=submitted, estimated_duration_s and odb_path. DO NOT wait for completion — poll with get_collapse_status until status=completed, then extract_collapse_frames + render_collapse_video. Estimate: n_theta=128 solves in ~400s (range ±50%), smaller n_theta floored at 300s.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tower part name", "default": "Tower"},
                "height": {"type": "number", "description": "Tower height (m)", "default": 70.0},
                "base_radius": {"type": "number", "description": "Base radius (m)", "default": 25.5},
                "throat_radius": {"type": "number", "description": "Throat radius (m)", "default": 14.5},
                "throat_elevation": {"type": "number", "description": "Throat elevation (m)", "default": 55.0},
                "top_radius": {"type": "number", "description": "Top radius (m)", "default": 15.599},
                "wall_thickness": {"type": "number", "description": "Wall thickness (m)", "default": 0.12},
                "opening_bottom_elevation": {"type": "number", "description": "Opening bottom elevation (m)", "default": 11.0},
                "opening_height": {"type": "number", "description": "Opening height (m)", "default": 3.0},
                "opening_angle_deg": {"type": "number", "description": "Opening central angle (degrees)", "default": 98.0},
                "opening_center_angle_deg": {"type": "number", "description": "Opening center azimuth (degrees, 0 = +X)", "default": 0.0},
                "n_theta": {"type": "integer", "description": "Circumferential mesh divisions — reduce for a faster solve (128 ≈ 400s; estimate floored at 300s, range ±50%)", "default": 128},
                "settle_time": {"type": "number", "description": "Gravity settle phase duration (s)", "default": 1.0},
                "time_period": {"type": "number", "description": "Collapse phase duration (s)", "default": 12.0},
                "cpus": {"type": "integer", "description": "CPU cores", "default": 4},
                "memory_percent": {"type": "integer", "description": "Memory limit (%)", "default": 80},
            },
        },
    ),
    Tool(
        name="extract_collapse_frames",
        description="Extract tower nodal displacement frames from the collapse ODB into data.npz (X/conn/t/U) for video rendering. Takes 1-3 minutes. Must be called AFTER setup_tower_collapse's job reaches status=completed (poll get_collapse_status). Does NOT rerun the solve.",
        inputSchema={
            "type": "object",
            "properties": {
                "odb_path": {"type": "string", "description": "Path to the collapse .odb (default: auto-discover the session workdir tower_job_run.odb)"},
                "out_dir": {"type": "string", "description": "Output directory (default: <project>/scripts/_tower_frames)"},
                "n_targets": {"type": "integer", "description": "Number of output frames", "default": 50},
                "t_start": {"type": "number", "description": "First target time (s)", "default": 0.5},
                "t_end": {"type": "number", "description": "Last target time (s)", "default": 13.0},
            },
        },
    ),
    Tool(
        name="render_collapse_video",
        description="Render the collapse animation from extracted frames: 50 frames x 2 views (side + top), compose two MP4s and deploy them to frontend/public/resource/Abaqus/ (same filenames — the frontend picks them up automatically), plus compute the collapse footprint (max/p95 radius, direction from the max-displacement node, final height). style='raw' renders single-color wireframe frames (no displacement color map, no ground circle, no colorbar) and writes cooling_tower_collapse_raw.mp4 / cooling_tower_collapse_top_raw.mp4 instead. One style per call. Runs in the server process — NO Abaqus license needed. Takes 3-8 minutes. Call AFTER extract_collapse_frames.",
        inputSchema={
            "type": "object",
            "properties": {
                "npz_path": {"type": "string", "description": "Path to the extracted data.npz (default: <project>/scripts/_tower_frames/data.npz)"},
                "fps": {"type": "integer", "description": "Video frame rate", "default": 10},
                "width": {"type": "integer", "description": "Frame width (px)", "default": 1280},
                "height": {"type": "integer", "description": "Frame height (px)", "default": 720},
                "style": {"type": "string", "description": "'rendered' (displacement color map + ground circle) or 'raw' (single-color wireframe, no ground/colorbar)", "default": "rendered"},
            },
        },
    ),
    Tool(
        name="get_collapse_status",
        description="Poll the collapse solve progress from the .sta status file. Returns status (submitted/running/completed/terminated/failed/not_found) with progress percent, step/total time, increments, and ODB availability. wait_seconds up to 180 per call; the solve keeps running in the background between calls. Loop until status=completed.",
        inputSchema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job id returned by setup_tower_collapse", "default": "tower_job_run"},
                "wait_seconds": {"type": "integer", "description": "Block this call up to N seconds (max 180)", "default": 60},
            },
        },
    ),
    Tool(
        name="stop_collapse",
        description="Terminate a running collapse solve: kill the solver process, remove the .lck lock. Use when the user wants to abort a long solve.",
        inputSchema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job id returned by setup_tower_collapse", "default": "tower_job_run"},
            },
        },
    ),
]


def _find_abaqus_launcher():
    """Read abaqus_env.json to locate the Abaqus command launcher (abq*.bat).

    Abaqus 2026 (3DEXPERIENCE integrated build) has NO standalone python.exe —
    the only valid entry point is `abq2026.bat cae noGUI=script.py`.
    """
    env_json = os.path.join(
        _PROJECT_DIR, "caiao_servers", "abaqus_environment_server", "abaqus_env.json"
    )
    env = {}
    try:
        with open(env_json, "r", encoding="utf-8") as f:
            env = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read {env_json}: {e}")

    paths = env.get("paths", {})
    candidates = []
    launcher = paths.get("launcher")
    if launcher:
        candidates.append(launcher)
    commands_dir = paths.get("commands")
    if commands_dir:
        candidates.extend([
            os.path.join(commands_dir, "abq2026.bat"),
            os.path.join(commands_dir, "abaqus.bat"),
        ])
    # Fallback: scan PATH for any abq*.bat
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if not p:
            continue
        try:
            candidates.extend(glob.glob(os.path.join(p, "abq*.bat")))
        except OSError:
            pass

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate, env
    return None, env


class AbaqusSession:
    """Manages a persistent Abaqus CAE noGUI kernel process with a file-based IPC channel.

    The Abaqus kernel is launched once as:
        cmd /c <abq2026.bat> cae noGUI=<abaqus_driver.py>
    The driver keeps the kernel alive (shared `mdb` model database) and polls task files.
    Each tool call writes task_<id>.json and waits for result_<id>.json.
    """

    # Timeouts are env-tunable and mean "single tool call protection net" — the
    # long tower solve runs in the background and is polled via get_collapse_status,
    # so it never blocks a call up to its full duration.
    def __init__(self):
        self._process = None
        self._lock = asyncio.Lock()
        self._workdir = None
        self._kernel_log = None
        self._tool_timeout_s = _env_int("ABAQUS_TOOL_TIMEOUT_S", 900)
        self._kernel_boot_timeout_s = _env_int("ABAQUS_KERNEL_BOOT_TIMEOUT_S", 180)
        self._poll_interval_s = _env_float("ABAQUS_POLL_INTERVAL_S", 0.5)

    @property
    def workdir(self) -> str | None:
        return self._workdir

    def _ensure_started(self):
        if self._process is not None and self._process.poll() is None:
            return

        launcher, env_data = _find_abaqus_launcher()
        if not launcher:
            raise RuntimeError(
                "Abaqus launcher (abq*.bat) not found. "
                "Check abaqus_env.json in abaqus_environment_server."
            )
        logger.info(f"launcher resolved to: {launcher}")
        logger.info(f"SERVER_DIR={_SERVER_DIR}  cwd={os.getcwd()}")

        driver_script = os.path.join(_SERVER_DIR, "abaqus_driver.py")
        self._workdir = tempfile.mkdtemp(prefix="abaqus_session_")
        self._kernel_log = open(
            os.path.join(self._workdir, "kernel.log"),
            "w",
            encoding="utf-8",
            errors="replace",
        )

        env = os.environ.copy()
        license_server = env_data.get("license", {}).get("server", "")
        if license_server:
            env["ABAQUSLM_LICENSE_FILE"] = license_server
        env["ABAQUS_DRIVER_WORKDIR"] = self._workdir
        env["ABAQUS_DRIVER_SERVERDIR"] = _SERVER_DIR
        # kernel-side fallback submit path (subprocess job=...) uses this
        env["ABAQUS_LAUNCHER"] = launcher

        # shell=True hands the raw command string to cmd.exe with interactive cmd
        # quoting rules — this is the exact form that works when run by hand:
        #     abq2026.bat cae noGUI="path with spaces\script.py"
        # (subprocess list-args + ["cmd","/c",...] double-escapes the quotes.)
        cmdline = f'"{launcher}" cae noGUI="{driver_script}"'
        logger.info(
            f"Starting Abaqus kernel: {cmdline} (workdir={self._workdir}) "
            f"lic={license_server or '(inherited)'}"
        )
        logger.info(
            "env keys: ABAQUS_DRIVER_WORKDIR={} ABAQUS_DRIVER_SERVERDIR={}".format(
                env.get("ABAQUS_DRIVER_WORKDIR"), env.get("ABAQUS_DRIVER_SERVERDIR")
            )
        )
        self._process = subprocess.Popen(
            cmdline,
            cwd=self._workdir,
            # CRITICAL: under MCP stdio the server's stdin is the MCP protocol
            # pipe. Without DEVNULL the Abaqus kernel inherits that pipe and can
            # block forever trying to read from it (kernel.log stays 0 bytes,
            # no ready.flag, process alive). DEVNULL gives it an EOF immediately.
            stdin=subprocess.DEVNULL,
            stdout=self._kernel_log,
            stderr=subprocess.STDOUT,
            env=env,
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        logger.info(f"Abaqus kernel started (pid={self._process.pid})")

    def _kill_process_tree(self):
        """Force-kill the kernel. shell=True gives us the cmd.exe PID, so a plain
        kill() would leave the SMAPython child orphaned and holding the license —
        use taskkill /T to take the whole tree down."""
        pid = self._process.pid if self._process is not None else None
        self._process = None
        if pid:
            try:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(pid)],
                    capture_output=True,
                    timeout=15,
                )
            except Exception:
                pass

    async def _wait_kernel_ready(self):
        """Wait for abaqus_driver.py to write ready.flag (proves the kernel is
        actually running the tool loop). Fail fast with the kernel log tail."""
        ready = os.path.join(self._workdir, "ready.flag")
        deadline = time.monotonic() + self._kernel_boot_timeout_s
        while time.monotonic() < deadline:
            if self._process is None or self._process.poll() is not None:
                self._kill_process_tree()
                raise RuntimeError(
                    "Abaqus kernel exited during boot "
                    f"(before ready.flag). See {os.path.join(self._workdir, 'kernel.log')}"
                )
            if os.path.exists(ready):
                logger.info("Abaqus kernel ready")
                return
            await asyncio.sleep(self._poll_interval_s)
        self._kill_process_tree()
        tail = ""
        log_path = os.path.join(self._workdir, "kernel.log")
        try:
            if os.path.isfile(log_path):
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.read().splitlines()
                tail = "\n".join(lines[-20:])
        except OSError:
            pass
        listing = ""
        try:
            names = sorted(os.listdir(self._workdir))
            listing = ", ".join(names) if names else "(empty)"
        except OSError:
            listing = "(unreadable)"
        raise RuntimeError(
            f"Abaqus kernel failed to boot within {self._kernel_boot_timeout_s}s "
            f"(no ready.flag). workdir={self._workdir} files=[{listing}] "
            f"kernel.log_size={os.path.getsize(log_path) if os.path.isfile(log_path) else 0} "
            f"Kernel log tail:\n{tail}"
        )

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        async with self._lock:
            self._ensure_started()
            await self._wait_kernel_ready()

            req_id = uuid.uuid4().hex
            task_path = os.path.join(self._workdir, f"task_{req_id}.json")
            result_path = os.path.join(self._workdir, f"result_{req_id}.json")
            request = {"id": req_id, "tool": tool_name, "arguments": arguments}

            try:
                with open(task_path, "w", encoding="utf-8") as f:
                    json.dump(request, f, ensure_ascii=False)
            except OSError as e:
                logger.warning(f"Failed to write task file, restarting kernel: {e}")
                self._process = None
                self._ensure_started()
                with open(task_path, "w", encoding="utf-8") as f:
                    json.dump(request, f, ensure_ascii=False)

            deadline = time.monotonic() + self._tool_timeout_s
            while time.monotonic() < deadline:
                if self._process is None or self._process.poll() is not None:
                    raise RuntimeError(
                        "Abaqus kernel exited unexpectedly. "
                        f"See {os.path.join(self._workdir, 'kernel.log')}"
                    )
                if os.path.exists(result_path):
                    with open(result_path, "r", encoding="utf-8") as f:
                        response = json.load(f)
                    try:
                        os.remove(result_path)
                    except OSError:
                        pass
                    if "error" in response:
                        out = {"error": response["error"]}
                        if response.get("traceback"):
                            out["traceback"] = response["traceback"]
                        return out
                    return response.get("result", {})
                await asyncio.sleep(self._poll_interval_s)

            self._kill_process_tree()
            raise TimeoutError(
                f"Tool {tool_name} timed out after {self._tool_timeout_s}s. "
                f"Kernel log: {os.path.join(self._workdir, 'kernel.log')}"
            )

    def stop(self):
        # a tower solve runs as its own process tree (not under the kernel cmd)
        # — kill it explicitly so the session exit cannot orphan a solver
        if self._workdir and os.path.exists(
                os.path.join(self._workdir, TOWER_JOB_NAME + ".lck")):
            try:
                subprocess.run(["taskkill", "/F", "/IM", "explicit.exe"],
                               capture_output=True, timeout=15)
            except Exception:
                pass
        if self._process is not None:
            try:
                if self._workdir:
                    exit_flag = os.path.join(self._workdir, "exit.flag")
                    with open(exit_flag, "w", encoding="utf-8") as f:
                        f.write("exit")
                self._process.wait(timeout=30)
            except Exception:
                self._kill_process_tree()
            else:
                self._process = None
        if self._kernel_log is not None:
            try:
                self._kernel_log.close()
            except Exception:
                pass
            self._kernel_log = None


_session = AbaqusSession()


def _read_job_status(job_id: str, workdir: str) -> dict:
    """Parse tower_job_run.{sta,log,lck,odb} into a status dict."""
    base = os.path.join(workdir, job_id)
    info = {
        "job_id": job_id,
        "status": "submitted",
        "progress_percent": None,
        "increments": None,
        "step_time": None,
        "total_time": None,
        "odb_exists": os.path.exists(base + ".odb"),
        "lck_exists": os.path.exists(base + ".lck"),
        "odb_path": base + ".odb",
    }
    text = ""
    for ext in (".sta", ".log"):
        path = base + ext
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text += fh.read()
            except OSError:
                pass
    if not text and not info["lck_exists"] and not info["odb_exists"]:
        if os.path.exists(base + ".inp"):
            info["status"] = "submitted"  # INP written, solver still starting
        else:
            info["status"] = "not_found"
        return info
    low = text.lower()
    if "completed successfully" in low or "analysis has completed" in low:
        info["status"] = "completed"
    elif "has terminated" in low or "job has terminated" in low:
        info["status"] = "terminated"
    elif "*** error" in low or "exited with an error" in low:
        info["status"] = "failed"
    elif info["lck_exists"] or "step time" in low:
        info["status"] = "running"
    for row in text.splitlines():
        fields = row.split()
        if len(fields) >= 3 and fields[0].isdigit() and \
                re.match(r"^\d+\.?\d*E[+-]\d+$", fields[1]):
            info["increments"] = int(fields[0])
            info["step_time"] = float(fields[1])
            info["total_time"] = float(fields[2])
    if info["status"] == "running" and info["total_time"] is not None:
        info["progress_percent"] = round(
            min(info["total_time"] / TOTAL_SIM_TIME, 1.0) * 100.0, 1)
    return info


def _handle_get_collapse_status(arguments: dict) -> dict:
    job_id = arguments.get("job_id", TOWER_JOB_NAME)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(job_id)):
        return {"error": f"invalid job_id: {job_id}"}
    try:
        wait_seconds = max(0, min(int(arguments.get("wait_seconds", 60)), 180))
    except (TypeError, ValueError):
        wait_seconds = 60
    workdir = _session.workdir
    if not workdir:
        return {"job_id": job_id, "status": "not_found",
                "message": "no kernel session yet — nothing has been submitted"}
    deadline = time.monotonic() + wait_seconds
    while True:
        info = _read_job_status(job_id, workdir)
        est = _read_job_estimate(job_id, workdir)
        if est:
            info["estimated_duration_s"] = est["estimated_duration_s"]
            info["estimated_duration_range"] = est["estimated_duration_range"]
        if info["status"] in ("completed", "terminated", "failed", "not_found"):
            return info
        if time.monotonic() >= deadline:
            return info
        time.sleep(2.0)


def _compute_footprint(X, t, U, npz_path: str) -> dict:
    """Footprint from the final extracted frame; direction uses the azimuth of
    the MAX-DISPLACEMENT node (not the farthest node — the fixed base ring
    would dominate the farthest-node metric)."""
    pos = X + U[-1]
    r = np.hypot(pos[:, 0], pos[:, 2])
    disp = np.linalg.norm(U[-1], axis=1)
    i_max = int(np.argmax(disp))
    n = len(r)
    p95 = float(np.sort(r)[int(0.95 * (n - 1))])

    def _az(x: float, z: float) -> float:
        return (math.degrees(math.atan2(z, x)) + 360.0) % 360.0

    mx, mz = float(pos[:, 0].mean()), float(pos[:, 2].mean())
    base_r = float(np.hypot(X[:, 0], X[:, 2]).max())
    r_max = float(r.max())
    return {
        "odb": npz_path,
        "frame_time_s": float(t[-1]),
        "tower_nodes": n,
        "max_radius_m": round(r_max, 3),
        "p95_radius_m": round(p95, 3),
        "direction_deg": round(_az(float(pos[i_max, 0]), float(pos[i_max, 2])), 2),
        "com_radius_m": round(math.hypot(mx, mz), 3),
        "com_direction_deg": round(_az(mx, mz), 2),
        "tower_base_radius_m": round(base_r, 3),
        "init_height_m": round(float(X[:, 1].max()), 3),
        "final_height_m": round(float(pos[:, 1].max()), 3),
        "ratio_max": round(r_max / base_r, 3) if base_r else None,
        "ratio_p95": round(p95 / base_r, 3) if base_r else None,
    }


def _read_job_estimate(job_id: str, workdir: str) -> dict | None:
    """Read the estimate json written by setup_tower_collapse (kernel side)."""
    path = os.path.join(workdir, job_id + ".estimate.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None


def _handle_render_collapse_video(arguments: dict) -> dict:
    """Render both views + compose MP4s + compute footprint, all in this
    process (needs numpy/matplotlib/imageio — available in the gateway venv).
    Reuses scripts/render_tower_frames.py module functions."""
    import sys as _sys

    scripts_dir = os.path.join(_PROJECT_DIR, "scripts")
    if scripts_dir not in _sys.path:
        _sys.path.insert(0, scripts_dir)
    import render_tower_frames as rtf

    style = arguments.get("style", "rendered")
    if style not in ("rendered", "raw"):
        return {"error": f"invalid style: {style} — expected 'rendered' or 'raw'"}
    raw = style == "raw"

    npz_path = arguments.get("npz_path") or os.path.join(
        scripts_dir, "_tower_frames", "data.npz")
    if not os.path.isfile(npz_path):
        return {"error": f"data.npz not found at {npz_path} — "
                         "run extract_collapse_frames first"}
    rtf.DATA_PATH = npz_path
    rtf.FPS = int(arguments.get("fps", 10))
    rtf.W = int(arguments.get("width", 1280))
    rtf.H = int(arguments.get("height", 720))
    X, conn, t, U = rtf.load_data()
    rtf.N_FRAMES = int(U.shape[0])

    # render module prints progress — keep it out of the MCP stdout pipe
    t0 = time.time()
    with contextlib.redirect_stdout(sys.stderr):
        rtf.mode_all(X, conn, U, raw=raw)
        rtf.mode_compose(raw=raw)
    elapsed = time.time() - t0

    footprint = _compute_footprint(X, t, U, npz_path)
    fp_path = os.path.join(_PROJECT_DIR, "frontend", "public", "resource",
                           "Abaqus", "cooling_tower_footprint.json")
    with open(fp_path, "w", encoding="utf-8") as fh:
        json.dump(footprint, fh, ensure_ascii=False, indent=2)

    return {
        "videos": {
            "side": ("/resource/Abaqus/cooling_tower_collapse_raw.mp4" if raw
                     else "/resource/Abaqus/cooling_tower_collapse.mp4"),
            "top": ("/resource/Abaqus/cooling_tower_collapse_top_raw.mp4" if raw
                    else "/resource/Abaqus/cooling_tower_collapse_top.mp4"),
        },
        "style": style,
        "footprint": footprint,
        "footprint_path": fp_path,
        "frames_rendered": int(U.shape[0]),
        "elapsed_seconds": round(elapsed, 1),
        "message": (f"Rendered {U.shape[0]} frames x 2 views ({style}), deployed "
                    f"2 MP4s to the frontend Abaqus panel, footprint written to "
                    f"{fp_path}"),
    }


def _run_server_tool(name: str, arguments: dict) -> dict:
    if name == "get_collapse_status":
        return _handle_get_collapse_status(arguments)
    if name == "render_collapse_video":
        return _handle_render_collapse_video(arguments)
    return {"error": f"unknown server-only tool: {name}"}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name in _SERVER_ONLY_TOOLS:
            timeout = _env_int("ABAQUS_RENDER_TIMEOUT_S", 900)
            result = await asyncio.wait_for(
                asyncio.to_thread(_run_server_tool, name, arguments), timeout=timeout)
        else:
            result = await _session.call_tool(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        try:
            await server.run(read, write, server.create_initialization_options())
        finally:
            _session.stop()


if __name__ == "__main__":
    asyncio.run(main())
