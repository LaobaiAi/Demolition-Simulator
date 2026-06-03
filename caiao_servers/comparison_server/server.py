"""CAIAO Server: Demolition Strategy Comparison Server

Compares all 4 demolition strategies (top_down, bottom_up, sequential, llm)
and provides scoring, ranking, and recommendations.

Intended for use after structural analysis to determine the optimal
demolition approach before executing the demolition sequence.
"""

import asyncio
import json
import logging
import os
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("comparison_server")

server = Server("comparison_server")

# Path setup for importing from sibling servers
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from planning_server.rule_planner import plan_top_down, plan_bottom_up, plan_sequential, plan_center_out, plan_alternating_floors
from planning_server.llm_planner import plan_with_llm
from recommendation import recommend_strategy

_STRATEGIES = ["top_down", "bottom_up", "sequential", "center_out", "alternating_floors", "llm"]


def _compute_plan_metrics(plan: dict) -> dict:
    """Compute quality metrics from a demolition plan."""
    steps = plan.get("steps", [])
    if not steps:
        return {"total_steps": 0, "estimated_duration_ms": 0}

    total_steps = len(steps)
    total_duration = sum(s.get("duration_ms", 0) for s in steps)

    type_counts = {}
    for s in steps:
        el_type = s.get("element_type", "unknown")
        type_counts[el_type] = type_counts.get(el_type, 0) + 1

    return {
        "total_steps": total_steps,
        "estimated_duration_ms": total_duration,
        "estimated_duration_s": round(total_duration / 1000, 1),
        "element_types": type_counts,
    }


def _run_single_strategy(structure: dict, strategy: str, user_prompt: str = "") -> dict:
    """Run a single demolition strategy and return structured results."""
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
        plan = plan_with_llm(structure, user_prompt)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    metrics = _compute_plan_metrics(plan)

    return {
        "strategy": strategy,
        "total_steps": plan["total_steps"],
        "estimated_duration_ms": plan["estimated_duration_ms"],
        "steps_preview": plan["steps"][:5],
        "structure_summary": plan.get("structure_summary", ""),
        "metrics": metrics,
    }


# ── Tools ─────────────────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="compare_demolition_strategies",
            description="Generate ALL 4 demolition strategies (top_down, bottom_up, sequential, llm) for a structure, compute quality scores (safety, efficiency, visual), and return ranked comparison data. Best for choosing the optimal demolition approach before execution.",
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
                    "max_stress_ratio": {
                        "type": "number",
                        "description": "Maximum stress ratio from structural analysis (0-1+). Used for scoring.",
                        "default": 0.5,
                    },
                    "max_displacement": {
                        "type": "number",
                        "description": "Maximum displacement in mm from structural analysis.",
                        "default": 0,
                    },
                    "floor_count": {
                        "type": "integer",
                        "description": "Number of floors in the structure.",
                        "default": 3,
                    },
                    "irregularity": {
                        "type": "number",
                        "description": "Structural irregularity score (0-1). 0=regular, 1=highly irregular.",
                        "default": 0,
                    },
                    "user_prompt": {
                        "type": "string",
                        "description": "Optional user prompt for the LLM strategy (e.g., 'remove perimeter elements first')",
                    },
                },
                "required": ["structure"],
            },
        ),
        Tool(
            name="get_comparison_summary",
            description="Get a human-readable comparison table of all demolition strategies. Use after compare_demolition_strategies to present results to the user in a readable format.",
            inputSchema={
                "type": "object",
                "properties": {
                    "comparison_data": {
                        "type": "object",
                        "description": "The comparison results object from compare_demolition_strategies",
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format: text or json",
                        "enum": ["text", "json"],
                        "default": "text",
                    },
                },
                "required": ["comparison_data"],
            },
        ),
        Tool(
            name="recommend_strategy",
            description="Analyze structure metrics and recommend the best demolition strategy. Uses rules: low-stress (<0.3) -> sequential, high-stress (>0.8) -> top_down, irregular (>0.5) -> llm, low-rise (<4 floors) -> bottom_up. Returns recommended strategy with explanation and full score matrix.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_stress_ratio": {
                        "type": "number",
                        "description": "Maximum stress ratio across all elements (0-1+)",
                        "default": 0.5,
                    },
                    "max_displacement": {
                        "type": "number",
                        "description": "Maximum displacement in mm",
                        "default": 0,
                    },
                    "element_count": {
                        "type": "integer",
                        "description": "Total number of elements in the structure",
                        "default": 10,
                    },
                    "floor_count": {
                        "type": "integer",
                        "description": "Number of floors",
                        "default": 3,
                    },
                    "irregularity": {
                        "type": "number",
                        "description": "Structural irregularity score (0-1). 0=regular, 1=highly irregular.",
                        "default": 0,
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

    try:
        if name == "compare_demolition_strategies":
            result = _handle_compare_strategies(arguments)
        elif name == "get_comparison_summary":
            result = _handle_comparison_summary(arguments)
        elif name == "recommend_strategy":
            result = _handle_recommend_strategy(arguments)
        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    except Exception as e:
        logger.exception(f"Error handling tool {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]


def _handle_compare_strategies(arguments: dict) -> dict:
    """Run all 4 strategies and return ranked comparison data."""
    structure = arguments.get("structure", {})
    max_stress_ratio = arguments.get("max_stress_ratio", 0.5)
    max_displacement = arguments.get("max_displacement", 0.0)
    floor_count = arguments.get("floor_count", 3)
    irregularity = arguments.get("irregularity", 0.0)
    user_prompt = arguments.get("user_prompt", "")

    if not structure.get("nodes") or not structure.get("elements"):
        return {"error": "Structure must contain 'nodes' and 'elements' arrays"}

    # Run all 4 strategies (pure functions, safe to call directly)
    strategies_results = {}
    for strategy in _STRATEGIES:
        strategies_results[strategy] = _run_single_strategy(structure, strategy, user_prompt)

    # Compute recommendation scores
    element_count = len(structure.get("elements", []))
    recommendation = recommend_strategy(
        max_stress_ratio=max_stress_ratio,
        max_displacement=max_displacement,
        element_count=element_count,
        floor_count=floor_count,
        irregularity=irregularity,
    )
    score_matrix = recommendation["score_matrix"]

    # Merge scores into strategy results and rank
    ranked = []
    for strategy in _STRATEGIES:
        entry = strategies_results[strategy]
        scores = score_matrix.get(strategy, {})
        entry["scores"] = scores
        ranked.append({
            "strategy": strategy,
            "total_steps": entry["total_steps"],
            "estimated_duration_s": entry["metrics"]["estimated_duration_s"],
            "scores": scores,
        })

    ranked.sort(key=lambda x: x["scores"].get("recommendation_score", 0), reverse=True)
    for i, entry in enumerate(ranked):
        entry["rank"] = i + 1

    return {
        "status": "ok",
        "strategies": strategies_results,
        "rankings": ranked,
        "recommendation": {
            "recommended_strategy": recommendation["recommended_strategy"],
            "recommendation_score": recommendation["recommendation_score"],
            "explanation": recommendation["explanation"],
            "rules_triggered": recommendation["rules_triggered"],
        },
        "structure_summary": {
            "element_count": element_count,
            "floor_count": floor_count,
            "max_stress_ratio": max_stress_ratio,
            "max_displacement_mm": max_displacement,
            "irregularity": irregularity,
        },
    }


def _handle_comparison_summary(arguments: dict) -> dict:
    """Generate human-readable comparison summary."""
    comparison_data = arguments.get("comparison_data", {})
    output_format = arguments.get("format", "text")

    if not comparison_data:
        return {"error": "comparison_data is required"}

    if output_format == "json":
        return {"status": "ok", "summary": comparison_data}

    lines = []
    lines.append("=" * 72)
    lines.append("  拆除方案对比 / Demolition Strategy Comparison")
    lines.append("=" * 72)

    rankings = comparison_data.get("rankings", [])
    lines.append(f"\n  Overall Rankings:")
    lines.append("  " + "-" * 68)
    header = f"{'Rank':<6} {'Strategy':<14} {'Steps':<8} {'Duration':<12} {'Safety':<8} {'Efficiency':<10} {'Visual':<8} {'Overall':<8}"
    lines.append("  " + header)
    lines.append("  " + "-" * 68)
    for r in rankings:
        rank = r.get("rank", "?")
        strategy = r["strategy"]
        steps = r["total_steps"]
        duration = f"{r['estimated_duration_s']}s"
        s = r.get("scores", {})
        lines.append(
            f"  #{rank:<3}  {strategy:<12} {steps:<8} {duration:<12} "
            f"{s.get('safety_score', 0):<8.0f} {s.get('efficiency_score', 0):<10.0f} "
            f"{s.get('visual_score', 0):<8.0f} {s.get('recommendation_score', 0):<8.0f}"
        )
    lines.append("  " + "-" * 68)

    rec = comparison_data.get("recommendation", {})
    lines.append(f"\n  Recommended: {rec.get('recommended_strategy', 'N/A')} "
                 f"(score: {rec.get('recommendation_score', 0):.1f})")
    lines.append(f"  {rec.get('explanation', '')}")

    strategies = comparison_data.get("strategies", {})
    for strategy in _STRATEGIES:
        s = strategies.get(strategy)
        if not s:
            continue
        lines.append(f"\n  {strategy.upper()}")
        lines.append(f"    Steps: {s['total_steps']}  |  Duration: {s['metrics']['estimated_duration_s']}s")
        lines.append(f"    Summary: {s.get('structure_summary', '')}")
        scores = s.get("scores", {})
        if scores:
            lines.append(f"    Safety: {scores.get('safety_score', 0):.1f}  |  "
                         f"Efficiency: {scores.get('efficiency_score', 0):.1f}  |  "
                         f"Visual: {scores.get('visual_score', 0):.1f}")

    lines.append("\n" + "=" * 72)

    return {"status": "ok", "summary": "\n".join(lines)}


def _handle_recommend_strategy(arguments: dict) -> dict:
    """Run the recommendation engine directly."""
    max_stress_ratio = arguments.get("max_stress_ratio", 0.5)
    max_displacement = arguments.get("max_displacement", 0.0)
    element_count = arguments.get("element_count", 10)
    floor_count = arguments.get("floor_count", 3)
    irregularity = arguments.get("irregularity", 0.0)

    result = recommend_strategy(
        max_stress_ratio=max_stress_ratio,
        max_displacement=max_displacement,
        element_count=element_count,
        floor_count=floor_count,
        irregularity=irregularity,
    )

    return {"status": "ok", "recommendation": result}


# ── Entry point ──────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
