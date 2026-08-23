# 完整结构拆除 — 完整 Prompt 流程

> 场景名：`full_structural` ｜ 类别：mechanics ｜ 渲染：WebGL
> 大型4跨6层钢框架，完整结构分析。最弱优先策略——每轮拆除应力最大的构件，重新分析，循环直到倒塌。

## 1. 触发话术

| 语言 | 话术 |
|---|---|
| 中文 | 做完整结构分析拆除 |
| English | Run a full structural demolition |

## 2. 完整对话流（Phase 1-4）

```
用户:  做完整结构分析拆除
━━━ Phase 1 · 理解需求 ━━━
助手:  (调用 get_scenario("full_structural"))
       已找到预置场景：完整结构拆除
       - 4跨6层钢框架，6m 跨度，3m 层高，Q355
       - 最弱优先策略：每轮拆应力最大的构件并重新分析，直到倒塌
       - 需要完整结构分析（约需 1-2 分钟/轮）
       是否开始？
用户:  开始
━━━ Phase 2 · 构建 + 初始分析 ━━━
助手:  (调用 build_frame_model(mode="mechanics", structure_params=full_structural))
       ✅ 模型构建完成（4×6 框架）。
       (调用 analyze_structure / run_full_analysis)
       ✅ 初始分析完成：已识别应力分布，将优先拆除最弱构件。
━━━ Phase 3 · 拆除（逐轮循环）━━━
助手:  (调用 plan_demolition_sequence(strategy="weakest_first"))
       ✅ 第 1 轮：拆除应力最大构件 → 重新分析 → 结构位移增大
       ✅ 第 2 轮：拆除下一最弱构件 → 重新分析 → …
       ...（循环直到倒塌判定）
       ✅ 倒塌判定达成，拆除计划完成。
       播放动画预览成功，是否渲染成视频？
用户:  渲染
━━━ Phase 4 · 渲染 ━━━
助手:  (调用 run_pipeline_stage(stage="render"))
       ✅ 视频已输出：<输出路径>
```

## 3. 工具调用链（后端视角）

| # | 阶段 | 工具调用 | 后端实现 |
|---|---|---|---|
| 1 | Phase 1 | `get_scenario("full_structural")` | `scenario_server` 返回场景规格 |
| 2 | Phase 2 | `build_frame_model(mode="mechanics")` + 结构分析 | `blender_build_server` + 分析服务器 |
| 3 | Phase 3 | `plan_demolition_sequence(strategy="weakest_first")` | `planning_server`（逐轮分析循环） |
| 4 | Phase 3 | `create_timeline` + `sequence_to_animation_data` + `generate_effects_config` | `animation_control_server` |
| 5 | Phase 4 | `run_pipeline_stage(stage="render")` | 前端 WebGL / 视频输出 |

## 4. 场景参数明细

| 参数 | 值 |
|---|---|
| structure_params | type=steel, num_bays_x=4, num_stories=6, span_x_m=6.0, story_height_m=3.0, steel_grade=Q355 |
| strategy | weakest_first（最弱优先，逐轮分析） |
| effects_preset | standard |
| speed | 1.0 |
| viz_mode | webgl |
| needs_analysis | **true**（完整结构分析） |

## 5. 各环节输入→输出明细

| 环节 | 输入 | 输出 | 耗时参考 |
|---|---|---|---|
| Phase 1 场景匹配 | 用户话术 | 场景规格 + 确认询问 | <1s |
| Phase 2 构建 + 分析 | 场景参数 | 模型 + 应力分布 | ~1-2 min |
| Phase 3 逐轮拆除 | 模型 + 应力数据 | 多轮拆除计划（直到倒塌） | 每轮 1-2 min |
| Phase 3 动画 | 拆除计划 | 动画数据 + 特效 | ~1 min |
| Phase 4 渲染（可选） | 动画数据 | 视频 | 5-10 min |

## 6. 拆除要点

- **最弱优先循环**：`拆除最弱构件 → 重新分析 → 再拆 → 再分析`，直到结构整体倒塌判定。
- **需要分析**：`needs_analysis=true`，走 mechanics 模式，每轮都有完整力学分析。
- **适合**：验证"逐步失效导致连锁倒塌"的结构工程场景。
