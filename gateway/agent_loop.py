"""ReAct Agent Loop — think → act → observe → repeat.  Streams steps as they happen."""

import json
import logging
from typing import Any, AsyncGenerator

from llm_engine import LLMEngine, SYSTEM_PROMPT
from caiao_hub import CAIAOClientHub

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5


class AgentLoop:
    """Orchestrates the ReAct loop: LLM reasoning + tool execution."""

    def __init__(self, llm: LLMEngine, hub: CAIAOClientHub):
        self.llm = llm
        self.hub = hub

    async def run(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
        memory_context: str = "",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Run the agent loop, yielding steps as they happen.

        Yields dicts:
            {"type": "thinking", "content": str}
            {"type": "tool_call", "name": str, "arguments": dict}
            {"type": "tool_result", "name": str, "result": Any}
            {"type": "response", "content": str}
            {"type": "error", "content": str}
        """
        system_content = SYSTEM_PROMPT
        if memory_context:
            system_content = f"{SYSTEM_PROMPT}\n\n{memory_context}"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_content},
        ]
        if history:
            for h in history:
                h_clean = {k: v for k, v in h.items() if k != "reasoning_content"}
                messages.append(h_clean)
        messages.append({"role": "user", "content": user_message})

        tools_list = await self.hub.list_tools()
        llm_tools = self.llm.format_tools_for_llm(tools_list) if tools_list else None

        for iteration in range(MAX_TOOL_ITERATIONS):
            logger.info(f"Agent iteration {iteration + 1}/{MAX_TOOL_ITERATIONS}")

            # Stream LLM response, collecting full result
            streamed_reasoning: list[str] = []
            streamed_content: list[str] = []
            final_tool_calls = None
            final_content = ""
            final_reasoning = ""

            try:
                async for chunk in self.llm.chat_stream(messages, tools=llm_tools):
                    if chunk["type"] == "reasoning_chunk":
                        streamed_reasoning.append(chunk["content"])
                        yield {"type": "thinking", "content": chunk["content"]}
                    elif chunk["type"] == "content_chunk":
                        streamed_content.append(chunk["content"])
                    elif chunk["type"] == "stream_complete":
                        final_tool_calls = chunk.get("tool_calls")
                        final_content = chunk.get("content", "")
                        final_reasoning = chunk.get("reasoning_content", "")
            except Exception as e:
                error_msg = str(e)
                logger.error(f"LLM stream failed: {error_msg}")
                yield {"type": "error", "content": f"LLM error: {error_msg}"}
                return

            if final_tool_calls:
                for tc in final_tool_calls:
                    yield {
                        "type": "tool_call",
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    }
                    logger.info(f"Tool call: {tc['name']}({tc['arguments']})")

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

                    result = await self.hub.call_tool(tc["name"], tc["arguments"])
                    if "result" in result:
                        result_data = result["result"]
                    elif "error" in result:
                        result_data = result  # preserve {"error": ...} so consumers can detect it
                    else:
                        result_data = str(result)
                    yield {
                        "type": "tool_result",
                        "name": tc["name"],
                        "result": result_data,
                    }
                    logger.info(f"Tool result: {str(result_data)[:100]}...")

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
                yield {"type": "response", "content": content}
                yield {"type": "history", "messages": messages[1:]}  # skip system msg
                return

        # Max iterations reached
        messages.append({
            "role": "user",
            "content": "Please summarize the results above in a clear, concise answer.",
        })
        try:
            final = await self.llm.chat(messages, tools=None)
            content = final.get("content") or "Unable to complete the task within the iteration limit."
        except Exception:
            content = "Unable to complete the task within the iteration limit."
        # Save full history for next round
        messages.append({"role": "assistant", "content": content})
        yield {"type": "response", "content": content}
        yield {"type": "history", "messages": messages[1:]}  # skip system msg
