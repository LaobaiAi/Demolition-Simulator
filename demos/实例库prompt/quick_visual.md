# 快速可视化倒塌 — 完整 Prompt 流程

> 场景名：`quick_visual` ｜ 类别：topology ｜ 渲染：WebGL
> 小型2跨3层钢框架，自上而下拆除，标准特效。最快看到视觉结果，不需要结构分析。

## 1. 触发话术

| 语言 | 话术 |
|---|---|
| 中文 | 做个快速倒塌演示 / 来个最简单的拆除动画 |
| English | Show a quick visual collapse |

## 2. 完整对话流（Phase 1-4）

```
用户:  来个最简单的拆除动画
━━━ Phase 1 · 理解需求 ━━━
助手:  (调用 get_scenario("quick_visual"))
       已找到预置场景：快速可视化倒塌
       - 2跨3层钢框架，6m 跨度，3m 层高，Q355
       - 自上而下拆除，标准特效，无需结构分析
       是否开始？
用户:  开始
━━━ Phase 2 · 构建 ━━━
助手:  (调用 build_frame_model(mode="topology", structure_params=quick_visual))
       ✅ 模型构建完成（2×3 框架）。
       默认拆除策略：自上而下，是否执行？
用户:  执行
━━━ Phase 3 · 拆除 ━━━
助手:  (调用 visual_demolition(mode="topology", strategy="top_down", effects_preset="standard"))
       ✅ 拆除计划完成
       ✅ 动画时间线完成
       ✅ 特效配置：标准
       播放动画预览成功，是否渲染成视频？
用户:  不用了，就这样
━━━ Phase 4 · 完成 ━━━
助手:  ✅ 演示完成，动画已在前端播放。
```

## 3. 工具调用链（后端视角）

| # | 阶段 | 工具调用 | 后端实现 |
|---|---|---|---|
| 1 | Phase 1 | `get_scenario("quick_visual")` | `scenario_server` 返回场景规格 |
| 2 | Phase 2 | `build_frame_model` | `blender_build_server`（WebGL 轻量模式） |
| 3 | Phase 3 | `visual_demolition` | `visual_demolition/caiao.yaml` 编排 |
| 4 | Phase 4 | `run_pipeline_stage(stage="render")`（可选） | 前端 WebGL 动画 / 视频输出 |

## 4. 场景参数明细

| 参数 | 值 |
|---|---|
| structure_params | type=steel, num_bays_x=2, num_stories=3, span_x_m=6.0, story_height_m=3.0, steel_grade=Q355 |
| strategy | top_down（自上而下） |
| effects_preset | standard（cascade/explosion/dust/buckling/fracture 开） |
| speed | 1.0 |
| viz_mode | webgl |

## 5. 各环节输入→输出明细

| 环节 | 输入 | 输出 | 耗时参考 |
|---|---|---|---|
| Phase 1 场景匹配 | 用户话术 | 场景规格 + 确认询问 | <1s |
| Phase 2 构建 | 场景参数 | 2跨3层框架模型 | ~10s |
| Phase 3 拆除 | 模型 + top_down | 动画数据 + 特效 | ~30s |
| Phase 4 渲染（可选） | 动画数据 | 视频 | 1-5 min |

## 6. 拆除要点

- **最短路径**：从顶层屋面开始，逐层向下拆除，每轮拆当前层所有构件。
- **无分析**：纯拓扑驱动（`needs_analysis=false`），适合快速验证视觉流程。
