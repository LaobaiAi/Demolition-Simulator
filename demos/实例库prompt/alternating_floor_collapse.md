# 隔层交替倒塌 — 完整 Prompt 流程

> 场景名：`alternating_floor_collapse` ｜ 类别：topology ｜ 渲染：WebGL
> 大型4跨4层钢框架。拆除顺序：4层 → 2层 → 3层 → 1层（隔层交替），制造连续渐进倒塌效果。电影级特效。

## 1. 触发话术

| 语言 | 话术 |
|---|---|
| 中文 | 做隔层交替倒塌演示 |
| English | Show alternating floor collapse |

## 2. 完整对话流（Phase 1-4）

```
用户:  做隔层交替倒塌演示
━━━ Phase 1 · 理解需求 ━━━
助手:  (调用 get_scenario("alternating_floor_collapse"))
       已找到预置场景：隔层交替倒塌
       - 4跨4层钢框架，6m 跨度，3m 层高，Q355
       - 拆除顺序：4层 → 2层 → 3层 → 1层（隔层交替）
       - 制造连续渐进倒塌效果，电影级特效
       是否开始？
用户:  开始
━━━ Phase 2 · 构建 ━━━
助手:  (调用 build_frame_model(mode="topology", structure_params=alternating_floor_collapse))
       ✅ 模型构建完成（4×4 框架）。
       默认拆除策略：隔层交替（4→2→3→1），是否执行？
用户:  执行
━━━ Phase 3 · 拆除 ━━━
助手:  (调用 visual_demolition(mode="topology", strategy="alternating", effects_preset="cinematic"))
       ✅ 第 1 轮：拆除第 4 层
       ✅ 第 2 轮：拆除第 2 层（隔层）
       ✅ 第 3 轮：拆除第 3 层
       ✅ 第 4 轮：拆除第 1 层
       ✅ 连续渐进倒塌动画完成
       ✅ 特效配置：cinematic
       播放动画预览成功，是否渲染成视频？
用户:  渲染
━━━ Phase 4 · 渲染 ━━━
助手:  (调用 run_pipeline_stage(stage="render"))
       ✅ 视频已输出：<输出路径>
```

## 3. 工具调用链（后端视角）

| # | 阶段 | 工具调用 | 后端实现 |
|---|---|---|---|
| 1 | Phase 1 | `get_scenario("alternating_floor_collapse")` | `scenario_server` 返回场景规格 |
| 2 | Phase 2 | `build_frame_model` | `blender_build_server`（WebGL 模式） |
| 3 | Phase 3 | `visual_demolition(strategy="alternating")` | `visual_demolition/caiao.yaml` 编排 |
| 4 | Phase 4 | `run_pipeline_stage(stage="render")` | 前端 WebGL / 视频输出 |

## 4. 场景参数明细

| 参数 | 值 |
|---|---|
| structure_params | type=steel, num_bays_x=4, num_stories=4, span_x_m=6.0, story_height_m=3.0, steel_grade=Q355 |
| strategy | **alternating**（隔层交替 4→2→3→1） |
| effects_preset | cinematic（全部特效） |
| speed | 1.0 |
| viz_mode | webgl |

## 5. 各环节输入→输出明细

| 环节 | 输入 | 输出 | 耗时参考 |
|---|---|---|---|
| Phase 1 场景匹配 | 用户话术 | 场景规格 + 确认询问 | <1s |
| Phase 2 构建 | 场景参数 | 4跨4层框架模型 | ~10s |
| Phase 3 拆除 | 模型 + alternating + cinematic | 隔层倒塌动画 + 特效 | ~1 min |
| Phase 4 渲染（可选） | 动画数据 | 视频 | 5-10 min |

## 6. 拆除要点

- **隔层交替顺序**：`4层 → 2层 → 3层 → 1层`，先拆 4、2 两层制造悬挂结构，再拆 3 层引发连锁，最后拆 1 层完成倒塌。
- **连续渐进倒塌**：每个拆除轮次之间结构保持部分完整，形成"渐进式"倒塌的视觉叙事。
- **纯拓扑**：不需要结构分析（`needs_analysis=false`）。
