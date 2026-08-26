# 蒸汽轮机厂房 — 完整 Prompt 流程

> 场景名：`steam_turbine_building` ｜ 类别：topology ｜ 渲染：Blender 管线
> 24榀x3轴(A/B/C)大型工业厂房，AB跨24m钢屋架(脊高27m)，BC跨9m平梁(8m/15m楼板)，柱高25m，共480构件。完整流程（构建+拆除+渲染）预估最长约 25-30 分钟。

## 1. 触发话术（用户可只给部分参数，缺失项助手用默认值补全）

| 语言 | 话术示例 |
|---|---|
| 中文 | 生成一个约 24 跨的钢厂房拆除演示，AB 跨跨度大概 24 米 / 生成一个蒸汽轮机厂房的拆除演示（全部用默认） |
| English | Build a ~24-bay steel plant demolition demo, AB bay span about 24m / Build a steam turbine building demolition demo (use defaults) |

## 2. 完整对话流（Phase 0 参数确认 → Phase 1-4）

| 轮次 | 说话方 | 内容 |
|---|---|---|
| 1 | 用户 | 给出项目概述与部分参数（跨数、跨度、柱高、层数等，可不全、可不精确；说"默认"则全部用默认值） |
| 2 | 助手 | 复述完整参数表：用户给出的保留，缺失项用默认值补全（24榀 × 3轴(A/B/C)，AB跨 24m 钢屋架(脊高27m)，BC跨 9m 平梁(8m/15m楼板)，柱高 25m，钢材 Q235，共 480 构件；拆除策略西→东、自上而下（C 轴柱最后保留）；特效 standard；速度 1.0）。说明预计时长：完整流程（构建+拆除+渲染）最长约 25-30 分钟。请求用户确认 |
| 3 | 用户 | 确认参数（或指出需调整的参数） |
| 4 | 助手 | (调用 get_scenario("steam_turbine_building")) 已找到预置场景：蒸汽轮机厂房，规格与确认参数一致。是否开始构建模型？ |
| 5 | 用户 | 开始 |
| 6 | 助手 | (调用 build_frame_model(building_type="steam_turbine")) 模型构建完成，已生成 480 个构件 |
| 7 | 助手 | (调用 steam_turbine_demolition(mode="topology")) 拆除计划 14 步工序、138 个动画步骤、739 个动画构件，动画时间线 ~192 秒 @ 24fps（~4608 帧），特效 standard。是否渲染成视频？ |
| 8 | 用户 | 渲染 |
| 9 | 助手 | (调用 run_pipeline_stage(stage="render", blend_input="<scene_animated.blend 完整路径>")) 视频已输出：<输出路径>（时长约 3 分 12 秒） |

**说明：** 任何参数调整都在轮 3 确认时提出；确认后不再变更。

**渲染注意：** 轮 9 调用 render 阶段时**必须**显式指定 `blend_input` 为动画文件 `scene_animated.blend`（含全部拆除关键帧，与 `scene_base.blend` 同在默认输出目录 `blender_pipeline/output/blend/` 下）。`scene_base.blend` 是静态基础模型，渲染它只会得到静态画面，禁止使用。

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
| Phase 0 参数确认 | 用户概述 + 默认值 | 完整参数表 + 确认 | 秒级 |
| Phase 1 场景匹配 | 用户话术 | 场景规格 + 确认询问 | <1s |
| Phase 2 构建 | `building_type=steam_turbine` | `scene_base.blend`（480 构件） | ~1 min |
| Phase 3-1 拆除计划 | 480 构件 + 策略 | 14 步工序计划 | ~10s |
| Phase 3-2 时间线 | 14 步计划 + 标准特效 | 138 动画步骤 | ~5s |
| Phase 3-3 动画数据 | 时间线 + 速度分区 | 4608 帧动画 | ~1 min |
| Phase 3-4 特效配置 | 标准预设 + 结构 | 变橙→缩小→下坠→隐藏 | ~5s |
| Phase 4 渲染 | `scene_animated.blend`（动画） | 视频（~192s @24fps） | 最长约 15 分钟 |
| 完整流程合计 | — | 视频 + 模型 | 最长约 25-30 分钟 |

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
