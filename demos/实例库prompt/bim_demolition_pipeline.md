# BIM 拆除管线 — 完整 Prompt 流程

> 内置 Demo ｜ BIM 结构模型 ｜ 管线：full_bim_demolition
> 生成详细 BIM 结构模型（钢结构/混凝土/混合），规划拆除顺序，创建动画时间线 — 完整 BIM 到拆除工作流。

## 1. 触发方式

| 方式 | 内容 |
|---|---|
| 前端 | 实例库卡片「BIM 拆除管线」点击运行 |
| 底层消息 | `launch_pipeline` → pipeline=`full_bim_demolition`，params: mode=topology, structure_type=steel, strategy=top_down, effects_preset=standard, speed=1.0 |

## 2. 完整流程（BIM Model → Plan → Timeline）

```
━━━ Phase 1 · BIM 建模（BIM Model）━━━
助手:  (调用 bim_model_server.generate_steel_frame)
       ✅ BIM 结构模型已生成（钢结构，可切换混凝土/混合）
       - 含 IFC 导出
━━━ Phase 2 · 规划（Plan）━━━
助手:  (调用 planning_server.plan_demolition_sequence)
       ✅ 拆除顺序已规划（strategy: top_down）
━━━ Phase 3 · 时间线（Timeline）━━━
助手:  (调用 animation_control_server.create_timeline)
       ✅ 动画时间线已创建（effects_preset: standard）
```

## 3. 工具调用链（caiao.yaml 编排）

| 步骤 | 服务器 | 工具 | 输入 → 输出 |
|---|---|---|---|
| 1 | `bim_model_server` | `generate_steel_frame` | `structure_type=steel` → BIM 模型 |
| 2 | `planning_server` | `plan_demolition_sequence` | `structure + strategy(top_down)` → `demolition_plan` |
| 3 | `animation_control_server` | `create_timeline` | `demolition_plan + effects_preset(standard)` → `timeline` |

**可切换结构类型：** `generate_steel_frame`（钢结构）/ `generate_concrete_structure`（混凝土）/ `generate_hybrid_structure`（混合）。

## 4. 参数明细

| 参数 | 值 |
|---|---|
| pipeline | full_bim_demolition |
| mode | topology |
| structure_type | steel（可 steel / concrete / hybrid） |
| strategy | top_down |
| effects_preset | standard |
| speed | 1.0 |
| viz_mode | 3d（模型/时间线可视化） |

## 5. 各环节输入→输出明细

| 环节 | 输入 | 输出 |
|---|---|---|
| BIM 建模 | structure_type | BIM 结构模型 + IFC |
| 规划 | BIM 模型 + 策略 | 拆除顺序计划 |
| 时间线 | 拆除计划 + 特效预设 | 动画时间线 |
