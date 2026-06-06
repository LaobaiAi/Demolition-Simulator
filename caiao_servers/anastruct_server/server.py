"""anaStruct CAIAO Server - 2D frame analysis and generation."""

import asyncio
import json
import logging
import os
import sys

# Ensure gateway venv packages are available (anastruct, etc.)
_VENV_SITE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "gateway", "venv", "Lib", "site-packages")
if os.path.isdir(_VENV_SITE) and _VENV_SITE not in sys.path:
    sys.path.insert(0, _VENV_SITE)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)
from _shared.analysis_format import annotate_result

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("anastruct_server")

# Import anaStruct at module level (not inside the async handler thread)
# to avoid C extension import issues on Windows thread pool
try:
    from anastruct import SystemElements
    _ANASTRUCT_AVAILABLE = True
except ImportError:
    _ANASTRUCT_AVAILABLE = False
    logger.warning("anastruct not available, analysis will fail")

server = Server("anastruct-server")

TOOLS = [
    Tool(
        name="generate_simple_frame",
        description="Generate a simple 2D rectangular frame structure with nodes, elements, supports, and loads.",
        inputSchema={
            "type": "object",
            "properties": {
                "spans": {"type": "integer", "description": "Number of horizontal bays/spans (default 2)", "default": 2},
                "stories": {"type": "integer", "description": "Number of vertical stories/floors (default 2)", "default": 2},
                "span_length": {"type": "number", "description": "Length of each span in meters (default 6.0)", "default": 6.0},
                "story_height": {"type": "number", "description": "Height of each story in meters (default 3.0)", "default": 3.0},
                "E": {"type": "number", "description": "Young's modulus in Pa (default 210e9 for steel)", "default": 210e9},
                "A": {"type": "number", "description": "Cross-sectional area in m^2 (default 0.005)", "default": 0.005},
                "I": {"type": "number", "description": "Moment of inertia about out-of-plane axis in m^4 (default 1e-5)", "default": 1e-5},
                "Iy": {"type": "number", "description": "Moment of inertia about local y-axis in m^4 (default 1e-5)", "default": 1e-5},
                "Iz": {"type": "number", "description": "Moment of inertia about local z-axis in m^4 (default 1e-5)", "default": 1e-5},
                "J": {"type": "number", "description": "Torsional constant in m^4 (default 1e-8)", "default": 1e-8},
            },
            "required": [],
        },
    ),
    Tool(
        name="analyze_frame",
        description="Analyze a 2D frame structure and return node displacements and element forces.",
        inputSchema={
            "type": "object",
            "properties": {
                "structure": {
                    "type": "object",
                    "description": "Structure definition with nodes, elements, loads, and supports",
                    "properties": {
                        "nodes": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "x": {"type": "number"}, "y": {"type": "number"}}, "required": ["id", "x", "y"]}},
                        "elements": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "node_i": {"type": "integer"}, "node_j": {"type": "integer"}, "E": {"type": "number"}, "A": {"type": "number"}, "I": {"type": "number"}, "Iy": {"type": "number"}, "Iz": {"type": "number"}, "J": {"type": "number"}}, "required": ["id", "node_i", "node_j", "E", "A", "I"]}},
                        "loads": {"type": "array", "items": {"type": "object", "properties": {"node_id": {"type": "integer"}, "Fx": {"type": "number"}, "Fy": {"type": "number"}}, "required": ["node_id", "Fx", "Fy"]}},
                        "supports": {"type": "array", "items": {"type": "object", "properties": {"node_id": {"type": "integer"}, "type": {"type": "string", "enum": ["fixed", "hinged", "roller"]}}, "required": ["node_id", "type"]}},
                    },
                    "required": ["nodes", "elements", "loads", "supports"],
                },
            },
            "required": ["structure"],
        },
    ),
    Tool(
        name="select_critical_element",
        description="Identify the most critical column for demolition based on analysis results. Returns the column element ID with the highest absolute axial force.",
        inputSchema={
            "type": "object",
            "properties": {
                "structure": {"type": "object", "description": "The structure definition from generate_simple_frame"},
                "analysis_result": {"type": "object", "description": "The result from analyze_frame containing element_forces"},
            },
            "required": ["structure", "analysis_result"],
        },
    ),
]


def _generate_frame(spans=2, stories=2, span_length=6.0, story_height=3.0, E=210e9, A=0.005, I=1e-5, Iy=1e-5, Iz=1e-5, J=1e-8):
    """Generate a standard rectangular frame."""
    nodes = []
    elements = []
    element_id = 0

    node_id = 0
    grid = {}
    for row in range(stories + 1):
        for col in range(spans + 1):
            x = col * span_length
            y = row * story_height
            nodes.append({"id": node_id, "x": x, "y": y})
            grid[(col, row)] = node_id
            node_id += 1

    # Columns (vertical)
    for row in range(stories):
        for col in range(spans + 1):
            elements.append({"id": element_id, "node_i": grid[(col, row)], "node_j": grid[(col, row + 1)], "E": E, "A": A, "I": I, "Iy": Iy, "Iz": Iz, "J": J})
            element_id += 1

    # Beams (horizontal)
    for row in range(1, stories + 1):
        for col in range(spans):
            elements.append({"id": element_id, "node_i": grid[(col, row)], "node_j": grid[(col + 1, row)], "E": E, "A": A, "I": I, "Iy": Iy, "Iz": Iz, "J": J})
            element_id += 1

    supports = [{"node_id": grid[(col, 0)], "type": "fixed"} for col in range(spans + 1)]
    loads = [{"node_id": grid[(col, stories)], "Fx": 0, "Fy": -50000} for col in range(spans + 1)]

    return {"nodes": nodes, "elements": elements, "loads": loads, "supports": supports}


def _analyze_structure(structure):
    """Run anaStruct analysis on a structure definition."""
    if not _ANASTRUCT_AVAILABLE:
        return {"error": "anastruct package not available", "node_displacements": [],
                "element_forces": [], "max_displacement": 0, "max_axial_force": 0}

    nodes = structure["nodes"]
    elements = structure["elements"]
    loads = structure.get("loads", [])
    supports = structure.get("supports", [])

    node_coords = {n["id"]: (n["x"], n["y"]) for n in nodes}

    ss = SystemElements()

    # Track mapping: anaStruct internal element ID (1-based) -> original element ID
    elem_id_map = {}
    for elem in elements:
        n1 = node_coords[elem["node_i"]]
        n2 = node_coords[elem["node_j"]]
        E = elem.get("E", 210e9)
        A = elem.get("A", 0.005)
        I = elem.get("I", 1e-5)
        ana_id = ss.add_element(location=[n1, n2], EA=E * A, EI=E * I, g=0)
        elem_id_map[ana_id] = elem["id"]

    # Build reverse mapping: coordinates -> anaStruct node ID
    coord_to_ana = {}
    for orig_id, coord in node_coords.items():
        ana_node = ss.find_node_id(coord)
        if ana_node is not None:
            coord_to_ana[orig_id] = ana_node

    for sup in supports:
        nid = sup["node_id"]
        ana_id = coord_to_ana.get(nid)
        if ana_id is None:
            continue  # Node not present in system (no elements connected)
        sup_type = sup.get("type", "fixed")
        if sup_type == "fixed":
            ss.add_support_fixed(node_id=ana_id)
        elif sup_type == "hinged":
            ss.add_support_hinged(node_id=ana_id)
        elif sup_type == "roller":
            ss.add_support_roll(node_id=ana_id, direction=2)

    if loads:
        for load in loads:
            nid = load["node_id"]
            ana_id = coord_to_ana.get(nid)
            if ana_id is None:
                continue  # Node not present in system
            Fx = load.get("Fx", 0)
            Fy = load.get("Fy", 0)
            if Fx != 0:
                ss.point_load(node_id=ana_id, Fx=Fx)
            if Fy != 0:
                ss.point_load(node_id=ana_id, Fy=Fy)

    try:
        ss.solve()
    except Exception as e:
        return {"error": f"Structural analysis failed: {e}"}

    node_displacements = []
    for orig_id in sorted(node_coords.keys()):
        ana_id = coord_to_ana.get(orig_id)
        if ana_id is None:
            node_displacements.append({"node_id": orig_id, "ux": 0.0, "uy": 0.0})
            continue
        d = ss.get_node_displacements(node_id=ana_id)
        node_displacements.append({"node_id": orig_id, "ux": float(d["ux"]), "uy": float(d["uy"])})

    element_forces = []
    for ana_id in range(1, len(ss.element_map) + 1):
        try:
            results = ss.get_element_results(element_id=ana_id, verbose=False)
            orig_elem_id = elem_id_map.get(ana_id, ana_id - 1)
            element_forces.append({
                "element_id": orig_elem_id,
                "Nmax": float(results["Nmax"]), "Nmin": float(results["Nmin"]),
                "Mmax": float(results["Mmax"]), "Mmin": float(results["Mmin"]),
                "Qmax": float(results["Qmax"]), "Qmin": float(results["Qmin"]),
            })
        except Exception:
            continue  # Skip elements that failed to solve

    if node_displacements:
        max_disp = max(abs(d["ux"]) + abs(d["uy"]) for d in node_displacements)
    else:
        max_disp = 0.0
    if element_forces:
        max_axial = max(max(abs(ef["Nmax"]), abs(ef["Nmin"])) for ef in element_forces)
    else:
        max_axial = 0.0

    return {"node_displacements": node_displacements, "element_forces": element_forces,
            "max_displacement": max_disp, "max_axial_force": max_axial,
            "solver": "anaStruct (2D linear elastic)"}


def _select_critical_element(structure, analysis_result):
    """Find the column with the highest absolute axial force."""
    nodes = structure.get("nodes", [])
    elements = structure.get("elements", [])
    element_forces = analysis_result.get("element_forces", [])

    node_coords = {n["id"]: (n["x"], n["y"]) for n in nodes}

    force_by_id = {}
    for ef in element_forces:
        eid = ef["element_id"]
        n_max = abs(ef.get("Nmax", 0))
        n_min = abs(ef.get("Nmin", 0))
        n_abs = abs(ef.get("N", 0))
        axial = max(n_max, n_min, n_abs)
        force_by_id[eid] = {"Nmax": axial, "Nmin": 0}

    # Find columns (vertical: same x-coordinate at both nodes)
    columns = []
    for elem in elements:
        eid = elem["id"]
        n1 = node_coords.get(elem["node_i"])
        n2 = node_coords.get(elem["node_j"])
        if n1 and n2 and abs(n1[0] - n2[0]) < 0.01:
            max_N = max(force_by_id.get(eid, {}).get("Nmax", 0), force_by_id.get(eid, {}).get("Nmin", 0))
            columns.append({"element_id": eid, "max_axial": max_N, "node_i": elem["node_i"], "node_j": elem["node_j"]})

    if not columns:
        best = max(elements, key=lambda e: max(force_by_id.get(e["id"], {}).get("Nmax", 0), force_by_id.get(e["id"], {}).get("Nmin", 0)))
        return {"critical_element_id": best["id"], "reason": "No vertical columns found. Selected element with highest axial force.", "all_columns": []}

    columns.sort(key=lambda c: c["max_axial"], reverse=True)
    best = columns[0]

    return {
        "critical_element_id": best["element_id"],
        "critical_axial_force_N": best["max_axial"],
        "reason": f"Column at element index {best['element_id']} has the highest axial force ({best['max_axial']:.1f} N). This is the most stressed vertical member and should be the demolition target.",
        "all_columns": columns,
        "column_count": len(columns),
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "generate_simple_frame":
            frame = _generate_frame(
                spans=arguments.get("spans", 2),
                stories=arguments.get("stories", 2),
                span_length=arguments.get("span_length", 6.0),
                story_height=arguments.get("story_height", 3.0),
                E=arguments.get("E", 210e9),
                A=arguments.get("A", 0.005),
                I=arguments.get("I", 1e-5),
                Iy=arguments.get("Iy", 1e-5),
                Iz=arguments.get("Iz", 1e-5),
                J=arguments.get("J", 1e-8),
            )
            return [TextContent(type="text", text=json.dumps(frame, indent=2))]

        elif name == "analyze_frame":
            structure = arguments.get("structure", {})
            if not structure:
                return [TextContent(type="text", text="Error: 'structure' argument is required")]
            try:
                # Run synchronous analysis directly (completes in <50ms for typical frames)
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, _analyze_structure, structure)
            except Exception as e:
                logger.exception("analyze_frame failed")
                result = {"error": f"Analysis error: {e}", "node_displacements": [], "element_forces": [],
                          "max_displacement": 0, "max_axial_force": 0,
                          "warning": "Structure may be unstable after element removal."}
            result = annotate_result(result, "anaStruct")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "select_critical_element":
            structure = arguments.get("structure", {})
            analysis_result = arguments.get("analysis_result", {})
            if not structure or not analysis_result:
                return [TextContent(type="text", text="Error: Both 'structure' and 'analysis_result' are required")]
            result = _select_critical_element(structure, analysis_result)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        else:
            return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]

    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
