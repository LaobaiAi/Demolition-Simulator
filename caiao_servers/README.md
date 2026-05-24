# CAIAO Servers

每个 CAIAO Server 是一个独立的 stdio 子进程，通过 MCP 协议与 CAIAOClientHub 通信。LLM 通过 AgentLoop 按需调度，互不耦合。

## Server 清单

| Server | 工具 | 用途 | 懒启动 |
|--------|------|------|--------|
| `anastruct_server` | `generate_simple_frame`, `analyze_frame`, `select_critical_element` | 快速 2D 线弹性分析，单榀框架首选 | -- |
| `frame_generator` | `generate_frame`, `generate_frame_3d`, `generate_from_text`, `list_materials` | 参数化框架生成，支持多跨多榀、材料选型 | -- |
| `opensees_server` | `high_fidelity_analysis` | OpenSeesPy 高精度 2D 线弹性验证 | ✓ |
| `pynite_server` | `pynite_analysis` | PyNiteFEA 3D 线弹性交叉验证 | ✓ |
| `fapp_server` | `fapp_analysis` | FAPP 直接刚度法 3D 线弹性交叉验证 | ✓ |
| `unity_simulator` | `apply_demolition_action` | 拆除动作 + 结构修改 + Unity TCP 通信 | ✓ |
| `demo_calculator` | 示例 | 开发测试用 demo | -- |

## 添加新 Server

```bash
cp -r caiao_servers/_template caiao_servers/my_solver
```

1. 编辑 `server.py`，实现 `list_tools()` 和 `call_tool()`
2. 在 `gateway/main.py` 的 `SERVER_CONFIGS` 中注册
3. 如需延迟启动（节省资源），设置 `"lazy": True`

## 设计原则

- 每个 Server 只做一件事
- 输出格式兼容下游（节点/单元/荷载/约束）
- 注册即可用，不改核心代码
