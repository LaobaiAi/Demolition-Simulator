# -*- coding: utf-8 -*-
"""FAPP CAIAO Server — lightweight 3D frame analysis via direct stiffness method."""

import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fapp_server")

server = Server("fapp-server")

TOOLS = [
    Tool(
        name="fapp_analysis",
        description="Run lightweight 3D frame analysis using FAPP (direct stiffness method). Extremely fast, pure Python. Ideal for quick verification. Returns node displacements and element forces.",
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


def _run_fapp(struct):
    from fapp.analysis import Analysis

    model = Analysis()
    nodes = struct["nodes"]
    elements = struct["elements"]
    loads = struct.get("loads", [])
    supports = struct.get("supports", [])

    # FAPP uses 0-based sequential tags internally (assign_dof uses 6*self.tag).
    # Map user node IDs to FAPP sequential tags.
    node_id_to_tag = {}
    for tag, n in enumerate(nodes):
        z = n.get("z", 0)
        model.add_node(tag, n["x"], n["y"], z)
        node_id_to_tag[n["id"]] = tag

    v = 0.3
    # FAPP ELE_FOR is indexed by the order elements are added, not by their tag.
    # Use sequential element indices and map user element IDs accordingly.
    elem_id_to_idx = {}
    for idx, elem in enumerate(elements):
        E = elem.get("E", 210e9)
        A = elem.get("A", 0.005)
        Ayy = Azz = 0.84 * A
        Iy = elem.get("Iy", elem.get("I", 1e-4))
        Iz = elem.get("Iz", elem.get("I", 1e-4))
        J = elem.get("J", 1e-8)
        i_tag = node_id_to_tag[elem["node_i"]]
        j_tag = node_id_to_tag[elem["node_j"]]
        model.add_element(idx, i_tag, j_tag, A, Ayy, Azz, Iy, Iz, J, E, v)
        elem_id_to_idx[elem["id"]] = idx

    for sup in supports:
        tag = node_id_to_tag[sup["node_id"]]
        st = sup.get("type", "fixed")
        if st == "fixed":
            model.add_fixity(tag, 0, 0, 0, 0, 0, 0)
        elif st == "hinged":
            model.add_fixity(tag, 0, 0, 0, "nan", "nan", "nan")
        elif st == "roller":
            model.add_fixity(tag, "nan", 0, 0, "nan", "nan", "nan")
        else:
            model.add_fixity(tag, 0, 0, 0, 0, 0, 0)

    for ld in loads:
        tag = node_id_to_tag[ld["node_id"]]
        model.add_load_nodal(tag, ld.get("Fx", 0) or 0, ld.get("Fy", 0) or 0, ld.get("Fz", 0) or 0)

    model.solve(print_info=False)

    # DEFL: list indexed by node FAPP tag → [ux, uy, uz, rx, ry, rz]
    defl = model.DEFL
    node_disps = []
    max_disp = 0.0

    for n in nodes:
        nid = n["id"]
        tag = node_id_to_tag[nid]
        d = defl[tag] if tag < len(defl) else [0, 0, 0, 0, 0, 0]
        ux, uy, uz = float(d[0]), float(d[1]), float(d[2])
        node_disps.append({"node_id": nid, "ux": ux, "uy": uy, "uz": uz})
        max_disp = max(max_disp, abs(ux) + abs(uy) + abs(uz))

    # ELE_FOR: list indexed by addition order → [Fx_i,Fy_i,Fz_i,Mx_i,My_i,Mz_i, Fx_j,Fy_j,Fz_j,Mx_j,My_j,Mz_j]
    ele_for = model.ELE_FOR
    elem_forces = []
    max_axial = 0.0
    for elem in elements:
        eid = elem["id"]
        idx = elem_id_to_idx[eid]
        if idx < len(ele_for):
            ef = ele_for[idx]
            N = abs(float(ef[0]))  # axial force = |Fx_i|
        else:
            N = 0
        elem_forces.append({"element_id": eid, "N": N})
        max_axial = max(max_axial, N)

    return {
        "node_displacements": node_disps,
        "element_forces": elem_forces,
        "max_displacement": float(max_disp),
        "max_axial_force": float(max_axial),
        "solver": "FAPP (direct stiffness, 3D)",
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "fapp_analysis":
            structure = arguments.get("structure", {})
            if not structure:
                return [TextContent(type="text", text="Error: 'structure' argument is required")]
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _run_fapp, structure)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]
    except asyncio.TimeoutError:
        return [TextContent(type="text", text=json.dumps({"error": "FAPP analysis timed out (>30s)"}))]
    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
