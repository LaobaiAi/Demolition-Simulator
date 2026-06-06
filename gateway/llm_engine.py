"""LLMEngine wraps OpenAI SDK for chat completions with tool calling support."""

import json
import logging
import os
from typing import Any, AsyncGenerator

import httpx
from openai import AsyncOpenAI
from model_capabilities import get_capabilities, build_thinking_config

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


CORE_PROMPT = """You are XuanwuAI, an AI structural engineering assistant specialized in structural analysis, BIM modeling, and progressive demolition simulation. You orchestrate multiple CAIAO servers to achieve complex engineering tasks.

## 🚨 RULES (non-negotiable)
1. **Use tools for ALL computations** — never answer structural/math questions from general knowledge alone.
2. **Progressive demolition is MANDATORY** — always re-analyze after each demolition (unless user requested visual-only mode). Never stop after one round unless collapsed.
3. **Tool errors → explain + suggest fix** — never just say "it failed."
4. **Forces in kN** (÷1000 from N). **Displacements in mm** (×1000 from m).
5. **Be concise and professional** — use engineering terminology. Chinese OK with Chinese users.
6. **Respect lazy servers** — first call to a lazy server may have ~1s startup delay. This is normal.
7. **Prefer merged pipelines** (quick_analysis, full_analysis_3d) over individual tool calls when possible.

## 🔄 PROGRESSIVE DEMOLITION WORKFLOW (CORE LOOP)

When the user triggers demolition:
```
STEP 1: apply_demolition_action (failed_elements: [critical element ID], force_multiplier: 1.5, structure: FULL current structure)
STEP 2: Check result — collapsed: true → "Building collapsed!" → STOP
STEP 3: Call analyze_frame with modified_structure from STEP 1 result
STEP 4: Call select_critical_element with modified_structure + new analysis
STEP 5: Report round summary
```

COLLAPSE CONDITIONS: analysis fails to converge | max displacement > 100 mm | all columns demolished
**→ "Structure collapsed after {N} rounds."**

## 📊 RESPONSE FORMAT

Analysis Report:
  {N}x{M} bay, {S}-story · {H}m story height · {span}m spans
  Max displacement: {D:.2f} mm  Max axial force: {A:.1f} kN  Critical column: Element #{id}

Demolition Round:
  Round {N} — Element #{X} demolished · {M} columns remaining · {D:.2f} mm max displacement
  Next target: Element #{Y} ({A:.1f} kN axial)
"""

TOOL_CATALOGUE = """
## ⚡ TOOL CATALOGUE

### A. ANALYSIS PIPELINES (preferred)
| quick_analysis | 2D frame | PREFERRED: generate + analyze + select critical in ONE call |
| full_analysis_3d | 3D frame (XY grid) | PREFERRED: generate_3d → PyNite 3D FEM → select critical |

### B. FRAME GENERATION
| generate_from_text | Natural language: "3x4 frame 5 stories 3m height 6m span Q355" |
| generate_frame | Parametric 2D frame |
| generate_frame_3d | 3D frame with XY grid |
| generate_simple_frame | Quick 2D single-bay frame |
| list_materials | Available steel/concrete grades |

### C. BIM STRUCTURAL MODELING
bim_model_server: generate_steel_frame, generate_concrete_structure, generate_hybrid_structure, export_ifc, generate_truss, generate_portal_frame, generate_beam
planning_server: plan_demolition_sequence, analyze_structure_topology, get_demolition_plan_summary, compute_collapse_chain
comparison_server: compare_demolition_strategies, get_comparison_summary, recommend_strategy

### D. DEMOLITION & ANIMATION
| apply_demolition_action | Remove element(s), trigger collapse. Pass full structure. |
| animation_control_server | create_timeline, sequence_to_animation_data, generate_effects_config |
| physics_server | init_physics_scene, step_physics, get_physics_state |

### E. VERIFICATION
| analyze_frame | anaStruct (2D) | Fast 2D analysis |
| high_fidelity_analysis | OpenSees (2D) | High-precision verification |
| fapp_analysis | FAPP (3D) | Sub-second 3D check |
| pynite_analysis | PyNite (3D) | Full 3D FEM with P-Delta |

### F. ABAQUS COLLAPSE SIMULATION
| setup_collapse | End-to-end FEM collapse simulation |
| build_factory | Complete factory model with CDP materials |
| get_max_displacement | Extract max displacement from ODB |
| submit_job | Submit job and wait for completion |
"""

ORCHESTRATION_PATTERNS = """
## 🧠 ORCHESTRATION PATTERNS

Pattern 1 "Analyze this structure": User provides dimensions → quick_analysis (2D) or full_analysis_3d (3D) → Report + offer demolish
Pattern 2 "Generate a BIM model": bim_model_server.generate_steel_frame/concrete/hybrid → Report → Optional: export_ifc
Pattern 3 "Plan demolition": planning_server.plan_demolition_sequence → get_demolition_plan_summary
Pattern 4 "Design and demolish": generate → quick_analysis → Report → demolish → re-analyze → loop until collapse
Pattern 5 "Visual-only demolition" (NO analysis): generate → plan_demolition_sequence → create_timeline → apply_demolition_action round by round
Pattern 6 "Demolition permit report": generate → plan_demolition_sequence → get_demolition_plan_summary → analyze_structure_topology
Pattern 7 "Abaqus collapse": setup_collapse with config {building, collapse, job}
"""

REFERENCE_DATA = """
## ⚙️ MATERIAL REFERENCE

Steel: Q235 (235MPa), Q355 (355MPa), Q390 (390MPa), Q420 (420MPa)
Sections: IPE 100-600 (beams), HE-A 100-600 (columns light), HE-B 100-600 (columns heavy)
Concrete: C25 (25MPa), C30 (30MPa), C35 (32.5MPa), C40 (33.5MPa)
Demolition: top_down (multi-story), bottom_up (single-story), sequential (simple), llm (irregular)
"""

# ── Section dispatch map ─────────────────────────────────────────────────────

SECTION_KEYWORDS: dict[str, str] = {
    "catalogue": TOOL_CATALOGUE,
    "patterns": ORCHESTRATION_PATTERNS,
    "reference": REFERENCE_DATA,
}

SECTION_TRIGGERS: dict[str, list[str]] = {
    "catalogue": ["tool", "tools", "what can you do", "help", "capabilities", "available"],
    "patterns": ["design", "permit", "report", "animation", "visual", "bim", "planning",
                 "generate a", "create a", "build a", "make a"],
    "reference": ["q235", "q355", "q390", "q420", "steel", "concrete", "ipe", "he-a", "he-b",
                  "material", "section", "grade", "c25", "c30", "c35", "c40",
                  "strategy", "top_down", "bottom_up"],
}


def build_system_prompt(user_message: str, has_tools: bool = True) -> str:
    """Build a context-aware system prompt, injecting only relevant sections."""
    msg_lower = user_message.lower()
    sections: list[str] = [CORE_PROMPT]

    if has_tools:
        trigger_catalogue = any(kw in msg_lower for kw in SECTION_TRIGGERS["catalogue"])
        trigger_patterns = any(kw in msg_lower for kw in SECTION_TRIGGERS["patterns"])
        trigger_reference = any(kw in msg_lower for kw in SECTION_TRIGGERS["reference"])

        simple_actions = {"demolish", "verify"}
        is_simple = len(msg_lower.split()) < 8 and any(
            msg_lower.startswith(kw) for kw in simple_actions
        )

        if is_simple:
            pass
        else:
            sections.append(TOOL_CATALOGUE)

        if trigger_patterns:
            sections.append(ORCHESTRATION_PATTERNS)

        if trigger_reference:
            sections.append(REFERENCE_DATA)

    return "\n".join(sections)


# Legacy full prompt kept for backward compatibility
SYSTEM_PROMPT = CORE_PROMPT + TOOL_CATALOGUE + ORCHESTRATION_PATTERNS + REFERENCE_DATA


class LLMEngine:
    """Thin wrapper around OpenAI SDK for tool-calling chat completions."""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
        thinking_enabled: bool = False,
    ):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.thinking_enabled = thinking_enabled

        client_kwargs: dict[str, Any] = {"http_client": _build_http_client()}
        if self.api_key:
            client_kwargs["api_key"] = self.api_key
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self.client = AsyncOpenAI(**client_kwargs)

    def configure(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None, thinking_enabled: bool | None = None):
        """Reconfigure the LLM engine at runtime (e.g., from frontend settings)."""
        if model is not None:
            self.model = model
        if api_key is not None:
            self.api_key = api_key
        if base_url is not None:
            self.base_url = base_url
        if thinking_enabled is not None:
            self.thinking_enabled = thinking_enabled

        client_kwargs: dict[str, Any] = {"http_client": _build_http_client()}
        if self.api_key:
            client_kwargs["api_key"] = self.api_key
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self.client = AsyncOpenAI(**client_kwargs)
        logger.info(f"LLM reconfigured: model={self.model}, base_url={self.base_url or 'default'}")

    def _get_extra_body(self, model: str, tools: list | None) -> dict:
        """Build extra_body for thinking config, using the model registry.

        Returns empty dict for models that don't support thinking — we
        never send unknown extra_body keys to providers.
        """
        caps = get_capabilities(model)
        return build_thinking_config(caps, tools, self.thinking_enabled)

    @staticmethod
    def _is_deepseek_model(model: str) -> bool:
        caps = get_capabilities(model)
        return caps.thinking_format == "deepseek_v4"

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

        # Auto-configure thinking mode based on model
        thinking_config = self._get_extra_body(self.model, tools)
        if thinking_config:
            kwargs["extra_body"] = thinking_config

        if tools:
            kwargs["tools"] = tools
            if tool_choice == "auto":
                kwargs["tool_choice"] = "auto"

        # Enable JSON mode for structured responses when appropriate
        is_deepseek = self._is_deepseek_model(self.model)
        max_retries = 2
        last_error = None

        for attempt in range(max_retries):
            try:
                response = await self.client.chat.completions.create(**kwargs)
            except Exception as e:
                error_msg = str(e)
                last_error = error_msg
                logger.error(f"LLM call failed (attempt {attempt+1}): {error_msg}")

                # Handle specific errors with retry
                if "rate" in error_msg.lower() or "503" in error_msg or "502" in error_msg:
                    import asyncio
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                if "401" in error_msg or "auth" in error_msg.lower():
                    return {"content": "Authentication failed. Please check your API key.", "tool_calls": None, "raw": None}
                if "model_not_found" in error_msg.lower() or "model" in error_msg.lower() and "not" in error_msg.lower():
                    return {"content": f"Model '{self.model}' is not available. Check your model name and API provider.", "tool_calls": None, "raw": None}
                if attempt == max_retries - 1:
                    return {"content": f"LLM error: {error_msg}", "tool_calls": None, "raw": None}
                continue

            choice = response.choices[0]
            message = choice.message

            # Normalize content
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

            # Preserve reasoning_content for thinking mode models
            reasoning = getattr(message, "reasoning_content", None)

            # Token usage tracking
            usage = {}
            if hasattr(response, "usage") and response.usage:
                usage = {
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
                }
                if reasoning:
                    usage["reasoning_tokens"] = getattr(response.usage, "completion_tokens_details", None) and \
                        getattr(response.usage.completion_tokens_details, "reasoning_tokens", 0) or 0

            return {
                "content": content,
                "tool_calls": tool_calls,
                "reasoning_content": reasoning,
                "usage": usage,
                "raw": response,
            }

        return {"content": f"Failed after {max_retries} retries: {last_error}", "tool_calls": None, "raw": None}

    def format_tools_for_llm(self, tools_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert internal tool format to OpenAI tool format."""
        formatted = []
        for tool in tools_list:
            params = tool.get("input_schema", {})
            # OpenAI requires type: object — fix empty/invalid schemas to avoid 400 errors
            if not isinstance(params, dict) or params.get("type") != "object":
                params = {"type": "object", "properties": {}}
            formatted.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": params,
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
            - type: "reasoning_chunk" (thinking content), "content_chunk", "tool_call_chunk", or "stream_complete"
            - On stream_complete: includes content, tool_calls, reasoning_content, usage
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }

        # Auto-configure thinking mode based on model
        thinking_config = self._get_extra_body(self.model, tools)
        if thinking_config:
            kwargs["extra_body"] = thinking_config

        if tools:
            kwargs["tools"] = tools
            if tool_choice == "auto":
                kwargs["tool_choice"] = "auto"

        logger.info(
            f"LLM chat_stream starting: model={self.model}, "
            f"tools={'yes' if tools else 'no'}, "
            f"thinking={'thinking' in kwargs.get('extra_body', {})}"
        )

        try:
            stream = await self.client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.error(f"LLM stream create failed ({self.model}): {type(e).__name__}: {e}")
            raise

        reasoning_parts: list[str] = []
        content_parts: list[str] = []
        tool_bufs: dict[int, dict[str, Any]] = {}

        try:
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
        except Exception as e:
            logger.exception(f"LLM stream iteration failed ({self.model}): {e}")
            raise

        reasoning_full = "".join(reasoning_parts)
        content_full = "".join(content_parts)

        # Estimate token usage from stream chunks
        usage_est = {
            "prompt_est": sum(len(m.get("content") or "") for m in messages) // 4,
            "completion_est": len(content_full) // 4 + sum(len(str(v)) for v in tool_bufs.values()) // 4,
            "reasoning_est": len(reasoning_full) // 4,
        }

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
                "usage": usage_est,
            }
        else:
            yield {
                "type": "stream_complete",
                "content": content_full,
                "reasoning_content": reasoning_full,
                "tool_calls": None,
                "usage": usage_est,
            }
