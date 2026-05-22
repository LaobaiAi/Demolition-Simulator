"""LLMEngine wraps OpenAI SDK for chat completions with tool calling support."""

import json
import logging
import os
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


def _normalize_content(content: Any) -> str | None:
    """Normalize message.content which may be str, list[ContentBlock], or None."""
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts) if parts else None
    return str(content)


SYSTEM_PROMPT = """You are XuanwuAI, an intelligent engineering assistant specialized in structural analysis and demolition simulation.

## Your Capabilities
You have access to these engineering tools:
- **Structural generation** (generate_simple_frame): Create a 2D steel frame with specified spans, stories, dimensions.
- **Structural analysis** (analyze_frame): Analyze a frame and get node displacements, element forces, max values.
- **Critical element selection** (select_critical_element): Identify the most stressed column for demolition.
- **High-fidelity verification** (high_fidelity_analysis): Run OpenSees nonlinear analysis for independent verification.
- **Demolition simulation** (apply_demolition_action): Trigger a physics-based collapse animation in Unity. Only call this when the user explicitly requests demolition.
- **Math tools** (add, subtract, multiply, divide): For any numerical calculations.

## Structural Analysis Workflow
When a user asks to analyze a structure, follow this sequence:

1. **Generate the frame**: Call `generate_simple_frame` with appropriate parameters.
2. **Analyze the frame**: Call `analyze_frame` with the generated structure.
3. **Select critical element**: Call `select_critical_element` with both the structure and the analysis result. This identifies the most stressed column.
4. **Report findings** in a clear summary:
   - Frame: {spans} spans × {stories} stories ({span_length}m × {story_height}m)
   - Max displacement: **{value} mm**
   - Max axial force: **{value} kN**
   - Critical column: **Element #{id}** ({axial} kN axial force, of {count} columns analyzed)
   - Suggestion: "Click the **Demolish** button in the right panel to trigger the collapse simulation."

## Demolition Triggering
- **IMPORTANT**: Do NOT call `apply_demolition_action` automatically.
- After reporting findings, tell the user to click the Demolish button in the UI.
- Only call `apply_demolition_action` if the user explicitly types a command like "demolish", "trigger collapse", "go ahead", "execute", or "do it".
- When calling `apply_demolition_action`, use:
  - `failed_elements`: [critical_element_id]
  - `force_multiplier`: 1.5

## Rules
- Always use tools for computations — never answer math/structure questions directly.
- Follow the workflow step by step. Do not skip steps or reorder them.
- If a tool returns an error, explain the error to the user and suggest a fix.
- Be concise and professional. Use engineering terminology.
- Present forces in kN (divide N by 1000) and displacements in mm (multiply m by 1000)."""


class LLMEngine:
    """Thin wrapper around OpenAI SDK for tool-calling chat completions."""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")

        client_kwargs: dict[str, Any] = {"_enforce_credentials": False}
        if self.api_key:
            client_kwargs["api_key"] = self.api_key
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self.client = AsyncOpenAI(**client_kwargs)

    def configure(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None):
        """Reconfigure the LLM engine at runtime (e.g., from frontend settings)."""
        if model is not None:
            self.model = model
        if api_key is not None:
            self.api_key = api_key
        if base_url is not None:
            self.base_url = base_url

        client_kwargs: dict[str, Any] = {"_enforce_credentials": False}
        if self.api_key:
            client_kwargs["api_key"] = self.api_key
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self.client = AsyncOpenAI(**client_kwargs)
        logger.info(f"LLM reconfigured: model={self.model}, base_url={self.base_url or 'default'}")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> dict[str, Any]:
        """Send a chat completion request and return the response dict.

        Returns a dict with keys:
            - content: str | None (text response if no tool calls)
            - tool_calls: list[dict] | None (tool calls requested)
            - raw: the full response object
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        if tools:
            kwargs["tools"] = tools
            if tool_choice == "auto":
                kwargs["tool_choice"] = "auto"

        try:
            response = await self.client.chat.completions.create(**kwargs)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"LLM call failed: {error_msg}")
            if "401" in error_msg or "auth" in error_msg.lower():
                return {"content": "Authentication failed. Please check your OPENAI_API_KEY.", "tool_calls": None, "raw": None}
            if "429" in error_msg or "rate" in error_msg.lower():
                return {"content": "Service is rate limited. Please try again later.", "tool_calls": None, "raw": None}
            return {"content": f"LLM error: {error_msg}", "tool_calls": None, "raw": None}

        choice = response.choices[0]
        message = choice.message

        # Normalize content: OpenAI SDK may return str, list[ContentBlock], or None
        content = _normalize_content(message.content)

        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments)
                    if isinstance(tc.function.arguments, str)
                    else tc.function.arguments,
                }
                for tc in message.tool_calls
            ]

        return {
            "content": content,
            "tool_calls": tool_calls,
            "raw": response,
        }

    def format_tools_for_llm(self, tools_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert internal tool format to OpenAI tool format."""
        formatted = []
        for tool in tools_list:
            formatted.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            })
        return formatted
