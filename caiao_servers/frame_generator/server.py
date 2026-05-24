"""Frame Generator CAIAO Server — parametric frame structure generation.

Generates 2D/3D frame structures from simple parameters.
Compatible with anaStruct/OpenSees analysis pipeline and SVG visualization.

Tools:
  - generate_frame       Generate a 2D frame structure for analysis
  - generate_frame_3d    Generate a 3D frame with geometry data
  - generate_from_text   Natural-language frame generation
  - list_materials       List available material grades
"""

import asyncio
import json
import logging
import os
import sys

_VENV_SITE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "gateway", "venv", "Lib", "site-packages")
if os.path.isdir(_VENV_SITE) and _VENV_SITE not in sys.path:
    sys.path.insert(0, _VENV_SITE)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from core import FrameGenerator, FrameGeneratorConfig, generate_from_natural, STEEL_GRADES, CONCRETE_GRADES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("frame_generator")

server = Server("frame-generator")

TOOLS = [
    Tool(
        name="generate_frame",
        description="Generate a 2D frame structure for structural analysis. Returns nodes, elements, loads, supports compatible with anaStruct/OpenSees.",
        inputSchema={
            "type": "object",
            "properties": {
                "num_bays_x": {"type": "integer", "description": "Number of bays in X direction (default 3)", "default": 3},
                "num_bays_y": {"type": "integer", "description": "Number of bays in Y direction for load calc (default 3)", "default": 3},
                "num_stories": {"type": "integer", "description": "Number of stories (default 4)", "default": 4},
                "span_x_m": {"type": "number", "description": "Span length in X direction in meters (default 6.0)", "default": 6.0},
                "span_y_m": {"type": "number", "description": "Span width in Y direction in meters (default 6.0)", "default": 6.0},
                "story_height_m": {"type": "number", "description": "Story height in meters (default 3.0)", "default": 3.0},
                "material_type": {"type": "string", "description": "Material type: 'steel' or 'concrete' (default 'steel')", "default": "steel"},
                "steel_grade": {"type": "string", "description": "Steel grade: Q235, Q345, Q355, Q390, Q420, S235, S275, S355 (default 'Q355')", "default": "Q355"},
                "concrete_grade": {"type": "string", "description": "Concrete grade: C20-C50 (default 'C30')", "default": "C30"},
                "dead_load_kpa": {"type": "number", "description": "Dead load per floor area in kPa (default 5.0)", "default": 5.0},
                "live_load_kpa": {"type": "number", "description": "Live load per floor area in kPa (default 2.0)", "default": 2.0},
                "base_support": {"type": "string", "description": "Base support type: 'fixed' or 'hinged' (default 'fixed')", "default": "fixed"},
            },
            "required": [],
        },
    ),
    Tool(
        name="generate_frame_3d",
        description="Generate a 3D frame with columns, beams, slabs, and Three.js-ready objects. Used for 3D visualization and Unity export.",
        inputSchema={
            "type": "object",
            "properties": {
                "num_bays_x": {"type": "integer", "description": "Number of bays in X direction (default 3)", "default": 3},
                "num_bays_y": {"type": "integer", "description": "Number of bays in Y direction (default 3)", "default": 3},
                "num_stories": {"type": "integer", "description": "Number of stories (default 4)", "default": 4},
                "span_x_m": {"type": "number", "description": "Span length in X direction in meters (default 6.0)", "default": 6.0},
                "span_y_m": {"type": "number", "description": "Span width in Y direction in meters (default 6.0)", "default": 6.0},
                "story_height_m": {"type": "number", "description": "Story height in meters (default 3.0)", "default": 3.0},
                "material_type": {"type": "string", "description": "Material type: 'steel' or 'concrete' (default 'steel')", "default": "steel"},
                "steel_grade": {"type": "string", "description": "Steel grade (default 'Q355')", "default": "Q355"},
                "concrete_grade": {"type": "string", "description": "Concrete grade (default 'C30')", "default": "C30"},
            },
            "required": [],
        },
    ),
    Tool(
        name="generate_from_text",
        description="Generate a 2D frame structure from a natural-language description. Examples: '3x4 frame 4 stories 3m height 6m span Q355 steel', 'concrete C30 5 floor frame'",
        inputSchema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Natural-language description of the frame structure"},
            },
            "required": ["description"],
        },
    ),
    Tool(
        name="list_materials",
        description="List all available steel and concrete grades with their material properties (E, fy/fc, density).",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info(f"Tool called: {name}({arguments})")

    try:
        if name == "generate_frame":
            cfg = FrameGeneratorConfig(
                num_bays_x=int(arguments.get("num_bays_x", 3)),
                num_bays_y=int(arguments.get("num_bays_y", 3)),
                num_stories=int(arguments.get("num_stories", 4)),
                span_x_m=float(arguments.get("span_x_m", 6.0)),
                span_y_m=float(arguments.get("span_y_m", 6.0)),
                story_height_m=float(arguments.get("story_height_m", 3.0)),
                material_type=str(arguments.get("material_type", "steel")),
                steel_grade=str(arguments.get("steel_grade", "Q355")),
                concrete_grade=str(arguments.get("concrete_grade", "C30")),
                dead_load_kpa=float(arguments.get("dead_load_kpa", 5.0)),
                live_load_kpa=float(arguments.get("live_load_kpa", 2.0)),
                base_support=str(arguments.get("base_support", "fixed")),
            )
            result = FrameGenerator(cfg).generate_2d_analysis_ready()
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "generate_frame_3d":
            cfg = FrameGeneratorConfig(
                num_bays_x=int(arguments.get("num_bays_x", 3)),
                num_bays_y=int(arguments.get("num_bays_y", 3)),
                num_stories=int(arguments.get("num_stories", 4)),
                span_x_m=float(arguments.get("span_x_m", 6.0)),
                span_y_m=float(arguments.get("span_y_m", 6.0)),
                story_height_m=float(arguments.get("story_height_m", 3.0)),
                material_type=str(arguments.get("material_type", "steel")),
                steel_grade=str(arguments.get("steel_grade", "Q355")),
                concrete_grade=str(arguments.get("concrete_grade", "C30")),
            )
            result = FrameGenerator(cfg).generate_3d()
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "generate_from_text":
            text = str(arguments.get("description", ""))
            if not text:
                return [TextContent(type="text", text=json.dumps({"error": "Empty description"}))]
            result = generate_from_natural(text)
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "list_materials":
            result = {
                "steel_grades": {k: {"E": v["E"], "fy": v["fy"], "nu": v["nu"], "rho": v["rho"]} for k, v in STEEL_GRADES.items()},
                "concrete_grades": {k: {"E": v["E"], "fc": v["fc"], "nu": v["nu"], "rho": v["rho"]} for k, v in CONCRETE_GRADES.items()},
            }
            return [TextContent(type="text", text=json.dumps(result))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except Exception as e:
        logger.error(f"Error in {name}: {e}", exc_info=True)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
