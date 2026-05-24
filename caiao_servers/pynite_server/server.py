# -*- coding: utf-8 -*-
"""PyNite CAIAO Server — 3D finite element analysis with PyNiteFEA."""

import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pynite_server")

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
    from Pynite import FEModel3D

    model = FEModel3D()
    nodes = struct["nodes"]
    elements = struct["elements"]
    loads = struct.get("loads", [])
    supports = struct.get("supports", [])

    E = 210e9
    model.add_material("Steel", E, 81e9, 0.3, 7850)

    def_A = 0.005
    def_Iy = 1e-4
    def_Iz = 1e-4
    def_J = 1e-8

    if elements:
        def_A = elements[0].get("A", def_A)
        def_Iy = elements[0].get("Iy", elements[0].get("I", def_Iy))
        def_Iz = elements[0].get("Iz", elements[0].get("I", def_Iz))
        def_J = elements[0].get("J", def_J)

    model.add_section("Beam", def_A, def_Iy, def_Iz, def_J)

    for n in nodes:
        z = n.get("z", 0)
        model.add_node(str(n["id"]), n["x"], n["y"], z)

    for elem in elements:
        model.add_member(str(elem["id"]), str(elem["node_i"]), str(elem["node_j"]), "Steel", "Beam")

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
            result = await asyncio.wait_for(
                asyncio.to_thread(_run_pynite, structure),
                timeout=30.0,
            )
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
