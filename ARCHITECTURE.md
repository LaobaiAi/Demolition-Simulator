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

## CAIAOServerizer Paradigm: Server Merge

### Concept

在 CAIAOServerizer 范式中，CAIAO Server 是**最小原子单元**，类比 LLM 的 token。
就像 LLM 把 token 组合成意义，我们把 CAIAO Server 组合成工程流水线（pipeline）。

当某个 Server 序列反复高频出现时，就将它**合并（merge）**为一个新的原子 Server——
这正是 BPE（Byte-Pair Encoding）合并高频 token 对的方式。

```
# 合并前：3 次子进程调用（3 个 "token"）
generate_frame  →  analyze_frame  →  select_critical_element

# 合并后：1 次子进程调用（1 个 "token"）
quick_analysis  ←  Pipeline A（三步合并为一个原子 Server）
```

### ⚡ First Merge: Pipeline A (2026-05-25)

`quick_analysis_server` 是 CAIAOServerizer 的第一个手动 server merge。
它将 `generate_frame` + `analyze_frame` + `select_critical_element` 三个
此前独立的原子 Server 合并为一个独立 Server：

```
caiao_servers/quick_analysis_server/
  └── server.py  ← imports: frame_generator.core + anastruct_server.server
```

| 对比 | 合并前 | 合并后 |
|------|--------|--------|
| 子进程通信 | 3 次 | 1 次 |
| LLM 决策 | 3 次 or composite | 1 次 |
| 原子性 | 部分失败风险 | 全有或全无 |
| 延迟 | ~300ms × 3 + IPC | ~300ms total |

**详细记录：** `dev-notes/architecture/2026-05-25-caiaoserverizer-first-merge.md`

### ⚡ Second Merge: Pipeline B (2026-05-25)

`full_analysis_3d_server` 是 CAIAOServerizer 的第二个 server merge。
它将 `generate_frame_3d` + `convert_to_unified_frame` + `pynite_analysis` + `select_critical_3d`
合并为一个独立 Server：

```
caiao_servers/full_analysis_3d_server/
  └── server.py  ← imports: frame_generator.core + pynite_server.server
                   └── _convert_3d_to_unified()  ← built-in converter
```

**核心价值：** 打通了 3D 可视化几何到 3D 结构分析的桥梁。
`generate_3d()` 的输出原本只用于可视化（无截面属性、无拓扑、无荷载），现在通过
UnifiedFrame 转换器自动生成拓扑格式，进入 PyNite 3D 求解器。

| 对比 | 合并前 | 合并后 |
|------|--------|--------|
| 子进程通信 | 4 次 | 1 次 |
| 数据格式转换 | 手动编写 | 自动 UnifiedFrame |
| 3D 分析能力 | 无（3D 只有可视化） | 完整 3D FEM 分析 |
| 坐标约定 | 多种不统一 | 统一为 {x, y, z} |

### Merge Roadmap

| # | Merge | 涉及 Server | 状态 |
|---|-------|-------------|------|
| 1 | **Quick Analysis** (Pipeline A) | generate_frame + anastruct.analyze + anastruct.select_critical | ✅ Done |
| 2 | **3D Full Analysis** (Pipeline B) | generate_frame_3d → convert → pynite_analysis → select_critical_3d | ✅ Done |
| 3 | **Verify Suite** | anastruct + opensees + pynite + fapp → consensus | 📋 Planned |
| 4 | **Demolition Cycle** | apply_demolition + analyze + select_critical | 📋 Planned |

### How to Create a Merge

```python
from frame_generator.core import FrameGenerator
from anastruct_server.server import _analyze_structure

def my_merged_tool(args):
    cfg = FrameGeneratorConfig(**args)
    structure = FrameGenerator(cfg).generate()
    analysis = _analyze_structure(structure)
    critical = _select_critical_element(structure, analysis)
    return {"structure": structure, "analysis": analysis, "critical": critical}
```

See `caiao_servers/quick_analysis_server/server.py` for the full example.

## CAIAO Server Manager (Meta-Server)

The `manager_server` is a self-referential CAIAO server that manages all other CAIAO servers:

```
┌─────────────────────────────────────────────────┐
│              Manager Server (meta)              │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ Create   │  │ Health   │  │ Orchestrate  │  │
│  │ Scaffold │  │ Monitor  │  │ Detect Merge │  │
│  │ Validate │  │ Metrics  │  │ Dep Graph    │  │
│  └──────────┘  └──────────┘  └──────────────┘  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ Extend   │  │ Migrate  │  │ Search       │  │
│  │ Add Tool │  │ Rename   │  │ Semantic     │  │
│  │ Import   │  │ Version  │  │ TF-IDF       │  │
│  └──────────┘  └──────────┘  └──────────────┘  │
└──────────┬──────────────┬──────────────────────┘
           │              │
    ┌──────▼──────┐  ┌────▼──────────────┐
    │ caiao.yaml  │  │ Gateway REST APIs │
    │ (manifests) │  │ /servers/*        │
    └─────────────┘  └───────────────────┘
```

**Key principles:**
- **Dogfooding:** The manager IS a CAIAO server, managed by the same hub it manages
- **Declarative state:** Manager writes `caiao.yaml` manifests; Gateway auto-discovers them via `caiao_config.py`
- **GitOps friendly:** All configuration is file-based, version-controllable
- **24 tools across 6 groups:** Creation, Extension, Enhancement, Migration, Retrieval, Orchestration

## Full Reference

See **[`CAIAO_PROTOCOL.md`](CAIAO_PROTOCOL.md)** for the complete CAIAO reference:
- Server independence principle
- Server registry (all servers, tools, status)
- Server manager documentation
- Merge roadmap
- Naming conventions
- Contract rules
- Change log

## Verification

Check at any time: `GET /tools` should return all registered tools grouped by server. If a tool isn't there, its CAIAO Server isn't running.
