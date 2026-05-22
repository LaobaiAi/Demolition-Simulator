# Contributing to XuanwuAI Demolition Simulator

## Table of Contents

1. [Project Architecture](#project-architecture)
2. [Development Setup](#development-setup)
3. [Branch Strategy](#branch-strategy)
4. [Commit Convention](#commit-convention)
5. [Code Style](#code-style)
6. [Pull Request Process](#pull-request-process)
7. [Testing](#testing)
8. [Project-Specific Conventions](#project-specific-conventions)

---

## Project Architecture

```
frontend/          Next.js 16 SPA (TypeScript + Tailwind CSS + shadcn/ui)
gateway/           FastAPI + Agent Loop + MCP Hub (Python)
mcp_servers/       MCP tool servers (stdio subprocesses)
  anastruct_server/    2D frame generation + linear analysis
  opensees_server/     High-fidelity nonlinear analysis
  unity_simulator/     TCP relay to Unity 3D physics engine
unity_project/     Unity 3D C# scripts (SimulationController, FrameBuilder)
```

**Data flow**: User input → WebSocket → Gateway AgentLoop (ReAct) → LLM → MCP tools → Results stream back → Frontend SVG + metrics + demolition

---

## Development Setup

### Prerequisites

- Node.js 20+
- Python 3.11+
- Unity 2022.3+ (optional, for 3D simulation)

### Backend (Gateway + MCP Servers)

```bash
cd gateway
python -m venv venv
source venv/Scripts/activate  # Windows
pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm install
```

### Run Development

```bash
# Terminal 1 — Gateway (port 8000)
cd gateway && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Frontend (port 3000)
cd frontend && npm run dev
```

---

## Branch Strategy

| Branch type | Pattern | Purpose |
|---|---|---|
| `master` | — | Production-ready, always deployable |
| Feature | `feature/<slug>` | New capabilities (e.g., `feature/nonlinear-pushover`) |
| Fix | `fix/<slug>` | Bug fixes (e.g., `fix/tool-result-wrapping`) |
| Refactor | `refactor/<slug>` | Code restructuring, no behavior change |

**Rules**:
- Branch from `master`, merge back to `master`
- Keep branches short-lived (< 3 days ideal)
- Rebase on `master` before opening a PR
- Never force-push to `master`

---

## Commit Convention

This project enforces **[Conventional Commits 1.0.0](https://www.conventionalcommits.org/)** with project-specific scopes.

### Format

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types

| Type | Usage |
|---|---|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `refactor` | Code restructuring without behavior change |
| `style` | Formatting, whitespace, semicolons (no logic change) |
| `docs` | Documentation only |
| `test` | Adding or updating tests |
| `chore` | Tooling, dependencies, build scripts |
| `perf` | Performance improvement |

### Scopes

| Scope | Applies to |
|---|---|
| `gateway` | FastAPI backend (`gateway/`) |
| `agent` | Agent loop logic (`gateway/agent_loop.py`) |
| `llm` | LLM engine (`gateway/llm_engine.py`) |
| `mcp` | MCP hub or any MCP server (`gateway/mcp_hub.py`, `mcp_servers/`) |
| `anastruct` | anaStruct MCP server (`mcp_servers/anastruct_server/`) |
| `opensees` | OpenSees MCP server (`mcp_servers/opensees_server/`) |
| `unity` | Unity simulator MCP server or Unity C# scripts |
| `frontend` | Next.js frontend — general |
| `viz` | Visualization components (`frame-visualization.tsx`) |
| `chat` | Chat panel, WebSocket client |
| `ui` | UI primitives, shadcn components, styling |
| `i18n` | Internationalization, translations |
| `settings` | LLM config, language toggle, localStorage |
| `ci` | GitHub Actions, CI/CD |
| `docs` | Documentation (README, CONTRIBUTING, etc.) |

### Examples

```bash
# New feature
feat(anastruct): add node displacement mapping to original structure IDs

# Bug fix
fix(agent): unwrap hub result before sending to frontend WebSocket

# Frontend UI change
feat(ui): replace X logo with diagonal 玄武 SVG text

# Documentation
docs: add CONTRIBUTING.md with commit conventions and code style

# Refactor
refactor(gateway): persist LLM config to llm_config.json for restart survival

# Test
test(anastruct): add coordinate-mapping test for 0-based node IDs

# Multi-scope (use comma)
feat(gateway,frontend): add global Chinese/English language switching
```

### Rules

1. **Type and scope are mandatory** — every commit must include both
2. **Description in English**, imperative mood, lowercase, no period at end
3. **Description ≤ 72 characters**
4. **One logical change per commit** — don't mix unrelated fixes
5. **Body optional but encouraged** for non-obvious changes: explain *why*, not *what*
6. **Breaking changes**: add `!` after type/scope and `BREAKING CHANGE:` in footer

```
feat!(mcp): change tool input schema to require explicit units

BREAKING CHANGE: all tool callers must now pass displacement in meters
and forces in Newtons. Previously mm and kN were accepted.
```

### Prohibited

- ❌ `update`, `changes`, `wip`, `tmp`, `misc` as types
- ❌ Vague descriptions: `fix bug`, `update code`, `changes`
- ❌ Amending published commits (force-push to shared branches)
- ❌ Mixing unrelated changes in one commit
- ❌ Empty commit messages
- ❌ `--no-verify` or `--no-gpg-sign` flags (fix the underlying issue instead)

---

## Code Style

### Python (Gateway + MCP Servers)

- **[Black](https://black.readthedocs.io/)** formatting, line length 120
- **Type hints** on all function signatures (`def foo(x: int) -> str:`)
- **Google-style docstrings** for public functions (one-liner preferred)
- **Imports**: standard library → third-party → local, alphabetically within groups
- **No `*` imports**
- **Logging** over `print()`: use `logging.getLogger(__name__)`
- **Pydantic models** for all API request/response types
- **Async/await** throughout the gateway; avoid blocking calls

```python
# Preferred
async def analyze_frame(structure: dict[str, Any]) -> dict[str, Any]:
    """Run linear analysis and return displacements + forces."""
    from anastruct import SystemElements
    ss = SystemElements()
    ...

# Avoid
def analyze_frame(structure):
    ...
```

### TypeScript / React (Frontend)

- **Prettier** + **ESLint** (`next/core-web-vitals` + `@typescript-eslint`)
- **Strict mode** (`tsconfig.json` `"strict": true`)
- **`"use client"`** directive on all interactive components
- **Interfaces** over `type` for component props (prefixed with component name)
- **Named exports** preferred (`export function Foo`), not `export default`
- **No `any`** — use `unknown` or proper types
- **Tailwind classes**: no `@apply` in CSS; compose in JSX
- **No inline styles** except for dynamic values (use Tailwind tokens)

```tsx
// Preferred
interface FrameVisualizationProps {
  structure: FrameStructure | null;
  displacements?: NodeDisplacement[] | null;
}

export function FrameVisualization({ structure, displacements }: FrameVisualizationProps) {
  // ...
}

// Avoid
export default function FrameVisualization(props: any) {
```

### MCP Server Convention

All MCP servers follow this skeleton:

```python
"""<name> MCP Server — <one-line purpose>."""

import asyncio, json, logging
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

app = Server("<server-name>")

TOOLS = [Tool(...), ...]

@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        # route by name
        ...
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

**Rules**:
- Always return `[TextContent(...)]`, never raw strings
- Serialize results with `json.dumps`
- Catch all exceptions and return `{"error": str(e)}`
- Tool names use `snake_case`
- Tools registered in `hub.call_tool()` return `{"result": json_string}`

---

## Pull Request Process

### Before Opening

- [ ] Branch is rebased on latest `master`
- [ ] All tests pass locally (`pytest` for backend, `npm test` for frontend)
- [ ] TypeScript compiles (`npx tsc --noEmit`)
- [ ] No lint warnings (`npx eslint .`)
- [ ] Manual smoke test performed (send a frame analysis request, verify visualization renders)
- [ ] Commit history is clean (meaningful messages, logical grouping)

### PR Title

Follow the same format as commits: `<type>(<scope>): <description>`

```
feat(viz): add deformation overlay with node ID mapping
fix(agent): unwrap double-wrapped tool results
```

### PR Body

```markdown
## Summary
- <bullet 1>
- <bullet 2>

## Test plan
- [ ] Step 1
- [ ] Step 2

## Screenshots (if UI change)
<before/after>
```

### Review Requirements

- At least one approving review
- All CI checks green (pytest + tsc + lint + vitest + next build)
- No unresolved review threads
- Reviewer verifies the full pipeline: chat → analysis → visualization → demolition

---

## Testing

### Backend Tests (`gateway/tests/`, `mcp_servers/*/tests/`)

```bash
cd gateway
pytest -v                          # all tests
pytest tests/test_agent_loop.py    # specific file
pytest -k "tool_call"              # filter by name
```

- Use `pytest-asyncio` for async tests
- Mock LLM calls with `unittest.mock` or `pytest-mock`
- Tool server tests use real MCP session fixtures
- Aim for > 80% coverage on gateway core (agent_loop, llm_engine, mcp_hub)

### Frontend Tests (`frontend/__tests__/`)

```bash
cd frontend
npm test                  # vitest
npm test -- --coverage    # with coverage
```

- **vitest** + **@testing-library/react** for component tests
- **jsdom** environment
- Mock WebSocket with `vitest.setup.ts` global mock
- Test user interactions (click, type, submit), not implementation details
- Each component test must cover: empty state, loading state, populated state, error state

### Integration Smoke Test

Before merging, manually verify:

1. Start gateway + frontend
2. Configure LLM API key in settings
3. Type "Analyze a 2-story 2-bay frame"
4. Verify: frame SVG renders, mechanical summary populates, Demolish button appears
5. Click Demolish → verify collapse state in Animation tab
6. Open Verification → check all 3 tabs display data correctly
7. Switch language to Chinese → verify UI text updates

---

## Project-Specific Conventions

### Data Format: Tool Results

The MCP hub wraps tool results as `{"result": "<json_string>"}`. The agent loop **must unwrap** before sending to the frontend:

```python
# agent_loop.py — correct
result = await self.hub.call_tool(name, args)
result_data = result.get("result", result.get("error", str(result)))
steps.append({"type": "tool_result", "name": name, "result": result_data})
```

**Never** send the raw `{"result": "..."}` dict to the frontend — it breaks JSON parsing.

### Node/Element ID Mapping

- **anaStruct** assigns **1-based** internal IDs
- **Frontend** expects **0-based** IDs matching the original structure
- **MCP server responsibility**: map anaStruct IDs back to original IDs before returning

```python
# anastruct_server — correct
orig_to_ana = {orig_id: ss.find_node_id(coord) for orig_id, coord in node_coords.items()}
node_displacements = [{"node_id": orig_id, ...} for orig_id, ana_id in orig_to_ana.items()]
```

### WebSocket Event Types

All events sent to the frontend must include a `type` field:

| Type | Purpose | Required fields |
|---|---|---|
| `user_echo` | Confirm user message received | `content` |
| `memory` | Context memory retrieved | `content` |
| `tool_call` | LLM requested a tool | `name`, `arguments` |
| `tool_result` | Tool execution result | `name`, `result` |
| `response` | Final LLM response | `content` |
| `error` | Error occurred | `content` |
| `thinking` | LLM reasoning (optional) | `content` |

### Localization

All user-facing text goes through `t(key, lang)` in `@/lib/i18n`:

```tsx
import { t, type Lang } from "@/lib/i18n";

// In component
<span>{t("chat.placeholder", lang)}</span>
```

**Rules**:
- Add new keys to both `en` and `zh` dictionaries
- Key format: `<section>.<name>` (e.g., `mech.displacement`)
- Never hardcode English strings in JSX — always use `t()`

### Unity Fallback

The `unity_simulator` MCP server must always return `failed_elements` in its result, even when Unity is not reachable. This allows the frontend 2D visualization to function independently:

```python
result = _send_to_unity(command)
if "error" in result:
    result = {"status": "simulated", "failed_elements": failed_elements, ...}
```

---

## References

- [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)
- [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
- [Angular Commit Guidelines](https://github.com/angular/angular/blob/main/CONTRIBUTING.md#commit)
- [Black — The Uncompromising Code Formatter](https://black.readthedocs.io/)
- [Next.js Documentation](https://nextjs.org/docs)
- [Tailwind CSS](https://tailwindcss.com/docs)
- [shadcn/ui](https://ui.shadcn.com/docs)
