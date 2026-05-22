"""ReAct Agent Loop — think → act → observe → repeat."""

import json
import logging
from typing import Any, AsyncGenerator

from llm_engine import LLMEngine, SYSTEM_PROMPT
from mcp_hub import MCPClientHub

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5


class AgentLoop:
    """Orchestrates the ReAct loop: LLM reasoning + tool execution."""

    def __init__(self, llm: LLMEngine, hub: MCPClientHub):
        self.llm = llm
        self.hub = hub

    async def run(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
        memory_context: str = "",
    ) -> list[dict[str, Any]]:
        """Run the agent loop and return the final messages.

        Returns a list of step dicts:
            {"type": "thinking", "content": str}
            {"type": "tool_call", "name": str, "arguments": dict}
            {"type": "tool_result", "name": str, "result": Any}
            {"type": "response", "content": str}
            {"type": "error", "content": str}
        """
        steps: list[dict[str, Any]] = []

        # Build system prompt with memory context if available
        system_content = SYSTEM_PROMPT
        if memory_context:
            system_content = f"{SYSTEM_PROMPT}\n\n{memory_context}"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_content},
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        # Get available tools
        tools_list = await self.hub.list_tools()
        llm_tools = self.llm.format_tools_for_llm(tools_list) if tools_list else None

        for iteration in range(MAX_TOOL_ITERATIONS):
            logger.info(f"Agent iteration {iteration + 1}/{MAX_TOOL_ITERATIONS}")

            response = await self.llm.chat(messages, tools=llm_tools)

            if response.get("content"):
                logger.info(f"LLM thinking: {response['content'][:100]}...")

            if response["tool_calls"]:
                # LLM wants to call tools
                for tc in response["tool_calls"]:
                    steps.append({
                        "type": "tool_call",
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    })
                    logger.info(f"Tool call: {tc['name']}({tc['arguments']})")

                    # Add assistant's tool call to messages
                    assistant_msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": response.get("content"),
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
                    # Preserve reasoning_content for DeepSeek thinking mode
                    if response.get("reasoning_content"):
                        assistant_msg["reasoning_content"] = response["reasoning_content"]
                    messages.append(assistant_msg)

                    # Execute the tool
                    result = await self.hub.call_tool(tc["name"], tc["arguments"])
                    # Unwrap hub result: {"result": "<json_string>"} → raw JSON string
                    result_data = result.get("result", result.get("error", str(result)))
                    steps.append({
                        "type": "tool_result",
                        "name": tc["name"],
                        "result": result_data,
                    })
                    logger.info(f"Tool result: {str(result_data)[:100]}...")

                    # Format result for LLM (result_data is already a string)
                    result_text = result_data if isinstance(result_data, str) else json.dumps(result_data)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_text,
                    })
            else:
                # Final response
                content = response.get("content") or "No response generated."
                steps.append({"type": "response", "content": content})
                return steps

        # Max iterations reached — ask LLM for final response
        messages.append({
            "role": "user",
            "content": "Please summarize the results above in a clear, concise answer.",
        })
        final = await self.llm.chat(messages, tools=None)
        content = final.get("content") or "Unable to complete the task within the iteration limit."
        steps.append({"type": "response", "content": content})
        return steps
