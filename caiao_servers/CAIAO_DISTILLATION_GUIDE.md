# CAIAO 原子 Server 蒸馏与贡献指南

> 基于 Steel Frame Design 项目的实践经验，总结从大型系统中蒸馏领域能力、封装为 CAIAO 标准 Server 的完整方法论。

---

## 1. 什么是"蒸馏"

在 CAIAO 生态中，"蒸馏"是指：

**从已有的复杂系统（如 StructureClaw）中，提取某一领域能力的纯计算逻辑，去除多用户、数据库、网络、前端等运行时依赖，封装为一个独立、契约化、LLM 可直接调用的原子 Server。**

| 蒸馏前（源系统） | 蒸馏后（CAIAO Server） |
|:---|:---|
| 单体/微服务架构，依赖链路深 | 单一 `.py` 文件，零间接依赖 |
| 通过 HTTP/gRPC 通信 | 通过 `call_tool(name, input)` 进程内/stdio 通信 |
| 耦合业务逻辑与基础设施 | 纯计算逻辑，输入 JSON → 输出 JSON |
| 面向人类开发者调试 | AI-ready：工具描述 + JSON Schema 完备声明 |

---

## 2. 蒸馏全流程方法论

```
源系统分析 → 领域边界划分 → 数据模型抽象 → 独立实现 → 契约验证 → 编排演示
```

### Step 1: 源系统分析
深入研读源系统的：
- Skill / Plugin 定义文件（如 `skill.yaml`）
- 核心计算模块（后端算法代码）
- 数据模型（怎样表达领域实体）
- 调用链路（从触发到结果输出经历了哪些环节）

**本项目的经验**：分析 StructureClaw 的 `structure-type: frame`、`section`、`load-boundary`、`analysis`、`code-check`、`report` 六个技能包，提取钢框架特有的计算逻辑，忽略使用者管理、权限等基础设施。

### Step 2: 领域边界划分
将全流程拆解为 3-6 个原子能力，每个原子能力对应一个 Server：

**拆分原则：**
- **单一职责** — 一个 Server 只做一件事
- **无状态** — 输入足够，不依赖外部隐式状态
- **可独立验证** — 给定输入，输出可单独测试
- **自然边界** — 沿领域知识边界切分，不强行割裂或过度合并

```
❌ 错误示范：一个 Server 既建模又分析又出报告
✅ 正确示范：Generator → Loader → Runner → Checker → Reporter
```

### Step 3: 数据模型抽象
每个 Server 的输入/输出定义为 JSON Schema：

- **自描述** — 每个字段有 `description`，AI 可无歧义理解
- **最小完备** — 只包含必要字段，不冗余
- **类型严格** — 物理量用 `number`，索引用 `integer`，ID 用 `string`
- **可扩展** — 不设 `additionalProperties: false`

```json
{
  "$id": "https://caiao.io/schemas/steel-frame/model.schema.json",
  "title": "Steel Frame Model",
  "type": "object",
  "required": ["nodes", "elements", "sections", "materials"],
  "properties": {
    "nodes": {
      "type": "array",
      "description": "节点列表，每个节点含 3D 坐标",
      "items": { "$ref": "#/definitions/node" }
    }
  }
}
```

### Step 4: 独立实现
每个 Server 从零实现，**不 import 其他 Server，不依赖源系统**。

关键指导原则：
- **优先纯 Python** — 依赖项只保留 `numpy` 等基础库
- **降级方案内置** — 可选依赖（如 Jinja2）不可用时自动 fallback
- **内置数据** — 截面库、材料库等常用数据直接硬编码在 Server 内
- **简化为先** — 先用简化算法覆盖主要场景，预留扩展接口

### Step 5: 契约验证
使用 `jsonschema` 库对每个 Server 的输入输出做 Schema 校验，确保数据契约不会在串联时断裂。

### Step 6: 编排演示
新建一个 Pipeline Server（合并 Server），顺序调用原子 Server，本身不含计算逻辑。再通过 CLI 入口提供一键运行的展示能力。

---

## 3. 关键设计决策速查表

以下是我们蒸馏过程中遇到的典型岔路口及推荐选择：

| 决策点 | 选项 A | 选项 B | 本项目选择 | 理由 |
|:---|:---|:---|:---|:---|
| **FEA 引擎** | OpenSeesPy（外部库） | 自研矩阵位移法 | B | 零安装门槛，100% 纯 Python |
| **荷载计算** | 精确双向板导荷 | 简化等效法 | B | 演示精度足够，复杂度大幅降低 |
| **规范校核** | 完整实现 GB50017 全部条款 | 核心公式 + 预留扩展 | B | 覆盖主要场景，可持续迭代 |
| **Server 通信** | subprocess + JSON 管道 | 进程内直接调用 | B (当前阶段) | 开发效率高，已预留 MCP 升级路径 |
| **报告生成** | 纯 Jinja2 | Jinja2 + 字符串 fallback | B | 环境受限时仍可工作 |
| **截面/材料数据** | 外部 CSV/JSON 加载 | 硬编码内置数据 | B | 覆盖常用场景，无文件依赖 |

---

## 4. 标准化 Server 模板

新 Server 只需继承 `base.py`，用 `@tool` 装饰器注册工具：

```python
"""
my_domain_server.py — CAIAO 原子 Server

蒸馏来源：<源系统>/<技能路径>
蒸馏日期：YYYY-MM-DD
"""
import json
import sys
from servers.base import CAIAOServer, tool


class MyDomainServer(CAIAOServer):
    """<一句话描述这个 Server 做什么>"""

    def __init__(self):
        super().__init__()

    @tool(
        name="do_something",
        description="清晰描述工具功能，AI 可据此理解调用时机与参数含义",
        input_schema={
            "type": "object",
            "required": ["param_1", "param_2"],
            "properties": {
                "param_1": {"type": "number", "description": "参数 1 说明"},
                "param_2": {"type": "string", "description": "参数 2 说明"}
            }
        }
    )
    def do_something(self, input_data: dict) -> dict:
        """核心计算逻辑"""
        # 1. 输入校验
        # 2. 业务计算
        # 3. 构建输出（符合 Schema）
        return {"result": "..."}


if __name__ == "__main__":
    server = MyDomainServer()
    if len(sys.argv) >= 3:
        tool_name = sys.argv[1]
        input_json = sys.argv[2]
        result = server.call_tool(tool_name, json.loads(input_json))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(server.list_tools(), indent=2, ensure_ascii=False))
```

### 模板使用 Checklist

- [ ] `__init__` 中调用 `super().__init__()`
- [ ] 每个工具用 `@tool` 装饰，`name` 唯一
- [ ] `input_schema` 每个字段有 `description`
- [ ] 核心方法返回纯 dict（可 JSON 序列化）
- [ ] `__main__` 块提供独立启动能力
- [ ] 不 import 任何其他 Server
- [ ] 最低依赖（Python 标准库 + numpy 为上限）

---

## 5. 合并 Server (Pipeline) 模式

```python
class MyPipeline(CAIAOServer):
    def __init__(self):
        super().__init__()
        self._step_a = StepAServer()
        self._step_b = StepBServer()
        self._step_c = StepCServer()

    @tool(name="run_pipeline", ...)
    def run_pipeline(self, input_data: dict) -> dict:
        out_a = self._step_a.call_tool("do_a", input_data)
        out_b = self._step_b.call_tool("do_b", {**input_data, **out_a})
        out_c = self._step_c.call_tool("do_c", out_b)
        return {"a": out_a, "b": out_b, "c": out_c}
```

**Pipeline Server 的铁律：**
- 不含任何领域计算逻辑
- 只做数据传递和顺序编排
- 下游输入 = 上游输出 + 原始参数（必要时 merge）

---

## 6. 向 MCP 升级的路径

当前所有 Server 已在接口层面就绪，迁移到 MCP 只需：

```
当前: Pipeline 中直接 import 并实例化
  ↓
步骤 1: 将 Server 作为 stdio 子进程启动
步骤 2: 通过 stdin/stdout JSON-RPC 通信
步骤 3: 注册到 CAIAO Hub / MCP Client
```

由于：
- 每个 Server 的 `__main__` 块已支持命令行 JSON 交互
- `list_tools()` 输出格式与 MCP `tools/list` 兼容
- `call_tool(name, input)` 与 MCP `tools/call` 语义一致

→ **无需改动 Server 内部代码，只需在外层套一层 MCP stdio transport。**

### 6.1 为什么需要 CAIAO 这层抽象？为什么不直接做成 MCP Server？

详细讨论见 `docs/DEVELOPMENT_MANUAL.md` 第 5.4 节「CAIAO 与 MCP 常见问答」。简要来说：

- CAIAO = 内部统一工具框架（现在就被 Pipeline 编排和 CLI 调试使用）
- MCP = 外部 AI 通信协议（仅在需要 AI 直接调用工具时才启用）
- `run_stdio_loop()` 中的手写 JSON-RPC 循环是"协议质检"——验证 CAIAO 接口与 MCP 对齐后，将来换 MCP SDK 的 transport 即可，业务逻辑零改动。

两者不是替代关系，而是**内部框架（CAIAO）+ 标准通信（MCP）**的分层设计：CAIAO 提供 `@tool` 注册、自动发现、统一调用等开发体验；MCP 提供 AI 生态的互通能力。

---

## 7. 常见陷阱与对策

| 陷阱 | 症状 | 对策 |
|:---|:---|:---|
| **依赖残留** | Server A import Server B 的类，导致无法独立运行 | 纯逻辑提取为独立工具函数，公共函数放 `base.py` 或单独 `utils.py` |
| **Schema 漂移** | Pipeline 串联时下游解析上游输出失败 | 每个 Server 输出后做 `jsonschema.validate()`，开发阶段即发现不匹配 |
| **硬编码路径** | 输出文件写到绝对路径，他人运行报错 | 输出目录通过参数传入，默认值用 `./output` |
| **AI 描述不足** | LLM Agent 不知道何时调用该工具 | `@tool` 的 `description` 写清：输入含义、输出含义、适用场景 |
| **过度简化** | 算法太简陋，演示效果差 | 核心计算（如刚度矩阵）可参考教材标准实现，不自行缩减 |
| **边界处理遗漏** | 零跨、单层、极端截面等情况崩溃 | 实现时考虑边界：最小/最大尺寸、空数组、特殊字符 |

---

## 8. 蒸馏效率经验值

基于本项目实际耗时，一个完整蒸馏项目的工作量估算：

| 阶段 | 参考工时 | 关键耗时 |
|:---|:---:|:---|
| 源系统分析 | 1-2h | 理解原系统数据流和算法粒度 |
| Schema 设计 | 1-2h | 与源系统数据结构对齐 |
| 原子 Server 实现（每 Server） | 1-3h | 算法翻译 + 边界处理 |
| Pipeline 编排 | 0.5-1h | 数据串联和错误传递 |
| CLI + 输出 | 1h | 美化输出、文件组织 |
| 测试 + 文档 | 1-2h | 端到端验证 |
| **合计** | **10-20h** | （3-5 个原子 Server 规模） |

---

## 9. 为生态贡献的检查清单

向 CAIAO Server 生态贡献一个新蒸馏 Server 时，请确认：

### 代码层面
- [ ] Server 为单一 `.py` 文件
- [ ] 继承 `CAIAOServer`，使用 `@tool` 注册
- [ ] 输入输出有完整 JSON Schema
- [ ] `__main__` 块支持独立启动和 JSON 交互
- [ ] 零间接依赖，最低外部库
- [ ] 纯计算逻辑，无 GUI / 网络 / 文件系统强制依赖

### 文档层面
- [ ] 每个工具 `description` 写清楚功能和适用条件
- [ ] 提供输入/输出样例
- [ ] 标注蒸馏来源（源系统 + 技能路径）
- [ ] 记录关键简化假设及其影响

### 测试层面
- [ ] 至少一个单元测试用例
- [ ] 输入输出 Schema 验证通过
- [ ] 边界情况覆盖（空输入、极值、非法输入）

### 集成层面
- [ ] 可从 CLI 独立启动
- [ ] 可与上下游 Server 通过 JSON 串联
- [ ] Pipeline 中包含该 Server 的端到端测试

---

## 10. 本项目的完整蒸馏成果

| 源系统技能 | 蒸馏产物 | Server 文件 | 关键取舍 |
|:---|:---|:---|:---|
| `structure-type: frame` + `section` | 参数化建模 | `steel_frame_generator.py` | 规则网格、7 种截面硬编码 |
| `load-boundary` | 荷载施加 | `steel_load_generator.py` | 简化从属面积法 |
| `analysis` (OpenSees) | 有限元分析 | `opensees_runner.py` | 自研矩阵位移法替代 |
| `code-check` | GB50017 校核 | `steel_code_check.py` | 核心公式简化实现 |
| `report` | 报告生成 | `report_generator.py` | Jinja2 + fallback |
| — | 流程编排 | `steel_frame_pipeline.py` | 合并 Server，仅编排 |

> 本项目是 CAIAO 原子 Server 哲学在结构工程领域的首次落地。期待这套方法论和模板能够降低未来贡献者的门槛，让更多领域能力以标准化的方式汇入 CAIAO 生态。
