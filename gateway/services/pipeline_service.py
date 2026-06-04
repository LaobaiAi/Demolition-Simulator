"""Pipeline service helpers — shared by REST and WebSocket pipeline execution."""

import json
from typing import Any

_TOOL_LABELS: dict[str, str] = {
    "generate_frame": "Generating structural frame",
    "analyze_frame": "Running structural analysis",
    "select_critical_element": "Identifying critical elements",
    "plan_demolition_sequence": "Planning demolition sequence",
    "create_timeline": "Creating animation timeline",
    "sequence_to_animation_data": "Building animation data",
    "generate_effects_config": "Configuring visual effects",
    "init_physics_scene": "Initializing physics engine",
}


def tool_label(tool_name: str) -> str:
    return _TOOL_LABELS.get(tool_name, tool_name.replace("_", " ").title())


def get_pipeline_config(hub, name: str) -> list[dict[str, Any]] | None:
    """Read pipeline steps from a composite server config (caiao.yaml manifest)."""
    for config in hub._server_configs:
        if config["name"] == name and config.get("composite"):
            pipeline = config.get("pipeline", [])
            steps: list[dict[str, Any]] = []
            for i, step in enumerate(pipeline):
                tool = step["tool"]
                s: dict[str, Any] = {
                    "server": step.get("server", ""),
                    "tool": tool,
                    "label": step.get("label") or tool_label(tool),
                }
                if tool == "generate_frame" and i == 0:
                    s["skip_if_structure"] = True
                steps.append(s)
            return steps
    return None


def parse_step_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Unwrap CAIAO tool result: if raw has a 'result' key with a JSON string, parse it."""
    result_val = raw.get("result")
    if isinstance(result_val, str):
        try:
            return json.loads(result_val)
        except (json.JSONDecodeError, TypeError):
            return {"raw": result_val}
    if isinstance(result_val, dict):
        return result_val
    return raw


def resolve_pipeline_args(
    tool_name: str,
    structure: dict[str, Any] | None,
    strategy: str,
    effects_preset: str,
    speed: float,
    structure_params: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """Build arguments for a pipeline step, using prior results from ctx."""
    effective_structure = structure
    gen_result = parse_step_result(ctx.get("generate_frame", {}))
    if gen_result.get("nodes") and gen_result.get("elements"):
        effective_structure = gen_result

    if tool_name == "plan_demolition_sequence":
        return {"structure": effective_structure or structure_params, "strategy": strategy}
    if tool_name == "create_timeline":
        return {
            "demolition_plan": parse_step_result(ctx.get("plan_demolition_sequence", {})),
            "effects_preset": effects_preset,
        }
    if tool_name == "sequence_to_animation_data":
        return {
            "demolition_sequence": parse_step_result(ctx.get("create_timeline", {})),
            "speed": speed,
        }
    if tool_name == "generate_effects_config":
        return {"preset": effects_preset, "structure": effective_structure or structure_params}
    if tool_name == "init_physics_scene":
        return {
            "structure": effective_structure or structure_params,
            "animation_data": parse_step_result(ctx.get("sequence_to_animation_data", {})),
        }
    if tool_name == "generate_frame":
        return {
            "num_bays_x": structure_params.get("num_bays_x", 3),
            "num_stories": structure_params.get("num_stories", 4),
            "span_x_m": structure_params.get("span_x_m", 6.0),
            "story_height_m": structure_params.get("story_height_m", 3.0),
            "steel_grade": structure_params.get("steel_grade", "Q355"),
        }
    if tool_name == "analyze_frame":
        return {"structure": effective_structure or structure_params}
    if tool_name == "select_critical_element":
        analysis = parse_step_result(ctx.get("analyze_frame", {}))
        return {
            "structure": effective_structure or structure_params,
            "analysis_result": analysis,
        }
    return {}


def trim_for_pipeline(result: dict[str, Any]) -> dict[str, Any]:
    """Trim verbose fields from a pipeline step result for progress messages."""
    trimmed: dict[str, Any] = {}
    for k, v in result.items():
        if k == "result":
            trimmed[k] = v
        elif k in ("steps", "chain_rounds", "animation_sequence", "body_states", "keyframes"):
            trimmed[k] = f"[{len(v)} items]" if isinstance(v, list) else str(v)[:200]
        elif k == "error":
            trimmed[k] = str(v)[:300]
        elif isinstance(v, str) and len(v) > 500:
            trimmed[k] = v[:500] + "..."
        else:
            trimmed[k] = v
    return trimmed


def extract_timeline_steps(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract a simplified timeline step list from pipeline context for the frontend."""
    plan_raw = parse_step_result(ctx.get("plan_demolition_sequence", {}))
    timeline_raw = parse_step_result(ctx.get("create_timeline", {}))

    steps = plan_raw.get("steps") or timeline_raw.get("steps") or []
    if isinstance(steps, list) and len(steps) > 0 and isinstance(steps[0], dict):
        return [
            {
                "id": s.get("step", i),
                "elementId": s.get("element_id", 0),
                "elementType": s.get("element_type", "unknown"),
                "phase": s.get("action", "remove"),
                "durationMs": s.get("duration_ms", 2000),
            }
            for i, s in enumerate(steps)
        ][:50]
    return []
