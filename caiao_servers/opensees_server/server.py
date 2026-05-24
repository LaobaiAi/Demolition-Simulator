"""OpenSees CAIAO Server — high-fidelity nonlinear structural analysis."""

import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("opensees_server")

server = Server("opensees-server")

TOOLS = [
    Tool(
        name="high_fidelity_analysis",
        description="Run high-fidelity static analysis on a 2D frame structure using OpenSees. Returns node displacements and element forces. More accurate than fast analysis but slower.",
        inputSchema={
            "type": "object",
            "properties": {
                "structure": {
                    "type": "object",
                    "description": "Structure definition with nodes, elements, loads, and supports",
                    "properties": {
                        "nodes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "integer"},
                                    "x": {"type": "number"},
                                    "y": {"type": "number"},
                                },
                                "required": ["id", "x", "y"],
                            },
                        },
                        "elements": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "integer"},
                                    "node_i": {"type": "integer"},
                                    "node_j": {"type": "integer"},
                                    "E": {"type": "number"},
                                    "A": {"type": "number"},
                                    "I": {"type": "number"},
                                },
                                "required": ["id", "node_i", "node_j", "E", "A", "I"],
                            },
                        },
                        "loads": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "node_id": {"type": "integer"},
                                    "Fx": {"type": "number"},
                                    "Fy": {"type": "number"},
                                },
                                "required": ["node_id", "Fx", "Fy"],
                            },
                        },
                        "supports": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "node_id": {"type": "integer"},
                                    "type": {"type": "string"},
                                },
                                "required": ["node_id", "type"],
                            },
                        },
                    },
                    "required": ["nodes", "elements", "supports"],
                },
            },
            "required": ["structure"],
        },
    ),
]


_OPENSEES_AVAILABLE = False
try:
    # On Windows, try multiple paths for MKL/Tcl DLL search before importing
    import os as _os
    _file_dir = _os.path.dirname(_os.path.abspath(__file__))
    # conda layout: venv/Library/bin
    _conda_bin = _os.path.join(_file_dir, "..", "..", "gateway", "venv", "Library", "bin")
    # pip layout: venv/Lib/site-packages/<pkg>   (DLLs may be alongside the .pyd)
    _openseespy_dir = _os.path.join(_file_dir, "..", "..", "gateway", "venv", "Lib", "site-packages", "openseespy")
    _dll_paths = [p for p in (_conda_bin, _openseespy_dir) if _os.path.exists(p)]
    if hasattr(_os, "add_dll_directory"):
        for _p in _dll_paths:
            _os.add_dll_directory(_os.path.abspath(_p))
            logger.info(f"Added DLL search directory: {_p}")

    import openseespy.opensees as ops  # noqa: F811
    _OPENSEES_AVAILABLE = True
    logger.info("OpenSeesPy loaded successfully — high-fidelity analysis available")
except Exception as _e:
    logger.warning(f"OpenSeesPy not available — running in degraded mode ({_e})")


def _run_opensees_analysis(structure):
    """Build and run an OpenSees model for static analysis."""
    if not _OPENSEES_AVAILABLE:
        return {"error": "OpenSeesPy is not available on this platform (Windows DLL issue). "
                "The verification comparison UI is ready — install OpenSees on Linux or macOS for full functionality."}
    import openseespy.opensees as ops

    ops.wipe()

    nodes = structure["nodes"]
    elements = structure["elements"]
    loads = structure.get("loads", [])
    supports = structure.get("supports", [])

    # Map user node IDs to OpenSees tags (must be 1-based sequential)
    node_id_to_tag = {}
    for i, n in enumerate(nodes):
        tag = i + 1
        node_id_to_tag[n["id"]] = tag

    # Model setup — 2D, 3 DOFs per node (ux, uy, rz)
    ops.model('basic', '-ndm', 2, '-ndf', 3)

    # Create nodes
    for n in nodes:
        ops.node(node_id_to_tag[n["id"]], n["x"], n["y"])

    # Create material (elastic) and transformation
    mat_tag = 1
    transf_tag = 1
    ops.uniaxialMaterial('Elastic', mat_tag, 210e9)
    ops.geomTransf('Linear', transf_tag)

    # Create elements
    for i, elem in enumerate(elements):
        ele_tag = i + 1
        i_tag = node_id_to_tag[elem["node_i"]]
        j_tag = node_id_to_tag[elem["node_j"]]
        A = elem.get("A", 0.005)
        E = elem.get("E", 210e9)
        I = elem.get("I", 1e-5)
        ops.element('elasticBeamColumn', ele_tag, i_tag, j_tag, A, E, I, transf_tag)

    # Apply supports
    for sup in supports:
        tag = node_id_to_tag[sup["node_id"]]
        sup_type = sup.get("type", "fixed")
        if sup_type == "fixed":
            ops.fix(tag, 1, 1, 1)
        elif sup_type == "hinged":
            ops.fix(tag, 1, 1, 0)
        elif sup_type == "roller":
            ops.fix(tag, 0, 1, 0)
        else:
            ops.fix(tag, 1, 1, 1)

    # Apply loads
    ts_tag = 1
    pat_tag = 1
    ops.timeSeries('Constant', ts_tag)
    ops.pattern('Plain', pat_tag, ts_tag)
    for load in loads:
        tag = node_id_to_tag[load["node_id"]]
        ops.load(tag, load.get("Fx", 0), load.get("Fy", 0), 0)

    # Analysis setup
    ops.system('BandGeneral')
    ops.numberer('Plain')
    ops.constraints('Plain')
    ops.integrator('LoadControl', 1.0)
    ops.algorithm('Linear')
    ops.analysis('Static')

    # Run analysis
    result_code = ops.analyze(1)
    if result_code != 0:
        ops.wipe()
        return {"error": f"OpenSees analysis failed to converge (code {result_code})"}

    # Extract node displacements
    node_displacements = []
    max_disp = 0.0
    for n in nodes:
        tag = node_id_to_tag[n["id"]]
        ux = ops.nodeDisp(tag, 1)
        uy = ops.nodeDisp(tag, 2)
        node_displacements.append({
            "node_id": n["id"],
            "ux": float(ux),
            "uy": float(uy),
        })
        max_disp = max(max_disp, abs(ux) + abs(uy))

    # Extract element forces
    element_forces = []
    max_axial = 0.0
    for i, elem in enumerate(elements):
        ele_tag = i + 1
        forces = ops.eleResponse(ele_tag, 'force')
        if forces and len(forces) >= 3:
            N = forces[0]  # axial force
            element_forces.append({
                "element_id": elem["id"],
                "N": float(N),
                "V1": float(forces[1]) if len(forces) > 1 else 0,
                "M1": float(forces[2]) if len(forces) > 2 else 0,
            })
            max_axial = max(max_axial, abs(N))
        else:
            element_forces.append({
                "element_id": elem["id"],
                "N": 0, "V1": 0, "M1": 0,
            })

    ops.wipe()

    return {
        "node_displacements": node_displacements,
        "element_forces": element_forces,
        "max_displacement": float(max_disp),
        "max_axial_force": float(max_axial),
        "solver": "OpenSeesPy (linear elastic)",
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "high_fidelity_analysis":
            structure = arguments.get("structure", {})
            if not structure:
                return [TextContent(type="text", text="Error: 'structure' argument is required")]
            result = await asyncio.wait_for(
                asyncio.to_thread(_run_opensees_analysis, structure),
                timeout=15.0,  # 60→15s: faster failure when unavailable
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        else:
            return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]

    except asyncio.TimeoutError:
        return [TextContent(type="text", text=json.dumps({"error": "OpenSees analysis timed out (>15s)"}))]
    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
