"""Pipeline executor — async generator that drives pipeline execution through the hub.

Every tool call goes through hub.call_tool(). This is the single orchestration path
for WebSocket-driven pipelines. When the caiao package adds streaming composite
execution, this module becomes a thin wrapper around hub's built-in method.
"""

import logging
from typing import Any, AsyncGenerator

from services.pipeline_service import (
    get_pipeline_config,
    parse_step_result,
    resolve_pipeline_args,
    trim_for_pipeline,
    extract_timeline_steps,
)

logger = logging.getLogger(__name__)


async def execute_pipeline_streaming(
    hub,
    pipeline_name: str,
    mode: str,
    structure: dict[str, Any] | None,
    strategy: str,
    effects_preset: str,
    speed: float,
    structure_params: dict[str, Any],
) -> AsyncGenerator[dict[str, Any], None]:
    pipeline_def = get_pipeline_config(hub, pipeline_name, mode)
    if not pipeline_def:
        yield {
            "type": "pipeline_error",
            "content": f"Unknown pipeline: {pipeline_name}",
        }
        return

    has_structure = structure and structure.get("nodes") and structure.get("elements")
    has_generator = any(s.get("tool") == "generate_frame" for s in pipeline_def)

    if not has_structure and not has_generator:
        yield {
            "type": "pipeline_error",
            "content": "Pipeline requires a valid structure — none provided and no generator step in pipeline",
        }
        return

    yield {
        "type": "pipeline_start",
        "pipeline": pipeline_name,
        "total_steps": len(pipeline_def),
        "strategy": strategy,
    }

    pipeline_ctx: dict[str, Any] = {}

    for i, step in enumerate(pipeline_def):
        if step.get("skip_if_structure") and has_structure:
            pipeline_ctx[step["tool"]] = {
                "nodes": structure["nodes"],
                "elements": structure["elements"],
                "loads": structure.get("loads", []),
                "supports": structure.get("supports", []),
            }
            yield {
                "type": "pipeline_step",
                "phase": step.get("label", step["tool"]),
                "progress": round((i + 1) / len(pipeline_def), 2),
                "step_index": i,
                "total_steps": len(pipeline_def),
                "tool": step["tool"],
                "data": {"status": "skipped", "reason": "structure already provided"},
            }
            continue

        tool_name = step["tool"]
        label = step.get("label", tool_name)
        server_hint = step.get("server")

        arguments = resolve_pipeline_args(
            tool_name, structure, strategy, effects_preset,
            speed, structure_params, pipeline_ctx,
        )

        if server_hint:
            await hub._ensure_server(tool_name, server_hint)

        result = await hub.call_tool(tool_name, arguments)
        pipeline_ctx[tool_name] = result

        progress = round((i + 1) / len(pipeline_def), 2)

        if "error" in result:
            yield {
                "type": "pipeline_step",
                "phase": label,
                "progress": progress,
                "step_index": i,
                "total_steps": len(pipeline_def),
                "tool": tool_name,
                "error": str(result.get("error", "Unknown error")),
            }
            yield {
                "type": "pipeline_error",
                "content": f"Pipeline failed at step {i + 1}/{len(pipeline_def)} ({label}): {result.get('error', 'Unknown error')}",
            }
            return

        yield {
            "type": "pipeline_step",
            "phase": label,
            "progress": progress,
            "step_index": i,
            "total_steps": len(pipeline_def),
            "tool": tool_name,
            "data": trim_for_pipeline(result),
        }

    plan_result = parse_step_result(pipeline_ctx.get("plan_demolition_sequence", {}))
    step_count = plan_result.get("total_steps", 0) if isinstance(plan_result, dict) else 0
    timeline_steps = extract_timeline_steps(pipeline_ctx)
    yield {
        "type": "pipeline_complete",
        "pipeline": pipeline_name,
        "timeline_steps": timeline_steps,
        "strategy": strategy,
        "step_count": step_count,
    }
