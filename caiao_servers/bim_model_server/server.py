"""BIM Model Server CAIAO Server — structural geometry generation and IFC export.

Generates steel frame, reinforced concrete, and hybrid steel-concrete structural
models using standard sections and material grades. Exports to IFC format.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

_VENV_SITE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "gateway", "venv", "Lib", "site-packages",
)
if os.path.isdir(_VENV_SITE) and _VENV_SITE not in sys.path:
    sys.path.insert(0, _VENV_SITE)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from steel_generator import generate_steel_frame as _generate_steel
from concrete_generator import generate_concrete_structure as _generate_concrete
from ifc_exporter import export_to_ifc as _export_ifc
from truss_generator import generate_truss as _generate_truss
from portal_generator import generate_portal_frame as _generate_portal
from beam_generator import generate_beam as _generate_beam

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bim_model_server")

server = Server("bim-model-server")

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

_TOOL_GENERATE_STEEL = Tool(
    name="generate_steel_frame",
    description="Generate a 3D steel frame structure with standard I-beam sections (IPE for beams, HE-A/HE-B for columns). Returns nodes, elements, loads, supports, and metadata.",
    inputSchema={
        "type": "object",
        "properties": {
            "num_bays_x": {"type": "integer", "description": "Number of bays in X direction (default 3)", "default": 3},
            "num_bays_y": {"type": "integer", "description": "Number of bays in Y direction (default 3)", "default": 3},
            "num_stories": {"type": "integer", "description": "Number of stories (default 4)", "default": 4},
            "span_x_m": {"type": "number", "description": "Span length in X direction in meters (default 6.0)", "default": 6.0},
            "span_y_m": {"type": "number", "description": "Span length in Y direction in meters (default 6.0)", "default": 6.0},
            "story_height_m": {"type": "number", "description": "Story height in meters (default 3.0)", "default": 3.0},
            "steel_grade": {"type": "string", "description": "Steel grade: Q235-Q420 or S235-S355 (default 'Q355')", "default": "Q355"},
            "base_support": {"type": "string", "description": "Base support type: 'fixed' or 'hinged' (default 'fixed')", "default": "fixed"},
        },
    },
)

_TOOL_GENERATE_CONCRETE = Tool(
    name="generate_concrete_structure",
    description="Generate a 3D reinforced concrete building with columns, beams, shear walls, and floor slabs. Supports grades C25-C40.",
    inputSchema={
        "type": "object",
        "properties": {
            "num_bays_x": {"type": "integer", "description": "Number of bays in X direction (default 3)", "default": 3},
            "num_bays_y": {"type": "integer", "description": "Number of bays in Y direction (default 3)", "default": 3},
            "num_stories": {"type": "integer", "description": "Number of stories (default 4)", "default": 4},
            "span_x_m": {"type": "number", "description": "Span length in X direction in meters (default 6.0)", "default": 6.0},
            "span_y_m": {"type": "number", "description": "Span length in Y direction in meters (default 6.0)", "default": 6.0},
            "story_height_m": {"type": "number", "description": "Story height in meters (default 3.5)", "default": 3.5},
            "wall_thickness": {"type": "number", "description": "Shear wall thickness in meters (default 0.20)", "default": 0.20},
            "slab_thickness": {"type": "number", "description": "Slab thickness in meters (default 0.15)", "default": 0.15},
            "concrete_grade": {"type": "string", "description": "Concrete grade: C25, C30, C35, C40 (default 'C30')", "default": "C30"},
            "base_support": {"type": "string", "description": "Base support type: 'fixed' or 'hinged' (default 'fixed')", "default": "fixed"},
        },
    },
)

_TOOL_GENERATE_HYBRID = Tool(
    name="generate_hybrid_structure",
    description="Generate a hybrid steel-concrete structure: steel perimeter frame with a reinforced concrete core shear walls at center or corner. Combines steel frame generation + concrete core generation into a single model.",
    inputSchema={
        "type": "object",
        "properties": {
            "num_bays_x": {"type": "integer", "description": "Number of bays in X direction (default 4)", "default": 4},
            "num_bays_y": {"type": "integer", "description": "Number of bays in Y direction (default 4)", "default": 4},
            "num_stories": {"type": "integer", "description": "Number of stories (default 10)", "default": 10},
            "span_x_m": {"type": "number", "description": "Span length in X direction in meters (default 8.0)", "default": 8.0},
            "span_y_m": {"type": "number", "description": "Span length in Y direction in meters (default 8.0)", "default": 8.0},
            "story_height_m": {"type": "number", "description": "Story height in meters (default 3.5)", "default": 3.5},
            "steel_grade": {"type": "string", "description": "Steel grade for perimeter frame (default 'Q355')", "default": "Q355"},
            "concrete_grade": {"type": "string", "description": "Concrete grade for core walls (default 'C35')", "default": "C35"},
            "wall_thickness": {"type": "number", "description": "Core wall thickness in meters (default 0.30)", "default": 0.30},
            "slab_thickness": {"type": "number", "description": "Slab thickness in meters (default 0.15)", "default": 0.15},
            "core_location": {"type": "string", "description": "Core location: 'center' or 'corner' (default 'center')", "default": "center"},
            "base_support": {"type": "string", "description": "Base support type: 'fixed' or 'hinged' (default 'fixed')", "default": "fixed"},
        },
    },
)

_TOOL_EXPORT_IFC = Tool(
    name="export_ifc",
    description="Export a structural model (steel, concrete, or hybrid) to IFC format. Requires IfcOpenShell. Returns status with file path and element count.",
    inputSchema={
        "type": "object",
        "properties": {
            "structure": {"type": "object", "description": "The structure JSON from generate_steel_frame, generate_concrete_structure, or generate_hybrid_structure"},
            "filepath": {"type": "string", "description": "Output file path (default 'output.ifc')", "default": "output.ifc"},
            "export_format": {"type": "string", "description": "Export format: 'ifc' for STEP .ifc, 'xml' for ifcXML (default 'ifc')", "default": "ifc"},
        },
        "required": ["structure"],
    },
)

_TOOL_GENERATE_TRUSS = Tool(
    name="generate_truss",
    description="Generate a truss structure (Pratt, Howe, or Warren). Steel tubular sections, pin/roller supports, gravity loads. Returns nodes, elements, loads, supports, and metadata.",
    inputSchema={
        "type": "object",
        "properties": {
            "truss_type": {"type": "string", "description": "Truss type: 'pratt', 'howe', or 'warren' (default 'pratt')", "enum": ["pratt", "howe", "warren"], "default": "pratt"},
            "span_m": {"type": "number", "description": "Total span in meters (default 18.0)", "default": 18.0},
            "height_m": {"type": "number", "description": "Truss height at eave in meters (default 2.5)", "default": 2.5},
            "panels": {"type": "integer", "description": "Number of truss panels (default 8)", "default": 8},
            "steel_grade": {"type": "string", "description": "Steel grade: Q235, Q355, Q420 (default 'Q355')", "default": "Q355"},
            "load_kN_per_node": {"type": "number", "description": "Vertical load per top chord node in kN (default 20.0)", "default": 20.0},
        },
    },
)

_TOOL_GENERATE_PORTAL = Tool(
    name="generate_portal_frame",
    description="Generate a steel portal frame (industrial building). Pitched roof, hot-rolled UB sections, pinned bases. Supports single or multi-bay (3D) configurations.",
    inputSchema={
        "type": "object",
        "properties": {
            "num_bays": {"type": "integer", "description": "Number of bays in 3D (default 1 = 2D frame)", "default": 1},
            "span_m": {"type": "number", "description": "Frame span in meters (default 18.0)", "default": 18.0},
            "eave_height_m": {"type": "number", "description": "Eave height in meters (default 6.0)", "default": 6.0},
            "roof_pitch_deg": {"type": "number", "description": "Roof pitch in degrees (default 5.0)", "default": 5.0},
            "bay_spacing_m": {"type": "number", "description": "Bay spacing in meters for 3D (default 6.0)", "default": 6.0},
            "steel_grade": {"type": "string", "description": "Steel grade: Q235, Q355, Q420 (default 'Q355')", "default": "Q355"},
            "load_kN_per_m2": {"type": "number", "description": "Roof load in kN/m² (default 0.5)", "default": 0.5},
        },
    },
)

_TOOL_GENERATE_BEAM = Tool(
    name="generate_beam",
    description="Generate a beam (simply supported, cantilever, continuous, or fixed-end). Steel or concrete material, UDL or point load. Returns nodes, elements, loads, supports, and metadata.",
    inputSchema={
        "type": "object",
        "properties": {
            "beam_type": {"type": "string", "description": "Beam type: 'simply_supported', 'cantilever', 'continuous', 'fixed' (default 'simply_supported')", "enum": ["simply_supported", "cantilever", "continuous", "fixed"], "default": "simply_supported"},
            "span_m": {"type": "number", "description": "Span in meters (default 6.0)", "default": 6.0},
            "material": {"type": "string", "description": "Material: 'steel' or 'concrete' (default 'steel')", "enum": ["steel", "concrete"], "default": "steel"},
            "steel_grade": {"type": "string", "description": "Steel grade: Q235, Q355, Q420 (default 'Q355')", "default": "Q355"},
            "concrete_grade": {"type": "string", "description": "Concrete grade for concrete beams: C25-C40 (default 'C30')", "default": "C30"},
            "udl_kN_per_m": {"type": "number", "description": "Uniformly distributed load in kN/m (default 10.0)", "default": 10.0},
            "num_spans": {"type": "integer", "description": "Number of spans for continuous beam (default 3)", "default": 3},
            "load_type": {"type": "string", "description": "Load type: 'udl' or 'point' (default 'udl')", "enum": ["udl", "point"], "default": "udl"},
        },
    },
)

TOOLS = [_TOOL_GENERATE_STEEL, _TOOL_GENERATE_CONCRETE, _TOOL_GENERATE_HYBRID, _TOOL_EXPORT_IFC, _TOOL_GENERATE_TRUSS, _TOOL_GENERATE_PORTAL, _TOOL_GENERATE_BEAM]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info(f"Tool called: {name}")

    try:
        if name == "generate_steel_frame":
            result = _generate_steel(
                num_bays_x=int(arguments.get("num_bays_x", 3)),
                num_bays_y=int(arguments.get("num_bays_y", 3)),
                num_stories=int(arguments.get("num_stories", 4)),
                span_x_m=float(arguments.get("span_x_m", 6.0)),
                span_y_m=float(arguments.get("span_y_m", 6.0)),
                story_height_m=float(arguments.get("story_height_m", 3.0)),
                steel_grade=str(arguments.get("steel_grade", "Q355")),
                base_support=str(arguments.get("base_support", "fixed")),
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "generate_concrete_structure":
            result = _generate_concrete(
                num_bays_x=int(arguments.get("num_bays_x", 3)),
                num_bays_y=int(arguments.get("num_bays_y", 3)),
                num_stories=int(arguments.get("num_stories", 4)),
                span_x_m=float(arguments.get("span_x_m", 6.0)),
                span_y_m=float(arguments.get("span_y_m", 6.0)),
                story_height_m=float(arguments.get("story_height_m", 3.5)),
                wall_thickness=float(arguments.get("wall_thickness", 0.20)),
                slab_thickness=float(arguments.get("slab_thickness", 0.15)),
                concrete_grade=str(arguments.get("concrete_grade", "C30")),
                base_support=str(arguments.get("base_support", "fixed")),
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "generate_hybrid_structure":
            result = _generate_hybrid(arguments)
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "export_ifc":
            structure = arguments.get("structure", {})
            filepath = str(arguments.get("filepath", arguments.get("file_path", "output.ifc")))
            fmt = str(arguments.get("export_format", arguments.get("format", "ifc")))
            if not structure:
                return [TextContent(type="text", text=json.dumps({"error": "structure argument required"}))]
            result = _export_ifc(structure, filepath, fmt)
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "generate_truss":
            result = _generate_truss(
                truss_type=str(arguments.get("truss_type", "pratt")),
                span_m=float(arguments.get("span_m", 18.0)),
                height_m=float(arguments.get("height_m", 2.5)),
                panels=int(arguments.get("panels", 8)),
                steel_grade=str(arguments.get("steel_grade", "Q355")),
                load_kN_per_node=float(arguments.get("load_kN_per_node", 20.0)),
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "generate_portal_frame":
            result = _generate_portal(
                num_bays=int(arguments.get("num_bays", 1)),
                span_m=float(arguments.get("span_m", 18.0)),
                eave_height_m=float(arguments.get("eave_height_m", 6.0)),
                roof_pitch_deg=float(arguments.get("roof_pitch_deg", 5.0)),
                bay_spacing_m=float(arguments.get("bay_spacing_m", 6.0)),
                steel_grade=str(arguments.get("steel_grade", "Q355")),
                load_kN_per_m2=float(arguments.get("load_kN_per_m2", 0.5)),
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "generate_beam":
            result = _generate_beam(
                beam_type=str(arguments.get("beam_type", "simply_supported")),
                span_m=float(arguments.get("span_m", 6.0)),
                material=str(arguments.get("material", "steel")),
                steel_grade=str(arguments.get("steel_grade", "Q355")),
                concrete_grade=str(arguments.get("concrete_grade", "C30")),
                udl_kN_per_m=float(arguments.get("udl_kN_per_m", 10.0)),
                num_spans=int(arguments.get("num_spans", 3)),
                load_type=str(arguments.get("load_type", "udl")),
            )
            return [TextContent(type="text", text=json.dumps(result))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except Exception as e:
        logger.error(f"Error in {name}: {e}", exc_info=True)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


# ---------------------------------------------------------------------------
# Hybrid structure generator
# ---------------------------------------------------------------------------

def _generate_hybrid(args: dict) -> dict:
    """Generate a steel perimeter frame with a concrete core."""
    num_bays_x = int(args.get("num_bays_x", 4))
    num_bays_y = int(args.get("num_bays_y", 4))
    num_stories = int(args.get("num_stories", 10))
    span_x_m = float(args.get("span_x_m", 8.0))
    span_y_m = float(args.get("span_y_m", 8.0))
    story_height_m = float(args.get("story_height_m", 3.5))
    steel_grade = str(args.get("steel_grade", "Q355"))
    concrete_grade = str(args.get("concrete_grade", "C35"))
    wall_thickness = float(args.get("wall_thickness", 0.30))
    slab_thickness = float(args.get("slab_thickness", 0.15))
    core_location = str(args.get("core_location", "center"))
    base_support = str(args.get("base_support", "fixed"))

    total_x = num_bays_x * span_x_m
    total_z = num_bays_y * span_y_m

    # Core spans about 35% of the building width
    core_w = total_x * 0.35
    core_d = total_z * 0.35
    core_w = max(core_w, span_x_m * 2)
    core_d = max(core_d, span_y_m * 2)

    # Core offset based on location
    if core_location == "corner":
        core_ox = 0.0
        core_oz = 0.0
    else:
        core_ox = (total_x - core_w) / 2.0
        core_oz = (total_z - core_d) / 2.0

    # Generate steel perimeter frame
    steel = _generate_steel(
        num_bays_x=num_bays_x,
        num_bays_y=num_bays_y,
        num_stories=num_stories,
        span_x_m=span_x_m,
        span_y_m=span_y_m,
        story_height_m=story_height_m,
        steel_grade=steel_grade,
        base_support=base_support,
    )

    # Generate concrete core walls: 2x2 grid within core footprint
    core_grid_x = 2
    core_grid_z = 2
    core_span_x = core_w / core_grid_x
    core_span_z = core_d / core_grid_z

    concrete = _generate_concrete(
        num_bays_x=core_grid_x,
        num_bays_y=core_grid_z,
        num_stories=num_stories,
        span_x_m=core_span_x,
        span_y_m=core_span_z,
        story_height_m=story_height_m,
        wall_thickness=wall_thickness,
        slab_thickness=slab_thickness,
        concrete_grade=concrete_grade,
        base_support=base_support,
    )

    # Offset concrete nodes to core position
    for node in concrete.get("nodes", []):
        node["x"] += core_ox
        node["z"] += core_oz

    # Remap concrete node IDs to avoid collision
    max_nid = max((n["id"] for n in steel.get("nodes", [])), default=-1) + 1
    node_map = {}
    for node in concrete.get("nodes", []):
        node_map[node["id"]] = max_nid
        node["id"] = max_nid
        max_nid += 1

    # Remap element IDs and node references
    max_eid = max((e["id"] for e in steel.get("elements", [])), default=-1) + 1
    for elem in concrete.get("elements", []):
        elem["id"] = max_eid
        elem["node_i"] = node_map.get(elem["node_i"], elem["node_i"])
        elem["node_j"] = node_map.get(elem["node_j"], elem["node_j"])
        max_eid += 1

    for load in concrete.get("loads", []):
        load["node_id"] = node_map.get(load["node_id"], load["node_id"])

    for support in concrete.get("supports", []):
        support["node_id"] = node_map.get(support["node_id"], support["node_id"])

    merged_nodes = steel.get("nodes", []) + concrete.get("nodes", [])
    merged_elements = steel.get("elements", []) + concrete.get("elements", [])
    merged_loads = steel.get("loads", []) + concrete.get("loads", [])
    merged_supports = steel.get("supports", [])

    return {
        "nodes": merged_nodes,
        "elements": merged_elements,
        "loads": merged_loads,
        "supports": merged_supports,
        "metadata": {
            "type": "hybrid_steel_concrete",
            "dimension": "3d",
            "num_bays_x": num_bays_x,
            "num_bays_y": num_bays_y,
            "num_stories": num_stories,
            "span_x_m": span_x_m,
            "span_y_m": span_y_m,
            "story_height_m": story_height_m,
            "steel_grade": steel_grade,
            "concrete_grade": concrete_grade,
            "core_location": core_location,
            "core_width_m": core_w,
            "core_depth_m": core_d,
            "elements_total": len(merged_elements),
            "base_support": base_support,
        },
        "materials": {
            "steel": steel.get("materials", {}).get("steel", {}),
            "concrete": concrete.get("materials", {}).get("concrete", {}),
        },
    }


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
