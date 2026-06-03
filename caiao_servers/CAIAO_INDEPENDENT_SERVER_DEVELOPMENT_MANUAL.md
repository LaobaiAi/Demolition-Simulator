# CAIAO 独立 Server 开发手册

> **版本**: v2.0  
> **面向**: 开发者 / AI 编程助手  
> **目标**: 指引你创建符合 CAIAO 生态规范、可被 Hub 发现、可独立运行的原子 Server

---

## 目录

1. [什么是 CAIAO Server](#1-什么是-caiao-server)
2. [核心契约与接口](#2-核心契约与接口)
3. [快速上手：第一个 CAIAO Server](#3-快速上手机第一个-caiao-server)
4. [CAIAOServer 基类详解](#4-caiaoserver-基类详解)
5. [工具注册与 `@tool` 装饰器](#5-工具注册与-tool-装饰器)
6. [JSON Schema 输入输出规范](#6-json-schema-输入输出规范)
7. [运行模式与认证](#7-运行模式与认证)
8. [接择入 CAIAO Hub 生态](#8-接入-caiao-hub-生态)
9. [子进程模式与 stdio 协议](#9-子进程模式与-stdio-协议)
10. [Server 分类与设计原则](#10-server-分类与设计原则)
11. [完整示例模板](#11-完整示例模板)
12. [高级模式](#12-高级模式)
13. [检查清单](#13-检查清单)

---

## 1. 什么是 CAIAO Server

**CAIAO (轻量原子 Server)** 是一个极简的工具框架，将领域能力封装为独立、可复用、LLM 可调用的原子单元。

```
CAIAO Server = 纯 Python 类 + @tool 装饰器 + JSON I/O 契约
```

### 核心理念

| 特性 | 说明 |
|------|------|
| **原子性** | 一个 Server 只做一件事，单文件 `.py` |
| **契约化** | `list_tools()` / `call_tool()` / `get_metadata()` 三接口统一 |
| **零互联** | Server 间绝不直接 import，通过 Hub 路由 JSON |
| **AI-ready** | 工具描述 + JSON Schema 完备声明，LLM 可直接调用 |
| **MCP-ready** | 接口已对齐 MCP 协议，无缝升级 |

### 架构全貌

```
                 ┌──────────────────────────────────┐
                 │          CAIAO Hub                │
                 │    (零业务逻辑的路由代理)           │
                 │  find_tool() / call_tool()        │
                 └──────┬───────────┬───────────────┘
                        │           │
             ┌──────────┘           └──────────────┐
             │  in_process                          │  subprocess
             ▼                                      ▼
    ┌─────────────────┐                  ┌──────────────────┐
    │  CAIAOServer    │                  │  CAIAOServer     │
    │  (主进程内直调)   │                  │  (独立子进程,     │
    │                  │                  │   stdio 通信)    │
    │  @tool(...)      │                  │  @tool(...)      │
    │  def tool_a():   │                  │  def tool_b():   │
    └─────────────────┘                  └──────────────────┘
```

---

## 2. 核心契约与接口

每个 CAIAO Server 必须实现三个接口方法：

### 2.1 `list_tools() -> list[dict]`

声明 Server 能力。返回工具描述列表，每个工具含三个字段：

```python
[
    {
        "name": "tool_name",           # 唯一工具名，snake_case
        "description": "...",          # 人类可读描述，AI 据此理解功能
        "inputSchema": {              # JSON Schema，定义输入参数
            "type": "object",
            "required": [...],
            "properties": {...}
        }
    }
]
```

### 2.2 `call_tool(tool_name: str, input_data: dict) -> dict`

执行指定工具。返回纯 dict（可 JSON 序列化）。

```python
# 成功
{"result": ..., "status": "success"}

# 失败
{"error": "Tool 'xxx' not found."}
```

### 2.3 `get_metadata() -> dict`

返回 Server 元数据（v2.0+）：

```python
{
    "name": "MyServer",
    "version": "1.0.0",
    "category": "<domain>",
    "description": "...",
    "tools": [{"name": "...", "description": "..."}],
    "dependencies": [],
    "compatibility": {
        "caiao_spec": "1.0",
        "mcp": True
    }
}
```

---

## 3. 快速上手：第一个 CAIAO Server

### 3.1 最小可用示例

在 `servers/my_first_server.py` 创建：

```python
"""
my_first_server.py — CAIAO 原子 Server 最小示例
"""
import sys
import json
from servers.base import CAIAOServer, tool


class MyFirstServer(CAIAOServer):
    """我最在的 CAIAO Server — 演示最简单的工具注册和执行。"""

    # ── 类级元信息 ──────────────────────────────
    server_name = "my-first-server"
    server_version = "1.0.0"
    server_category = "demo"
    server_description = "演示 Server，用于学习 CAIAO 开发"
    server_dependencies = []

    # ── 运行模式 ────────────────────────────────
    # "orchestration"  = 主进程内直调（默认）
    # "computational"  = 建议子进程运行
    server_type = "orchestration"
    _caiao_subprocess = False

    def __init__(self):
        super().__init__()

    @tool(
        name="hello_caiao",
        description="返回一个问候消息。调用时机：当用户需要问候时。",
        input_schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要问候的名字"
                },
                "language": {
                    "type": "string",
                    "description": "问候语言：'zh' 或 'en'，默认 'zh'"
                }
            }
        }
    )
    def hello_caiao(self, input_data: dict) -> dict:
        """核心逻辑：生成问候语"""
        name = input_data.get("name", "World")
        lang = input_data.get("language", "zh")

        if lang == "zh":
            message = f"你好, {name}！欢迎来到 CAIAO 生态。"
        else:
            message = f"Hello, {name}! Welcome to CAIAO ecosystem."

        return {
            "message": message,
            "greeted_at": "2026"  # 示例，实际可以用 datetime.now()
        }

    @tool(
        name="calculate",
        description="执行基础算术运算。调用时机：当需要计算时。",
        input_schema={
            "type": "object",
            "required": ["a", "b", "operation"],
            "properties": {
                "a": {"type": "number", "description": "第一个数字"},
                "b": {"type": "number", "description": "第二个数字"},
                "operation": {
                    "type": "string",
                    "enum": ["add", "subtract", "multiply", "divide"],
                    "description": "运算类型"
                }
            }
        }
    )
    def calculate(self, input_data: dict) -> dict:
        """核心逻辑：算术运算"""
        a = float(input_data["a"])
        b = float(input_data["b"])
        op = input_data["operation"]

        if op == "add":
            result = a + b
        elif op == "subtract":
            result = a - b
        elif op == "multiply":
            result = a * b
        elif op == "divide":
            if b == 0:
                return {"error": "除数不能为零"}
            result = a / b
        else:
            return {"error": f"未知操作: {op}"}

        return {"a": a, "b": b, "operation": op, "result": result}


# ── 独立启动入口 ──────────────────────────────────
if __name__ == "__main__":
    server = MyFirstServer()

    # 无参数时，进入 stdio 循环（子进程模式）
    if len(sys.argv) <= 1:
        server.run_stdio_loop()
    else:
        # 有参数时，CLI 模式：python my_first_server.py tool_name '{"key": "val"}'
        server.run_cli(sys.argv[1:])
```

### 3.2 测试你的 Server

```bash
# 1. 列出所有工具
python servers/my_first_server.py
# 输出: Tools: ['hello_caiao', 'calculate']

# 2. 调用 hello_caiao
python servers/my_first_server.py hello_caiao "{\"name\":\"张三四\"}"
# 输出: {"message": "你好, 张三四！欢迎来到 CAIAO 生态。", "greeted_at": "2026"}

# 3. 调用 calculate
python servers/my_first_server.py calculate "{\"a\":3.14,\"b\":2.0,\"operation\":\"multiply\"}"
# 输出: {"a": 3.14, "b": 2.0, "operation": "multiply", "result": 6.28}
```

---

## 4. CAIAOServer 基类详解

### 4.1 完整类定义

```python
# 文件: servers/base.py

class CAIAOServer:
    """CAIAO 原子 Server 基类"""

    # ── 类级元信息（子类必须覆盖）─────────────────────
    server_name: str = ""                # Server 唯一标识
    server_version: str = "1.0.0"        # 语义化版本
    server_category: str = "general"     # 分类: 如 "structural", "demo", "finance"
    server_description: str = ""         # 一句话描述
    server_dependencies: list[str] = []  # 依赖的 Server 名列表（声明式，非 import）

    # ── 运行模式 ─────────────────────────────────────
    server_type: str = "orchestration"   # "orchestration" | "computational"
    _caiao_subprocess: bool = False      # True: Hub 自动扫描时跳过，须手动注册子进程
```

### 4.2 核心方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `()` | 初始化，自动调用 `_discover_tools()` 扫描所有 `@tool` 装饰的方法 |
| `_discover_tools` | `()` | 反射扫描，收集所有带 `_caiao_tool` 属性的方法 |
| `list_tools` | `() -> list[dict]` | 返回所有已注册工具的描述列表 |
| `call_tool` | `(tool_name, input_data) -> dict` | 按名称调取工具，错误自动捕获返回 `{"error": ...}` |
| `get_metadata` | `() -> dict` | 返回 Server 元数据 |
| `run_stdio_loop` | `()` | 启动 stdio JSON-RPC 循环（子进程模式/ MCP 预留） |
| `run_cli` | `(args) -> None` | 从命令行参数直接调用工具 |

### 4.3 `call_tool` 的执行流程

```
call_tool(tool_name, input_data)
    │
    ├── tool_name 不在 _tools → return {"error": "Tool 'xxx' not found..."}
    │
    └── tool_name 存在 →
            try:
                result = self._tools[tool_name](input_data)
                return result
            except Exception as e:
                return {"error": "Tool 'xxx' execution failed: {e}"}
```

**关键点**: `call_tool` 始终捕获异常，返回带有 `"error"` 键的字典，绝不抛出未处理的异常。

---

## 5. 工具注册与 `@tool` 装饰器

### 5.1 装饰器签名

```python
def tool(name: str, description: str, input_schema: dict):
    """装饰器：将方法注册为一个 CAIAO Tool"""
```

**字段约束**:

| 字段 | 类型 | 约束 | 示例 |
|------|------|------|------|
| `name` | `str` | snake_case，唯一 | `generate_frame` |
| `description` | `str` | 写清功能、输入含义、输出含义、适用场景、调用时机。AI 据此理解何时调用。 | `"根据网格参数生成钢框架结构模型..."` |
| `input_schema` | `dict` | 符合 JSON Schema Draft-07，每个 `property` 必须有 `description` | 见下方 |

### 5.2 `input_schema` 示例

```python
@tool(
    name="generate_frame",
    description="根据网格参数、层数和层高生成钢框架结构模型。输出含节点坐标、单元连接、截面属性和材料属性。适用于规则矩形网格建筑。",
    input_schema={
        "type": "object",
        "required": ["grid_x", "grid_y", "num_stories", "story_heights"],
        "properties": {
            "grid_x": {
                "type": "array",
                "items": {"type": "number"},
                "description": "X 方向各跨度的长度 (m)，如 [6.0, 6.0, 6.0] 表示 3 跨 6m"
            },
            "grid_y": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Y 方向各跨度的长度 (m)"
            },
            "num_stories": {
                "type": "integer",
                "minimum": 1,
                "description": "楼层数"
            },
            "story_heights": {
                "type": "array",
                "items": {"type": "number"},
                "description": "各层高度 (m)，长度应等于 num_stories"
            },
            "column_section": {
                "type": "string",
                "description": "柱截面型号，如 HW350x350x12x19。默认 HW300x300x10x15"
            },
            "material": {
                "type": "string",
                "enum": ["Q235", "Q355"],
                "description": "钢材牌号，默认 Q355"
            }
        }
    }
)
def generate_frame(self, input_data: dict) -> dict:
    ...
```

### 5.3 内部实现原理

`@tool` 装饰器将元信息存储为方法的 `_caiao_tool` 属性：

```python
def tool(name, description, input_schema):
    def decorator(func):
        func._caiao_tool = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
        }
        return func
    return decorator
```

基类 `__init__` 中通过 `dir(self)` 反射扫描所有带 `_caiao_tool` 的方法并注册到 `self._tools` 字典。

---

## 6. JSON Schema 输入输出规范

### 6.1 设计原则

| # | 原则 | 说明 |
|---|------|------|
| 1 | **自描述** | 每个字段有 `description`，AI 可无歧义理解 |
| 2 | **最小完备** | 只含必要字段，不冗余 |
| 3 | **类型严格** | 物理量用 `number`，索引用 `integer`，ID 用 `string` |
| 4 | **可扩展** | 不设 `additionalProperties: false`，允许传额外字段 |
| 5 | **声明约束** | 用 `minimum`, `maximum`, `enum`, `pattern` 等约束声明 |

### 6.2 输出规范

工具的返回值必须是**纯 dict**，所有值可 JSON 序列化：

```python
# ✅ 正确
return {"status": "success", "data": {"nodes": [...], "elements": [...]}}

# ✅ 正确 — 带计算过程
return {
    "stress_ratio": 0.85,
    "stability_ratio": 0.72,
    "pass": True,
    "calc_processes": [
        {"step": 1, "formula": "σ = N/A + My/Wx", "result": 298.5},
        {"step": 2, "formula": "λ = L/i", "result": 45.2},
    ]
}

# ❌ 错误 — 直接返回 numpy 数组
return {"nodes": np.array([...])}  # 应用 .tolist() 转换

# ❌ 错误 — 返回不可序列化的对象
return {"result": MyCustomClass()}
```

### 6.3 输出 Schema 验证（推荐）

在开发阶段使用 `jsonschema` 验证输出：

```python
import jsonschema

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["nodes", "elements", "sections"],
    "properties": {
        "nodes": {"type": "array", "items": {"$ref": "#/definitions/node"}},
        ...
    }
}

def generate_frame(self, input_data: dict) -> dict:
    result = self._compute(...)
    jsonschema.validate(result, OUTPUT_SCHEMA)  # 开发期验证
    return result
```

---

## 7. 运行模式与认证

### 7.1 三种运行方式

| 方式 | 命令 | 适用场景 |
|------|------|----------|
| **直接调用** | `server = MyServer(); server.call_tool(...)` | 代码内编排、测试 |
| **CLI 模式** | `python my_server.py tool_name '{"key":"val"}'` | 调试、手工验证 |
| **stdio 循环** | `python -u my_server.py` | 子进程模式、MCP 集成 |

### 7.2 `run_cli()` 用法

```python
if __name__ == "__main__":
    server = MyServer()
    if len(sys.argv) > 1:
        server.run_cli(sys.argv[1:])   # 有参数 → CLI 模式
    else:
        server.run_stdio_loop()        # 无参数 → stdio 模式
```

示例：
```bash
# 列出工具
python servers/my_server.py

# 调用工具
python servers/my_server.py my_tool '{"param1": 123, "param2": "hello"}'

# 无 input_data（使用默认值）
python servers/my_server.py my_tool
```

### 7.3 `server_type` 选择

```python
# 编排型— 主进程内安全运行
server_type = "orchestration"     # 默认

# 计算型— 建议子进程隔离（崩溃不牵连主进程）
server_type = "computational"     
_caiao_subprocess = True          # Hub 自动扫描时跳过
```

---

## 8. 接入 CAIAO Hub 生态

### 8.1 两种接入方式

```
in_process：主进程内实例化，Hub 通过 call_tool() 直调
subprocess：独立子进程，Hub 通过 stdin/stdout JSON 通信
```

### 8.2 作为 in_process Server

#### 方式 1: 自动发现（推荐）

只需将文件放在 `servers/` 目录下，Hub 初始化时自动扫描并注册：

```python
# 你的 my_server.py 放于 servers/ 下
# Hub 自动发现条件:
# 1. 文件名不以 _ 开头
# 2. 类继承 CAIAOServer
# 3. _caiao_subprocess = False (默认)

# hub 端无需额外代码
from caiao_hub import Hub
hub = Hub()  # 自动扫描 servers/ 目录
result = hub.call_tool("my_tool", {...})  # 自动路由到你的 Server
```

#### 方式 2: 手动注册

需要自定义构造参数（如传入 hub 引用）时使用：

```python
from caiao_hub import Hub
from servers.my_server import MyServer

hub = Hub()
my_server = MyServer(config={"api_key": "sk-xxx"})
hub.register(my_server)  # 手动注册

result = hub.call_tool("my_tool", {...})
```

### 8.3 作为 subprocess Server

计算型 Server（如 FEA 求解器）建议在独立子进程运行：

#### Step 1: Server 端 — 标记为子进程模式

```python
class MyComputationalServer(CAIAOServer):
    server_type = "computational"
    _caiao_subprocess = True  # Hub 自动扫描时跳过

if __name__ == "__main__":
    MyComputationalServer().run_stdio_loop()
```

#### Step 2: Hub 端 — 注册子进程配置

```python
hub = Hub()
hub.register_subprocess({
    "name": "my_computation",
    "command": sys.executable,
    "args": ["-u", "-m", "servers.my_computational_server"],
    "cwd": project_root,
    "lazy": True,  # 惰性启动：首次 call_tool 时才 spawn
    "tools": ["run_analysis"],  # 已知工具名（用于静态注册）
})

# 现在可以通过 Hub 调用了
result = hub.call_tool("run_analysis", {...})
```

#### Step 3（可选）: 使用特定虚拟环境

```python
hub.register_subprocess({
    "name": "fea_runner",
    "command": ".venv_opensees/Scripts/python.exe",  # Windows
    # "command": ".venv_opensees/bin/python",         # Linux/Mac
    "args": ["-u", "-m", "servers.opensees_runner"],
    "cwd": project_root,
    "lazy": True,
    "tools": ["run_analysis"],
})
```

### 8.4 Hub.call_tool 路由机制

```
hub.call_tool("tool_name", input_data)
    │
    ├── 1) 查 in_process 注册表 (_tool_registry)
    │      └── 找到 → entry["server"].call_tool(tool_name, input_data)
    │
    ├── 2) 查 subprocess 注册表 (_subprocess_tool_registry)
    │      └── 找到 → mgr = _ensure_subprocess(tool_name)  # 惰性启动
    │                 └── mgr.call_tool(tool_name, input_data)  # stdio 通信
    │
    └── 3) 全未找到 → return {"error": "Tool 'xxx' not found."}
```

---

## 9. 子进程模式与 stdio 协议

### 9.1 通信协议（轻量 JSON-RPC）

每一行是一个完整的 JSON 消息。

**请求格式**:
```json
{"method": "...", "params": {...}, "id": <int>}
```

**响应格式**:
```json
{"id": <int>, "result": {...}}
```

**支持的方法**:

| method | params | 说明 |
|--------|--------|------|
| `list_tools` | `{}` | 返回工具列表 |
| `call_tool` | `{"tool_name": "...", "input": {...}}` | 执行工具 |
| `get_metadata` | `{}` | 返回 Server 元数据 |

### 9.2 `run_stdio_loop()` 实现细节

基类已实现，子类无需重写：

```python
def run_stdio_loop(self):
    """启动 stdio JSON-RPC 循环"""
    sys.stderr.write(f"[{name}] CAIAO stdio loop started (type={self.server_type})\n")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        method = request.get("method", "")
        req_id = request.get("id")

        if method == "list_tools":
            response = {"id": req_id, "result": self.list_tools()}
        elif method == "call_tool":
            tool_name = request["params"].get("tool_name", "")
            input_data = request["params"].get("input", {})
            result = self.call_tool(tool_name, input_data)
            response = {"id": req_id, "result": result}
        elif method == "get_metadata":
            response = {"id": req_id, "result": self.get_metadata()}
        else:
            response = {"id": req_id, "error": f"Unknown method: {method}"}

        print(json.dumps(response, ensure_ascii=False), flush=True)
```

### 9.3 SubprocessManager 生命周期管理

`caiao_hub.py` 中的 `SubprocessManager` 管理子进程的完整生命周期：

```python
mgr = SubprocessManager(
    name="my_server",          # 唯一标识
    command=sys.executable,    # 解释器路径
    args=["-u", "server.py"],  # 参数（-u: Python 无缓冲 stdout）
    cwd=project_root,          # 工作目录
    lazy=True                  # 惰性模式：首次 call_tool 时才 spawn
)

# 生命周期:
mgr.start()       # 启动子进程，发送 list_tools 获取工具列表
mgr.call_tool()   # 发送 call_tool 请求
mgr.stop()        # SIGTERM → 5秒超时 → SIGKILL
mgr.is_running    # 检查子进程存活状态
```

---

## 10. Server 分类与设计原则

### 10.1 原子 Server vs 合并 Server

| | 原子 Server | 合并 Server (Pipeline) |
|---|---|---|
| **定义** | 独立计算逻辑，单一领域功能 | 编排多个原子 Server，自己不含计算逻辑 |
| **示例** | `generate_frame`, `run_analysis` | `run_full_pipeline`, `execute_with_llm` |
| **依赖** | 不 import 其他 Server | 通过 Hub 调用其他 Server |
| **运行模式** | 任意 | 仅 `in_process` (纯编排，无计算) |

### 10.2 设计原则总表

| # | 原则 | 说明 |
|---|------|------|
| 1 | **原子化** | 一个 Server 只做一件事，单一职责 |
| 2 | **零互联** | Server 间绝不直接 import，通过 Hub 路由 JSON |
| 3 | **无状态** | 输入足够，不依赖外部隐式状态 |
| 4 | **可独立验证** | 给定输入，输出可单独测试 |
| 5 | **契约驱动** | `list_tools()` + `call_tool()` 统一接择 |
| 6 | **AI 原生** | `@tool` 的 `description` 和 `inputSchema` 完整，LLM Agent 可直接调用 |
| 7 | **容错** | `call_tool` 捕获异常返回 `{"error": ...}`，不抛出未处理异常 |
| 8 | **进程隔离** | 计算型 Server 子进程运行，崩溃不牵连主进程 |

### 10.3 错误处理模式

```python
@tool(...)
def my_tool(self, input_data: dict) -> dict:
    # 1. 输入校验
    if "required_field" not in input_data:
        return {"error": "Missing required field: required_field"}

    # 2. 业务逻辑
    try:
        result = self._heavy_computation(input_data)
    except ValueError as e:
        return {"error": f"Invalid value: {e}"}
    except Exception as e:
        return {"error": f"Computation failed: {e}"}

    # 3. 正常返回
    return {"status": "success", "result": result}
```

### 10.4 键盘选择：是否启用子进程

```
Server 会 crash 吗？
    ├── 否 → server_type = "orchestration", 主进程直调
    │         示例: 编排器、参数校验器、报告生成器
    │
    └── 是 → server_type = "computational", _caiao_subprocess = True
              示例: FEA 求解器、大计算量的算法引擎
              (子进程崩溃不影响主进程、自动重启)
```

---

## 11. 完整示例模板

### 11.1 模板：原子 Server

```python
"""
my_domain_server.py — CAIAO 原子 Server

蒸馏来源：<源系统>/<技能路径>
蒸馏日期：YYYY-MM-DD
独立功能：<一句话描述>
"""
import json
import sys
import logging
from typing import Any

from servers.base import CAIAOServer, tool

logger = logging.getLogger(__name__)


class MyDomainServer(CAIAOServer):
    """<一句话描述这个 Server 做什么>

    蒸馏来源: <源系统>
    关键简化: <列出假设和简化>
    """

    # ── 类级元信息 ──────────────────────────────────
    server_name: str = "my-domain-server"
    server_version: str = "1.0.0"
    server_category: str = "your-domain"          # 领域分类
    server_description: str = "实现 XXX 功能"
    server_dependencies: list[str] = []

    # ── 运行模式 ────────────────────────────────────
    server_type: str = "orchestration"             # or "computational"
    _caiao_subprocess: bool = False                # True if computational

    def __init__(self):
        """初始化：加载数据、建立索引等"""
        super().__init__()
        # 初始化你的数据（截面库、材料库、配置等）
        self._load_data()

    def _load_data(self):
        """加载内置数据（硬编码，避免外部文件依赖）"""
        # 示例：硬编码常量 / 内置表
        self._constants = {
            "gravity": 9.81,
            "pi": 3.141592653589793,
        }

    # ── 工具方法 ────────────────────────────────────

    @tool(
        name="process_data",
        description=(
            "对输入数据执行 XXX 处理并返回结果。"
            "调用时机：当需要 XXX 时。"
            "输入：data (原始数据)、options (处理选项)。"
            "输出：processed_result (处理结果)、stats (统计信息)。"
        ),
        input_schema={
            "type": "object",
            "required": ["data"],
            "properties": {
                "data": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "输入数据数组"
                },
                "option_a": {
                    "type": "number",
                    "default": 1.0,
                    "description": "选项 A，控制 XXX 行为。默认 1.0"
                },
                "option_b": {
                    "type": "boolean",
                    "default": False,
                    "description": "选项 B，是否启用 XXX。默认 false"
                }
            }
        }
    )
    def process_data(self, input_data: dict) -> dict:
        """核心计算逻辑"""
        data = input_data.get("data", [])
        opt_a = input_data.get("option_a", 1.0)
        opt_b = input_data.get("option_b", False)

        # 1. 输入校验
        if not data:
            return {"error": "data 不能为空"}
        if len(data) > 100000:
            return {"error": "data 超过最大长度 100000"}

        # 2. 业务计算
        try:
            total = sum(data)
            avg = total / len(data)

            if opt_b:
                avg *= opt_a

            result_list = [x * opt_a + avg for x in data]

        except Exception as e:
            logger.error(f"处理失败: {e}")
            return {"error": f"数据处理失败: {str(e)}"}

        # 3. 构建输出
        return {
            "processed_data": result_list,
            "stats": {
                "count": len(data),
                "total": total,
                "average": avg,
                "option_a": opt_a,
                "option_b": opt_b,
            },
            "status": "success",
        }


# ── 独立启动入口 ──────────────────────────────────
if __name__ == "__main__":
    server = MyDomainServer()

    if len(sys.argv) > 1:
        # CLI 模式
        server.run_cli(sys.argv[1:])
    else:
        # stdio 循环（子进程模式 / MCP 预留）
        server.run_stdio_loop()
```

### 11.2 模板：合拢 Server (Pipeline)

```python
"""
my_pipeline.py — CAIAO 合拢 Server (Pipeline)

职责：纯编排，不含任何领域计算逻辑。
"""
from servers.base import CAIAOServer, tool


class MyPipeline(CAIAOServer):
    """组合多个原子 Server 完成端到端流程。

    铁律：
    1. 不含任何领域计算逻辑
    2. 只做数据传递和顺序编排
    3. 下游输入 = 上游输出 + 原始参数
    """

    server_name = "my-pipeline"
    server_category = "orchestration"
    server_type = "orchestration"

    def __init__(self, hub=None):
        super().__init__()
        self._hub = hub

        # 如果无 Hub，直接实例化（向后兼容）
        if hub is None:
            from servers.my_server_a import ServerA
            from servers.my_server_b import ServerB
            self._server_a = ServerA()
            self._server_b = ServerB()
        else:
            self._server_a = None
            self._server_b = None

    def _call(self, tool_name: str, input_data: dict) -> dict:
        """统一调用入口：Hub 优先 → 直接调用回退"""
        if self._hub:
            return self._hub.call_tool(tool_name, input_data)
        # fallback: 根据 tool_name 路由
        mapping = {
            "tool_a": self._server_a,
            "tool_b": self._server_b,
        }
        server = mapping.get(tool_name)
        if server:
            return server.call_tool(tool_name, input_data)
        return {"error": f"Tool '{tool_name}' not found"}

    @tool(
        name="run_pipeline",
        description="端到端流程：步骤A → 步骤B，返回全部中间结果和最终报告。",
        input_schema={
            "type": "object",
            "required": ["raw_input"],
            "properties": {
                "raw_input": {"type": "object", "description": "原始输入参数"},
                "options": {"type": "object", "description": "流水线选项"}
            }
        }
    )
    def run_pipeline(self, input_data: dict) -> dict:
        steps = []

        # Step 1
        result_a = self._call("tool_a", input_data["raw_input"])
        steps.append({"step": "tool_a", "status": "error" if "error" in result_a else "ok"})

        # Step 2
        result_b = self._call("tool_b", {**input_data["raw_input"], **result_a})
        steps.append({"step": "tool_b", "status": "ok"})

        return {
            "status": "success",
            "step_a": result_a,
            "step_b": result_b,
            "steps": steps,
        }


if __name__ == "__main__":
    import sys
    server = MyPipeline()
    if len(sys.argv) > 1:
        server.run_cli(sys.argv[1:])
    else:
        server.run_stdio_loop()
```

---

## 12. 高级模式

### 12.1 依赖式依赖声明

如果一个 Server 需要另一个 Server 的输出作为前置条件（但又不直接 import），在类级声明：

```python
class CodeCheck(CAIAOServer):
    server_dependencies = ["steel_frame_generator", "opensees_runner"]
    # 表明此 Server 需要上游先完成建块和FEA，但通过 Hub 通信，不 import
```

这些字符串唯一的声明式信息——用于元数据展示和文档，不影响运行时行为。

### 12.2 计算过程可追踪

对于需要展示详细计算步骤的场景，在输出中附加 `calc_processes`：

```python
@tool(name="check_code", ...)
def check_code(self, input_data: dict) -> dict:
    calc_processes = []

    # 强度校核
    sigma = N / A + My / Wx + Mz / Wy
    calc_processes.append({
        "step": 1,
        "name": "强度校核",
        "formula": "σ = N/A + My/(γx·Wx) + Mz/(γy·Wy)",
        "values": {"N": N, "A": A, "My": My, "Wx": Wx},
        "result": round(sigma, 2),
        "unit": "MPa"
    })

    # 稳定性校核
    # ...

    return {
        "stress_ratio": stress_ratio,
        "pass": True,
        "calc_processes": calc_processes,  # ← 前端可直接渲染
    }
```

### 12.3 hub 引用注入模式

对于需要在工具内部调用其他工具的 Server，从 `__init__` 注入 hub 引用：

```python
class LLMParamExtractor(CAIAOServer):
    """纯计算的参数提取器，通过 Hub 调用 llm_gateway"""

    def __init__(self, hub=None):
        super().__init__()
        self._hub = hub

    @tool(name="extract_params_from_text", ...)
    def extract_params_from_text(self, input_data: dict) -> dict:
        # 通过 Hub 调用 LLM Gateway（非直接 import）
        llm_response = self._hub.call_tool("chat_completion", {
            "messages": [{"role": "user", "content": input_data["prompt"]}],
            "system_prompt": self.SYSTEM_PROMPT,
        })
        return self._parse_and_validate(llm_response)

# Hub 注册时传入引用
hub = Hub()
extractor = LLMParamExtractor(hub=hub)
hub.register(extractor)
```

---

## 13. 检查清单

### 新增 Server 提交前确认

#### 代码层面

- [ ] Server 为单一 `.py` 文件，放在 `servers/` 目录
- [ ] 继承 `CAIAOServer`，覆盖类级元信息
- [ ] 使用 `@tool` 装饰注册所有公开工具
- [ ] 每个工具的 `name` 唯一 (snake_case)
- [ ] 每个工具的 `description` 写清功能和适用条件
- [ ] 每个工具的 `input_schema` 所有 `property` 有 `description`
- [ ] 每个工具的返回值为纯 dict（可 JSON 序列化）
- [ ] `__main__` 块支持独立启动（CLI 模式 + stdio 循环）
- [ ] 不 import 任何其他 Server
- [ ] 最低外部依赖（Python 标准库 + numpy 为上限）
- [ ] `server_type` 正确设置 (orchestration / computational)
- [ ] 计算型 Server 设置 `_caiao_subprocess = True`

#### 功能层面

- [ ] 可从 CLI 独立启动测试
- [ ] `list_tools()` 返回正确格式
- [ ] `call_tool()` 异常时返回 `{"error": "..."}`
- [ ] 边界情况处理（空输入、极值、非法参数）

#### 测试层面

- [ ] 至少一个单元测试用例
- [ ] 输入校验覆盖 空/错误/正常 三种情况
- [ ] 与上下游 JSON 数据能够串联

#### 文档层面

- [ ] 文件头注释标明蒸馏来源（如有）和蒸馏日期
- [ ] 类 docstring 简要描述功能和关键简化
- [ ] 标注依赖说明（如有前置条件）

#### 集成层面

- [ ] Hub 自动发现能正确注册（in_process 模式）
- [ ] 通过 Hub.call_tool() 调用成功
- [ ] Pipeline 中包含端到端测试验证

---

## 附录 A：项目文件结构参考

```
my-caiao-project/
├── caiao_hub.py                  # Hub 调度中心（只需一个，项目级别）
├── servers/
│   ├── __init__.py               # 包标记
│   ├── base.py                   # CAIAOServer 基类 + @tool 装饰器
│   ├── my_server_a.py            # 原子 Server A
│   ├── my_server_b.py            # 原子 Server B
│   └── my_pipeline.py            # 合并 Server (可选)
├── schemas/                      # JSON Schema 定义（推荐）
│   ├── input.schema.json
│   └── output.schema.json
├── tests/
│   └── test_servers.py
├── requirements.txt
└── README.md
```

移植到新项目时，至少需要拷贝 `servers/base.py` 和 `caiao_hub.py` 两个文件。

## 附录 B：与 MCP 协议的关系

```
          CAIAO                         MCP
  ┌───────────────────┐        ┌───────────────────┐
  │ 内部统一工具框架      │        │ AI 行业标准通信协议   │
  │ @tool 注册          │        │ stdio JSON-RPC     │
  │ list_tools()        │  ≈≈≈  │ tools/list         │
  │ call_tool()         │  ≈≈≈  │ tools/call         │
  │ get_metadata()      │        │ —                  │
  │ run_cli() 调试      │        │ —                  │
  └───────────────────┘        └───────────────────┘

CAIAO ≠ MCP 的替代品
CAIAO = 你现在就需要的开发框架 (Pipeline 编排、CLI 调试)
MCP   = 你将来接入 AI 助手的标准协议
两者接口已对齐，CAIAO Server 升级 MCP 只需换 transport 层 (0 行业务代码改动)
```

## 附录 C：常见问题

**Q1: 我的 Server 需要读取文件怎么办？**

> 通过 `input_data` 传入文件路径或直接传入数据内容。不硬编码路径，不依赖当前目录。

**Q2: 可以在一个 Server 里注册多个 tool 吗？**

> 可以，且推荐按功能类别组合。但每个 tool 必须是单一明确的职责。

**Q3: `server_type` 选错有什么影响？**

> 仅仅是声明式信息，不影响功能。它主要用于提示 Hub 是否应该用子进程隔离。

**Q4: 我的 Server 需要依赖第三方库怎么办？**

> 记录在 `requirements.txt` 中。但应尽量减少依赖，优先纯 Python 实现。必须依赖的外部库应在 Server docstring 中说明。

**Q5: `_caiao_subprocess` 和 `server_type` 的区别？**

> `server_type` = 声明式描述（给人类读的标签）。`_caiao_subprocess` = 控制 Hub 自动扫描行为（True → Hub 跳过，需手动通过 `register_subprocess()` 注册）。

---

> **本手册基于 Steel Frame Design 项目的 CAIAO v2.0 架构编写**  
> **编写日期**: 2026-05-28  
> **适用版本**: CAIAO Server Spec v1.0 / Hub v2.0
