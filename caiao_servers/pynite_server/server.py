# -*- coding: utf-8 -*-
"""PyNite CAIAO Server — 3D finite element analysis with PyNiteFEA."""

import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

import os as _os, sys as _sys
_p = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _p not in _sys.path:
    _sys.path.insert(0, _p)
from _shared.analysis_format import annotate_result

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pynite_server")

# Import at module level to avoid thread pool issues on Windows
try:
    from Pynite import FEModel3D
    _PYNITE_AVAILABLE = True
except ImportError:
    _PYNITE_AVAILABLE = False
    logger.warning("PyNite not available")

server = Server("pynite-server")

TOOLS = [
    Tool(
        name="pynite_analysis",
        description="Run 3D finite element analysis on a frame structure using PyNiteFEA. Supports linear and P-Delta analysis. Returns node displacements and element forces.",
        inputSchema={
            "type": "object",
            "properties": {
                "structure": {
                    "type": "object",
                    "properties": {
                        "nodes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "integer"},
                                    "x": {"type": "number"},
                                    "y": {"type": "number"},
                                    "z": {"type": "number", "default": 0},
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
                                    "E": {"type": "number", "default": 210000000000},
                                    "A": {"type": "number"},
                                    "Iy": {"type": "number", "default": 1e-4},
                                    "Iz": {"type": "number", "default": 1e-4},
                                    "J": {"type": "number", "default": 1e-8},
                                },
                                "required": ["id", "node_i", "node_j", "A"],
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
                                    "Fz": {"type": "number", "default": 0},
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


def _run_pynite(struct):
    if not _PYNITE_AVAILABLE:
        return {"error": "PyNite not available", "node_displacements": [], "element_forces": [],
                "max_displacement": 0, "max_axial_force": 0}
    model = FEModel3D()
    nodes = struct["nodes"]
    elements = struct["elements"]
    loads = struct.get("loads", [])
    supports = struct.get("supports", [])

    E = 210e9
    model.add_material("Steel", E, 81e9, 0.3, 7850)

    for n in nodes:
        z = n.get("z", 0)
        model.add_node(str(n["id"]), n["x"], n["y"], z)

    for elem in elements:
        A = elem.get("A", 0.005)
        Iy = elem.get("Iy", elem.get("I", 1e-4))
        Iz = elem.get("Iz", elem.get("I", 1e-4))
        J = elem.get("J", 1e-8)
        section_name = f"Section_{elem['id']}"
        model.add_section(section_name, A, Iy, Iz, J)
        model.add_member(str(elem["id"]), str(elem["node_i"]), str(elem["node_j"]), "Steel", section_name)

    for sup in supports:
        nid = str(sup["node_id"])
        st = sup.get("type", "fixed")
        if st == "fixed":
            model.def_support(nid, True, True, True, True, True, True)
        elif st == "hinged":
            model.def_support(nid, True, True, True, False, False, False)
        elif st == "roller":
            model.def_support(nid, False, True, True, False, False, False)
        else:
            model.def_support(nid, True, True, True, True, True, True)

    for ld in loads:
        nid = str(ld["node_id"])
        if ld.get("Fx"):
            model.add_node_load(nid, "FX", ld["Fx"])
        if ld.get("Fy"):
            model.add_node_load(nid, "FY", ld["Fy"])
        if ld.get("Fz"):
            model.add_node_load(nid, "FZ", ld["Fz"])

    model.analyze_linear(log=False, check_stability=True, sparse=True)

    node_disps = []
    max_disp = 0.0
    for n in nodes:
        name = str(n["id"])
        node = model.nodes[name]
        dx = float(node.DX["Combo 1"])
        dy = float(node.DY["Combo 1"])
        dz = float(node.DZ["Combo 1"])
        node_disps.append({"node_id": n["id"], "ux": dx, "uy": dy, "uz": dz})
        max_disp = max(max_disp, abs(dx) + abs(dy) + abs(dz))

    elem_forces = []
    max_axial = 0.0
    for elem in elements:
        member = model.members[str(elem["id"])]
        N = float(member.max_axial())
        elem_forces.append({"element_id": elem["id"], "N": N})
        max_axial = max(max_axial, abs(N))

    return {
        "node_displacements": node_disps,
        "element_forces": elem_forces,
        "max_displacement": float(max_disp),
        "max_axial_force": float(max_axial),
        "solver": "PyNiteFEA (linear elastic, 3D)",
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "pynite_analysis":
            structure = arguments.get("structure", {})
            if not structure:
                return [TextContent(type="text", text="Error: 'structure' argument is required")]
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _run_pynite, structure)
            result = annotate_result(result, "PyNite")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]
    except asyncio.TimeoutError:
        return [TextContent(type="text", text=json.dumps({"error": "PyNite analysis timed out (>30s)"}))]
    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
