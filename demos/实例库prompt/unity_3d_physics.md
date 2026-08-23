# 3D Unity 物理仿真 — 完整 Prompt 流程

> 场景名：`unity_3d_physics` ｜ 类别：mechanics ｜ 渲染：Unity 3D
> 3x4柱网4层钢框架，完整结构分析 + Unity 实时物理仿真。需 Unity 编辑器运行中。

## 1. 触发话术

| 语言 | 话术 |
|---|---|
| 中文 | 用 Unity 做 3D 物理拆除 |
| English | Run a Unity 3D physics simulation |

## 2. 完整对话流（Phase 1-4）

```
用户:  用 Unity 做 3D 物理拆除
━━━ Phase 1 · 理解需求 ━━━
助手:  (调用 get_scenario("unity_3d_physics"))
       已找到预置场景：3D Unity 物理仿真
       - 3x4 柱网、4层钢框架，6m 跨度，3m 层高，Q355
       - 完整结构分析 + Unity 实时物理仿真
       - 需要 Unity 编辑器运行中
       （检查 Unity 环境）
       检测到 Unity 就绪，是否开始？
用户:  开始
━━━ Phase 2 · 构建 + 分析 ━━━
助手:  (调用 build_frame_model(mode="mechanics", structure_params=unity_3d_physics))
       ✅ 模型构建完成（3×4 柱网、4 层）。
       (调用 analyze_structure)
       ✅ 完整结构分析完成：已生成应力分布报告。
       拆除策略：最弱优先（逐轮分析），是否执行？
用户:  执行
━━━ Phase 3 · 拆除 + Unity 仿真 ━━━
助手:  (调用 plan_demolition_sequence(strategy="weakest_first"))
       ✅ 拆除计划完成（多轮分析直到倒塌）。
       (调用 unity 桥接：导出模型 → Unity 物理引擎实时仿真)
       ✅ Unity 实时物理仿真运行中：构件按物理定律倒塌（重力、碰撞）
       ✅ 特效配置：Unity 物理特效
       是否渲染/导出仿真结果？
用户:  导出
━━━ Phase 4 · 导出 ━━━
助手:  ✅ Unity 仿真已导出：<输出路径>
```

## 3. 工具调用链（后端视角）

| # | 阶段 | 工具调用 | 后端实现 |
|---|---|---|---|
| 1 | Phase 1 | `get_scenario("unity_3d_physics")` | `scenario_server` 返回场景规格 |
| 2 | Phase 2 | `build_frame_model(mode="mechanics")` + 结构分析 | `blender_build_server` + 分析服务器 |
| 3 | Phase 3 | `plan_demolition_sequence(strategy="weakest_first")` | `planning_server` |
| 4 | Phase 3 | Unity 桥接（模型导出 + 实时物理） | `unity_bridge_server` / 前端 Unity WebGL |
| 5 | Phase 4 | 仿真导出 | Unity 场景导出 |

## 4. 场景参数明细

| 参数 | 值 |
|---|---|
| structure_params | type=steel, num_bays_x=3, num_bays_z=4, num_stories=4, span_x_m=6.0, story_height_m=3.0, steel_grade=Q355 |
| strategy | weakest_first（最弱优先，逐轮分析） |
| effects_preset | unity_physics（重力/碰撞/物理特效） |
| speed | 1.0 |
| viz_mode | **unity** |
| needs_analysis | **true**（完整结构分析） |

## 5. 各环节输入→输出明细

| 环节 | 输入 | 输出 | 耗时参考 |
|---|---|---|---|
| Phase 1 场景匹配 + 环境检查 | 用户话术 | 场景规格 + Unity 就绪确认 | <1s |
| Phase 2 构建 + 分析 | 场景参数 | 模型 + 应力报告 | ~1-2 min |
| Phase 3 拆除 + 物理仿真 | 模型 + 应力数据 | 拆除计划 + Unity 实时物理 | 实时 |
| Phase 4 导出（可选） | 仿真数据 | Unity 场景/视频 | 5-10 min |

## 6. 拆除要点

- **完整力学分析**：`needs_analysis=true`，走 mechanics 模式，生成应力分布报告。
- **Unity 实时物理**：拆除过程由 Unity 物理引擎驱动（重力、碰撞、刚体动力学），非预编程动画。
- **前置条件**：需要 Unity 编辑器运行中（由启动脚本 `-Unity` 选项拉起）。
