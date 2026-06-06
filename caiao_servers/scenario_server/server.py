"""Scenario Server — demolition scenario presets for visual demolition launch.

Provides structured scenario configurations that replace hardcoded English
prompts in frontend demo callbacks. LLM-discoverable, version-controlled,
extensible without frontend changes.
"""

import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scenario_server")

server = Server("scenario-server")

SCENARIOS: dict[str, dict] = {
    "quick_visual": {
        "name": "quick_visual",
        "title": {"en": "Quick Visual Collapse", "zh": "快速可视化倒塌"},
        "description": {
            "en": "Small 2-bay 3-story frame, top-down demolition with standard effects. Fastest path to visual result — no structural analysis needed.",
            "zh": "小型2跨3层框架，自上而下拆除，标准特效。最快看到视觉结果——不需要结构分析。",
        },
        "category": "topology",
        "structure_params": {
            "type": "steel",
            "num_bays_x": 2,
            "num_stories": 3,
            "span_x_m": 6.0,
            "story_height_m": 3.0,
            "steel_grade": "Q355",
        },
        "strategy": "top_down",
        "effects_preset": "standard",
        "speed": 1.0,
        "viz_mode": "webgl",
        "needs_analysis": False,
        "tags": ["quick", "visual", "small", "topology"],
    },
    "full_structural": {
        "name": "full_structural",
        "title": {"en": "Full Structural Demolition", "zh": "完整结构拆除"},
        "description": {
            "en": "Large 4-bay 6-story frame with full structural analysis. Weakest-first strategy — each round removes the most stressed element, re-analyzes, and repeats until collapse.",
            "zh": "大型4跨6层框架，完整结构分析。最弱优先策略——每轮拆除应力最大的构件，重新分析，循环直到倒塌。",
        },
        "category": "mechanics",
        "structure_params": {
            "type": "steel",
            "num_bays_x": 4,
            "num_stories": 6,
            "span_x_m": 6.0,
            "story_height_m": 3.0,
            "steel_grade": "Q355",
        },
        "strategy": "weakest_first",
        "effects_preset": "standard",
        "speed": 1.0,
        "viz_mode": "webgl",
        "needs_analysis": True,
        "tags": ["analysis", "mechanics", "large", "weakest_first"],
    },
    "cinematic_collapse": {
        "name": "cinematic_collapse",
        "title": {"en": "Cinematic Collapse", "zh": "电影级倒塌"},
        "description": {
            "en": "Medium 3-bay 4-story frame with all visual effects enabled — particles, dust, sound, shake, buckling, fracture. Top-down demolition with extended durations for dramatic effect.",
            "zh": "中型3跨4层框架，启用全部视觉特效——粒子、灰尘、音效、震动、屈曲、断裂。自上而下拆除，延长动画时间增强戏剧效果。",
        },
        "category": "topology",
        "structure_params": {
            "type": "steel",
            "num_bays_x": 3,
            "num_stories": 4,
            "span_x_m": 6.0,
            "story_height_m": 3.0,
            "steel_grade": "Q355",
        },
        "strategy": "top_down",
        "effects_preset": "cinematic",
        "speed": 0.5,
        "viz_mode": "webgl",
        "needs_analysis": False,
        "tags": ["cinematic", "effects", "visual", "dramatic"],
    },
    "bottom_up_implosion": {
        "name": "bottom_up_implosion",
        "title": {"en": "Bottom-Up Implosion", "zh": "底部爆破内塌"},
        "description": {
            "en": "Medium 3-bay 4-story frame, bottom-up demolition simulating implosion. Remove ground-floor columns first — upper structure collapses inward. Cinematic effects, no analysis needed.",
            "zh": "中型3跨4层框架，自下而上拆除模拟内爆。先拆底层柱——上部结构向内倒塌。电影级特效，不需要分析。",
        },
        "category": "topology",
        "structure_params": {
            "type": "steel",
            "num_bays_x": 3,
            "num_stories": 4,
            "span_x_m": 6.0,
            "story_height_m": 3.0,
            "steel_grade": "Q355",
        },
        "strategy": "bottom_up",
        "effects_preset": "cinematic",
        "speed": 1.0,
        "viz_mode": "webgl",
        "needs_analysis": False,
        "tags": ["implosion", "bottom_up", "dramatic", "topology"],
    },
    "unity_3d_physics": {
        "name": "unity_3d_physics",
        "title": {"en": "3D Unity Physics Simulation", "zh": "3D Unity 物理仿真"},
        "description": {
            "en": "3D 3x4-column-grid 4-story frame with Unity real-time physics. Full structural analysis + weakest-first demolition with Unity 3D rendering. Requires Unity to be running.",
            "zh": "3D 3x4柱网4层框架，Unity 实时物理。完整结构分析+最弱优先拆除+Unity 3D 渲染。需要 Unity 运行。",
        },
        "category": "mechanics",
        "structure_params": {
            "type": "steel",
            "num_bays_x": 3,
            "num_bays_z": 4,
            "num_stories": 4,
            "span_x_m": 6.0,
            "span_z_m": 6.0,
            "story_height_m": 3.0,
            "steel_grade": "Q355",
            "dimension": "3d",
        },
        "strategy": "weakest_first",
        "effects_preset": "standard",
        "speed": 1.0,
        "viz_mode": "unity",
        "needs_analysis": True,
        "tags": ["3d", "unity", "physics", "mechanics"],
    },
    "alternating_floor_collapse": {
        "name": "alternating_floor_collapse",
        "title": {"en": "Alternating Floor Collapse", "zh": "隔层交替倒塌"},
        "description": {
            "en": "Medium 4-bay 4-story frame, alternating floor removal. Remove floors 4, 2, then 3, 1 — creating cascading progressive collapse with each gap. Standard effects, topology-driven.",
            "zh": "中型4跨4层框架，隔层交替拆除。先拆第4层、第2层，再拆第3层、第1层——每层间隙制造连续渐进倒塌。标准特效，拓扑驱动。",
        },
        "category": "topology",
        "structure_params": {
            "type": "steel",
            "num_bays_x": 4,
            "num_stories": 4,
            "span_x_m": 6.0,
            "story_height_m": 3.0,
            "steel_grade": "Q355",
        },
        "strategy": "alternating_floors",
        "effects_preset": "standard",
        "speed": 1.0,
        "viz_mode": "webgl",
        "needs_analysis": False,
        "tags": ["alternating", "progressive", "cascade", "topology"],
    },
    "steam_turbine_building": {
        "name": "steam_turbine_building",
        "title": {"en": "Steam Turbine Building", "zh": "蒸汽轮机厂房"},
        "description": {
            "en": "Large 24-bay x 3-axis (A/B/C) industrial building. AB bay 24m steel truss (ridge 27m), BC bay 9m flat beam, column height 25m. 14-step top-down demolition via Blender.",
            "zh": "24榀x3轴(A/B/C)大型工业厂房。AB跨24m钢屋架(脊高27m)，BC跨9m平梁，柱高25m。14步自上而下拆除，走 Blender 管线。",
        },
        "category": "topology",
        "structure_params": {
            "type": "steel",
            "building_type": "steam_turbine",
            "num_bays_x": 24,
            "num_stories": 1,
            "span_x_m": 8.0,
            "story_height_m": 25.0,
            "steel_grade": "Q235",
        },
        "strategy": "top_down",
        "effects_preset": "standard",
        "speed": 1.0,
        "viz_mode": "blender",
        "needs_analysis": False,
        "tags": ["industrial", "steam_turbine", "blender", "large", "topology"],
    },
}

EFFECTS_PRESETS: dict[str, dict] = {
    "minimal": {
        "cascade": False,
        "explosion": False,
        "dust": False,
        "shake": False,
        "buckling": True,
        "fracture": True,
        "flash": False,
        "trail": False,
        "bounce": False,
    },
    "standard": {
        "cascade": True,
        "explosion": True,
        "dust": True,
        "shake": False,
        "buckling": True,
        "fracture": True,
        "flash": False,
        "trail": False,
        "bounce": False,
    },
    "cinematic": {
        "cascade": True,
        "explosion": True,
        "dust": True,
        "shake": True,
        "buckling": True,
        "fracture": True,
        "flash": True,
        "trail": True,
        "bounce": True,
    },
}


def _scenario_summary(s: dict) -> dict:
    return {
        "name": s["name"],
        "title": s["title"],
        "description": s["description"],
        "category": s["category"],
        "needs_analysis": s["needs_analysis"],
        "tags": s["tags"],
        "viz_mode": s["viz_mode"],
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_scenarios",
            description="List all available demolition scenarios. "
                        "Returns scenario summaries: name, title (en/zh), description, "
                        "category (topology/mechanics), whether analysis is needed, and tags.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Filter by category: topology (no analysis needed) or mechanics (requires structural analysis)",
                        "enum": ["topology", "mechanics"],
                    },
                    "tag": {
                        "type": "string",
                        "description": "Filter by tag: quick, visual, cinematic, dramatic, 3d, etc.",
                    },
                },
            },
        ),
        Tool(
            name="get_scenario",
            description="Get the full parameter set for a specific scenario by name. "
                        "Returns structure_params, strategy, effects_preset, speed, viz_mode, "
                        "and needs_analysis flag — everything needed to launch a pipeline.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Scenario name: quick_visual, full_structural, cinematic_collapse, bottom_up_implosion, unity_3d_physics, alternating_floor_collapse",
                        "enum": list(SCENARIOS.keys()),
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="recommend_scenario",
            description="Recommend the best scenario(s) based on a user's natural-language "
                        "description or structural metrics. Returns ranked matches with scores.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "User's description of what they want, e.g. 'I want to see a dramatic bottom-up implosion' or 'quick visualization of a small frame'",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of recommendations to return",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info(f"Tool called: {name}")

    try:
        if name == "list_scenarios":
            result = _handle_list(arguments)
        elif name == "get_scenario":
            result = _handle_get(arguments)
        elif name == "recommend_scenario":
            result = _handle_recommend(arguments)
        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    except Exception as e:
        logger.exception(f"Error handling tool {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]


def _handle_list(arguments: dict) -> dict:
    category = arguments.get("category")
    tag = arguments.get("tag")

    scenarios = list(SCENARIOS.values())

    if category:
        scenarios = [s for s in scenarios if s["category"] == category]
    if tag:
        scenarios = [s for s in scenarios if tag in s["tags"]]

    summaries = [_scenario_summary(s) for s in scenarios]

    return {
        "total": len(summaries),
        "scenarios": summaries,
    }


def _handle_get(arguments: dict) -> dict:
    name = arguments.get("name", "")
    scenario = SCENARIOS.get(name)

    if not scenario:
        return {"error": f"Unknown scenario: {name}. Use list_scenarios to see available names."}

    effects = EFFECTS_PRESETS.get(scenario["effects_preset"], EFFECTS_PRESETS["standard"])

    return {
        "name": scenario["name"],
        "title": scenario["title"],
        "description": scenario["description"],
        "category": scenario["category"],
        "needs_analysis": scenario["needs_analysis"],
        "structure_params": scenario["structure_params"],
        "strategy": scenario["strategy"],
        "effects_preset": scenario["effects_preset"],
        "effects": effects,
        "speed": scenario["speed"],
        "viz_mode": scenario["viz_mode"],
        "tags": scenario["tags"],
    }


def _handle_recommend(arguments: dict) -> dict:
    query = arguments.get("query", "").lower()
    max_results = arguments.get("max_results", 3)

    scores: list[tuple[str, float]] = []

    for name, scenario in SCENARIOS.items():
        score = 0.0

        title_en = scenario["title"]["en"].lower()
        title_zh = scenario["title"]["zh"].lower()
        desc_en = scenario["description"]["en"].lower()
        desc_zh = scenario["description"]["zh"].lower()
        tags = " ".join(scenario["tags"])

        search_space = f"{title_en} {title_zh} {desc_en} {desc_zh} {tags} {scenario['category']} {scenario['strategy']}"

        query_terms = query.split()
        for term in query_terms:
            if term in search_space:
                score += 1.0
            if term in title_en or term in title_zh:
                score += 2.0

        for tag in scenario["tags"]:
            if tag in query:
                score += 1.5

        strategy_keywords = {
            "top_down": ["top", "自上", "自上而下", "topdown"],
            "bottom_up": ["bottom", "自下", "自下而上", "bottomup", "implosion", "爆破", "内爆"],
            "weakest_first": ["weakest", "最弱", "analysis", "分析", "structural", "结构"],
            "alternating_floors": ["alternating", "隔层", "交替", "隔"],
        }
        for strat, keywords in strategy_keywords.items():
            if scenario["strategy"] == strat:
                for kw in keywords:
                    if kw in query:
                        score += 1.5

        if score > 0:
            scores.append((name, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    top = scores[:max_results]

    recommendations = []
    for name, score in top:
        s = SCENARIOS[name]
        recommendations.append({
            "name": name,
            "title": s["title"],
            "score": round(score, 1),
            "category": s["category"],
            "needs_analysis": s["needs_analysis"],
            "match_reason": _match_reason(query, s, score),
        })

    return {
        "query": query,
        "total_matches": len(scores),
        "recommendations": recommendations,
    }


def _match_reason(query: str, scenario: dict, score: float) -> str:
    if score >= 5:
        return "Strong match — multiple keywords and tags align with this scenario"
    if score >= 3:
        return "Good match — key terms overlap with scenario description"
    return "Partial match — some terms align with this scenario"


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
