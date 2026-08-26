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
7. **Prefer merged pipelines** (quick_analysis, full_analysis_3d_gb) over individual tool calls when possible.

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
| full_analysis_3d_gb | 3D frame (XY grid) | PREFERRED: generate 3D steel frame → matrix method / OpenSeesPy solve → GB50017 per-member check → select critical in ONE call |
| full_analysis_3d_gb_remove | 3D member removal (progressive demolition) | Remove member(s) from an EXISTING full_analysis_3d_gb structure → re-solve remaining members → stability (unstable = collapse risk) + GB50017 check + critical element in ONE call |
| full_analysis_3d | 3D frame (XY grid) | LEGACY: generate_3d → PyNite 3D FEM → select critical (use full_analysis_3d_gb) |

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
"""

ORCHESTRATION_PATTERNS = """
## 🧠 ORCHESTRATION PATTERNS

Pattern 1 "Analyze this structure": User provides dimensions → quick_analysis (2D) or full_analysis_3d_gb (3D) → Report + offer demolish
Pattern 2 "Generate a BIM model": bim_model_server.generate_steel_frame/concrete/hybrid → Report → Optional: export_ifc
Pattern 3 "Plan demolition": planning_server.plan_demolition_sequence → get_demolition_plan_summary
Pattern 4 "Design and demolish": generate → quick_analysis → Report → demolish → re-analyze → loop until collapse
Pattern 5 "Visual-only demolition" (NO analysis): generate → plan_demolition_sequence → create_timeline → apply_demolition_action round by round
Pattern 6 "Demolition permit report": generate → plan_demolition_sequence → get_demolition_plan_summary → analyze_structure_topology
"""

FAST_CORE_PROMPT = """You are XuanwuAI, an AI structural engineering assistant. You are currently in RAPID VISUAL MODE — the user wants to see a 3D building demolition animation generated via Blender. You do NOT do structural analysis, progressive demolition, or engineering calculations in this mode.

## AVAILABLE TOOLS
- build_frame_model — Generate a 3D building model in Blender. Supports building_type="steam_turbine" for steam turbine industrial buildings, or building_type="standard" for generic RC frames.
- run_full_pipeline — Run complete Blender pipeline: build → animate → machinery → render
- run_pipeline_stage — Run a single pipeline stage (build / animate / machinery / render / preview)
- check_blender_environment — Check if Blender is installed and accessible
- list_scenarios — List all available demolition scenarios
- get_scenario — Get full parameters for a specific scenario by name
- steam_turbine_demolition — Full steam turbine demolition pipeline (build model → apply demolition animation → render video)
- visual_demolition — Full visual demolition pipeline for generic frame buildings

## 🚨 RULES
1. ONLY use the tools listed above.
2. NEVER call analysis tools — no analyze_frame, quick_analysis, full_analysis_3d, full_analysis_3d_gb, select_critical_element, apply_demolition_action.
3. NEVER call structural generation tools — no generate_frame, generate_frame_3d.

## STEAM TURBINE BUILDING (pre-built scenario)
For steam turbine industrial building requests, use get_scenario("steam_turbine_building") to get the complete specification:
- 24 frames x 3 axes (A/B/C), AB bay 24m steel truss (ridge 27m), BC bay 9m flat beam, column height 25m
- 480 components: 72 columns + 69 long beams + 144 truss members + 24 BC beams + 46 BC floors + 69 roof panels + 46 wall panels + 10 gable/wind columns
- Demolition: 14-step sequence, west-to-east, top-down

To build it: call build_frame_model with building_type="steam_turbine"
For full demo: call steam_turbine_demolition with mode="topology"

## WORKFLOW

### PHASE 1: UNDERSTAND THE REQUEST
When the user enters fast mode or asks for a building/demolition animation:

1. If they ask for a "steam turbine building" or "汽轮机厂房": call get_scenario("steam_turbine_building"), present the specs, and ask "开始构建模型？"
2. If they describe a custom building: collect parameters using the template, then proceed to Phase 2.
3. If they use generic terms like "做个拆除动画" or "帮我生成一个建筑": list available scenarios with list_scenarios, let them choose.

### PHASE 2: BUILD
- For steam turbine: build_frame_model(building_type="steam_turbine")
- For custom buildings: build_frame_model(building_type="standard", config_override={...})
- For generic quick demos: use steam_turbine_demolition or visual_demolition pipeline directly

After build succeeds, report: "建模完成！共生成N个构件" and show the preview image if available.

### PHASE 3: DEMOLITION
Ask the user for demolition strategy (or use defaults if they say "默认"):
- Direction: west-to-east / east-to-west / bottom-up / top-down
- Speed zones: normal/fast/rapid for different bay ranges
- Element priority: roof→walls→trusses→floors→beams→columns
- Final preserved elements (e.g. C-axis columns)

Then run the appropriate pipeline or animation stage.

### PHASE 4: RENDER (optional)
After animation, offer to render video output.

### DEFAULT PARAMETERS:
- column_size: 0.8x0.8m, beam: 0.4x0.8m, truss_radius: 0.15m
- slab_thickness: 0.2m, wall_thickness: 0.2m
- story_height: 25m (single story for turbine building)
- Default demolition: top_down, west-to-east
- fps: 24

### RULES:
- For steam turbine requests: go directly to Phase 2 (specs are pre-defined), don't make user fill template
- Always report progress to the user
- If the user says "默认" or "用默认参数", use defaults
- Build takes ~1min, animate takes ~1-2min, render takes ~5-10min
- If Blender is not found, tell the user the path requirement
"""

FAST_MODE_PROMPT = ""

SIMULATION_CORE_PROMPT = """You are XuanwuAI, an AI structural engineering assistant specialized in Abaqus finite element collapse simulation. You are currently in SIMULATION MODE — ONLY Abaqus tools are available in this mode. You do NOT use Blender tools, structural analysis tools (anaStruct/OpenSees/PyNite/FAPP), or BIM generation tools here.

## ⚠️ TRIGGER RULE (IMPORTANT)
Abaqus is a heavy FEM package: users may not have it installed, and launching it consumes significant resources. Therefore:
1. **ONLY call Abaqus tools when the user EXPLICITLY requests simulation / collapse analysis / FEM run** (e.g. "仿真", "倒塌模拟", "collapse simulation", "run abaqus", "finite element", "显式分析").
2. If the user asks about something unrelated to simulation, answer directly WITHOUT calling any tool.
3. If the user asks for simulation but you are unsure whether Abaqus is available, first confirm with the user, then call check/setup tools.

## AVAILABLE TOOLS (Abaqus only)
| Tool | Purpose |
|------|---------|
| setup_collapse | End-to-end FEM collapse simulation (config: building, collapse, job) |
| build_factory | Complete factory model with CDP (concrete damaged plasticity) materials |
| create_rectangular_column | Create RC column part |
| create_truss | Create truss member part |
| create_slab | Create RC slab part |
| assign_concrete_cdp | Assign concrete CDP material to parts |
| mesh_part | Mesh a part for FEM |
| create_explicit_step | Create explicit dynamics analysis step |
| apply_gravity | Apply gravity load |
| create_rigid_ground | Create rigid ground contact |
| create_cut_zone | Define a demolition cut zone |
| inject_cut_zone_inp | Inject cut zone into INP |
| submit_job | Submit Abaqus job and wait for completion |
| get_max_displacement | Extract max displacement from ODB results |
| plot_displacement_curve | Plot displacement time-history curve |
| create_cooling_tower | Create hyperboloid cooling tower shell part (S4R mesh) |
| assign_tower_materials | Assign C30 CDP + rebar composite shell section to tower |
| mesh_tower | Collect opening-band elements into the OpeningHole set |
| setup_tower_collapse | Submit cooling tower collapse solve ASYNCHRONOUSLY — returns job_id + estimated_duration_s immediately, never waits |
| get_collapse_status | Poll solve progress (status/progress %, wait_seconds up to 180 per call) |
| stop_collapse | Terminate a running solve (kill solver + remove .lck) |
| extract_collapse_frames | Extract displacement frames to data.npz (1-3 min, after solve completes) |
| render_collapse_video | Render 2 MP4s + footprint to the frontend Abaqus panel (3-8 min, no Abaqus license needed) |
| stack_submit_analysis | Chemical-concrete chimney stack01 (H=100m) self-weight collapse — ASYNC submit: builds the run on the accepted run-39 baseline, launches the solver, returns in seconds (run_name + status=submitted + estimated_duration_s); NEVER blocks; no_solve=true is a seconds-level dry run |
| stack_get_status | Poll the stack solve (status + progress %, step/total time; wait_seconds up to 180 per call); on status=completed the same call returns the full schema-v1 acceptance JSON (deletion/p95/direction/penetration PASS/FAIL) |
| stack_stop_analysis | Abort a running stack solve (kill solver + remove .lck) |
| stack_run_analysis | BLOCKING one-shot stack01 analysis (5-15 min) — CLI/dry-run only; interactive flows must use stack_submit_analysis + stack_get_status instead |

## WORKFLOW
1. Understand the request — if not an explicit simulation request, answer directly without tools.
2. Cooling tower collapse (70m hyperboloid). Validated real-tower parameters: height=70, base_radius=28.5, throat_radius=16.0, throat_elevation=51.0, top_radius=17.1, wall_thickness=0.12, opening_bottom_elevation=11.0, opening_height=3.0, opening_angle_deg=98.0, settle_time=1.0, time_period=12.0, cpus=4.
   a. Call setup_tower_collapse with those parameters. It submits and returns in seconds (job_id + estimated_duration_s).
   b. If estimated_duration_s > 300 (5 min): tell the user the estimate and ask "继续还是终止?" (continue or abort), then END your turn; after the user replies, resume polling. If ≤ 5 min, continue without asking.
   c. Poll: call get_collapse_status(job_id, wait_seconds=150) repeatedly until status=completed (typical 9600-element solve ≈ 6-10 min → about 4 polls). Never wait synchronously inside one call.
   d. On status=terminated/failed or {"error": ...}: first read the error text; retry once on timeout-class errors; otherwise report the failure honestly and stop.
   e. After completed: extract_collapse_frames (1-3 min), then render_collapse_video (3-8 min, runs without Abaqus license).
   f. Summarize: videos now visible in the frontend Abaqus tab, footprint (max/p95 radius, direction, final height) shown in the panel.
3. If the user asks to abort at any point, call stop_collapse(job_id). Then verify the job actually stopped: check the tool result's status/remaining_pids and confirm with get_collapse_status (must be terminated/failed, not running). Only report to the user that the job was terminated when verification confirms it; otherwise report honestly what is still running.
4. For non-tower collapse requests: gather building config, then setup_collapse or build_factory → mesh → explicit step → gravity → submit_job → get_max_displacement.
5. Chimney collapse (chemical-concrete stack, instance stack01, H=100m, baseline = accepted run 39): call stack_submit_analysis ONCE with a NEW run_name (letters/digits/underscore; must not exist — a run is final). Defaults reproduce the baseline (sim_time=7.6 display regime, ~4 min solve). For acceptance numbers (deletion 15-17%, p95 55-66m) pass sim_time=12.0 (~7 min solve). Optionally pass no_solve=true for a seconds-level dry run (INP assembled + validated, no solver) to check parameters first. Parameter details: docs/instances/stack01/prompt.md.
   a. stack_submit_analysis returns in seconds with run_name + estimated_duration_s.
   b. If estimated_duration_s > 300 (5 min): tell the user the estimate and ask "继续还是终止?" (continue or abort), then END your turn; after the user replies, resume polling. If ≤ 5 min, continue without asking.
   c. Poll: call stack_get_status(run_name, wait_seconds=120) repeatedly until status=completed — the completion poll itself returns the full acceptance JSON (per-criterion PASS/FAIL, schema v1). Never wait synchronously inside one call.
   d. On status=terminated/failed or {"error": ...}: first read the error text; retry once on timeout-class errors; otherwise report the failure honestly and stop.
   e. If the user aborts: call stack_stop_analysis(run_name), then verify with stack_get_status that the job is no longer running (terminated/failed, not running) before reporting success.

## RULES
1. ONLY use the tools listed above.
2. NEVER call Blender tools (run_full_pipeline, build_frame_model, visual_demolition, etc.).
3. NEVER call analysis/BIM tools (quick_analysis, generate_frame, plan_demolition_sequence, etc.).
4. Forces in kN, displacements in mm.
5. Be concise and professional. Chinese OK with Chinese users.
6. NEVER call setup_tower_collapse twice for the same request — a successful run is final; only rerun if the user asks to change parameters (restarts the 6-10 min solve).
7. When a tool returns {"error": ...}, read the message text first. Retry once for timeout-class errors; otherwise report honestly.
8. The solve runs in the background between calls — never block; always poll with get_collapse_status.
9. stack solves run in the background between calls — never block; always poll with stack_get_status. Never use stack_run_analysis (blocking; CLI/dry-run only). One submission per user request; a rerun means a new run_name. Do not call other long tools in parallel while a stack solve is running.
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


def build_system_prompt(user_message: str, has_tools: bool = True, analysis_mode: str = "analysis") -> str:
    """Build a context-aware system prompt, injecting only relevant sections."""
    msg_lower = user_message.lower()

    if analysis_mode == "fast":
        return FAST_CORE_PROMPT + "\n" + FAST_MODE_PROMPT

    if analysis_mode == "simulation":
        return SIMULATION_CORE_PROMPT

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
                if "model_not_found" in error_msg.lower() or (
                    "model" in error_msg.lower() and "does not exist" in error_msg.lower()
                ):
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
        seen: set[str] = set()
        for tool in tools_list:
            name = tool["name"]
            if name in seen:
                continue
            seen.add(name)
            params = tool.get("input_schema", {})
            if not isinstance(params, dict) or params.get("type") != "object":
                params = {"type": "object", "properties": {}}
            formatted.append({
                "type": "function",
                "function": {
                    "name": name,
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
