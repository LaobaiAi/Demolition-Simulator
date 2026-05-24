"""
╔══════════════════════════════════════════════════════════════════════╗
║  CAIAO Server: Pipeline B — 3D Full Structural Analysis             ║
║                                                                     ║
║  ⚡ SECOND CAIAOSERVERIZER SERVER MERGE (2026-05-25)                  ║
║                                                                     ║
║  Merges: generate_frame_3d → convert_to_unified_frame →             ║
║          pynite_analysis → select_critical_3d                       ║
║                                                                     ║
║  UnifiedFrame: solver-agnostic intermediate format that bridges     ║
║  the geometry-oriented 3D output to topology-oriented analysis.     ║
╚══════════════════════════════════════════════════════════════════════╝

Reference: CAIAO_PROTOCOL.md §9 (Merge #2)
           ARCHITECTURE.md §CAIAOServerizer Paradigm
"""

import json
import os
import sys
from typing import Any

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from frame_generator.core import FrameGenerator, FrameGeneratorConfig
from pynite_server.server import _run_pynite

from mcp.server import Server
import mcp.types as types
from mcp.server.models import InitializationOptions

server = Server("full_analysis_3d_server")

# ---------------------------------------------------------------------------
# UnifiedFrame converter: generate_3d() geometry → topology format
# ---------------------------------------------------------------------------

def _remap_coord(geom_pt: list[float]) -> tuple[float, float, float]:
    """Remap geometry coords [x, z_vertical, y_horiz] → analysis {x, y, z}."""
    return (geom_pt[0], geom_pt[1], geom_pt[2])


def _node_key(x: float, y: float, z: float) -> str:
    """Deterministic key for node deduplication (mm precision)."""
    return f"{x:.6f},{y:.6f},{z:.6f}"


def _convert_3d_to_unified(geometry: dict[str, Any], cfg: FrameGeneratorConfig) -> dict[str, Any]:
    """Convert generate_3d() geometry output to UnifiedFrame topology format.

    The geometry format uses [x, z_vert, y_horiz] coordinates.
    The analysis format uses {x, y_vert, z_horiz} coordinates.

    Returns {nodes, elements, loads, supports, metadata} compatible with
    PyNite solver and the project's FrameStructure interface.
    """
    columns = geometry.get("columns", [])
    beams = geometry.get("beams", [])

    node_map: dict[str, int] = {}     # _node_key → node_id
    nodes: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    nid = 0
    eid = 0

    def _get_or_create_node(pt_geom: list[float]) -> int:
        nonlocal nid
        x, y, z = _remap_coord(pt_geom)
        key = _node_key(x, y, z)
        if key in node_map:
            return node_map[key]
        node_map[key] = nid
        nodes.append({"id": nid, "x": x, "y": y, "z": z})
        nid += 1
        return node_map[key]

    # Columns → elements (vertical)
    for col in columns:
        n_i = _get_or_create_node(col["start"])
        n_j = _get_or_create_node(col["end"])
        elements.append({
            "id": eid,
            "node_i": n_i,
            "node_j": n_j,
            "E": col.get("E", 210e9),
            "A": col.get("A", col.get("width", 0.4) * col.get("depth", 0.4)),
            "Iy": col.get("Iy", 1e-4),
            "Iz": col.get("Iz", 1e-4),
            "J": col.get("J", 1e-8),
            "type": "column",
            "original_id": col.get("id", f"C{eid}"),
        })
        eid += 1

    # Beams → elements (horizontal)
    for beam in beams:
        n_i = _get_or_create_node(beam["start"])
        n_j = _get_or_create_node(beam["end"])
        w = beam.get("width", 0.2)
        d = beam.get("height", 0.4)
        elements.append({
            "id": eid,
            "node_i": n_i,
            "node_j": n_j,
            "E": beam.get("E", 210e9),
            "A": beam.get("A", w * d),
            "Iy": beam.get("Iy", 1e-4),
            "Iz": beam.get("Iz", 1e-4),
            "J": beam.get("J", 1e-8),
            "type": "beam",
            "original_id": beam.get("id", f"B{eid}"),
        })
        eid += 1

    # Supports — base nodes (y ≈ 0, i.e. remapped z_vert ≈ 0)
    base_nodes = [n for n in nodes if abs(n["y"]) < 0.001]
    supports = [{"node_id": n["id"], "type": cfg.base_support} for n in base_nodes]

    # Loads — distribute floor load to all nodes at each story level
    # geometry metadata gives us story count and spans
    meta = geometry.get("metadata", {})
    grid = meta.get("grid", {})
    num_stories = grid.get("stories", cfg.num_stories)
    nodes_per_floor = len([n for n in nodes if abs(n["y"]) < 0.001])
    if nodes_per_floor == 0:
        nodes_per_floor = (cfg.num_bays_x + 1) * (cfg.num_bays_y + 1)

    floor_area = cfg.span_x_m * cfg.span_y_m
    total_dead_N = cfg.dead_load_kpa * 1000 * floor_area
    total_live_N = cfg.live_load_kpa * 1000 * floor_area
    per_node = (total_dead_N + total_live_N) / nodes_per_floor

    loads: list[dict[str, Any]] = []
    for n in nodes:
        if n["y"] > 0.001:  # non-base nodes receive load
            loads.append({"node_id": n["id"], "Fx": 0, "Fy": -per_node, "Fz": 0})

    # Lateral load
    if cfg.lateral_load_kN > 0:
        top_y = max(n["y"] for n in nodes)
        top_nodes = [n for n in nodes if abs(n["y"] - top_y) < 0.001]
        per_node_lateral = cfg.lateral_load_kN * 1000 / len(top_nodes)
        for n in top_nodes:
            loads.append({"node_id": n["id"], "Fx": per_node_lateral, "Fy": 0, "Fz": 0})

    return {
        "nodes": nodes,
        "elements": elements,
        "loads": loads,
        "supports": supports,
        "metadata": {
            "dimension": "3d",
            "num_nodes": len(nodes),
            "num_elements": len(elements),
            "num_columns": len(columns),
            "num_beams": len(beams),
            "num_base_nodes": len(base_nodes),
        },
    }


# ---------------------------------------------------------------------------
# 3D critical element selector
# ---------------------------------------------------------------------------

def _select_critical_3d(structure: dict, analysis: dict) -> dict[str, Any]:
    """Find the most critical column in a 3D analysis result.

    Identifies columns (elements whose nodes share x,z but differ in y),
    then returns the one with the highest absolute axial force.
    """
    elements = structure.get("elements", [])
    nodes = {n["id"]: n for n in structure.get("nodes", [])}
    node_displacements = analysis.get("node_displacements", [])
    element_forces = analysis.get("element_forces", [])

    force_by_id: dict[int, float] = {}
    for ef in element_forces:
        eid = ef.get("element_id")
        if eid is None:
            continue
        axial = abs(ef.get("N", 0))
        axial = max(axial, abs(ef.get("Nmax", 0)), abs(ef.get("Nmin", 0)))
        force_by_id[eid] = axial

    # Identify columns: nodes have same x,z but different y
    columns = []
    for elem in elements:
        n_i = nodes.get(elem["node_i"])
        n_j = nodes.get(elem["node_j"])
        if n_i and n_j:
            # Column check: x and z are the same, only y differs
            if abs(n_i["x"] - n_j["x"]) < 0.01 and abs(n_i["z"] - n_j["z"]) < 0.01:
                axial = force_by_id.get(elem["id"], 0)
                story = int(abs(n_j["y"] - n_i["y"]) / max(0.1, abs(n_j["y"] - n_i["y"])))
                columns.append({
                    "element_id": elem["id"],
                    "max_axial_N": axial,
                    "bottom_node": n_i["id"],
                    "top_node": n_j["id"],
                    "x": n_i["x"],
                    "z": n_i["z"],
                    "original_id": elem.get("original_id", str(elem["id"])),
                })

    if not columns:
        return {
            "critical_element_id": -1,
            "reason": "No vertical columns found in 3D structure.",
            "all_columns": [],
        }

    columns.sort(key=lambda c: c["max_axial_N"], reverse=True)
    best = columns[0]

    return {
        "critical_element_id": best["element_id"],
        "critical_axial_force_N": best["max_axial_N"],
        "critical_original_id": best["original_id"],
        "critical_position": {"x": best["x"], "z": best["z"]},
        "reason": (
            f"Column at (x={best['x']:.1f}, z={best['z']:.1f}) — "
            f"element {best['original_id']} has the highest axial force "
            f"({best['max_axial_N']:.1f} N)."
        ),
        "all_columns": columns,
        "column_count": len(columns),
    }


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def _run_pipeline(arguments: dict) -> dict[str, Any]:
    """Run 3D Full Analysis: generate_3d → convert → pynite → select critical."""
    cfg = FrameGeneratorConfig(
        num_bays_x=int(arguments.get("num_bays_x", 3)),
        num_bays_y=int(arguments.get("num_bays_y", 3)),
        num_stories=int(arguments.get("num_stories", 4)),
        span_x_m=float(arguments.get("span_x_m", 6.0)),
        span_y_m=float(arguments.get("span_y_m", 6.0)),
        story_height_m=float(arguments.get("story_height_m", 3.0)),
        material_type=arguments.get("material_type", "steel"),
        steel_grade=arguments.get("steel_grade", "Q355"),
        concrete_grade=arguments.get("concrete_grade", "C30"),
        dead_load_kpa=float(arguments.get("dead_load_kpa", 5.0)),
        live_load_kpa=float(arguments.get("live_load_kpa", 2.0)),
        lateral_load_kN=float(arguments.get("lateral_load_kN", 0.0)),
        base_support=arguments.get("base_support", "fixed"),
    )

    # Step 1: Generate 3D geometry
    generator = FrameGenerator(cfg)
    geometry = generator.generate_3d()

    # Step 2: Convert to UnifiedFrame (topology format)
    structure = _convert_3d_to_unified(geometry, cfg)

    # Step 3: Run PyNite 3D analysis
    analysis = _run_pynite(structure)
    if "error" in analysis and analysis.get("node_displacements") is None:
        return {"status": "error", "error": analysis["error"]}

    # Step 4: Select critical column in 3D
    critical = _select_critical_3d(structure, analysis)

    return {
        "status": "complete",
        "pipeline": "full_analysis_3d",
        "dimension": "3d",
        "geometry": geometry,
        "structure": structure,
        "analysis": analysis,
        "critical_element": critical,
        "unified_frame": {
            "format": "UnifiedFrame",
            "version": "1.0",
            "description": "Solver-agnostic topology format: geometry → nodes+elements topology",
        },
        "metadata": {
            "pipeline": "full_analysis_3d",
            "dimension": "3d",
            "description": "Merge #2: generate_frame_3d → convert → pynite_analysis → select_critical_3d",
            "config": {
                "num_bays_x": cfg.num_bays_x,
                "num_bays_y": cfg.num_bays_y,
                "num_stories": cfg.num_stories,
                "span_x_m": cfg.span_x_m,
                "span_y_m": cfg.span_y_m,
                "story_height_m": cfg.story_height_m,
                "material_type": cfg.material_type,
            },
        },
    }


# ---------------------------------------------------------------------------
# MCP interface
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="full_analysis_3d",
            description="Merge #2: Generate a 3D frame → convert to UnifiedFrame → run PyNite 3D FEM analysis → identify critical column. One atomic call. Returns geometry, structure (UnifiedFrame topology), analysis results, and critical element.",
            inputSchema={
                "type": "object",
                "properties": {
                    "num_bays_x": {"type": "integer", "default": 3},
                    "num_bays_y": {"type": "integer", "default": 3},
                    "num_stories": {"type": "integer", "default": 4},
                    "span_x_m": {"type": "number", "default": 6.0},
                    "span_y_m": {"type": "number", "default": 6.0},
                    "story_height_m": {"type": "number", "default": 3.0},
                    "material_type": {"type": "string", "default": "steel", "enum": ["steel", "concrete"]},
                    "steel_grade": {"type": "string", "default": "Q355"},
                    "concrete_grade": {"type": "string", "default": "C30"},
                    "dead_load_kpa": {"type": "number", "default": 5.0},
                    "live_load_kpa": {"type": "number", "default": 2.0},
                    "lateral_load_kN": {"type": "number", "default": 0.0},
                    "base_support": {"type": "string", "default": "fixed", "enum": ["fixed", "hinged"]},
                },
                "required": [],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "full_analysis_3d":
        raise ValueError(f"Unknown tool: {name}")
    result = _run_pipeline(arguments)
    return [types.TextContent(type="text", text=json.dumps(result, default=str))]


if __name__ == "__main__":
    from mcp.server.stdio import stdio_server
    import anyio
    anyio.run(stdio_server, server, InitializationOptions(
        server_name="full_analysis_3d_server",
        server_version="0.1.0",
    ))
