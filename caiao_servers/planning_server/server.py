"""Planning CAIAO Server — demolition sequence planning and structural topology analysis.

Provides tools for planning demolition sequences, analyzing structural topology,
and generating human-readable demolition plan summaries.
"""

import asyncio
import json
import logging
import os
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Path setup for sibling imports when running as __main__
_self_dir = os.path.dirname(os.path.abspath(__file__))
if _self_dir not in sys.path:
    sys.path.insert(0, _self_dir)

from demolition_schemas import DemolitionPlan
from rule_planner import plan_top_down, plan_bottom_up, plan_sequential, plan_center_out, plan_alternating_floors, analyze_topology
from llm_planner import plan_with_llm
from collapse_propagation import compute_collapse_chain, create_propagation_timeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("planning_server")

server = Server("planning-server")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="plan_demolition_sequence",
            description="Generate demolition step sequence for a structure by strategy. "
                        "Strategies: top_down (remove top floor first, safest), "
                        "bottom_up (remove from bottom, riskiest), "
                        "sequential (element-by-element by ID), "
                        "llm (template-based smart planning guided by user prompt).",
            inputSchema={
                "type": "object",
                "properties": {
                    "structure": {
                        "type": "object",
                        "description": "Structure JSON with nodes ({id, x, y, z}) and elements ({id, node_i, node_j, type})",
                        "properties": {
                            "nodes": {"type": "array", "items": {"type": "object"}},
                            "elements": {"type": "array", "items": {"type": "object"}},
                            "loads": {"type": "array", "items": {"type": "object"}},
                            "supports": {"type": "array", "items": {"type": "object"}},
                        },
                        "required": ["nodes", "elements"],
                    },
                    "strategy": {
                        "type": "string",
                        "description": "Demolition strategy: top_down, bottom_up, sequential, center_out, alternating_floors, llm",
                        "enum": ["top_down", "bottom_up", "sequential", "center_out", "alternating_floors", "llm"],
                        "default": "top_down",
                    },
                    "constraints": {
                        "type": "object",
                        "description": "Optional constraints: max_steps, skip_element_types, custom_durations, user_prompt",
                        "properties": {
                            "max_steps": {"type": "integer", "description": "Maximum number of demolition steps"},
                            "skip_element_types": {
                                "type": "array",
                                "items": {"type": "string", "enum": ["column", "beam", "wall", "slab"]},
                                "description": "Element types to skip",
                            },
                            "custom_durations": {
                                "type": "object",
                                "description": "Override durations per element type in ms",
                            },
                            "user_prompt": {
                                "type": "string",
                                "description": "User strategy description for llm strategy",
                            },
                        },
                    },
                },
                "required": ["structure"],
            },
        ),
        Tool(
            name="analyze_structure_topology",
            description="Analyze structural topology: load paths, dependencies, primary vs secondary elements, "
                        "floor mapping, and critical load paths.",
            inputSchema={
                "type": "object",
                "properties": {
                    "structure": {
                        "type": "object",
                        "description": "Structure JSON with nodes ({id, x, y, z}) and elements ({id, node_i, node_j, type})",
                        "properties": {
                            "nodes": {"type": "array", "items": {"type": "object"}},
                            "elements": {"type": "array", "items": {"type": "object"}},
                        },
                        "required": ["nodes", "elements"],
                    },
                },
                "required": ["structure"],
            },
        ),
        Tool(
            name="get_demolition_plan_summary",
            description="Get a human-readable summary of a demolition plan.",
            inputSchema={
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "array",
                        "description": "Demolition plan steps array",
                        "items": {"type": "object"},
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format: text, table, or json",
                        "enum": ["text", "table", "json"],
                        "default": "text",
                    },
                },
                "required": ["plan"],
            },
        ),
        Tool(
            name="compute_collapse_chain",
            description="Compute progressive collapse chain reaction after removing elements. "
                        "Detects topology-based propagation: beams losing support → overloaded columns → cascading failure. "
                        "Returns multiple rounds of chain reaction events for animation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "structure": {
                        "type": "object",
                        "description": "Structure JSON with nodes ({id, x, y, z}) and elements ({id, node_i, node_j, type})",
                    },
                    "initial_removals": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Element IDs initially removed",
                    },
                    "max_rounds": {
                        "type": "integer",
                        "description": "Maximum propagation rounds",
                        "default": 10,
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Propagation threshold 0-1",
                        "default": 0.3,
                    },
                },
                "required": ["structure", "initial_removals"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info(f"Tool called: {name}")

    try:
        if name == "plan_demolition_sequence":
            result = _handle_plan_demolition(arguments)
        elif name == "analyze_structure_topology":
            result = _handle_analyze_topology(arguments)
        elif name == "get_demolition_plan_summary":
            result = _handle_plan_summary(arguments)
        elif name == "compute_collapse_chain":
            result = _handle_collapse_chain(arguments)
        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    except Exception as e:
        logger.exception(f"Error handling tool {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]


def _handle_plan_demolition(arguments: dict) -> dict:
    structure = arguments.get("structure", {})
    strategy = arguments.get("strategy", "top_down")
    constraints = arguments.get("constraints", {})

    if not structure.get("nodes") or not structure.get("elements"):
        return {"error": "Structure must contain 'nodes' and 'elements' arrays"}

    from rule_planner import _normalize_structure
    structure = _normalize_structure(structure)

    strategy_name = strategy

    if strategy == "top_down":
        plan = plan_top_down(structure)
    elif strategy == "bottom_up":
        plan = plan_bottom_up(structure)
    elif strategy == "sequential":
        plan = plan_sequential(structure)
    elif strategy == "center_out":
        plan = plan_center_out(structure)
    elif strategy == "alternating_floors":
        plan = plan_alternating_floors(structure)
    elif strategy == "llm":
        user_prompt = constraints.get("user_prompt", "") if constraints else ""
        plan = plan_with_llm(structure, user_prompt)
        strategy_name = plan.get("strategy", "llm")
    else:
        return {"error": f"Unknown strategy: {strategy}. Use: top_down, bottom_up, sequential, center_out, alternating_floors, llm"}

    plan = _apply_constraints(plan, constraints or {})

    steps = plan["steps"]
    plan_name = f"demolition_plan_{strategy_name}"

    return {
        "plan_name": plan_name,
        "strategy": strategy_name,
        "total_steps": len(steps),
        "steps": steps,
        "estimated_duration_ms": plan["estimated_duration_ms"],
    }


def _handle_analyze_topology(arguments: dict) -> dict:
    structure = arguments.get("structure", {})

    if not structure.get("nodes") or not structure.get("elements"):
        return {"error": "Structure must contain 'nodes' and 'elements' arrays"}

    from rule_planner import _normalize_structure
    structure = _normalize_structure(structure)

    topology = analyze_topology(structure)

    # Convert dependencies list to dependency_graph dict for consistency
    deps_list = topology.get("dependencies", [])
    dependency_graph = {}
    for dep in deps_list:
        dependency_graph[str(dep["element_id"])] = dep.get("depends_on", [])

    return {
        "primary_elements": topology.get("primary_elements", []),
        "secondary_elements": topology.get("secondary_elements", []),
        "load_paths": topology.get("load_paths", []),
        "dependency_graph": dependency_graph,
        "element_count": len(structure.get("elements", [])),
        "floor_count": topology.get("floor_count", 0),
        "critical_load_paths": topology.get("critical_load_paths", []),
    }


def _handle_plan_summary(arguments: dict) -> dict:
    plan_steps = arguments.get("plan", [])
    output_format = arguments.get("format", "text")

    if not plan_steps:
        return {"error": "Plan must contain at least one step"}

    if output_format == "json":
        return {
            "status": "ok",
            "summary": {
                "total_steps": len(plan_steps),
                "total_duration_ms": sum(s.get("duration_ms", 0) for s in plan_steps),
                "element_types": _count_element_types(plan_steps),
                "effects_used": _collect_effects(plan_steps),
                "steps": plan_steps,
            },
        }

    if output_format == "table":
        lines = []
        lines.append(f"{'Step':<6} {'Action':<22} {'Type':<8} {'ID':<6} {'Duration':<10} {'Effects'}")
        lines.append("-" * 80)
        for step in plan_steps:
            step_num = step.get("step", "?")
            action = step.get("action", "?")
            el_type = step.get("element_type", "?")
            el_id = step.get("element_id", "?")
            duration = f"{step.get('duration_ms', 0)}ms"
            effects = ", ".join(step.get("effects", []))[:30]
            lines.append(f"{step_num:<6} {action:<22} {el_type:<8} {el_id:<6} {duration:<10} {effects}")
        lines.append("-" * 80)
        lines.append(f"Total: {len(plan_steps)} steps, "
                     f"{sum(s.get('duration_ms', 0) for s in plan_steps) / 1000:.1f}s estimated duration")
        return {
            "status": "ok",
            "summary": "\n".join(lines),
        }

    # Default: text format
    lines = []
    lines.append("=" * 60)
    lines.append("拆除方案摘要 / Demolition Plan Summary")
    lines.append("=" * 60)
    lines.append(f"总步数 / Total Steps: {len(plan_steps)}")
    lines.append(f"预估总时长 / Est. Duration: {sum(s.get('duration_ms', 0) for s in plan_steps) / 1000:.1f}s")
    lines.append("")

    type_counts = _count_element_types(plan_steps)
    if type_counts:
        lines.append("构件类型 / Element Types:")
        for el_type, count in sorted(type_counts.items()):
            lines.append(f"  {el_type}: {count}")
        lines.append("")

    lines.append("步骤详情 / Step Details:")
    lines.append("-" * 60)
    for step in plan_steps:
        step_num = step.get("step", "?")
        action = step.get("action", "?")
        el_type = step.get("element_type", "?")
        el_id = step.get("element_id", "?")
        desc = step.get("description", "")
        duration = step.get("duration_ms", 0)
        effects = step.get("effects", [])
        effects_str = ", ".join(effects) if effects else "—"

        lines.append(f"  #{step_num:3d} | {action:20s} | {el_type:6s} #{el_id:<4d} | {duration:4d}ms | {effects_str}")
        if desc:
            lines.append(f"       {desc}")
    lines.append("-" * 60)

    return {
        "status": "ok",
        "summary": "\n".join(lines),
    }


def _apply_constraints(plan: DemolitionPlan, constraints: dict) -> DemolitionPlan:
    """Apply optional constraints to a demolition plan."""
    steps = list(plan["steps"])

    skip_types = constraints.get("skip_element_types", [])
    if skip_types:
        steps = [s for s in steps if s["element_type"] not in skip_types]
        for i, s in enumerate(steps, start=1):
            s["step"] = i

    max_steps = constraints.get("max_steps", 0)
    if max_steps > 0 and len(steps) > max_steps:
        steps = steps[:max_steps]

    custom_durations = constraints.get("custom_durations", {})
    if custom_durations:
        for s in steps:
            el_type = s.get("element_type", "")
            if el_type in custom_durations:
                s["duration_ms"] = custom_durations[el_type]

    plan["steps"] = steps
    plan["total_steps"] = len(steps)
    plan["estimated_duration_ms"] = sum(s["duration_ms"] for s in steps)
    return plan


def _count_element_types(steps: list) -> dict:
    counts: dict[str, int] = {}
    for s in steps:
        el_type = s.get("element_type", "unknown")
        if el_type != "system":
            counts[el_type] = counts.get(el_type, 0) + 1
    return counts


def _collect_effects(steps: list) -> list:
    all_effects: set[str] = set()
    for s in steps:
        all_effects.update(s.get("effects", []))
    return sorted(all_effects)


def _handle_collapse_chain(arguments: dict) -> dict:
    structure = arguments.get("structure", {})
    initial_removals = arguments.get("initial_removals", [])
    max_rounds = arguments.get("max_rounds", 10)
    threshold = arguments.get("threshold", 0.3)

    if not structure.get("nodes") or not structure.get("elements"):
        return {"error": "Structure must contain 'nodes' and 'elements' arrays"}
    if not initial_removals:
        return {"error": "initial_removals must contain at least one element ID"}

    from rule_planner import _normalize_structure
    structure = _normalize_structure(structure)

    chain_rounds = compute_collapse_chain(
        structure, initial_removals, max_rounds, threshold
    )

    timeline = create_propagation_timeline(chain_rounds)

    total_removed = set()
    for r in chain_rounds:
        total_removed.update(r.get("new_removals", []))

    total_propagation = len(chain_rounds) - 1  # minus initial
    total_collapsed = len(total_removed)

    return {
        "status": "complete",
        "chain_rounds": chain_rounds,
        "timeline": timeline,
        "total_rounds": len(chain_rounds),
        "total_removed": total_collapsed,
        "propagation_rounds": max(0, total_propagation),
        "propagation_threshold": threshold,
        "description": f"Collapse propagation: {total_collapsed} elements across {len(chain_rounds)} rounds "
                       f"({total_propagation} propagation rounds, threshold {threshold:.0%})",
    }


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
