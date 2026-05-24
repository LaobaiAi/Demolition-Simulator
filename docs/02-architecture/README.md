# 系统架构

## 核心理念：一切皆 CAIAO Server

**CAIAO** 是项目自定义的抽象层，底层使用标准 MCP 协议。

```
User → Frontend → WebSocket → Gateway AgentLoop → LLM (decides tool)
       → CAIAOClientHub → CAIAO Server 子进程 (stdio) → Result → User
```

LLM 不直接调用任何工具，而是通过 AgentLoop → CAIAOClientHub 分发到各子进程。

## 组件清单

| 组件 | 目录 | 技术栈 | 类型 |
|------|------|--------|------|
| Gateway | `gateway/` | FastAPI + WebSocket | 中央路由 |
| Agent Loop | `gateway/agent_loop.py` | ReAct (think→act→observe) | 业务编排 |
| LLM Engine | `gateway/llm_engine.py` | OpenAI SDK | LLM 封装 |
| Memory | `gateway/memory.py` | mem0 + local JSON fallback | 记忆管理 |
| CAIAO Hub | `gateway/caiao_hub.py` | MCP Client | 服务器管理 |
| anaStruct Server | `caiao_servers/anastruct_server/` | anaStruct | 快速线性分析 |
| OpenSees Server | `caiao_servers/opensees_server/` | OpenSeesPy | 高精度验证 |
| Frame Generator | `caiao_servers/frame_generator/` | 算法生成 | 框架结构生成 |
| Unity Simulator | `caiao_servers/unity_simulator/` | TCP + Unity | 3D 物理拆除 |
| Frontend | `frontend/` | Next.js + Tailwind | Web UI |

## 数据流

```
用户输入 → WebSocket → Gateway → LLM 推理
                                  │
                                  ▼
                           需要调用工具？
                                  │
                           ┌──────┴──────┐
                           ▼              ▼
                         CAIAO Hub   直接回复
                           │
                           ▼
                    CAIAO Server 子进程
                           │
                           ▼
                    结果返回 → LLM 继续推理 → 最终回复
                                               │
                                               ▼
                                         WebSocket → 前端渲染
```

## 关键设计决策

- **无中心数据库**：对话存储在 localStorage，服务器状态在 local_memory.json
- **懒加载**：OpenSees、PyNite、Unity 等重型 CAIAO Server 按需启动
- **双轨验证**：快速分析 (anaStruct) + 高精度分析 (OpenSees) 同时运行，对比结果

详情见 [ARCHITECTURE.md](../ARCHITECTURE.md) 和 [dev-notes/architecture/](../dev-notes/architecture/)。
