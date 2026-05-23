"""LLMEngine wraps OpenAI SDK for chat completions with tool calling support."""

import json
import logging
import os
from typing import Any, AsyncGenerator

import httpx
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


def _build_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(retries=1),
        timeout=httpx.Timeout(60.0, connect=10.0),
    )


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


SYSTEM_PROMPT = """You are XuanwuAI, an intelligent engineering assistant specialized in structural analysis and progressive demolition simulation.

## Your Capabilities
You have access to these engineering tools:
- **Structural generation** (generate_simple_frame): Create a 2D steel frame with specified spans, stories, dimensions.
- **Structural analysis** (analyze_frame): Analyze a frame and get node displacements, element forces, max values.
- **Critical element selection** (select_critical_element): Identify the most stressed column for demolition.
- **High-fidelity verification** (high_fidelity_analysis): Run OpenSees 2D linear elastic analysis for independent verification.
- **3D cross-validation** (pynite_analysis): Run PyNiteFEA 3D linear elastic analysis. Use when 2D results are uncertain or deviating — provides an independent 3D perspective.
- **3D cross-validation** (fapp_analysis): Run FAPP direct stiffness 3D linear elastic analysis. Another independent 3D solver for consensus verification.
- **Demolition simulation** (apply_demolition_action): Remove an element from the structure and trigger collapse animation in the frontend. Pass the full structure so the modified version (without failed elements) can be returned for re-analysis.

## Structural Analysis Workflow
When a user asks to analyze a new structure, follow this sequence:

1. **Generate the frame**: Call `generate_simple_frame` with appropriate parameters.
2. **Analyze the frame**: Call `analyze_frame` with the generated structure.
3. **Select critical element**: Call `select_critical_element` with both the structure and the analysis result.
4. **Report findings** concisely:
   - Frame: {spans} spans x {stories} stories
   - Max displacement: **{value} mm**
   - Max axial force: **{value} kN**
   - Critical column: **Element #{id}** ({axial} kN axial force)
   - "Click **Demolish** below the chat to remove this column."

## Progressive Demolition Workflow
After the user triggers demolition (by clicking the Demolish button or typing "demolish"), you MUST continue:

1. **Execute demolition**: Call `apply_demolition_action` with:
   - `failed_elements`: [current critical element ID]
   - `force_multiplier`: 1.5
   - `structure`: the FULL current structure (with ALL previously failed elements already removed)

2. **Evaluate collapse**: Check the result. If `collapsed: true`, the structure has fully collapsed — report it and STOP.

3. **Re-analyze remaining structure**: Call `analyze_frame` with the `modified_structure` from the demolition result (structure without the just-removed element).

4. **Find next target**: Call `select_critical_element` with the modified structure and new analysis.

5. **Report round summary**:
   ```
   Round {N}: Element #{X} demolished.
   Remaining: {M} columns. Max displacement: {disp} mm.
   Next critical: Element #{Y} ({axial} kN axial).
   Structure is {weakening/close to collapse}. Click Demolish to continue.
   ```
   If max displacement exceeds 50mm OR only 1 column remains, warn: "**Structure near collapse!**"

## Collapse Criteria
The structure has collapsed when:
- The analysis fails to converge (remove too many elements makes it unstable)
- OR max displacement exceeds 100 mm
- OR all columns have been demolished
- Report: "**Structure collapsed after {N} demolition rounds. {M} elements failed.**"

## Rules
- Always use tools for computations — never answer math/structure questions directly.
- For demolition commands, follow the progressive demolition workflow. Always re-analyze after each demolition.
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

        client_kwargs: dict[str, Any] = {"http_client": _build_http_client()}
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

        client_kwargs: dict[str, Any] = {"http_client": _build_http_client()}
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
            "extra_body": {"thinking": {"type": "disabled"}},
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

        # Preserve reasoning_content for DeepSeek thinking mode
        reasoning = getattr(message, "reasoning_content", None)

        return {
            "content": content,
            "tool_calls": tool_calls,
            "reasoning_content": reasoning,
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

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Streaming chat completion — yields chunks as they arrive.

        Yields dicts with keys:
            - type: "reasoning_chunk" (DeepSeek thinking), "content_chunk", or "stream_complete"
            - On stream_complete: includes content, tool_calls (parsed), reasoning_content
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "extra_body": {"thinking": {"type": "disabled"}},
        }

        if tools:
            kwargs["tools"] = tools
            if tool_choice == "auto":
                kwargs["tool_choice"] = "auto"

        stream = await self.client.chat.completions.create(**kwargs)

        reasoning_parts: list[str] = []
        content_parts: list[str] = []
        tool_bufs: dict[int, dict[str, Any]] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            reasoning = getattr(delta, "reasoning_content", None) or ""
            if reasoning:
                reasoning_parts.append(reasoning)
                yield {"type": "reasoning_chunk", "content": reasoning}

            if delta.content:
                content_parts.append(delta.content)
                yield {"type": "content_chunk", "content": delta.content}

            if delta.tool_calls:
                for td in delta.tool_calls:
                    idx = td.index
                    if idx not in tool_bufs:
                        tool_bufs[idx] = {"id": "", "name": "", "arguments": ""}
                    if td.id:
                        tool_bufs[idx]["id"] = td.id
                    if td.function and td.function.name:
                        tool_bufs[idx]["name"] += td.function.name
                    if td.function and td.function.arguments:
                        tool_bufs[idx]["arguments"] += td.function.arguments

        reasoning_full = "".join(reasoning_parts)
        content_full = "".join(content_parts)

        if tool_bufs:
            parsed_calls = []
            for idx in sorted(tool_bufs.keys()):
                buf = tool_bufs[idx]
                try:
                    args = json.loads(buf["arguments"])
                except (json.JSONDecodeError, TypeError):
                    args = buf["arguments"]
                parsed_calls.append({
                    "id": buf["id"],
                    "name": buf["name"],
                    "arguments": args,
                })
            yield {
                "type": "stream_complete",
                "tool_calls": parsed_calls,
                "reasoning_content": reasoning_full,
                "content": content_full,
            }
        else:
            yield {
                "type": "stream_complete",
                "content": content_full,
                "reasoning_content": reasoning_full,
                "tool_calls": None,
            }
