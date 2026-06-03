"""
CAIAO Server: Animation Control Server

Manages demolition animation timelines — converts multi-round
demolition plans into keyframe-based timelines, provides state
queries at any timestamp, and generates effects config for the
frontend collapse animation system.

Frontend counterpart: frontend/components/frame-visualization.tsx
  -> CollapseAnimation component consumes EffectKey-based config
"""

import json
import logging
import math
import sys
import os
import uuid

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("animation_control_server")

server = Server("animation_control_server")

# Path setup for sibling imports when running as __main__
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from timeline_manager import (
    Timeline,
    create_timeline_from_plan,
    get_state_at_time,
)
from effects_presets import (
    LOW_INTENSITY,
    MEDIUM_INTENSITY,
    HIGH_INTENSITY,
    CINEMATIC,
    STYLE_OVERLAYS,
)

_INTENSITY_MAP = {
    "low": LOW_INTENSITY,
    "medium": MEDIUM_INTENSITY,
    "high": HIGH_INTENSITY,
    "cinematic": CINEMATIC,
}


def _build_animation_sequence(plan: list[dict], total_duration_ms: int) -> list[dict]:
    """Build animation_sequence entries from a demolition plan."""
    sequence = []
    total_steps = len(plan)
    for step in plan:
        round_idx = step.get("round", 0)
        element_ids = step.get("element_ids", [])
        action = step.get("action", "collapse")
        effects = step.get("effects", ["flash", "fall", "dust"])
        delay_ms = int(total_duration_ms * round_idx / max(total_steps, 1))
        duration_ms = total_duration_ms // max(total_steps * max(len(element_ids), 1), 1)
        sequence.append({
            "step": round_idx,
            "element_ids": element_ids,
            "action": action,
            "delay_ms": delay_ms,
            "duration_ms": duration_ms,
            "effects": effects,
        })
    return sequence


# ── Tools ─────────────────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="create_timeline",
            description="Create an animation timeline from a demolition plan. Converts multi-round demolition steps into a keyframe-based timeline with flash, fall, explode, dust, and settle phases per element. Returns timeline with keyframes, element positions, and metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "demolition_plan": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "round": {"type": "integer"},
                                "element_ids": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                },
                                "critical_element_id": {"type": "integer"},
                            },
                        },
                        "description": "List of demolition steps, each with round index, element_ids, and optional critical_element_id",
                    },
                    "structure": {
                        "type": "object",
                        "description": "Frame structure JSON with nodes, elements, loads, supports",
                    },
                    "total_duration_ms": {
                        "type": "integer",
                        "description": "Total animation duration in milliseconds",
                        "default": 8000,
                    },
                    "effects_intensity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "cinematic"],
                        "description": "Effects intensity level — maps to built-in presets (low=simple removal, medium=flash+fall, high=full effects, cinematic=all+slowmo)",
                        "default": "high",
                    },
                },
                "required": ["demolition_plan", "structure"],
            },
        ),
        Tool(
            name="get_timeline_state",
            description="Get the scene state at a specific timestamp within a timeline. Returns which elements are active, falling, or removed at that moment. Useful for syncing a running animation or scrubbing through a sequence.",
            inputSchema={
                "type": "object",
                "properties": {
                    "timeline": {
                        "type": "object",
                        "description": "Timeline object previously returned by create_timeline",
                    },
                    "timestamp_ms": {
                        "type": "integer",
                        "description": "Query time in milliseconds",
                    },
                },
                "required": ["timeline", "timestamp_ms"],
            },
        ),
        Tool(
            name="sequence_to_animation_data",
            description="Convert a demolition plan to frontend-compatible animation data. Produces an animation_sequence array with per-step delays, durations, and effects, suitable for direct consumption by the frontend Three.js or SVG renderer.",
            inputSchema={
                "type": "object",
                "properties": {
                    "demolition_plan": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "round": {"type": "integer"},
                                "element_ids": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                },
                            },
                        },
                        "description": "List of demolition steps",
                    },
                    "structure": {
                        "type": "object",
                        "description": "Frame structure with nodes and elements",
                    },
                    "effects_config": {
                        "type": "object",
                        "description": "Optional effects configuration object (from generate_effects_config)",
                    },
                },
                "required": ["demolition_plan", "structure"],
            },
        ),
        Tool(
            name="generate_effects_config",
            description="Generate visual effects configuration for the frontend. Maps intensity/style to the frontend EffectKey system (cascade, explosion, dust, shake, buckling, fracture, flash, trail, bounce). Returns enabled effects toggles and parameter overrides.",
            inputSchema={
                "type": "object",
                "properties": {
                    "intensity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "cinematic"],
                        "description": "Visual intensity level: low (simple removal), medium (flash+fall), high (full effects), cinematic (all effects with slow motion)",
                        "default": "medium",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["realistic", "dramatic", "technical"],
                        "description": "Visual style overlay: realistic (accurate physics), dramatic (enhanced effects), technical (debug info, element IDs)",
                        "default": "realistic",
                    },
                },
                "required": [],
            },
        ),
    ]


# ── Tool dispatch ─────────────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    logger.info(f"Tool called: {name}")

    if name == "create_timeline":
        plan = arguments.get("demolition_plan", [])
        structure = arguments.get("structure", {})
        total_duration_ms = int(arguments.get("total_duration_ms", 8000))
        intensity = arguments.get("effects_intensity", "high")

        preset = _INTENSITY_MAP.get(intensity, HIGH_INTENSITY)
        config = preset.get("params") if preset else None

        timeline = create_timeline_from_plan(plan, structure, total_duration_ms, config)
        result = {
            "timeline_id": str(uuid.uuid4()),
            "total_duration_ms": timeline["total_duration_ms"],
            "keyframe_count": timeline["metadata"]["keyframe_count"],
            "keyframes": timeline["keyframes"],
            "total_elements": timeline["element_count"],
        }

    elif name == "get_timeline_state":
        timeline = arguments.get("timeline", {})
        timestamp_ms = int(arguments.get("timestamp_ms", 0))
        state = get_state_at_time(timeline, timestamp_ms)
        result = {
            "timestamp_ms": state["timestamp_ms"],
            "active_elements": state["active"],
            "falling_elements": [f["element_id"] for f in state["falling"]],
            "removed_elements": state["removed"],
            "progress": state["progress"],
        }

    elif name == "sequence_to_animation_data":
        plan = arguments.get("demolition_plan", [])
        structure = arguments.get("structure", {})
        effects_config = arguments.get("effects_config")

        animation_sequence = _build_animation_sequence(
            plan,
            effects_config.get("params", {}).get("fall_duration_ms", 1000) * len(plan) * 3
            if effects_config
            else 8000,
        )

        node_map = {n["id"]: n for n in structure.get("nodes", [])}
        total_elements = len(structure.get("elements", []))
        total_steps = len(plan)

        total_duration = sum(s["delay_ms"] + s["duration_ms"] for s in animation_sequence) or 8000

        result = {
            "animation_sequence": animation_sequence,
            "total_duration_ms": total_duration,
            "effect_config": effects_config or {},
            "metadata": {
                "total_elements": total_elements,
                "total_steps": total_steps,
            },
        }

    elif name == "generate_effects_config":
        intensity = arguments.get("intensity", "medium")
        style = arguments.get("style", "realistic")

        preset = _INTENSITY_MAP.get(intensity, MEDIUM_INTENSITY)
        overlay = STYLE_OVERLAYS.get(style, STYLE_OVERLAYS["realistic"])

        merged_params = dict(preset.get("params", {}))
        merged_params.update(overlay.get("overrides", {}))

        result = {
            "preset": preset.get("preset", "medium"),
            "label": f'{preset.get("label", "")} + {overlay.get("label", "")}',
            "effects": dict(preset.get("effects", {})),
            "params": merged_params,
            "total_score": preset.get("total_score", 0),
            "style": style,
        }

    else:
        result = {"error": f"Unknown tool: {name}"}

    return [TextContent(type="text", text=json.dumps(result, default=str))]


# ── Entry point ──────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
