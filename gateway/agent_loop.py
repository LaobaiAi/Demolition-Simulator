"""ReAct Agent Loop — plans then acts, streaming steps as they happen.

Supports deep reasoning (thinking mode) for complex multi-tool orchestration
with tool result caching, iteration tracking, and graceful degradation.
Supports external cancel/stop and pause/resume via asyncio.Event signals.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncGenerator

from llm_engine import LLMEngine, build_system_prompt
from caiao import CAIAOClientHub

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 16
REPLAN_AFTER = 10  # after this many iterations, force a summary/replan


def _make_cache_key(name: str, args: dict) -> str:
    """Deterministic cache key for tool calls."""
    return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"


TOOL_KEYWORD_MAP: dict[str, list[str]] = {
    "generate": ["generate_frame", "generate_frame_3d", "generate_simple_frame",
                 "generate_from_text", "generate_steel_frame", "generate_concrete_structure",
                 "generate_hybrid_structure", "generate_truss", "generate_portal_frame",
                 "generate_beam", "export_ifc", "list_materials"],
    "analyze": ["analyze_frame", "quick_analysis", "full_analysis_3d",
                "high_fidelity_analysis", "fapp_analysis", "pynite_analysis",
                "select_critical_element"],
    "demolish": ["apply_demolition_action", "plan_demolition_sequence",
                 "analyze_structure_topology", "get_demolition_plan_summary",
                 "compute_collapse_chain", "compare_demolition_strategies",
                 "get_comparison_summary", "recommend_strategy"],
    "animate": ["create_timeline", "sequence_to_animation_data",
                "generate_effects_config", "init_physics_scene",
                "step_physics", "get_physics_state"],
    "verify": ["high_fidelity_analysis", "fapp_analysis", "pynite_analysis"],
    "abaqus": ["create_rectangular_column", "create_truss", "create_slab",
               "assign_concrete_cdp", "mesh_part", "create_explicit_step",
               "apply_gravity", "create_rigid_ground", "submit_job",
               "get_max_displacement", "plot_displacement_curve",
               "create_cut_zone", "inject_cut_zone_inp", "build_factory",
               "setup_collapse",
               "create_cooling_tower", "assign_tower_materials", "mesh_tower",
               "setup_tower_collapse", "extract_collapse_frames",
               "render_collapse_video", "get_collapse_status", "stop_collapse",
               "stack_run_analysis"],
    "bim": ["generate_steel_frame", "generate_concrete_structure",
            "generate_hybrid_structure", "export_ifc", "generate_truss",
            "generate_portal_frame", "generate_beam"],
}

# ── Mode-scoped tool groups ─────────────────────────────────────────────────
# fast (Blender) 模式只暴露 Blender 管线工具
BLENDER_PIPELINE_TOOLS: set[str] = {
    "run_full_pipeline", "run_pipeline_stage", "check_blender_environment",
    "build_frame_model", "list_scenarios", "get_scenario",
    "steam_turbine_demolition", "visual_demolition",
}
# simulation (Abaqus) 模式只暴露 Abaqus 仿真工具
ABAQUS_TOOLS: set[str] = set(TOOL_KEYWORD_MAP["abaqus"])

# ── Tool call safety & caching ───────────────────────────────────────────────
TOOL_CALL_TIMEOUT_S = 600.0
# stack_run_analysis blocks until its own solve budget (GLOBAL_BUDGET_S=9000s) expires —
# a shorter gateway timeout would kill a legitimate solve mid-run and orphan Abaqus.
POLL_TOOL_TIMEOUT_S = 9000.0
POLL_TOOLS: set[str] = {"get_collapse_status", "stack_run_analysis"}
TOOL_CACHE_TTL_S = 30.0


def _is_no_cache_tool(name: str) -> bool:
    """Stateful tools (submit/stop/setup/query, all Abaqus tools) must never be cached —
    identical args can return different state (e.g. poll progress)."""
    return name in ABAQUS_TOOLS or name.startswith(("setup_", "clear_", "stop_"))


def _filter_tools_by_message(
    user_message: str,
    llm_tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Filter tools to only those relevant to the user's message."""
    if not llm_tools or len(llm_tools) < 20:
        return llm_tools

    msg_lower = user_message.lower()
    matched: set[str] = set()

    for keyword, tools in TOOL_KEYWORD_MAP.items():
        if keyword in msg_lower:
            matched.update(tools)

    if not matched:
        return llm_tools

    filtered = [t for t in llm_tools if t["function"]["name"] in matched]
    if len(filtered) < 3:
        return llm_tools

    logger.info(
        f"Tool filter: {len(llm_tools)} -> {len(filtered)} "
        f"(keywords: {[k for k in TOOL_KEYWORD_MAP if k in msg_lower]})"
    )
    return filtered


def _truncate_tool_result(result_data: Any, max_chars: int = 3000) -> Any:
    """Truncate large tool results to keep LLM context lean."""
    if isinstance(result_data, dict):
        trimmed = {}
        for k, v in result_data.items():
            if k in ("nodes", "elements", "element_forces", "node_displacements",
                     "loads", "supports", "keyframes", "steps", "body_states"):
                if isinstance(v, list):
                    trimmed[k] = f"[{len(v)} entries - full data on frontend]"
                elif isinstance(v, str) and len(v) > 500:
                    trimmed[k] = v[:500] + "..."
                else:
                    trimmed[k] = v
            elif isinstance(v, str) and len(v) > max_chars:
                trimmed[k] = v[:max_chars] + "..."
            elif isinstance(v, dict):
                trimmed[k] = _truncate_tool_result(v, max_chars)
            else:
                trimmed[k] = v
        return trimmed
    if isinstance(result_data, str) and len(result_data) > max_chars:
        return result_data[:max_chars] + "..."
    return result_data


# ── Lazy tool schema enrichment ──────────────────────────────────────────────
# Lazy servers are not running at list_tools() time, so the hub returns them with
# a placeholder description and an empty input_schema. Their caiao.yaml manifests
# carry the real descriptions — merge those in before handing tools to the LLM.
_SERVERS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "caiao_servers")
_yaml_tool_meta: dict[str, dict[str, Any]] = {}


def _load_yaml_tool_meta() -> dict[str, dict[str, Any]]:
    """Load tool name → manifest entry for every caiao_servers/*/caiao.yaml (cached)."""
    if _yaml_tool_meta:
        return _yaml_tool_meta
    try:
        import yaml
    except ImportError:
        return _yaml_tool_meta
    if not os.path.isdir(_SERVERS_DIR):
        return _yaml_tool_meta
    for entry in os.scandir(_SERVERS_DIR):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        manifest = os.path.join(entry.path, "caiao.yaml")
        if not os.path.exists(manifest):
            continue
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for tool in data.get("tools") or []:
            if isinstance(tool, dict) and tool.get("name"):
                _yaml_tool_meta[tool["name"]] = tool
    return _yaml_tool_meta


def _enrich_tool_schemas(tools_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace lazy-placeholder descriptions with manifest descriptions (in place)."""
    meta = _load_yaml_tool_meta()
    for tool in tools_list:
        info = meta.get(tool.get("name", ""))
        if not info:
            continue
        if info.get("description") and "(lazy)" in tool.get("description", ""):
            tool["description"] = info["description"]
        schema = tool.get("input_schema")
        if not isinstance(schema, dict) or not schema.get("properties"):
            tool["input_schema"] = {"type": "object", "properties": {}}
    return tools_list


class AgentLoop:
    """Orchestrates the ReAct loop: LLM reasoning + tool execution."""

    def __init__(self, llm: LLMEngine, hub: CAIAOClientHub):
        self.llm = llm
        self.hub = hub
        self._tool_cache: dict[str, tuple[float, Any]] = {}
        self._cancel_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._resume_event = asyncio.Event()
        self._resume_event.set()  # not paused initially
        self._cached_tools: list[dict[str, Any]] | None = None

    def cancel(self) -> None:
        """Signal the agent loop to stop at the next checkpoint."""
        self._cancel_event.set()
        self._resume_event.set()  # unblock pause if waiting

    def pause(self) -> None:
        """Signal the agent loop to pause at the next checkpoint."""
        self._pause_event.set()
        self._resume_event.clear()

    def resume(self) -> None:
        """Resume a paused agent loop."""
        self._pause_event.clear()
        self._resume_event.set()

    def reset_signals(self) -> None:
        """Reset all signals for a new run."""
        self._cancel_event.clear()
        self._pause_event.clear()
        self._resume_event.set()

    async def _check_control(self) -> tuple[bool, str | None]:
        """Check cancel/pause signals. Returns (should_continue, status).
        status is 'paused' or 'resumed' to yield to frontend, or None."""
        if self._cancel_event.is_set():
            logger.info("Agent loop cancelled by external signal")
            return False, "cancelled"
        if self._pause_event.is_set():
            logger.info("Agent loop paused, waiting for resume...")
            await self._resume_event.wait()
            if self._cancel_event.is_set():
                logger.info("Agent loop cancelled while paused")
                return False, "cancelled"
            logger.info("Agent loop resumed")
            return True, "resumed"
        return True, None

    async def run(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
        memory_context: str = "",
        analysis_mode: str = "analysis",
    ) -> AsyncGenerator[dict[str, Any], None]:
        if self._cached_tools is None:
            self._cached_tools = await self.hub.list_tools()
            _enrich_tool_schemas(self._cached_tools)
            logger.info(f"Cached {len(self._cached_tools)} tools from hub")
        tools_list = self._cached_tools
        llm_tools = self.llm.format_tools_for_llm(tools_list) if tools_list else None
        if analysis_mode == "fast" and llm_tools:
            llm_tools = [t for t in llm_tools if t["function"]["name"] in BLENDER_PIPELINE_TOOLS]
            logger.info(f"Fast mode: filtered to {len(llm_tools)} blender pipeline tools")
        elif analysis_mode == "simulation" and llm_tools:
            llm_tools = [t for t in llm_tools if t["function"]["name"] in ABAQUS_TOOLS]
            logger.info(f"Simulation mode: filtered to {len(llm_tools)} abaqus tools")
        else:
            # analysis 模式：排除 Blender 与 Abaqus 工具，其余按消息关键词过滤
            if llm_tools:
                llm_tools = [
                    t for t in llm_tools
                    if t["function"]["name"] not in BLENDER_PIPELINE_TOOLS
                    and t["function"]["name"] not in ABAQUS_TOOLS
                ]
            llm_tools = _filter_tools_by_message(user_message, llm_tools)

        system_content = build_system_prompt(user_message, has_tools=llm_tools is not None, analysis_mode=analysis_mode)
        if memory_context:
            system_content = f"{system_content}\n\n{memory_context}"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_content},
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        total_reasoning: list[str] = []
        total_iterations = 0

        for iteration in range(MAX_TOOL_ITERATIONS):
            total_iterations += 1
            logger.info(f"Agent iteration {iteration + 1}/{MAX_TOOL_ITERATIONS}")

            should_continue, ctrl_status = await self._check_control()
            if not should_continue:
                yield {"type": "response", "content": "Task cancelled by user.", "cancelled": True}
                yield {"type": "history", "messages": messages[1:]}
                return
            if ctrl_status:
                yield {"type": "status", "content": ctrl_status}

            # Decide whether to replan at certain intervals
            if iteration > 0 and iteration % REPLAN_AFTER == 0:
                replan_msg = (
                    "You have completed several steps. Briefly summarize what you've done so far, "
                    "then continue with the next logical step to fully address the user's request. "
                    "If the task is complete, provide the final summary."
                )
                messages.append({"role": "user", "content": replan_msg})

            # Stream LLM response
            streamed_reasoning: list[str] = []
            streamed_content: list[str] = []
            final_tool_calls = None
            final_content = ""
            final_reasoning = ""

            try:
                thinking_buf: list[str] = []
                async for chunk in self.llm.chat_stream(messages, tools=llm_tools):
                    if chunk["type"] == "reasoning_chunk":
                        streamed_reasoning.append(chunk["content"])
                        total_reasoning.append(chunk["content"])
                        thinking_buf.append(chunk["content"])
                        if sum(len(c) for c in thinking_buf) >= 100:
                            yield {"type": "thinking", "content": "".join(thinking_buf)}
                            thinking_buf.clear()
                    elif chunk["type"] == "content_chunk":
                        streamed_content.append(chunk["content"])
                        thinking_buf.append(chunk["content"])
                        if sum(len(c) for c in thinking_buf) >= 100:
                            yield {"type": "thinking", "content": "".join(thinking_buf)}
                            thinking_buf.clear()
                    elif chunk["type"] == "stream_complete":
                        final_tool_calls = chunk.get("tool_calls")
                        final_content = chunk.get("content", "")
                        final_reasoning = chunk.get("reasoning_content", "")
                if thinking_buf:
                    yield {"type": "thinking", "content": "".join(thinking_buf)}
            except Exception as e:
                error_msg = str(e)
                logger.exception(f"LLM stream failed: {error_msg}")
                yield {"type": "error", "content": f"LLM error: {error_msg}", "iteration": iteration}
                return

            if final_tool_calls:
                for tc in final_tool_calls:
                    yield {
                        "type": "tool_call",
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                        "iteration": iteration,
                    }
                    logger.info(f"Tool call [{iteration}]: {tc['name']}")

                    assistant_msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": final_content or None,
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc["arguments"]),
                                },
                            }
                        ],
                    }
                    if final_reasoning:
                        assistant_msg["reasoning_content"] = final_reasoning
                    messages.append(assistant_msg)

                    # Tool cache — idempotent read-only tools only, TTL-bounded
                    cache_key = _make_cache_key(tc["name"], tc["arguments"])
                    cached_result = None
                    if not _is_no_cache_tool(tc["name"]):
                        entry = self._tool_cache.get(cache_key)
                        if entry is not None:
                            ts, value = entry
                            if time.monotonic() - ts <= TOOL_CACHE_TTL_S:
                                cached_result = value
                            else:
                                self._tool_cache.pop(cache_key, None)
                    if cached_result is not None:
                        logger.info(f"Tool cache hit: {tc['name']}")
                        result_data = cached_result
                        yield {
                            "type": "tool_result",
                            "name": tc["name"],
                            "result": result_data,
                            "cached": True,
                            "iteration": iteration,
                        }
                    else:
                        timeout = POLL_TOOL_TIMEOUT_S if tc["name"] in POLL_TOOLS else TOOL_CALL_TIMEOUT_S
                        try:
                            result = await asyncio.wait_for(
                                self.hub.call_tool(tc["name"], tc["arguments"]), timeout
                            )
                        except asyncio.TimeoutError:
                            logger.error(f"Tool call timed out after {timeout}s: {tc['name']}")
                            result = {"error": f"Tool '{tc['name']}' timed out after {int(timeout)}s"}
                        if "result" in result:
                            result_data = result["result"]
                        elif "error" in result:
                            result_data = result
                        else:
                            result_data = str(result)

                        # Cache successful results (skip errors and stateful tools)
                        if not _is_no_cache_tool(tc["name"]):
                            if isinstance(result_data, str) and "error" not in result_data.lower()[:50]:
                                self._tool_cache[cache_key] = (time.monotonic(), result_data)
                            elif isinstance(result_data, dict) and "error" not in result_data:
                                self._tool_cache[cache_key] = (time.monotonic(), result_data)

                        yield {
                            "type": "tool_result",
                            "name": tc["name"],
                            "result": result_data,
                            "cached": False,
                            "iteration": iteration,
                        }
                        logger.info(f"Tool result [{iteration}]: {str(result_data)[:120]}")

                    truncated_data = _truncate_tool_result(result_data)
                    result_text = truncated_data if isinstance(truncated_data, str) else json.dumps(truncated_data)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_text,
                    })
            else:
                # Final response — no tool calls
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": final_content or "No response generated.",
                }
                if final_reasoning:
                    assistant_msg["reasoning_content"] = final_reasoning
                messages.append(assistant_msg)

                content = final_content or "No response generated."
                total_iterations_count = iteration + 1
                yield {
                    "type": "response",
                    "content": content,
                    "iterations": total_iterations_count,
                }
                yield {"type": "history", "messages": messages[1:]}
                return

        # Max iterations reached — force summary
        messages.append({
            "role": "user",
            "content": (
                "You have reached the maximum number of tool call iterations. "
                "Please provide a complete summary of what was accomplished."
            ),
        })
        try:
            final = await self.llm.chat(messages, tools=None)
            content = final.get("content") or "Task incomplete within iteration limit."
        except Exception:
            content = "Unable to complete the task within the iteration limit."

        messages.append({"role": "assistant", "content": content})
        yield {
            "type": "response",
            "content": content,
            "iterations": total_iterations,
            "truncated": True,
        }
        yield {"type": "history", "messages": messages[1:]}
