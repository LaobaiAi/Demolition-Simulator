# XuanwuAI Architecture: CAIAO Bus

> **This one principle governs all code in this project:**
> *Every capability is an independent CAIAO Server. The LLM talks to the CAIAO Hub, never directly to tools.*

## What is CAIAO?

**CAIAO** is the project-specific naming layer built on top of the standard [MCP (Model Context Protocol)](https://modelcontextprotocol.io) SDK. Every CAIAO Server is technically an MCP Server under the hood — the Python `mcp` package handles stdio transport, JSON-RPC messaging, and tool lifecycle. CAIAO is our project's abstraction that defines:

- **Naming convention**: all our servers are called `CAIAO Server` (not MCP Server)
- **File/dir convention**: `caiao_servers/`, `caiao_hub.py`, `CAIAOClientHub`
- **Case rule**: `CAIAO` (uppercase) for concepts, classes, constants; `caiao` (lowercase) for file paths, directory names
- **Architecture pattern**: every solver/tool is an independent subprocess, never inline logic in Gateway

### CAIAO vs MCP

| Layer | What it is | In our project |
|-------|-----------|----------------|
| **MCP SDK** | Python package `mcp>=1.0.0` | `from mcp.server import Server` in server.py |
| **MCP stdio transport** | JSON-RPC over stdin/stdout | `stdio_server()` handles serialization |
| **CAIAO Server** | Our project's concept of a tool server | Every `caiao_servers/<name>/server.py` |
| **CAIAO Client Hub** | Our multi-server lifecycle manager | `gateway/caiao_hub.py` → `CAIAOClientHub` |

The MCP SDK is an **implementation detail** — developers only need to follow the CAIAO contract below.

## Why CAIAO?

```
┌─────────────────┐      ┌────────────────────────────────────────┐
│   User (chat)   │ ──►  │  Gateway (FastAPI)                     │
└─────────────────┘      │  ┌───────────┐  ┌──────────────────┐  │
                         │  │ AgentLoop │──►  CAIAOClientHub  │  │
                         │  │ (ReAct)   │  │  (tool router)   │  │
                         │  └───────────┘  └────────┬─────────┘  │
                         └──────────────────────────┼─────────────┘
                                                     │
                    ┌────────────────────────────────┼────────────┐
                    │         CAIAO stdio bus        │            │
                    ▼                                ▼            ▼
          ┌─────────────────┐              ┌─────────────────┐
          │ anaStruct (2D)  │              │ OpenSees (HiFi) │  ...
          │ server.py       │              │ server.py        │
          └─────────────────┘              └─────────────────┘
```

1. **Isolation** — each solver runs as its own subprocess. A crash in OpenSees doesn't take down pyNite.
2. **Language agnostic** — any language that can do stdio JSON-RPC can be a CAIAO Server. C++, Rust, Julia — doesn't matter.
3. **Plug and play** — add a solver by writing one file and registering it. Zero changes to Gateway core.
4. **Future-proof** — want a GPU-accelerated solver? Write a CAIAO Server that spawns a CUDA process. Done.

## The Contract

Every CAIAO Server lives in `caiao_servers/<name>/server.py` and MUST follow this skeleton:

```python
"""<name> CAIAO Server — <one-line purpose>."""

import asyncio, json, logging
from mcp.server import Server          # MCP SDK (external package)
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("<server-name>")

TOOLS = [
    Tool(name="my_tool", description="...", inputSchema={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},
        },
        "required": ["param1"],
    }),
]

@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "my_tool":
            result = {"status": "ok", "result": "processed"}
        else:
            result = {"error": f"Unknown tool: {name}"}
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

### Contract Rules

1. **Always return `[TextContent(type="text", text=json.dumps(...))]`** — never raw strings
2. **Serialize everything as JSON** — the Gateway extracts `result` from the JSON string
3. **Catch all exceptions** and return `{"error": str(e)}` — never crash the subprocess
4. **Tool names use `snake_case`** — consistent with Python conventions
5. **Input schema is JSON Schema** — the LLM uses it to generate correct arguments

## Naming Conventions

| Context | Convention | Examples |
|---------|-----------|----------|
| Class names | `CAIAO` (uppercase) + PascalCase | `CAIAOClientHub` |
| Constants | `CAIAO_` prefix + UPPER_SNAKE | `CAIAO_SERVERS_DIR` |
| File names | `caiao_` prefix + lowercase | `caiao_hub.py` |
| Directory name | `caiao_servers/` | `caiao_servers/anastruct_server/` |
| Config server name | `caiao` (lowercase, scope) | commit scope `caiao` |
| SDK imports (external) | `from mcp.server import Server` | unchanged, not our naming |

## Adding a New Solver

1. Copy `caiao_servers/_template/server.py` → `caiao_servers/my_solver/server.py`
2. Implement `list_tools()` and `call_tool()` following The Contract
3. Register in `gateway/main.py` → `SERVER_CONFIGS` list with `"lazy": True` for heavyweight solvers
4. Restart Gateway — tool appears in `/tools` automatically

## Verification

Check at any time: `GET /tools` should return all registered tools grouped by server. If a tool isn't there, its CAIAO Server isn't running.
