"""ReAct Agent Loop — plans then acts, streaming steps as they happen.

Supports deep reasoning (thinking mode) for complex multi-tool orchestration
with tool result caching, iteration tracking, and graceful degradation.
Supports external cancel/stop and pause/resume via asyncio.Event signals.
"""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

from llm_engine import LLMEngine, SYSTEM_PROMPT
from caiao_hub import CAIAOClientHub

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 12
REPLAN_AFTER = 6  # after this many iterations, force a summary/replan


def _make_cache_key(name: str, args: dict) -> str:
    """Deterministic cache key for tool calls."""
    return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"


class AgentLoop:
    """Orchestrates the ReAct loop: LLM reasoning + tool execution."""

    def __init__(self, llm: LLMEngine, hub: CAIAOClientHub):
        self.llm = llm
        self.hub = hub
        self._tool_cache: dict[str, Any] = {}
        self._cancel_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._resume_event = asyncio.Event()
        self._resume_event.set()  # not paused initially

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
    ) -> AsyncGenerator[dict[str, Any], None]:
        system_content = SYSTEM_PROMPT
        if memory_context:
            system_content = f"{SYSTEM_PROMPT}\n\n{memory_context}"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_content},
        ]
        if history:
            # NOTE: reasoning_content is preserved in history for DeepSeek models,
            # which require it when the previous assistant turn had tool_calls.
            # OpenAI models ignore this field so it's harmless to keep it.
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        tools_list = await self.hub.list_tools()
        llm_tools = self.llm.format_tools_for_llm(tools_list) if tools_list else None

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
                async for chunk in self.llm.chat_stream(messages, tools=llm_tools):
                    if chunk["type"] == "reasoning_chunk":
                        streamed_reasoning.append(chunk["content"])
                        total_reasoning.append(chunk["content"])
                    elif chunk["type"] == "content_chunk":
                        streamed_content.append(chunk["content"])
                    elif chunk["type"] == "stream_complete":
                        final_tool_calls = chunk.get("tool_calls")
                        final_content = chunk.get("content", "")
                        final_reasoning = chunk.get("reasoning_content", "")
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

                    # Check tool cache (avoid redundant calls with identical args)
                    cache_key = _make_cache_key(tc["name"], tc["arguments"])
                    cached = self._tool_cache.get(cache_key)
                    if cached is not None:
                        logger.info(f"Tool cache hit: {tc['name']}")
                        result_data = cached
                        yield {
                            "type": "tool_result",
                            "name": tc["name"],
                            "result": result_data,
                            "cached": True,
                            "iteration": iteration,
                        }
                    else:
                        result = await self.hub.call_tool(tc["name"], tc["arguments"])
                        if "result" in result:
                            result_data = result["result"]
                        elif "error" in result:
                            result_data = result
                        else:
                            result_data = str(result)

                        # Cache successful results (skip errors)
                        if isinstance(result_data, str) and "error" not in result_data.lower()[:50]:
                            self._tool_cache[cache_key] = result_data
                        elif isinstance(result_data, dict) and "error" not in result_data:
                            self._tool_cache[cache_key] = result_data

                        yield {
                            "type": "tool_result",
                            "name": tc["name"],
                            "result": result_data,
                            "cached": False,
                            "iteration": iteration,
                        }
                        logger.info(f"Tool result [{iteration}]: {str(result_data)[:120]}")

                    result_text = result_data if isinstance(result_data, str) else json.dumps(result_data)
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
