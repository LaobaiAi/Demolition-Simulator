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
| `unity_simulator` | `apply_demolition_action` 等 4 个 | 拆除动作 + 结构修改 + Unity TCP 通信 | ✓ |
| `quick_analysis_server` | `quick_analysis` | ⚡ Pipeline A: generate + analyze + select_critical 合并 | -- |
| `full_analysis_3d_server` | `full_analysis_3d` | ⚡ Pipeline B: 3D 生成 → UnifiedFrame → PyNite → 选柱 | -- |
| `manager_server` | 24 个工具 | 元 Server: 创建/扩展/健康/迁移/检索/编排 | -- |
| `blender_environment_server` | 4 个工具 | 🔧 Blender 环境发现 + 校验 (infrastructure) | -- |
| `blender_build_server` | `build_frame_model` | Blender 框架建模 | ✓ |
| `blender_animate_server` | `apply_demolition_sequence` | Blender 拆除动画 | ✓ |
| `blender_machinery_server` | `add_construction_machinery` | Blender 施工机械 | ✓ |
| `blender_render_server` | `render_animation`, `render_preview` | Blender 渲染 | ✓ |
| `blender_pipeline_server` | 3 个工具 | Blender 全流程编排 | ✓ |
| `abaqus_environment_server` | 3 个工具 | 🔧 Abaqus 环境发现 + 校验 (infrastructure) | -- |
| `abaqus_session_server` | 15 个工具 | ⚡ Abaqus CAE 持久会话: 建模+分析+拆除 (merged) | ✓ |
| `abaqus_collapse_pipeline` | `run_abaqus_collapse` | Abaqus 倒塌全流程编排 (composite) | -- |

## 添加新 Server

```bash
cp -r caiao_servers/_template caiao_servers/my_solver
```

1. 编辑 `server.py`，实现 `list_tools()` 和 `call_tool()`
2. 创建 `caiao.yaml` manifest（参考 `_template/caiao.yaml`）→ Gateway 启动时自动发现
3. 如需延迟启动（节省资源），设置 `start_mode: lazy`

## 设计原则

- 每个 Server 只做一件事
- 输出格式兼容下游（节点/单元/荷载/约束）
- 注册即可用，不改核心代码
