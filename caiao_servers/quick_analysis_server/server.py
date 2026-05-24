"""
╔══════════════════════════════════════════════════════════════════════╗
║  CAIAO Server: Pipeline A — Quick 2D Structural Analysis           ║
║                                                                     ║
║  ⚡ FIRST CAIAOSERVERIZER SERVER MERGE (2026-05-25)                  ║
║                                                                     ║
║  What was 3 separate subprocess calls:                              ║
║    generate_frame → analyze_frame → select_critical_element        ║
║                                                                     ║
║  Is now 1 atomic call: quick_analysis                              ║
║                                                                     ║
║  Like BPE merging frequent token pairs, this composes frequently    ║
║  used CAIAO Servers into a single merged Server.                   ║
╚══════════════════════════════════════════════════════════════════════╝

Reference: ARCHITECTURE.md §CAIAOServerizer Paradigm
           dev-notes/architecture/2026-05-25-caiaoserverizer-first-merge.md
"""

import json
import os
import sys
from typing import Any

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from frame_generator.core import FrameGenerator, FrameGeneratorConfig
from anastruct_server.server import _analyze_structure, _select_critical_element

from mcp.server import Server
import mcp.types as types
from mcp.server.models import InitializationOptions

server = Server("quick_analysis_server")


def _run_pipeline(arguments: dict) -> dict[str, Any]:
    """Run the full Pipeline A: generate → analyze → select critical."""
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

    generator = FrameGenerator(cfg)
    structure = generator.generate_2d_analysis_ready()

    analysis = _analyze_structure(structure)
    if "error" in analysis:
        return {"status": "error", "error": analysis["error"]}

    critical = _select_critical_element(structure, analysis)

    return {
        "status": "complete",
        "structure": structure,
        "analysis": analysis,
        "critical_element": critical,
        "metadata": {
            "pipeline": "quick_analysis",
            "dimension": "2d",
            "description": "Pipeline A: generate_frame → analyze_frame → select_critical_element",
            "config": {
                "num_bays_x": cfg.num_bays_x,
                "num_bays_y": cfg.num_bays_y,
                "num_stories": cfg.num_stories,
                "span_x_m": cfg.span_x_m,
                "story_height_m": cfg.story_height_m,
                "material_type": cfg.material_type,
            },
        },
    }


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="quick_analysis",
            description="Pipeline A: Generate a 2D frame → run anaStruct linear analysis → identify the critical column. One atomic call — accepts the same parameters as generate_frame and returns structure + analysis + critical_element in a single response.",
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
    if name != "quick_analysis":
        raise ValueError(f"Unknown tool: {name}")
    result = _run_pipeline(arguments)
    return [types.TextContent(type="text", text=json.dumps(result, default=str))]


if __name__ == "__main__":
    from mcp.server.stdio import stdio_server
    import anyio
    anyio.run(stdio_server, server, InitializationOptions(
        server_name="quick_analysis_server",
        server_version="0.1.0",
    ))
