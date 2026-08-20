"""Abaqus Session CAIAO Server — MCP wrapper managing a persistent Abaqus CAE session.

Runs in system Python. On first tool call, spawns an Abaqus Python subprocess
running abaqus_session.py, then forwards all tool calls via stdin/stdout JSON-RPC.
The single Abaqus process persists across tool calls, sharing one model database.
"""

import asyncio
import glob
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import uuid

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("abaqus_session")

_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(os.path.dirname(_SERVER_DIR))

server = Server("abaqus-session")

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

    # Solver jobs (setup_collapse) can run for many minutes.
    _TOOL_TIMEOUT_S = 3600

    def __init__(self):
        self._process = None
        self._lock = asyncio.Lock()
        self._workdir = None
        self._kernel_log = None

    def _ensure_started(self):
        if self._process is not None and self._process.poll() is None:
            return

        launcher, env_data = _find_abaqus_launcher()
        if not launcher:
            raise RuntimeError(
                "Abaqus launcher (abq*.bat) not found. "
                "Check abaqus_env.json in abaqus_environment_server."
            )

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

        # shell=True hands the raw command string to cmd.exe with interactive cmd
        # quoting rules — this is the exact form that works when run by hand:
        #     abq2026.bat cae noGUI="path with spaces\script.py"
        # (subprocess list-args + ["cmd","/c",...] double-escapes the quotes.)
        cmdline = f'"{launcher}" cae noGUI="{driver_script}"'
        logger.info(f"Starting Abaqus kernel: {cmdline} (workdir={self._workdir})")
        self._process = subprocess.Popen(
            cmdline,
            cwd=self._workdir,
            stdout=self._kernel_log,
            stderr=subprocess.STDOUT,
            env=env,
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        logger.info(f"Abaqus kernel started (pid={self._process.pid})")

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        async with self._lock:
            self._ensure_started()

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

            deadline = time.monotonic() + self._TOOL_TIMEOUT_S
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
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
                await asyncio.sleep(0.5)

            raise TimeoutError(
                f"Tool {tool_name} timed out after {self._TOOL_TIMEOUT_S}s. "
                f"Kernel log: {os.path.join(self._workdir, 'kernel.log')}"
            )

    def stop(self):
        if self._process is not None:
            try:
                if self._workdir:
                    exit_flag = os.path.join(self._workdir, "exit.flag")
                    with open(exit_flag, "w", encoding="utf-8") as f:
                        f.write("exit")
                self._process.wait(timeout=30)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        if self._kernel_log is not None:
            try:
                self._kernel_log.close()
            except Exception:
                pass
            self._kernel_log = None


_session = AbaqusSession()


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
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
