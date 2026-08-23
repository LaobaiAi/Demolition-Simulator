# 蒸汽轮机厂房 — 完整 Prompt 流程

> 场景名：`steam_turbine_building` ｜ 类别：topology ｜ 渲染：Blender 管线
> 24榀x3轴(A/B/C)大型工业厂房，AB跨24m钢屋架(脊高27m)，BC跨9m平梁(8m/15m楼板)，柱高25m，共480构件。

## 1. 触发话术

| 语言 | 话术 |
|---|---|
| 中文 | 生成一个蒸汽轮机厂房的拆除演示 |
| English | Build a steam turbine building demolition demo |

## 2. 完整对话流（Phase 1-4）

```
用户:  生成一个蒸汽轮机厂房的拆除演示
━━━ Phase 1 · 理解需求 ━━━
助手:  (调用 get_scenario("steam_turbine_building"))
       已找到预置场景：蒸汽轮机厂房
       - 24榀 × 3轴(A/B/C)，AB跨 24m 钢屋架(脊高27m)，BC跨 9m 平梁(8m/15m楼板)，柱高 25m
       - 共 480 构件（72柱+69纵梁+144屋架+24BC梁+46BC楼板+69屋面板+46墙板+10山墙/抗风柱）
       是否开始构建模型？
用户:  开始
━━━ Phase 2 · 构建 ━━━
助手:  (调用 build_frame_model(building_type="steam_turbine"))
       ✅ 模型构建完成！已生成 480 个构件。
       默认拆除策略：西→东、自上而下（C 轴柱最后保留），速度分区正常+加速，是否执行？
用户:  执行
━━━ Phase 3 · 拆除（5步管线）━━━
助手:  (调用 steam_turbine_demolition(mode="topology"))
       ✅ 拆除计划：14 步工序，138 个动画步骤，739 个动画构件
       ✅ 动画时间线：~192 秒 @ 24fps（~4608 帧）
       ✅ 特效配置：标准（变橙→缩小→下坠→隐藏）
       播放动画预览成功，是否渲染成视频？
用户:  渲染
━━━ Phase 4 · 渲染 ━━━
助手:  (调用 run_pipeline_stage(stage="render"))
       ✅ 视频已输出：<输出路径>  (时长约 3 分 12 秒)
```

## 3. 工具调用链（后端视角）

| # | 阶段 | 工具调用 | 后端实现 |
|---|---|---|---|
| 1 | Phase 1 | `get_scenario("steam_turbine_building")` | `scenario_server` 返回场景规格 |
| 2 | Phase 2 | `build_frame_model(building_type="steam_turbine")` | `blender_build_server` → `projects/steam_turbine_building/scripts/main.py` |
| 3 | Phase 3 | `steam_turbine_demolition(mode="topology")` | `caiao_servers/steam_turbine_demolition/caiao.yaml` 编排，内部 5 步（见下） |
| 4 | Phase 4 | `run_pipeline_stage(stage="render")` | Blender EEVEE / 视频输出 |

**`steam_turbine_demolition` 内部 5 步管线（caiao.yaml）：**

| 步骤 | 服务器 | 工具 | 输入 → 输出 |
|---|---|---|---|
| 1 | `blender_build_server` | `build_frame_model` | `mode=topology, building_type=steam_turbine` → 480 构件模型 |
| 2 | `planning_server` | `plan_demolition_sequence` | `structure + strategy(top_down)` → `demolition_plan`（14 步） |
| 3 | `animation_control_server` | `create_timeline` | `demolition_plan + effects_preset(standard)` → `timeline`（138 步） |
| 4 | `animation_control_server` | `sequence_to_animation_data` | `timeline + speed` → `animation_data` |
| 5 | `animation_control_server` | `generate_effects_config` | `preset + structure` → `effects_config` |

## 4. 场景参数明细

| 参数 | 值 |
|---|---|
| structure_params | type=steel, building_type=steam_turbine, num_bays_x=24, num_stories=1, span_x_m=8.0, story_height_m=25.0, steel_grade=Q235 |
| strategy | top_down（西→东、自上而下，C 轴柱最后保留） |
| effects_preset | standard（cascade/explosion/dust/buckling/fracture 开，shake/flash/trail/bounce 关） |
| speed | 1.0（正常 48 帧/步=2s，加速 12 帧/步=0.5s） |
| viz_mode | blender |

## 5. 各环节输入→输出明细

| 环节 | 输入 | 输出 | 耗时参考 |
|---|---|---|---|
| Phase 1 场景匹配 | 用户话术 | 场景规格 + 确认询问 | <1s |
| Phase 2 构建 | `building_type=steam_turbine` | `scene_base.blend`（480 构件） | ~1 min |
| Phase 3-1 拆除计划 | 480 构件 + 策略 | 14 步工序计划 | ~10s |
| Phase 3-2 时间线 | 14 步计划 + 标准特效 | 138 动画步骤 | ~5s |
| Phase 3-3 动画数据 | 时间线 + 速度分区 | 4608 帧动画 | ~1 min |
| Phase 3-4 特效配置 | 标准预设 + 结构 | 变橙→缩小→下坠→隐藏 | ~5s |
| Phase 4 渲染 | 动画 + 镜头方案 | 视频（~192s @24fps） | 5-10 min |

## 6. 拆除 14 步工序（实例内容核心）

**全局规则：西→东、自上而下；拆梁规则：首跨拆左右梁，后续跨只拆左梁（右梁已被前跨拆掉）。**

| 步骤 | 速度 | 拆除内容 |
|---|---|---|
| 0 | 正常 | 西端 BC 山墙 |
| 1 | 正常 | BC 跨屋面板 / 梁 / 楼板（Bay23→21） |
| 2 | 正常 | AB 屋面板 |
| 3 | 正常 | 钢屋架 24→22 |
| 4 | 正常 | A 轴墙板 |
| 5 | 正常 | 西端 AB 山墙 + 抗风柱 |
| 6 | 正常 | BC 山墙收尾 |
| 7-11 | **加速** | AB 屋面板 20→1 → A 轴墙板 20→1 → 钢屋架 21→1 → 东端山墙 → 东端抗风柱 |
| 12 | 加速 | A 轴柱子 24→1 |
| 13 | 加速 | 批量剩余构件西→东（**排除 C 轴柱**） |
| 14 | 加速 | **C 轴柱子最后保留拆除** |

**动画参数：** 正常 48 帧/步（2s）、加速 12 帧/步（0.5s）、24fps；总 138 步、739 动画构件、~4608 帧、~192 秒。

**镜头方案：** 东南俯瞰 20mm 广角，`TRACK_TO` 跟随，X 轴从西→东→中移动。
