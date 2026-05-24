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
| `run_full_analysis` | Composite | (pipeline) | Legacy | — |

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

#### `run_full_analysis` — Composite Pipeline (Legacy)

- **Type:** Gateway-level orchestration (no subprocess)
- **Pipeline:** `generate_frame → analyze_frame → select_critical_element`
- **Status:** Legacy — replaced by `quick_analysis_server` for new work

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

---

**Related documents:** `ARCHITECTURE.md` (CAIAO bus technical detail), `CLAUDE.md` (project instructions), `dev-notes/architecture/2026-05-25-caiaoserverizer-first-merge.md` (first merge record)
