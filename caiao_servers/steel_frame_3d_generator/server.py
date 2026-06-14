"""CAIAO Server: Parametric 3D steel frame generator.

Generates a 3D steel frame model from a regular grid, story heights, and
section/material assignments. Returns a complete JSON model with nodes, elements,
sections, and materials ready for structural analysis.
"""

import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from steel_sections import BUILTIN_SECTIONS, BUILTIN_MATERIALS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("steel-frame-3d-generator")

server = Server("steel-frame-3d-generator")


def _validate_positive_numbers(values, name: str) -> None:
    if not values or not all(isinstance(v, (int, float)) and v > 0 for v in values):
        raise ValueError(f"{name} must be a non-empty list of positive numbers")


def _generate_frame(
    grid_x: list,
    grid_y: list,
    num_stories: int,
    story_heights: list,
    column_section: str,
    beam_section: str,
    material: str,
    name: str,
) -> dict:
    # Validate inputs
    _validate_positive_numbers(grid_x, "grid_x")
    _validate_positive_numbers(grid_y, "grid_y")

    if num_stories < 1 or num_stories > 100:
        raise ValueError("num_stories must be between 1 and 100")
    if len(story_heights) != num_stories:
        raise ValueError(
            f"story_heights length ({len(story_heights)}) must equal num_stories ({num_stories})"
        )
    _validate_positive_numbers(story_heights, "story_heights")

    if column_section not in BUILTIN_SECTIONS:
        raise ValueError(f"Unknown column section: {column_section}")
    if beam_section not in BUILTIN_SECTIONS:
        raise ValueError(f"Unknown beam section: {beam_section}")
    if material not in BUILTIN_MATERIALS:
        raise ValueError(f"Unknown material: {material}")

    # Build cumulative Z levels: ground at z=0, then each floor at accumulated height
    z_levels = [0.0]
    for h in story_heights:
        z_levels.append(round(z_levels[-1] + h, 6))

    nx, ny = len(grid_x), len(grid_y)

    # Build cumulative X/Y positions for node coordinates
    x_pos = [0.0]
    for dx in grid_x:
        x_pos.append(round(x_pos[-1] + dx, 6))

    y_pos = [0.0]
    for dy in grid_y:
        y_pos.append(round(y_pos[-1] + dy, 6))

    # Generate nodes: every grid intersection at every floor level (including roof)
    nodes = []
    node_id = 1
    # node_lookup[(ix, iy, iz)] = node_id for building elements
    node_lookup = {}
    for iz in range(num_stories + 1):  # 0=ground, 1..num_stories=floors
        z = z_levels[iz]
        for iy in range(ny + 1):
            y = y_pos[iy]
            for ix in range(nx + 1):
                x = x_pos[ix]
                nodes.append({
                    "id": node_id,
                    "x": x,
                    "y": y,
                    "z": z,
                })
                node_lookup[(ix, iy, iz)] = node_id
                node_id += 1

    # Generate columns: vertical elements between consecutive floor levels
    columns = []
    col_id = 1
    for iz in range(num_stories):
        for iy in range(ny + 1):
            for ix in range(nx + 1):
                bottom_node = node_lookup[(ix, iy, iz)]
                top_node = node_lookup[(ix, iy, iz + 1)]
                columns.append({
                    "id": col_id,
                    "type": "column",
                    "node_i": bottom_node,
                    "node_j": top_node,
                    "section": column_section,
                    "material": material,
                    "floor": iz + 1,
                    "grid_x": ix,
                    "grid_y": iy,
                })
                col_id += 1

    # Generate beams in X direction
    beams_x = []
    bx_id = 1
    for iz in range(1, num_stories + 1):  # beams at each floor
        for iy in range(ny + 1):
            for ix in range(nx):
                node_a = node_lookup[(ix, iy, iz)]
                node_b = node_lookup[(ix + 1, iy, iz)]
                beams_x.append({
                    "id": bx_id,
                    "type": "beam_x",
                    "node_i": node_a,
                    "node_j": node_b,
                    "section": beam_section,
                    "material": material,
                    "floor": iz,
                    "grid_x_start": ix,
                    "grid_x_end": ix + 1,
                    "grid_y": iy,
                })
                bx_id += 1

    # Generate beams in Y direction
    beams_y = []
    by_id = 1
    for iz in range(1, num_stories + 1):
        for ix in range(nx + 1):
            for iy in range(ny):
                node_a = node_lookup[(ix, iy, iz)]
                node_b = node_lookup[(ix, iy + 1, iz)]
                beams_y.append({
                    "id": by_id,
                    "type": "beam_y",
                    "node_i": node_a,
                    "node_j": node_b,
                    "section": beam_section,
                    "material": material,
                    "floor": iz,
                    "grid_x": ix,
                    "grid_y_start": iy,
                    "grid_y_end": iy + 1,
                })
                by_id += 1

    return {
        "name": name,
        "grid_x": grid_x,
        "grid_y": grid_y,
        "num_stories": num_stories,
        "story_heights": story_heights,
        "z_levels": z_levels,
        "nodes": nodes,
        "columns": columns,
        "beams_x": beams_x,
        "beams_y": beams_y,
        "elements": columns + beams_x + beams_y,
        "sections": {
            "column": BUILTIN_SECTIONS[column_section],
            "beam": BUILTIN_SECTIONS[beam_section],
        },
        "materials": {
            material: BUILTIN_MATERIALS[material],
        },
        "stats": {
            "num_nodes": len(nodes),
            "num_columns": len(columns),
            "num_beams_x": len(beams_x),
            "num_beams_y": len(beams_y),
            "num_elements": len(columns) + len(beams_x) + len(beams_y),
        },
    }


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="generate_3d_frame",
            description="Generate a 3D steel frame model from a regular grid, story heights, and section/material assignments",
            inputSchema={
                "type": "object",
                "properties": {
                    "grid_x": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Span lengths in X direction (m)",
                    },
                    "grid_y": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Span lengths in Y direction (m)",
                    },
                    "num_stories": {
                        "type": "integer",
                        "description": "Number of stories",
                    },
                    "story_heights": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Height of each story (m), length must equal num_stories",
                    },
                    "column_section": {
                        "type": "string",
                        "description": "Column section name from GB/T 11263 HW series",
                        "default": "HW350x350x12x19",
                    },
                    "beam_section": {
                        "type": "string",
                        "description": "Beam section name from GB/T 11263 HM series",
                        "default": "HM340x250x9x14",
                    },
                    "material": {
                        "type": "string",
                        "description": "Material grade (Q235, Q355, Q390, Q420)",
                        "default": "Q235",
                    },
                    "name": {
                        "type": "string",
                        "description": "Frame name",
                        "default": "Steel Frame",
                    },
                },
                "required": ["grid_x", "grid_y", "num_stories", "story_heights"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    logger.info(f"Tool called: {name}")

    if name == "generate_3d_frame":
        try:
            result = _generate_frame(
                grid_x=arguments["grid_x"],
                grid_y=arguments["grid_y"],
                num_stories=arguments["num_stories"],
                story_heights=arguments["story_heights"],
                column_section=arguments.get("column_section", "HW350x350x12x19"),
                beam_section=arguments.get("beam_section", "HM340x250x9x14"),
                material=arguments.get("material", "Q235"),
                name=arguments.get("name", "Steel Frame"),
            )
            return [TextContent(type="text", text=json.dumps(result))]
        except ValueError as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
    else:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
