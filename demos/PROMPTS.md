# 场景触发提示词速查表 (Scenario Prompt Cheat Sheet)

> 用法：把下表中的**用户话术**直接发给前端对话（Gateway `/chat` 或快速视觉模式），
> LLM 会通过 `gateway/llm_engine.py` 的 `FAST_CORE_PROMPT` 自动路由到对应场景。
> 场景数据源：`caiao_servers/scenario_server/server.py` 的 `SCENARIOS`。

---

## 0. 快速视觉模式规则（LLM 内部触发逻辑）

快速视觉模式（`analysis_mode="fast"`）下 LLM 只允许使用可视化工具，禁止结构分析：

- 用户提到 **"steam turbine building" / "汽轮机厂房"** → 调 `get_scenario("steam_turbine_building")` 展示规格 → 问"开始构建模型？"
- 用户描述**自定义建筑** → 用参数模板收集参数 → 直接进入 Phase 2 构建
- 用户说**泛化话术**（"做个拆除动画"）→ 调 `list_scenarios` 列出场景让用户选

**通用 4 阶段工作流（Phase 1-4）：**
1. **理解需求** → 匹配场景或收集参数
2. **构建** → `build_frame_model`（汽轮机厂房约 1 分钟）
3. **拆除** → 确认策略（方向 / 速度分区 / 构件优先级 / 保留构件）→ 跑管线（约 1-2 分钟）
4. **渲染**（可选）→ 输出视频（约 5-10 分钟）

---

## 1. 预置场景触发话术

| # | 场景 | 推荐话术（中文） | 推荐话术（English） | 说明 |
|---|---|---|---|---|
| 1 | **蒸汽轮机厂房** `steam_turbine_building` | "生成一个蒸汽轮机厂房的拆除演示" | "Build a steam turbine building demolition demo" | 24榀×3轴大型工业厂房，14步西→东自上而下拆除，走 Blender 管线 |
| 2 | **快速可视化倒塌** `quick_visual` | "做个快速倒塌演示" / "来个最简单的拆除动画" | "Show a quick visual collapse" | 2跨3层小框架，最短路径出图 |
| 3 | **完整结构拆除** `full_structural` | "做完整结构分析拆除" | "Run a full structural demolition" | 4跨6层，最弱优先策略，逐轮重分析直到倒塌 |
| 4 | **电影级倒塌** `cinematic_collapse` | "来个电影级倒塌效果" | "Make a cinematic collapse" | 3跨4层，粒子/灰尘/震动/屈曲全特效，慢速戏剧化 |
| 5 | **底部爆破内塌** `bottom_up_implosion` | "模拟底部爆破内塌" | "Simulate a bottom-up implosion" | 3跨4层，先拆底层柱，上部向内倒塌 |
| 6 | **3D Unity 物理仿真** `unity_3d_physics` | "用 Unity 做 3D 物理拆除" | "Run a Unity 3D physics simulation" | 3x4柱网4层，完整分析+实时物理，**需 Unity 运行** |
| 7 | **隔层交替倒塌** `alternating_floor_collapse` | "做隔层交替倒塌演示" | "Show alternating floor collapse" | 4跨4层，拆 4→2→3→1 层，制造连续渐进倒塌 |

---

## 2. 自定义建筑话术模板

描述一个**非预置**建筑时，可用任意顺序提供这些参数（缺省用默认值）：

```
帮我建一个 N跨 M层 的钢框架并做拆除动画：
- 跨度 X m，层高 Y m
- 钢材 Q355
- 拆除方向：西→东
- 拆除顺序：先屋面 → 墙 → 屋架 → 楼板 → 梁 → 柱
- 特效：标准
```

**默认参数**（`FAST_CORE_PROMPT` DEFAULT PARAMETERS）：
- 柱 0.8×0.8m，梁 0.4×0.8m，屋架杆件半径 0.15m
- 楼板厚 0.2m，墙厚 0.2m
- 层高 25m（汽轮机厂房单层）；fps = 24
- 默认策略：top_down + 西→东
- 说 **"默认"** 即全部采用默认值，直接开跑

---

## 3. 通用触发词速查

| 意图 | 话术示例 | 路由 |
|---|---|---|
| 列出全部场景 | "有哪些拆除场景可选？" / "List available scenarios" | `list_scenarios` |
| 查看某场景参数 | "看下蒸汽轮机厂房的规格" | `get_scenario("steam_turbine_building")` |
| 直接跑完整管线 | "直接做汽轮机厂房拆除，用默认参数" | `steam_turbine_demolition(mode="topology")` |
| 通用框架拆除 | "做个拆除动画" / "帮我生成一个建筑" | `visual_demolition`（LLM 先列场景） |
| 只要模型 | "建个模型就行" | `build_frame_model` 后停下 |
| 建模+动画+渲染全流程 | "完整做一遍并渲染出视频" | `run_full_pipeline` |

---

## 4. 编排模式（高级，来自 `ORCHESTRATION_PATTERNS`）

| Pattern | 触发话术 | 流程 |
|---|---|---|
| 1 分析结构 | "分析这个结构" | 参数 → quick/full analysis → 报告 → 提议拆除 |
| 2 生成 BIM 模型 | "生成一个 BIM 模型" | `generate_steel_frame/concrete/hybrid` → 可选导出 IFC |
| 3 规划拆除 | "做个拆除方案" | `plan_demolition_sequence` → 方案摘要 |
| 4 设计与拆除 | "设计并拆除" | 生成 → 分析 → 报告 → 拆除 → 重分析循环 |
| 5 纯可视化拆除 | "只要动画不要分析" | 生成 → 规划 → 时间线 → 逐轮动画 |
| 6 拆除许可报告 | "出一份拆除许可报告" | 生成 → 规划 → 方案摘要 → 拓扑分析 |
| 7 Abaqus 倒塌仿真 | "用 Abaqus 做倒塌仿真" | `setup_collapse` + 提交作业 |

---

## 5. 关键注意事项

- **汽轮机厂房是唯一走 Blender 预构建场景**（`viz_mode="blender"`），其余场景为 WebGL 前端渲染，`unity_3d_physics` 需 Unity 运行中。
- 拆除阶段可指定**速度分区**（正常 48 帧/步 / 加速 12 帧/步）和**保留构件**（如"C 轴柱子最后保留"）。
- 若 Blender 未安装，LLM 会提示路径要求（见 `check_blender_environment`）。
- 构建约 1 分钟，动画约 1-2 分钟，渲染约 5-10 分钟 —— 过程中不要重复发送同一条话术，否则会触发多实例堆积。

---

## 6. 典型实例：蒸汽轮机厂房端到端拆除演示

> 以 `steam_turbine_building` 场景为完整示例，演示"一句话 → 4 阶段工作流 → 5 步管线 → 14 步拆除"的全过程。

### 6.1 完整对话流（用户视角）

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

### 6.2 工具调用链（后端视角）

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

### 6.3 各环节输入→输出明细

| 环节 | 输入 | 输出 | 耗时参考 |
|---|---|---|---|
| Phase 1 场景匹配 | 用户话术 | 场景规格 + 确认询问 | <1s |
| Phase 2 构建 | `building_type=steam_turbine` | `scene_base.blend`（480 构件） | ~1 min |
| Phase 3-1 拆除计划 | 480 构件 + 策略 | 14 步工序计划 | ~10s |
| Phase 3-2 时间线 | 14 步计划 + 标准特效 | 138 动画步骤 | ~5s |
| Phase 3-3 动画数据 | 时间线 + 速度分区 | 4608 帧动画 | ~1 min |
| Phase 3-4 特效配置 | 标准预设 + 结构 | 变橙→缩小→下坠→隐藏 | ~5s |
| Phase 4 渲染 | 动画 + 镜头方案 | 视频（~192s @24fps） | 5-10 min |

### 6.4 拆除 14 步工序（实例内容核心）

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
