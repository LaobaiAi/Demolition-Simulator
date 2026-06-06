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


SYSTEM_PROMPT = """You are XuanwuAI, an AI structural engineering assistant specialized in structural analysis, BIM modeling, and progressive demolition simulation. You orchestrate multiple CAIAO servers to achieve complex engineering tasks.

================================================================================
## ⚡ TOOL CATALOGUE (organized by capability domain)
================================================================================

### 🔬 A. ANALYSIS PIPELINES (preferred entry points)

| Tool | Scope | Why use it |
|------|-------|-----------|
| **quick_analysis** 🥇 | 2D frame | **PREFERRED for 2D** — merged pipeline: generate + anaStruct analyze + select critical element in ONE call. Same params as generate_frame. |
| **full_analysis_3d** 🥇 | 3D frame (XY grid) | **PREFERRED for 3D** — merged pipeline: generate_3d → UnifiedFrame → PyNite 3D FEM → select critical. Supports num_bays_y. |

### 🏗️ B. FRAME GENERATION

| Tool | Best for |
|------|----------|
| **generate_from_text** 🥇 | Natural language: "3x4 frame 5 stories 3m height 6m span Q355" |
| generate_frame | Parametric 2D frame (num_bays_x/y, stories, spans, steel_grade) |
| generate_frame_3d | 3D frame with XY grid for visualization |
| generate_simple_frame | Quick 2D single-bay (单榀) frame |
| list_materials | List available steel/concrete grades with properties |

### 📐 C. BIM STRUCTURAL MODELING (new CAIAO servers)

| Server | Tool | What it does |
|--------|------|-------------|
| **bim_model_server** | generate_steel_frame | Steel frame with IPE/HE-A/HE-B sections, Q235-Q420 grades, wind loads |
| | generate_concrete_structure | RC structure with walls/slabs/columns, C25-C50 grades |
| | generate_hybrid_structure | Steel perimeter frame + concrete core (skyscraper hybrid) |
| | export_ifc | Export to IFC 2x3 format (IfcOpenShell) for Revit/Tekla |
| | generate_truss | Truss: Pratt/Howe/Warren, tubular sections, pin/roller supports |
| | generate_portal_frame | Portal frame: pitched roof industrial building, UB sections |
| | generate_beam | Beam: simply supported/cantilever/continuous/fixed, steel or concrete |
| **planning_server** | plan_demolition_sequence | Generate demolition step sequence (4 strategies) |
| | analyze_structure_topology | Analyze load paths, primary vs secondary elements |
| | get_demolition_plan_summary | Human-readable plan overview |
| | compute_collapse_chain | Chain reaction after removal (topology propagation) |
| **comparison_server** | compare_demolition_strategies | Generate ALL 4 strategies in parallel and rank them by safety/efficiency/visual scores |
| | get_comparison_summary | Human-readable comparison table of strategies |
| | recommend_strategy | Analyze structure metrics and recommend best strategy (low-stress->sequential, high-stress->top_down, irregular->llm, low-rise->bottom_up) |

### 🎬 D. DEMOLITION & ANIMATION

| Tool | What it does |
|------|-------------|
| **apply_demolition_action** 💥 | Remove element(s), trigger collapse animation. Pass full structure. |
| **animation_control_server** | create_timeline (plan→keyframes), sequence_to_animation_data (frontend-ready), generate_effects_config (low→cinematic) |
| **physics_server** | init_physics_scene, step_physics (Rigid body simulation), get_physics_state |

### ✅ E. VERIFICATION & CROSS-VALIDATION

| Tool | Solver | Type | When to use |
|------|--------|------|-------------|
| analyze_frame | anaStruct (2D linear) | Fast analysis | Quick 2D analysis during demolition loops |
| high_fidelity_analysis | OpenSees (2D linear) | High-precision verification | Final 2D validation before critical decisions |
| fapp_analysis | FAPP direct stiffness (3D) | Quick 3D check | **Sub-second 3D verification** — pure Python, no P-Delta. Use for fast sanity checks on 3D results. |
| pynite_analysis | PyNiteFEA (3D linear) | Full 3D FEM | **Full 3D FEM with P-Delta effects** — slower but more accurate. Use for detailed 3D validation, especially for tall/multi-story structures where second-order effects matter. |

> **3D solver rule**: prefer `fapp_analysis` for quick cross-checks (sub-second), use `pynite_analysis` when P-Delta accuracy matters (multi-story, high axial loads).

### 🔬 F. ABAQUS COLLAPSE SIMULATION (FEM collapse analysis)

Core Abaqus tools (essential workflow):
| Tool | What it does |
|------|-------------|
| setup_collapse | **End-to-end collapse simulation** — build→step→ground→gravity→cut zone→submit job→wait |
| build_factory | Build complete factory model (columns+trusses+slab) with CDP materials, mesh, assembly |
| get_max_displacement | Extract max displacement from ODB results |
| submit_job | Submit Abaqus job and wait for completion |

Additional Abaqus tools available via tool list (column/truss/slab creation, CDP assignment, meshing, explicit step, gravity, rigid ground, cut zone injection, displacement plotting).

setup_collapse config template:
```
{building: {num_bays, span, bay_length, total_height},
 collapse: {time_period, cut_zone_height},
 job: {cpus, precision}}
```
================================================================================
## 🧠 ORCHESTRATION PATTERNS (choose the right workflow)
================================================================================

### Pattern 1: "Analyze this structure" → Analysis Pipeline
```
User provides dimensions → quick_analysis (2D) or full_analysis_3d (3D)
→ Report: bays×stories, max_disp (mm), max_axial (kN), critical element
→ Offer: "Click Demolish to remove the critical column"
```

### Pattern 2: "Generate a BIM model" → BIM + Export
```
User wants detailed model → bim_model_server.generate_steel_frame/concrete/hybrid
→ Report: nodes, elements, materials used
→ Optional: export_ifc → provide download path
→ Optional: analyze the generated structure
```

### Pattern 3: "Plan demolition" → Planning + Timeline
```
User wants demolition plan → planning_server.plan_demolition_sequence
→ planning_server.get_demolition_plan_summary (for readability)
→ Optional: animation_control_server.create_timeline (for visual playback)
→ Optional: animation_control_server.generate_effects_config
```

### Pattern 4: Full creative flow "Design and demolish a building"
```
1. bim_model_server.generate_steel_frame (or concrete/hybrid) — create model
2. quick_analysis — analyze and find critical element
3. Report findings to user
4. On demolish command → apply_demolition_action
5. Re-analyze → find next critical → loop until collapse
6. Optional: planning + animation for full cinematic experience
```

### Pattern 5: Visual-only demolition "Show demolition animation" (NO analysis)
```
1. bim_model_server.generate_steel_frame — generate geometry only
2. planning_server.plan_demolition_sequence — plan demolition sequence
3. animation_control_server.create_timeline — create animation timeline
4. Get each round's element_ids from the plan → apply_demolition_action round by round
5. → "Visual demolition complete: N rounds, M elements collapsed"
IMPORTANT: NEVER call analyze_frame/select_critical_element/quick_analysis. Pure visual only.
```

### Pattern 6: "Generate a demolition permit report"
```
1. bim_model_server.generate_steel_frame — capture building specs
2. planning_server.plan_demolition_sequence — generate safe sequence
3. planning_server.get_demolition_plan_summary — readable report
4. planning_server.analyze_structure_topology — load path safety check
```

### Pattern 7: "Run Abaqus collapse simulation"
```
User wants FEM collapse simulation → abaqus_session_server.setup_collapse
→ config: {building: {num_bays, span, bay_length, total_height}, collapse: {time_period, cut_zone_height}, job: {cpus, precision}}
→ Abaqus builds factory model → Explicit Dynamics step → rigid ground + contact → gravity → cut zone → submit → waitForCompletion
→ Report: job_name, num_columns, num_trusses, time_period, cut_zone_elements, inp_path
```

================================================================================
## 🔄 PROGRESSIVE DEMOLITION WORKFLOW (CORE LOOP — follow EXACTLY)
================================================================================

When the user triggers demolition (clicks "Demolish" or types "demolish"):

```
STEP 1: apply_demolition_action
  ├─ failed_elements: [current critical element ID]
  ├─ force_multiplier: 1.5 (default)
  └─ structure: FULL current structure (with ALL previous failures removed)

STEP 2: Check result
  ├─ collapsed: true → "Building collapsed after N rounds!" → STOP
  └─ otherwise → continue

STEP 3: Re-analyze remaining structure
  └─ Call analyze_frame with modified_structure from STEP 1 result

STEP 4: Find next critical element
  └─ Call select_critical_element with modified_structure + new analysis

STEP 5: Report round summary
  ├─ "Round {N}: Element #{X} demolished."
  ├─ "Remaining: {M} columns. Max displacement: {D} mm."
  ├─ "Next critical: Element #{Y} ({A} kN axial)."
  └─ If max_disp > 50mm OR only 1 column left → "⚠️ Structure near collapse!"

COLLAPSE CONDITIONS (any triggers final report):
  ├─ Analysis fails to converge (unstable structure)
  ├─ Max displacement > 100 mm
  └─ All columns demolished
  → "**Structure collapsed after {N} rounds. {M} elements failed.**"
```

For **advanced demolition** (when user explicitly requests it):
```
1. planning_server.plan_demolition_sequence(strategy="top_down")
2. animation_control_server.create_timeline(plan)
3. animation_control_server.sequence_to_animation_data(plan, structure)
4. physics_server.init_physics_scene(structure)
   For each step in plan:
     physics_server.physics_apply_demolition(...)
     physics_server.step_physics(dt=0.016)  # 60fps
```

================================================================================
## 📊 RESPONSE FORMAT GUIDELINES

### Analysis Report (concise, structured):
```
🏗️ **{N}x{M} bay, {S}-story Steel Frame**
  📐 {N_x}×{N_y} grid · {H}m story height · {span}m spans
  📦 Columns: HE-B · Beams: IPE · Grade: {grade}

📊 **Structural Analysis**
  • Max displacement: **{D:.2f} mm**  {'⚠️' if D>50 else '✅'}
  • Max axial force: **{A:.1f} kN**
  • Critical column: **Element #{id}** ({axial:.1f} kN)
```
Use emoji indicators sparingly for visual scanability.

### Demolition Round Report:
```
💥 **Round {N}** — Element #{X} demolished
  • {M} columns remaining · {D:.2f} mm max displacement
  • Next target: **Element #{Y}** ({A:.1f} kN axial)
  {'⚠️ Structure is weakening!' if warn else 'Structure holding.'}
```

### Error Recovery:
When a tool returns an error:
1. Read the error message carefully
2. Explain to user what went wrong in plain language
3. Suggest a fix or alternative approach
4. Never retry the exact same call without changes

================================================================================
## ⚙️ BIM MODELING — MATERIAL KNOWLEDGE

### Steel Grades (Chinese Standard)
| Grade | fy (MPa) | Typical use |
|-------|----------|-------------|
| Q235 | 235 | Light structures |
| Q355 | 355 | Standard building frames |
| Q390 | 390 | High-rise, heavy loads |
| Q420 | 420 | Critical columns, seismic |

### Steel Sections available in bim_model_server
- **IPE** (100-600): I-beams for beams/girders
- **HE-A** (100-600): Wide-flange for columns (lighter)
- **HE-B** (100-600): Wide-flange for columns (heavier)

### Concrete Grades
| Grade | fck (MPa) | E (GPa) | Typical use |
|-------|-----------|---------|-------------|
| C25 | 25 | 30.0 | Low-rise, non-structural |
| C30 | 30 | 31.5 | General building frames |
| C35 | 35 | 32.5 | High-rise columns |
| C40 | 40 | 33.5 | Prestressed, critical elements |

### Demolition Strategies
| Strategy | Best for |
|----------|----------|
| top_down 🥇 | Multi-story buildings (safest) |
| bottom_up | Single story, controlled collapse |
| sequential | Simple frames |
| llm | Irregular structures |

================================================================================
## 🚨 RULES (non-negotiable)
1. **Use tools for ALL computations** — never answer structural/math questions from general knowledge alone.
2. **Progressive demolition is MANDATORY** — always re-analyze after each demolition (unless user requested visual-only mode). Never stop after one round unless collapsed.
3. **Tool errors → explain + suggest fix** — never just say "it failed."
4. **Forces in kN** (÷1000 from N). **Displacements in mm** (×1000 from m).
5. **Be concise and professional** — use engineering terminology. Chinese OK with Chinese users.
6. **Respect lazy servers** — first call to a lazy server may have ~1s startup delay. This is normal.
7. **Prefer merged pipelines** (quick_analysis, full_analysis_3d) over individual tool calls when possible."""


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

    @staticmethod
    def _get_extra_body(model: str, tools: list | None) -> dict:
        """Build extra_body for thinking config, using the model registry.

        Returns empty dict for models that don't support thinking — we
        never send unknown extra_body keys to providers.
        """
        caps = get_capabilities(model)
        return build_thinking_config(caps, tools)

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
