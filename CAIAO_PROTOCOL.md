# CAIAO Protocol — Complete Reference

> **Single source of truth for all CAIAO-related matters.**
> Every CAIAO change MUST update this document (enforced by CLAUDE.md).

---

## 1. What is CAIAO?

CAIAO is the project-specific naming layer built on top of the standard [MCP (Model Context Protocol)](https://modelcontextprotocol.io) SDK. Every CAIAO Server is technically an MCP Server — the Python `mcp` package handles stdio transport and JSON-RPC. We rename the abstraction to distinguish our project's convention from the generic protocol.

### Core Philosophy

```
Everything is a CAIAO Server.
The LLM talks to the CAIAO Hub, never directly to tools.
```

CAIAO Server = minimum atomic unit in the system, analogous to an LLM **token**.
Just as LLMs compose tokens into meaning, we compose CAIAO Servers into engineering workflows.

---

## 2. Core Principles

### P1: Server Independence

**Every CAIAO Server is fully independent.** No server depends on another server's runtime. Dependencies are only by importing pure logic (functions, classes) from another server's module — never by requiring another server process to be running.

| Do | Don't |
|----|-------|
| Import `_analyze_structure()` from `anastruct_server.server` | Require `anastruct_server` subprocess to be alive |
| Copy + own the logic if coupling becomes tight | Share mutable state across servers |
| Create a merged server that imports multiple servers' logic | Modify an existing server to serve a new merged server |

### P2: Server as Atomic Unit

A CAIAO Server is the minimum deployable unit:
- It runs as its own stdio subprocess
- It exposes tools via `list_tools()` / `call_tool()`
- It can be started eagerly (gateway init) or lazily (first tool call)
- One crash never cascades — the hub restarts or reports the failure

### P3: Merge, Don't Modify

When a sequence of servers is used repeatedly, **merge them into a new independent server** by importing their logic. Never modify the original servers to serve the merge.

```
# Correct:
quick_analysis_server imports from frame_generator.core + anastruct_server.server
→ new subprocess, independent

# Wrong:
Modify anastruct_server to include frame generation
→ breaks the atomicity of anastruct_server
```

### P4: Extract Only When ROI Justifies

If multiple servers share common logic:
1. First occurrence: inline it
2. Second occurrence: still inline it
3. Third occurrence: evaluate ROI of extracting into a shared module
4. Only extract if the shared logic is non-trivial and stable

Don't create shared abstractions "just in case."

---

## 3. CAIAO vs MCP SDK

| Layer | What it is | In our project |
|-------|-----------|----------------|
| **MCP SDK** | Python package `mcp>=1.0.0` | `from mcp.server import Server` in server.py |
| **MCP stdio transport** | JSON-RPC over stdin/stdout | `stdio_server()` handles serialization |
| **CAIAO Server** | Our project's concept of a tool server | Every `caiao_servers/<name>/server.py` |
| **CAIAO Client Hub** | Our multi-server lifecycle manager | `gateway/caiao_hub.py` → `CAIAOClientHub` |

The MCP SDK is an **implementation detail** — developers only need to follow the CAIAO contract below.

---

## 4. Server Lifecycle

```
Gateway start
  │
  ├─ For each SERVER_CONFIGS entry:
  │    ├─ "lazy": True   → skip, register tool name for on-demand start
  │    ├─ "composite": True → register local handler, no subprocess
  │    └─ default        → _start_one(): spawn subprocess → list_tools → register
  │
  ├─ AgentLoop needs a tool
  │    ├─ Local handler? → execute inline (composite pipelines)
  │    ├─ Server running? → route to session
  │    ├─ Server lazy?   → _ensure_server(): spawn subprocess → list_tools → route
  │    └─ Not found?     → semantic fallback (fuzzy name match)
  │
  └─ Gateway shutdown
       └─ Terminate all subprocess sessions
```

### Lazy vs Eager

| Type | When it starts | Use for |
|------|---------------|---------|
| **Eager** (no `lazy` key) | Gateway init | Lightweight, always-needed servers (anaStruct, frame_generator, quick_analysis) |
| **Lazy** (`lazy: True`) | First tool call | Heavyweight solvers (OpenSees, PyNite, FAPP, Unity) |
| **Composite** (`composite: True`) | No subprocess | Gateway-level orchestration pipelines |

---

## 5. Creating a CAIAO Server

### Step 1: Create the server file

```python
# caiao_servers/my_solver/server.py
"""My Solver CAIAO Server — purpose statement."""

import json
from mcp.server import Server
import mcp.types as types
from mcp.server.models import InitializationOptions

server = Server("my_solver")

@server.list_tools()
async def list_tools():
    return [types.Tool(
        name="my_tool",
        description="What this tool does",
        inputSchema={
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "..."},
            },
            "required": ["param1"],
        },
    )]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "my_tool":
        raise ValueError(f"Unknown tool: {name}")
    result = {"status": "ok", "result": "processed"}
    return [types.TextContent(type="text", text=json.dumps(result))]

if __name__ == "__main__":
    from mcp.server.stdio import stdio_server
    import anyio
    anyio.run(stdio_server, server, InitializationOptions(
        server_name="my_solver", server_version="0.1.0",
    ))
```

Or copy the template: `caiao_servers/_template/server.py`

### Step 2: Register in gateway

```python
# gateway/main.py → SERVER_CONFIGS
{
    "name": "my_solver",
    "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
    "args": ["server.py"],
    "cwd": os.path.join(CAIAO_SERVERS_DIR, "my_solver"),
    "tools": ["my_tool"],
    "lazy": True,  # optional, for heavyweight solvers
},
```

### Step 3: Update this document

Add the server to §8 Server Registry below.

---

## 6. The Server Merge Pattern

The most powerful pattern in the CAIAOServerizer paradigm: composing multiple atomic servers into a **merged server** that does everything in one subprocess call.

### When to Merge

A merge is justified when the same sequence of server calls appears repeatedly in the workflow. The canonical example was Pipeline A:

```
# Before: 3 subprocess hops
generate_frame → analyze_frame → select_critical_element

# After: 1 subprocess hop
quick_analysis (atomic merged server)
```

### Merge Rules

1. **Import logic, never require the source server process.** The merged server imports functions/classes from existing server modules — it never depends on those servers running.
2. **Never modify the source servers.** The atomic servers remain independent and unchanged.
3. **Return a unified result.** The merged server's tool returns everything the frontend needs in one response.
4. **Keep the old servers.** Atomic servers stay available for users who need them individually.

### Merge Template

```python
# caiao_servers/my_merged_server/server.py
import sys, os
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from server_a.core import step_one
from server_b.server import step_two

def _run_pipeline(args):
    result1 = step_one(args)
    result2 = step_two(result1)
    return {"merged": result1, "result": result2}
```

---

## 7. Server Independence Principle (Detailed)

This principle governs ALL CAIAO Server relationships.

### What "Independent" Means

| Aspect | Independent Server | Not Independent |
|--------|-------------------|----------------|
| Process | Own subprocess, own stdio | Shares process with another server |
| Lifecycle | Start/stop independently | Depends on another server's lifecycle |
| Data | Carries own data or imports pure functions | Reads another server's runtime state |
| Failure | Crash doesn't affect others | One crash cascades |

### Merge ≠ Dependency

A merged server imports **pure logic** from source servers at import time. This is compile-time/dependency coupling, not runtime coupling:

```
quick_analysis_server
  ├── import FrameGenerator from frame_generator.core  ✅  pure class
  ├── import _analyze_structure from anastruct_server   ✅  pure function
  └── runs in its own subprocess                        ✅  independent
```

If `frame_generator.core` has a breaking change, `quick_analysis_server` needs to be updated — but it doesn't crash at runtime because `frame_generator` crashed. That's the difference between **code dependency** (acceptable, managed through imports) and **runtime dependency** (forbidden).

### Common Pattern Evaluation

| Pattern | ROI | Decision |
|---------|-----|----------|
| Shared steel section database | Medium (3+ servers need it) | Extract to `caiao_servers/shared/sections.py` if 3rd consumer appears |
| Shared coordinate conversion | Low (trivial math) | Inline in each server |
| Shared OpenSees result parser | Medium | Currently only one server uses it — wait |
| Unified frame conversion (3d → analysis) | High (enables merge #2) | Embed in the merged server, don't extract yet |

---

## 8. Server Registry

| Server | Kind | Tools | Status | Since |
|--------|------|-------|--------|-------|
| `quick_analysis_server` | ⚡ Merged | `quick_analysis` | Active | 2026-05-25 |
| `full_analysis_3d_server` | ⚡ Merged | `full_analysis_3d` | Active | 2026-05-25 |
| `anastruct_server` | Atomic | `generate_simple_frame`, `analyze_frame`, `select_critical_element` | Active | — |
| `frame_generator` | Atomic | `generate_frame`, `generate_frame_3d`, `generate_from_text`, `list_materials` | Active | — |
| `opensees_server` | Atomic | `high_fidelity_analysis` | Active (lazy) | — |
| `pynite_server` | Atomic | `pynite_analysis` | Active (lazy) | — |
| `fapp_server` | Atomic | `fapp_analysis` | Active (lazy) | — |
| `unity_simulator` | Atomic | `apply_demolition_action`, `modify_structure`, `get_structure_status`, `get_removed_elements` | Active (lazy) | — |
| `animation_control_server` | Atomic | `create_timeline`, `get_timeline_state`, `sequence_to_animation_data`, `generate_effects_config` | Active | 2026-05-31 |
| `planning_server` | Atomic | `plan_demolition_sequence`, `analyze_structure_topology`, `get_demolition_plan_summary`, `compute_collapse_chain` | Active | 2026-05-31 |
| `comparison_server` | Atomic | `compare_demolition_strategies`, `get_comparison_summary`, `recommend_strategy` | Active (lazy) | 2026-05-31 |
| `run_full_analysis` | Composite | (pipeline) | Legacy | — |
| `manager_server` | Atomic | 24 tools: create/list/validate servers, health/metrics, search, dependency analysis, merge detection | Active | 2026-05-31 |
| `blender_build_server` | Atomic | `build_frame_model` | Active (lazy) | 2026-06-03 |
| `blender_animate_server` | Atomic | `apply_demolition_sequence` | Active (lazy) | 2026-06-03 |
| `blender_machinery_server` | Atomic | `add_construction_machinery` | Active (lazy) | 2026-06-03 |
| `blender_render_server` | Atomic | `render_animation`, `render_preview` | Active (lazy) | 2026-06-03 |
| `blender_pipeline_server` | Atomic | `run_full_pipeline`, `run_pipeline_stage`, `check_blender_environment` | Active (lazy) | 2026-06-03 |

### Server Details

#### ⚡ `quick_analysis_server` — Pipeline A (First Merge)

- **Merges:** `generate_frame` + `analyze_frame` + `select_critical_element`
- **Importing from:** `frame_generator.core`, `anastruct_server.server`
- **Lazy:** No
- **Creation:** 2026-05-25
- **Significance:** First manual server merge in CAIAOServerizer paradigm

#### ⚡ `full_analysis_3d_server` — Pipeline B (Second Merge)

- **Merges:** `generate_frame_3d` → `convert_to_unified_frame` → `pynite_analysis` → `select_critical_3d`
- **Importing from:** `frame_generator.core`, `pynite_server.server`
- **Key innovation:** `convert_to_unified_frame` bridges the gap between 3D geometry format (columns/beams/slabs) and topology format (nodes/elements/loads/supports). Coordinate remap: `[x, z_vert, y_horiz]` → `{x, y, z}`.
- **Lazy:** No
- **Creation:** 2026-05-25
- **Significance:** Second CAIAOServerizer server merge. Enables true 3D structural analysis with XY grid support.

#### `anastruct_server` — Fast 2D Linear Analysis

- **Engine:** anaStruct (Python)
- **Tools:**
  - `generate_simple_frame` — Simple 2D frame grid generation
  - `analyze_frame` — 2D linear elastic frame analysis
  - `select_critical_element` — Column with highest axial force
- **Lazy:** No
- **Data format:** `{nodes, elements, loads, supports}` (FrameStructure)

#### `frame_generator` — Parametric Frame Generation

- **Tools:**
  - `generate_frame` — 2D analysis-ready frame (nodes+elements+loads+supports)
  - `generate_frame_3d` — 3D visualization geometry (columns+beams+slabs)
  - `generate_from_text` — Natural language frame generation
  - `list_materials` — Steel/concrete property tables
- **Lazy:** No
- **Note:** `generate_3d()` output now includes `E, A, Iy, Iz, J` on columns and beams

#### `opensees_server` — High-Fidelity 2D Analysis

- **Engine:** OpenSeesPy
- **Lazy:** Yes
- **Tool:** `high_fidelity_analysis`
- **Limitation:** Windows DLL issues — use Linux/macOS/WSL2

#### `pynite_server` — 3D FEM Analysis

- **Engine:** PyNiteFEA
- **Lazy:** Yes
- **Tool:** `pynite_analysis`
- **Format:** `{nodes: [{x,y,z}], elements: [{A,Iy,Iz,J}]}`

#### `fapp_server` — 3D FEM Analysis (Alternative)

- **Engine:** FAPP direct stiffness
- **Lazy:** Yes
- **Tool:** `fapp_analysis`

#### `unity_simulator` — Demolition Physics

- **Bridge to:** Unity 3D via TCP :5005
- **Lazy:** Yes
- **Tools:** Demolition action, structure modification, status queries

#### `animation_control_server` — Animation Timeline Management

- **Purpose:** Manages demolition animation timelines, converts multi-round demolition plans into keyframe-based timelines, and generates effects configurations for the frontend.
- **Lazy:** Yes
- **Tools:**
  - `create_timeline` — Convert demolition plan to keyframe-based timeline with flash/fall/explode/dust/settle phases
  - `get_timeline_state` — Query element state (active/removed/falling/flashing/exploding) at any timestamp
  - `sequence_to_animation_data` — Generate frontend-compatible cascade/debris/dust/impactRings animation data
  - `generate_effects_config` — Build effects config matching frontend EffectKey system (cascade/explosion/dust/shake/buckling/fracture/flash/trail/bounce) with intensity/style presets
- **Presets:** 4 intensity levels (low/medium/high/cinematic), 3 style overlays (realistic/dramatic/technical)

#### `planning_server` — Demolition Sequence Planning

- **Purpose:** Plans demolition step sequences for building structures using rule-based and template-based strategies. Analyzes structural topology (load paths, floor mapping, element dependencies).
- **Lazy:** Yes
- **Strategies:**
  - `top_down` — Remove top floor first: slabs → beams → columns, repeat downward (safest)
  - `bottom_up` — Remove from bottom: columns → beams → slabs, going upward (riskiest)
  - `sequential` — Element by element in ID order
  - `llm` — Template-based smart planning with perimeter/core and floor-aware strategies
- **Tools:**
  - `plan_demolition_sequence` — Generate demolition step sequence with configurable strategy and constraints
  - `analyze_structure_topology` — Build dependency graph, detect primary vs secondary elements, trace critical load paths
  - `get_demolition_plan_summary` — Human-readable text or structured JSON summary of a demolition plan
- **Step format:** Each step includes element_id, element_type, action, description, duration_ms, and visual effects (flash_red, shake, fall_down, debris, dust, crack, sway, collapse_chain, smoke)
- **Constraints:** Supports max_steps cap, skip_element_types filter, and custom_durations overrides

#### `bim_model_server` — BIM Structural Modeling

- **Purpose:** Generates structural geometry models for steel, concrete, and hybrid structures. Exports to industry-standard IFC format.
- **Lazy:** Yes
- **Tools:**
  - `generate_steel_frame` — Steel frame with IPE/HE-A/HE-B section families, Q235-Q420/S235-S355 steel grades, wind loads
  - `generate_concrete_structure` — RC structure with columns, beams, shear walls, slabs; C25-C50 grades
  - `generate_hybrid_structure` — Steel perimeter frame + RC core (configurable core position and span ratio)
  - `export_ifc` — Export to IFC/ifcXML via IfcOpenShell; falls back to JSON summary if not installed
- **Dependencies:** `ifcopenshell` (optional, for IFC export), `numpy`
- **Output format:** Standard `{nodes, elements, loads, supports, materials}` JSON

#### `physics_server` — Rigid Body Physics Simulation

- **Purpose:** Simulates rigid body dynamics for demolition animation (falling elements, collisions, debris).
- **Lazy:** Yes
- **Tools:**
  - `init_physics_scene` — Create physics world from structure nodes/elements
  - `apply_demolition_action` — Apply force or remove bodies from simulation
  - `step_physics` — Step simulation by dt_seconds with substeps
  - `get_physics_state` — Get position, rotation, velocity of bodies
  - `reset_physics` — Reset scene to initial state
- **Engines:**
  - **Primary:** Rapier (Rust-based, high perf) — `pip install rapier`
  - **Fallback:** KinematicSimulator (zero deps, Euler integration with ground collision)
- **State format:** `{element_id, position: [x,y,z], rotation: [x,y,z,w], velocity: [x,y,z]}`

#### `comparison_server` — Multi-Strategy Demolition Plan Comparison

- **Purpose:** Compares all 4 demolition strategies (top_down, bottom_up, sequential, llm) and provides scoring, ranking, and recommendations.
- **Lazy:** Yes
- **Tools:**
  - `compare_demolition_strategies` — Generate ALL 4 strategies for a structure, compute quality scores (safety, efficiency, visual), and return ranked comparison data
  - `get_comparison_summary` — Human-readable comparison table with rankings, scores, and per-strategy details
  - `recommend_strategy` — Rule-based recommendation engine: low-stress (<0.3)->sequential, high-stress (>0.8)->top_down, irregular (>0.5)->llm, low-rise (<4 floors)->bottom_up
- **Importing from:** `planning_server.rule_planner`, `planning_server.llm_planner` (pure functions, no process dependency)
- **Scoring:** safety_score (0-100), efficiency_score (0-100), visual_score (0-100), weighted recommendation_score (safety=0.5, efficiency=0.3, visual=0.2)

#### `run_full_analysis` — Composite Pipeline (Legacy)

- **Type:** Gateway-level orchestration (no subprocess)
- **Pipeline:** `generate_frame → analyze_frame → select_critical_element`
- **Status:** Legacy — replaced by `quick_analysis_server` for new work

#### `manager_server` — CAIAO Server Manager (Meta-Server)

- **Purpose:** Manage all CAIAO servers — creation, extension, enhancement, migration, retrieval, orchestration
- **Kind:** Atomic MCP Server (starts eagerly at gateway init)
- **Lazy:** No
- **Tools (24):**
  - **Creation (4):** `create_server`, `list_archetypes`, `generate_manifest`, `validate_server`
  - **Extension (4):** `add_tool`, `update_tool`, `remove_tool`, `add_import`
  - **Enhancement (4):** `health_check`, `get_metrics`, `restart_server`, `configure_health`
  - **Migration (4):** `rename_server`, `bump_version`, `archive_server`, `migrate_to_manifest`
  - **Retrieval (5):** `search_capabilities`, `list_servers`, `get_server`, `find_tool_owner`, `build_search_index`
  - **Orchestration (3):** `detect_merge_opportunities`, `analyze_dependency_graph`, `suggest_pipeline`
- **Architecture:** The manager is itself a CAIAO server (dogfooding). It operates through `caiao.yaml` manifest files — the manager writes manifests, the gateway auto-discovers them via `caiao_config.py`. Health/metrics data comes from hub REST endpoints.
- **Creation:** 2026-05-31
- **Significance:** The highest-dimension CAIAO server — it manages the ecosystem that manages it. Enables self-service server creation, health monitoring, semantic search, and automated merge detection.

#### `blender_build_server` — Procedural Frame Modeling (Blender)

- **Engine:** Blender 4.2+ (bpy)
- **Lazy:** Yes
- **Tool:** `build_frame_model`
- **Output:** `scene_base.blend` with 139 individual elements, each carrying 8 metadata properties (element_type, floor, grid_x/y, bay_x/y, importance, label_cn)
- **Config:** `blender_pipeline/data/project_config.json`
- **Creation:** 2026-06-03

#### `blender_animate_server` — Demolition Animation Keyframing (Blender)

- **Engine:** Blender 4.2+ (bpy)
- **Lazy:** Yes
- **Tool:** `apply_demolition_sequence`
- **Input:** `scene_base.blend`
- **Output:** `scene_animated.blend` + `computed_demolition_schedule.csv`
- **Logic:** Metadata-driven sorting (floor→importance→type→position) → grouping → visibility/scale/location keyframes
- **Creation:** 2026-06-03

#### `blender_machinery_server` — Construction Machinery Addition (Blender)

- **Engine:** Blender 4.2+ (bpy)
- **Lazy:** Yes
- **Tool:** `add_construction_machinery`
- **Input:** `scene_animated.blend`
- **Output:** `scene_final.blend` (with excavator + dump truck models)
- **Creation:** 2026-06-03

#### `blender_render_server` — Animation Rendering (Blender)

- **Engine:** Blender 4.2+ (OpenGL viewport + Workbench)
- **Lazy:** Yes
- **Tools:** `render_animation` (MP4 via OpenGL viewport), `render_preview` (fast white-model via Workbench)
- **Input:** `scene_final.blend` (or any animated .blend)
- **Output:** MP4 video (H.264, 1280×720, 24fps)
- **Creation:** 2026-06-03

#### `blender_pipeline_server` — Full Pipeline Orchestrator

- **Purpose:** Chains build → animate → machinery → render into a single end-to-end workflow
- **Lazy:** Yes
- **Tools:**
  - `run_full_pipeline` — Complete end-to-end pipeline with configurable stages (machinery on/off, render on/off)
  - `run_pipeline_stage` — Execute a single stage independently (build/animate/machinery/render/preview)
  - `check_blender_environment` — Verify Blender installation and pipeline file availability
- **Pipeline flow:** generate_building.py → apply_demolition.py → add_machinery.py → render.py
- **Creation:** 2026-06-03

---

## 9. Merge Roadmap

| # | Merge | Atomic Servers Involved | Status |
|---|-------|-------------------------|--------|
| 1 | **Quick Analysis** (Pipeline A) | generate_frame + anastruct.analyze + anastruct.select_critical | ✅ **Done** 2026-05-25 |
| 2 | **3D Full Analysis** (Pipeline B) | generate_frame_3d → convert_to_unified_frame → pynite_analysis → select_critical_3d | ✅ **Done** 2026-05-25 |
| 3 | **Verify Suite** | anastruct + opensees + pynite + fapp → consensus | 📋 Planned |
| 4 | **Demolition Cycle** | apply_demolition + analyze + select_critical | 📋 Planned |

### Merge #2 Details (Done 2026-05-25)

**Implementation:** `caiao_servers/full_analysis_3d_server/server.py`

```
generate_frame_3d → convert_to_unified_frame → pynite_analysis → select_critical_3d
                         │
                         └→ UnifiedFrame (internal converter) {
                              nodes: [{id, x, y, z}],
                              elements: [{id, node_i, node_j, A, Iy, Iz, J, E, type, original_id}],
                              loads: [{node_id, Fx, Fy, Fz}],
                              supports: [{node_id, type}],
                              dimension: "3d",
                            }

convert_to_unified_frame (embedded in the merged server):
  - Remap coordinates: geometry [x, z_vert, y_horiz] → analysis {x, y, z}
  - Deduplicate nodes at beam-column joints (mm precision)
  - Convert geometry {columns[], beams[]} → topology {nodes[], elements[]}
  - Transfer section properties (E, A, Iy, Iz, J) from geometry to elements
  - Generate default loads and supports based on config
  - Includes unit tests: 14 tests (all pass) covering topology, coords, analysis, critical selection
```

---

## 10. Naming Conventions

| Context | Convention | Example |
|---------|-----------|---------|
| Class name | `CAIAO` + PascalCase | `CAIAOClientHub` |
| Constant | `CAIAO_` + UPPER_SNAKE | `CAIAO_SERVERS_DIR` |
| Filename | `caiao_` + lowercase | `caiao_hub.py` |
| Directory | `caiao_servers/` | `caiao_servers/anastruct_server/` |
| Config server name | lowercase | commit scope `caiao` |
| SDK imports | keep `from mcp.server import Server` | external package, not our naming |
| Tool names | `snake_case` | `quick_analysis`, `analyze_frame` |
| Return format | JSON in `TextContent` | `json.dumps({"status": "ok"})` |

---

## 11. Contract Rules

1. **Always return `[TextContent(type="text", text=json.dumps(...))]`** — never raw strings
2. **Serialize everything as JSON** — the Gateway extracts `result` from the JSON string
3. **Catch all exceptions** and return `{"error": str(e)}` — never crash the subprocess
4. **Tool names use `snake_case`** — consistent with Python conventions
5. **Input schema is JSON Schema** — the LLM uses it to generate correct arguments
6. **Non-lazy servers must start fast** — no heavy imports at module level
7. **Lazy servers must degrade gracefully** — if dependency missing, return `{"error": "unavailable"}`

---

## 12. Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-05-25 | Created CAIAO_PROTOCOL.md with full reference | Claude |
| 2026-05-25 | Added `quick_analysis_server` — first server merge | Claude |
| 2026-05-25 | Added Server Independence Principle (P1-P4) | Claude |
| 2026-05-25 | Registered all 8 servers in Server Registry | Claude |
| 2026-05-25 | Added `full_analysis_3d_server` — second server merge (Merge #2, Pipeline B) | Claude |
| 2026-05-25 | UnifiedFrame converter: generate_3d geometry → topology format for 3D analysis | Claude |
| 2026-05-31 | Added `animation_control_server` — demolition animation timeline management with effects presets (4 intensities, 3 styles), keyframe state query, and frontend-compatible animation data export | Claude |
| 2026-05-31 | Added `planning_server` — demolition sequence planning (top_down, bottom_up, sequential, llm strategies), structural topology analysis (load paths, dependency graph, floor mapping), and plan summary generation | Claude |
| 2026-05-31 | Added `bim_model_server` — structural BIM generation with steel frames (IPE/HE-A/HE-B), RC structures (C25-C50), hybrid steel-concrete, and IFC export via IfcOpenShell | Claude |
| 2026-05-31 | Added `physics_server` — rigid body physics simulation with Rapier (high perf) / kinematic fallback (zero deps), including init/step/force/reset tools | Claude |
| 2026-05-31 | Added `DemolitionController` and `IFCViewer` frontend components; updated frontend with web-ifc and cannon-es packages | Claude |
| 2026-05-31 | All new servers registered in Gateway; SYSTEM_PROMPT updated with tool descriptions | Claude |
| 2026-05-31 | Added `comparison_server` — multi-strategy demolition plan comparison, scoring (safety/efficiency/visual), ranking, and rule-based strategy recommendation (low-stress->sequential, high-stress->top_down, irregular->llm, low-rise->bottom_up) | Claude |
| 2026-05-31 | Added `manager_server` — meta-server managing all 15 CAIAO servers with 24 tools across 6 groups (creation, extension, enhancement, migration, retrieval, orchestration). Introduced `caiao.yaml` manifest format, `caiao_config.py` auto-discovery, hub state machine, and frontend management dashboard | Claude |

---

**Related documents:** `ARCHITECTURE.md` (CAIAO bus technical detail), `CLAUDE.md` (project instructions), `dev-notes/architecture/2026-05-25-caiaoserverizer-first-merge.md` (first merge record)
