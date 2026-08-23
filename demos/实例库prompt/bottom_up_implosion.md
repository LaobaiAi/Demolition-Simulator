# 底部爆破内塌 — 完整 Prompt 流程

> 场景名：`bottom_up_implosion` ｜ 类别：topology ｜ 渲染：WebGL
> 中型3跨4层钢框架，自下而上拆除模拟内爆。先拆底层柱，上部结构向内倒塌。电影级特效，不需要分析。

## 1. 触发话术

| 语言 | 话术 |
|---|---|
| 中文 | 模拟底部爆破内塌 |
| English | Simulate a bottom-up implosion |

## 2. 完整对话流（Phase 1-4）

```
用户:  模拟底部爆破内塌
━━━ Phase 1 · 理解需求 ━━━
助手:  (调用 get_scenario("bottom_up_implosion"))
       已找到预置场景：底部爆破内塌
       - 3跨4层钢框架，6m 跨度，3m 层高，Q355
       - 先拆底层柱，上部结构向内倒塌（模拟内爆）
       - 电影级特效，无需结构分析
       是否开始？
用户:  开始
━━━ Phase 2 · 构建 ━━━
助手:  (调用 build_frame_model(mode="topology", structure_params=bottom_up_implosion))
       ✅ 模型构建完成（3×4 框架）。
       默认拆除策略：自下而上（先拆底层柱），是否执行？
用户:  执行
━━━ Phase 3 · 拆除 ━━━
助手:  (调用 visual_demolition(mode="topology", strategy="bottom_up", effects_preset="cinematic"))
       ✅ 拆除计划完成：先拆底层柱 → 上层向内塌落
       ✅ 动画时间线完成
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
| 1 | Phase 1 | `get_scenario("bottom_up_implosion")` | `scenario_server` 返回场景规格 |
| 2 | Phase 2 | `build_frame_model` | `blender_build_server`（WebGL 模式） |
| 3 | Phase 3 | `visual_demolition(strategy="bottom_up")` | `visual_demolition/caiao.yaml` 编排 |
| 4 | Phase 4 | `run_pipeline_stage(stage="render")` | 前端 WebGL / 视频输出 |

## 4. 场景参数明细

| 参数 | 值 |
|---|---|
| structure_params | type=steel, num_bays_x=3, num_stories=4, span_x_m=6.0, story_height_m=3.0, steel_grade=Q355 |
| strategy | **bottom_up**（自下而上） |
| effects_preset | cinematic（全部特效） |
| speed | 1.0 |
| viz_mode | webgl |

## 5. 各环节输入→输出明细

| 环节 | 输入 | 输出 | 耗时参考 |
|---|---|---|---|
| Phase 1 场景匹配 | 用户话术 | 场景规格 + 确认询问 | <1s |
| Phase 2 构建 | 场景参数 | 3跨4层框架模型 | ~10s |
| Phase 3 拆除 | 模型 + bottom_up + cinematic | 内塌动画 + 特效 | ~1 min |
| Phase 4 渲染（可选） | 动画数据 | 视频 | 5-10 min |

## 6. 拆除要点

- **内爆模拟**：先拆**底层柱**（模拟爆破点），上部结构因失去支撑**向内倒塌**，形成经典内爆效果。
- **电影级特效**：cinematic 预设全开（粒子、灰尘、震动、闪光等）。
- **纯拓扑**：不需要结构分析（`needs_analysis=false`）。
