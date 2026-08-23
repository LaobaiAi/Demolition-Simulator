# 电影级倒塌 — 完整 Prompt 流程

> 场景名：`cinematic_collapse` ｜ 类别：topology ｜ 渲染：WebGL
> 中型3跨4层钢框架，启用全部视觉特效（粒子/灰尘/音效/震动/屈曲/断裂）。自上而下拆除，延长动画时间增强戏剧效果。

## 1. 触发话术

| 语言 | 话术 |
|---|---|
| 中文 | 来个电影级倒塌效果 |
| English | Make a cinematic collapse |

## 2. 完整对话流（Phase 1-4）

```
用户:  来个电影级倒塌效果
━━━ Phase 1 · 理解需求 ━━━
助手:  (调用 get_scenario("cinematic_collapse"))
       已找到预置场景：电影级倒塌
       - 3跨4层钢框架，6m 跨度，3m 层高，Q355
       - 全部特效开启：粒子、灰尘、音效、震动、屈曲、断裂、闪光、轨迹、弹跳
       - 慢速动画（0.5 倍速）增强戏剧效果
       是否开始？
用户:  开始
━━━ Phase 2 · 构建 ━━━
助手:  (调用 build_frame_model(mode="topology", structure_params=cinematic_collapse))
       ✅ 模型构建完成（3×4 框架）。
       默认拆除策略：自上而下 + 电影级特效，是否执行？
用户:  执行
━━━ Phase 3 · 拆除 ━━━
助手:  (调用 visual_demolition(mode="topology", strategy="top_down", effects_preset="cinematic", speed=0.5))
       ✅ 拆除计划完成
       ✅ 动画时间线完成（慢速，戏剧化节奏）
       ✅ 特效配置：cinematic（全部开启）
       播放动画预览成功，是否渲染成视频？
用户:  渲染
━━━ Phase 4 · 渲染 ━━━
助手:  (调用 run_pipeline_stage(stage="render"))
       ✅ 视频已输出：<输出路径>
```

## 3. 工具调用链（后端视角）

| # | 阶段 | 工具调用 | 后端实现 |
|---|---|---|---|
| 1 | Phase 1 | `get_scenario("cinematic_collapse")` | `scenario_server` 返回场景规格 |
| 2 | Phase 2 | `build_frame_model` | `blender_build_server`（WebGL 模式） |
| 3 | Phase 3 | `visual_demolition` | `visual_demolition/caiao.yaml` 编排 |
| 4 | Phase 4 | `run_pipeline_stage(stage="render")` | 前端 WebGL / 视频输出 |

## 4. 场景参数明细

| 参数 | 值 |
|---|---|
| structure_params | type=steel, num_bays_x=3, num_stories=4, span_x_m=6.0, story_height_m=3.0, steel_grade=Q355 |
| strategy | top_down（自上而下） |
| effects_preset | **cinematic**（cascade/explosion/dust/shake/buckling/fracture/flash/trail/bounce 全部开启） |
| speed | **0.5**（慢速，延长动画时长） |
| viz_mode | webgl |

## 5. 各环节输入→输出明细

| 环节 | 输入 | 输出 | 耗时参考 |
|---|---|---|---|
| Phase 1 场景匹配 | 用户话术 | 场景规格 + 确认询问 | <1s |
| Phase 2 构建 | 场景参数 | 3跨4层框架模型 | ~10s |
| Phase 3 拆除 | 模型 + top_down + cinematic | 动画数据 + 全套特效 | ~1 min |
| Phase 4 渲染（可选） | 动画数据 | 视频 | 5-10 min |

## 6. 拆除要点

- **全部特效**：粒子（particles）、灰尘（dust）、音效（sound）、震动（shake）、屈曲（buckling）、断裂（fracture）、闪光（flash）、轨迹（trail）、弹跳（bounce）全开。
- **慢速戏剧化**：`speed=0.5`，每个拆除步骤的动画时长翻倍，增强视觉冲击。
- **纯视觉**：拓扑驱动，不需要结构分析（`needs_analysis=false`）。
