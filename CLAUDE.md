# XuanwuAI Demolition Simulator — Project Record

## 🔴 最高约束（必须遵守）

**对话窗口绝对零输出。** 不输出任何文字——不输出思考、代码、工具调用、进度。全部后台 Agent 静默执行。完成后只说"完成。"

**严禁在对话窗口输出任何代码。** 任何时候都不得出现代码块（markdown 代码 fence）、内联代码、命令示例。不得使用任何编程语言的真实语法。如果必须提及技术内容，只能用自然语言文字描述算法、逻辑或步骤。这条约束没有例外——即使对方要求举例，也只能用纯文字类比说明。

所有代码变更只通过文件编辑工具（Edit/Write）静默完成。对话中只描述要做什么、做了什么，不展示代码片段。

**执行模式：静默执行，完成后汇报。** 用户给出指令后，无需在对话中逐步汇报进度，直接通过工具静默完成所有修改。全部完成后，只说三件事：完成了什么、有没有问题、下一步需要什么决策。

**所有代码变更必须通过后台 Agent 执行。** 严禁直接在对话中调用 Write/Edit/Bash 等会产生大量代码内容的工具。代码内容会随 tool call 参数注入对话窗口，等同于输出代码，违反最高约束。代码编写、文件修改、测试运行等操作一律通过 Agent 工具（`run_in_background: true` 或 Workflow）在后台完成，对话窗口只接收执行结果摘要。这是宪法级约束，没有例外。

**呈现结果时只输出结论和必要的文字解释。** 不输出过程描述、中间状态、工具调用细节、文件列表、commit hash 等非必要信息。不要复述"做了什么"的步骤清单——只说结论和问题。如果某条信息用户没有明确要求，就不要输出。最大限度节省对话 token。

## ⚡ CORE DESIGN PRINCIPLE (read this first)
**Everything is a CAIAO Server.** Every tool, every solver, every external capability is an independent CAIAO Server process, discovered and routed through a central CAIAO Hub. The LLM never calls anything directly — it tells the AgentLoop what it wants, the AgentLoop routes through the CAIAO Hub, and the Hub dispatches to the correct subprocess.

```
User → Frontend → WebSocket → Gateway AgentLoop → LLM (decides tool)
       → CAIAOClientHub → CAIAO Server subprocess (stdio) → Result → User
```

Adding a new solver/feature = writing one new CAIAO Server file + registering it. No core code changes.

## What This Project Is
智能结构拆除模拟器：AI 驱动的渐进式建筑倒塌分析系统。用户输入框架参数 → AI 生成结构 → 分析力学 → 识别关键柱 → 多轮渐进拆除直到倒塌。

## User Directives (来自对话记录，持久生效)

### 1. 功能优先级
- **渐进式拆除** 是核心价值：必须支持多轮杆件拆除，直到结构完全倒塌，不是只拆一根
- **应力比云图** 必须显示：结构模型要能切换 Deformation / Stress Ratio 视图，用颜色直观表示每根杆件的危险程度
- **对话可回顾**：切换/重载对话后必须恢复完整状态（结构模型 + 分析结果 + 倒塌动画 + 应力云图）
- **动画要真实**：不要 ASCII art 占位符，要 SVG 物理倒塌动画
- **日志要有可读性**：不要 dump 原始 JSON，要提取关键指标用人类可读格式显示

### 2. UI/UX 要求
- 对话框要宽，数据不能折行
- 选项卡名字要简洁（Disp / Forces / Compare / Dev）
- 按钮位置描述要准确（Demolish 在左下角聊天输入框下方，不是右侧面板）
- 设置面板要有存储控制（清空对话、清空记忆、导出备份）

### 3. 技术决策
- **Unity 3D 物理引擎**：通过 WebRTC 提供 3D 实时倒塌可视化，CAIAO server + Unity Editor 按需启动
- **SVG 2D 降级方案**：当 Unity 未运行时自动 fallback 到 SVG + requestAnimationFrame
- **不用 Three.js**：2D SVG 框架可视化即可满足降级需求
- **OpenSees 高精度**：已修复（之前前端没传 structure 参数），OpenSeesPy 在 Windows venv 中可用
- **mem0 有本地 fallback**：gateway/memory.py 有 local_memory.json 备选方案，不依赖 OpenAI API key
- **对话存储在 localStorage**：不需要后端数据库
- **Agent memory 存储**：gateway/local_memory.json（服务器端）

### 4. 代码风格
- 不写注释（除非 WHY 不明显）
- 不做过度抽象
- 编辑已有文件优先于新建文件
- 不改动不相关代码

### 5. 核心工作原则

#### 5.1 Think Before Coding（先思考，再编码）
动手前先说明对需求的理解、不确定的地方和可能的替代方案。通过提问消除歧义，而不是默默做错误假设直接开干。

#### 5.2 Simplicity First（简单至上）
用最简单直接的方式解决问题。避免不必要的抽象层、设计模式和功能扩展。不要为"将来可能用"而提前复杂化。

#### 5.3 Surgical Changes（外科手术式修改）
只修改任务所必需的文件和代码行。禁止顺手"优化"、重构或改动无关代码。每处修改都应有明确的必要性。

#### 5.4 Goal-Driven & Verifiable（目标驱动且可验证）
动手前将模糊指令转化为可验证的目标。例如"加个校验"→"先为非法输入写测试，再让测试通过"。明确什么是"完成"的标准。

### 6. 国际化
- 中英文双语支持，翻译文件：frontend/lib/i18n.ts
- **所有用户可见文字必须走 `t(key, lang)` 调用**，禁止在 JSX 中硬编码英文或中文
- 英文作为源语言（source language），中文翻译按需补齐
- `t()` 对未翻译的 key 自动 fallback 到英文，不阻塞功能
- dev 模式下（客户端），缺中文翻译时 `console.warn` 提示，方便发现遗漏
- 翻译 key 命名规范：`模块.语义`，如 `sidebar.expand`、`dc.play`、`export.download`
- 带变量的文字用 `{n}` 占位符，调用处 `.replace("{n}", value)` 替换
- 新增组件流程：先用英文写 key → 立刻能用 → 后续统一补中文
- 组件通过 `lang: Lang` prop 接收当前语言，从 page.tsx 逐层传递

## Current Architecture

```
gateway/          ← FastAPI 后端，LLM 引擎 + Agent Loop
  main.py         ← API + WebSocket 入口
  llm_engine.py   ← SYSTEM_PROMPT + OpenAI SDK 封装
  agent_loop.py   ← ReAct agent (think → act → observe)
  memory.py       ← mem0 + local JSON fallback
  caiao_config.py   ← caiao.yaml 自动发现（替代硬编码 SERVER_CONFIGS）
caiao_servers/
  manager_server/         ← 🔧 CAIAO Server 管理器（元 Server：创建/扩展/健康/迁移/检索/编排）
  anastruct_server/       ← 快速线性分析 (anaStruct)
  opensees_server/        ← 高精度分析 (OpenSeesPy)
  pynite_server/          ← 3D FEM (PyNite)
  fapp_server/            ← 3D FEM (FAPP)
  unity_simulator/        ← 拆除动作 + 结构修改 + Unity TCP 通信
  frame_generator/        ← 参数化框架生成 (2D + 3D)
  quick_analysis_server/  ← ⚡ Pipeline A: 第一个 CAIAOServerizer server merge
  full_analysis_3d_server/  ← ⚡ Pipeline B: 第二个 server merge (3D 全分析)
  abaqus_environment_server/  ← Abaqus 环境发现 + 校验 (infrastructure)
  abaqus_session_server/      ← Abaqus CAE 持久会话，15 个建模/分析/拆除工具 (merged)
unity_project/
  Assets/Scripts/
    SimulationController.cs  ← TCP 监听 :5005, 物理拆除
    FrameBuilder.cs          ← 程序化框架建模
    WebRTCStreamer.cs        ← 相机画面 WebRTC 推流
    WebRTCSignaling.cs       ← SDP 信令桥接到 Gateway
    Editor/
      XuanwuAISceneSetup.cs  ← 一键场景搭建菜单
frontend/
  app/page.tsx       ← 主页面（65% 以上的逻辑在这里）
  components/
    frame-visualization.tsx  ← SVG 结构模型 + 应力云图 + 倒塌动画
    unity-video-panel.tsx    ← Unity WebRTC 视频面板（3D 视图）
    verification-panel.tsx   ← 双轨验证面板（Displacements/Forces/Compare/Dev）
    sidebar.tsx
    floating-toolbar.tsx
    server-manager.tsx
    mechanical-summary.tsx
  lib/
    i18n.ts     ← 中英文翻译
    api.ts      ← REST + WebSocket 客户端
```

## Key Files to Know
- **SYSTEM_PROMPT** 在 `gateway/llm_engine.py`，控制 AI 行为
- **verify endpoint** 在 `gateway/main.py`，处理 OpenSees 对比验证
- **WebRTC signaling** 在 `gateway/main.py` (/webrtc/offer, /webrtc/answer)，Unity ↔ 前端 SDP 交换
- **会话恢复** 在 `frontend/app/page.tsx` 的 `restoreStateFromMessages()` 函数
- **应力比计算** 在 `frame-visualization.tsx`，用 `FY=235e6` (钢屈服强度)
- **倒塌判定**：所有柱被拆除 或 位移 >100mm 或 分析不收敛
- **Unity 场景搭建**：Unity Editor → Tools → XuanwuAI → Setup Scene（一键创建）

## 冷却塔 Abaqus 仿真速查
新会话先读本节省时；原理与细节一律查手册，不以记忆为准。

### 文件地图

| 文件路径 | 职责 | 何时用 |
|---|---|---|
| `dev-notes/abaqus/2026-08-22-cooling-tower-collapse-manual.md`（手册） | 12 章，原理/学习/照做清单（第十章检查清单 + 10.4 验证顺序），历史事故都有记录 | 新会话先读；跑法/原理/细节任何疑问 |
| `dev-notes/abaqus/2026-08-22-cooling-tower-parameters.md`（参数文件） | 全部参数取值 + 项目状态（run 8 真实塔为当前基准）+ 调优入口速查（第四章）+ 版本变更历史（第三章）+ 用户反馈台账与调优分析（第六章）；参数变更与项目状态以此为准 | **改参数前必查、跑完必回填、调优必登记；用户反馈仿真效果必须先登记反馈台账（关联参数版本）再调优** |
| `dev-notes/abaqus/2026-08-23-real-video-calibration-and-collapse-mechanism.md`（实拍校准与机制讨论） | 占地 51m 机制讨论（扑倒/弯折/碎裂三模式）、开洞角误差讨论（87-92° vs 98°）、视频对比方案与模型能力边界（deepseek 无视觉）、video_analysis_server 设想、待用户协助清单 | 调优方向争议、视频校准问题先读此文件；实拍分析产物在 `scripts/video_calibration/` |
| `dev-notes/abaqus/2026-08-23-site-collapse-description.md`（现场倒塌描述权威汇总，用户审核版） | 用户 2026-08-23 三次澄清后的权威时间线（0-2s 慢倾 → 2s 起连续加速 → 4s 根部断裂 → 扑倒落地，全程约 6s，无速度突变）+ 裂缝/断裂/残留/占地/底座 8 点 + 未知待定项（钢筋、环梁 500-800mm、自由落体为感觉） | 调优目标与时间线任何疑问先读此文件；run 13 起以四阶段时间线验证 |
| `todo/abaqus-cooling-tower.md` | 冷却塔历轮 run 状态与开发决策 | 查历史 run 记录；每轮 run 脚本自动追加 |
| `todo/abaqus-stack.md` | 烟囱历轮 run 状态与开发决策（run 1–26 全记录 + 常驻索引） | 查烟囱历史 run 记录；烟囱线回填此处 |
| `scripts/run_tower_collapse.py` | 求解驱动：塔几何/壁厚/洞口/网格/求解时长/CPU 常量 + 提交作业（fallback 链路） | 改参数、跑求解 |
| `scripts/verify_cooling_tower_build.py` | 建模验证（8/8 ALL_PASS，不提交作业） | 每轮跑求解前先验证建模 |
| `scripts/extract_tower_frames.py` | 帧提取（ODB → `_tower_frames/data.npz` 50 帧，内核侧脚本） | 求解完成后、渲染前；每轮必改 ODB_PATH |
| `scripts/render_tower_frames.py` | 渲染/合成/验证（MP4 + frames，部署 frontend/public/resource/Abaqus/） | 提取帧后合成与 verify |
| `scripts/footprint_report.py` | 占地报告（内核侧，生成 cooling_tower_footprint.json） | 核对落点/方向/堆高；每轮必改 ODB_PATH |

### 标准跑法（宿主脚本链路，5 步）
宿主脚本用 gateway venv python；内核侧脚本只能 `abq2026.bat cae noGUI=<脚本>` 批跑（launcher 路径在 `caiao_servers/abaqus_environment_server/abaqus_env.json`）。在仓库根目录执行：
1. **建模验证**：`gateway/venv/Scripts/python.exe scripts/verify_cooling_tower_build.py` → 8/8 ALL_PASS（不提交作业，分钟级）
2. **求解**：`gateway/venv/Scripts/python.exe scripts/run_tower_collapse.py` → .sta 成功 + collapse_happened（run 8 实测求解 397.6s、总 439.4s，硬预算 555s；自动追加 todo 记录）
3. **提取帧**：先改 extract_tower_frames.py 的 ODB_PATH → `abq2026.bat cae noGUI=extract_tower_frames.py` → `_tower_frames/data.npz` 50 帧（分钟级；缺 npz 时 render test 会自动代跑）
4. **渲染合成**：`gateway/venv/Scripts/python.exe scripts/render_tower_frames.py all` → `compose`（MP4 部署到 frontend/public/resource/Abaqus/）→ `verify`（分钟级）
5. **占地报告**：改 footprint_report.py 的 ODB_PATH → `abq2026.bat cae noGUI=footprint_report.py` → 核对 `frontend/public/resource/Abaqus/cooling_tower_footprint.json`（秒级）

### 改参数位置速查
- 塔几何/壁厚/洞口/网格/求解时长/CPU：`scripts/run_tower_collapse.py` 顶部常量（TOWER_HEIGHT / TOWER_BASE_RADIUS / TOWER_THROAT_RADIUS / TOWER_THROAT_ELEVATION / TOWER_TOP_RADIUS / WALL_THICKNESS / OPENING_* / N_THETA / TOTAL_SIM_TIME），setup_tower_collapse 调用处显式传参
- **N_THETA 双处**：run 脚本常量 + `abaqus_session.py` `_handle_create_cooling_tower` 硬编码 n_theta=128（只改一处会不一致）
- 材料表：`caiao_servers/abaqus_session_server/abaqus_session.py` `_handle_assign_tower_materials`（C30 完整 CDP 表 + 钢筋层，换等级改这里）
- 渲染常量：`scripts/render_tower_frames.py` 顶部（W/H/FPS/N_FRAMES/GROUND_R/U_MAX/视角/帧差阈值）
- **改完先在参数文件登记再跑**（新 run 编号、新取值、变更项）

### 每轮必改点
- `scripts/extract_tower_frames.py` 的 ODB_PATH 硬编码 → 新 workdir（现指向 run 8 `tower_collapse_67hq82px`）
- `scripts/footprint_report.py` 的 ODB_PATH 硬编码（⚠️ 现在仍指向 run 7 `tower_collapse_96t8sjpa`，重跑必须同步）
- `scripts/render_tower_frames.py` 俯视虚线环半径 28.5（≈底半径）；塔更大/更高时另调 GROUND_R=45.0 与 U_MAX=75.0

### 注意事项
- 渲染轴映射 [x, -z, y]（Y-up 数据 → Z-up 渲染）必过——不过则塔横躺、俯视变侧视（历史事故）
- 2026 内核 assembly.Set 必炸 → 宿主机 fallback 路径（宿主拼 INP + `abq2026.bat job=...`）已绕行，主路径修复 P2
- 显式作业进度从 .sta 解析（MONITOR_INTERVAL_S=30）；超求解硬上限且进度不足会被终止
- 跑完回填：todo/abaqus-cooling-tower.md（run 脚本自动追加）+ 参数文件项目状态；烟囱线回填 todo/abaqus-stack.md
- 长任务（求解/提取/渲染 >5 分钟）必须用 python scripts/run_with_wake.py <命令> 包裹执行，防电源计划空闲睡眠中断后台任务（2026-08-23 事故：Agent 卡死+系统睡眠双重中断）

### 验证清单
1. verify_cooling_tower_build.py → 8/8 ALL_PASS（建模层）
2. run_tower_collapse.py → completed、collapse_happened=True、.sta 成功
3. render test 帧差 ≥1.0（第 1 vs 25 帧，视角修正前是 5.0）
4. footprint 数值核对：tower_base_radius=新底半径、final_height/max_radius/p95 量级、direction 与洞口方位一致
5. 数值抽查：侧视塔竖直、俯视地面圆正圆

### 前端链路
前端 LLM 对话驱动冷却塔尚未打通：`gateway/agent_loop.py` 的 TOOL_KEYWORD_MAP["abaqus"] 缺 4 个冷却塔工具（create_cooling_tower / assign_tower_materials / mesh_tower / setup_tower_collapse，事实核查遗漏），P0 仿真模式端到端验证待执行；当前全部走宿主脚本链路。打通后可直接在前端跑，Claude Code 用于高级操作（改参数/重跑/调优）。

## CAIAO Architecture (enforced)

**CAIAO** is our project-specific naming layer on top of the standard MCP SDK. Every CAIAO Server is technically an MCP Server under the hood — the `mcp` Python package handles stdio transport and JSON-RPC. We rename the abstraction to distinguish our project's convention from the generic protocol.

### Rules
- **Every new capability must be a CAIAO Server** — never add logic directly to Gateway or frontend that belongs in a solver
- **Template**: copy `caiao_servers/_template/server.py` to start a new server
- **Registration**: add to `gateway/main.py` → `SERVER_CONFIGS`
- **Lazy loading**: use `"lazy": True` for heavyweight solvers (OpenSees, PyNite, FAPP, Unity)

### Server Independence Principle
- **Every server is fully independent.** No server requires another server's process to be running.
- **Merge by importing logic, never by depending on another server's runtime.** A merged server imports pure functions/classes from source servers — it doesn't need them running.
- **Never modify an existing server to serve a merge.** Merges create new Servers; atomic servers stay unchanged.
- **Extract shared logic only when ROI justifies it** (3+ consumers, non-trivial logic). Don't abstract prematurely.
- **Detailed rationale**: `CAIAO_PROTOCOL.md §7`

### Naming Convention
| Context | Convention | Example |
|---------|-----------|---------|
| Class name | `CAIAO` + PascalCase | `CAIAOClientHub` |
| Constant | `CAIAO_` + UPPER_SNAKE | `CAIAO_SERVERS_DIR` |
| Filename | `caiao_` + lowercase | `caiao_config.py` |
| Directory | `caiao_servers/` | `caiao_servers/anastruct_server/` |
| SDK imports | keep `from mcp.server import Server` | external package, not our naming |

### Docs
- **CAIAO protocol (complete reference)**: see `CAIAO_PROTOCOL.md`
- **Full principle doc**: see `ARCHITECTURE.md`
- **Dev docs**: see `dev-notes/architecture.md`

### Auto-Update Rule
**Every CAIAO-related change MUST update `CAIAO_PROTOCOL.md`.** This includes:
- New server creation → add to Server Registry (§8)
- New merge → add to Merge Roadmap (§9) + Server Registry (§8)
- Naming convention change → update (§10)
- Contract rule change → update (§11)
- Any other CAIAO architectural decision → append to Change Log (§12)
- `CAIAO_PROTOCOL.md` is the single source of truth for all CAIAO matters.

### CAIAOServerizer 范式（CAIAO Server = 原子单元）

CAIAO Server 是系统最小原子单元，类比 LLM 的 token。核心演化方向：

**1. Server 可组合（✅ first merge done）**
多个 Server 可声明式组合成新 Server，无需写代码：
```
# 已实现: quick_analysis_server = generate_frame + analyze_frame + select_critical
frame_generator + anastruct + postprocess = full_analysis  （新复合 Server）
```
复合 Server 本身可被索引和复用（类似 BPE 合并规则）。参见 `ARCHITECTURE.md` CAIAOServerizer 章节。

**2. 并行资源自适应**
多 Server 并行执行前必须评估机器负载，超限则自动回退串行：
```
请求 → 资源评估（CPU>80%? 内存<2GB?）→ 并行 or 串行
```
这是 P0 机制，现在就要实现。

**3. 向量路由（远期）**
用 embedding 语义匹配请求到 Server/组合，替代硬编码路由。

**4. 自进化**
记录高频组合模式 → 自动固化 → 优化编排顺序。
详见 `dev-notes/architecture/2026-05-24-caiaoserverizer-paradigm.md`

## Feature Status
- [x] 框架生成 + 快速分析
- [x] 关键柱识别
- [x] 渐进式多轮拆除（AI 自动重新分析）
- [x] 应力比云图（绿色<30%, 黄色30-60%, 橙色60-85%, 红色>85%）
- [x] SVG 倒塌动画（requestAnimationFrame）
- [x] OpenSees 高精度验证（已修复 structure 参数传递）
- [x] 对话完整状态恢复（结构 + 分析 + 倒塌 + 应力）
- [x] 日志可读性优化
- [x] 设置面板存储管理
- [x] 本地记忆 fallback (local_memory.json)
- [x] Unity 3D 物理引擎集成（WebRTC 视频流 + 一键启动 + 自动搭建场景 + 自动 Play 模式）
- [x] 前端一键 Launch Unity（无需手动打开 Editor / Setup Scene / Play）
- [x] ⚡ 第一个 CAIAOServerizer server merge: quick_analysis_server
  （generate + analyze + select_critical 合并为单次调用）
- [x] ⚡ 第二个 CAIAOServerizer server merge: full_analysis_3d_server
  （3D 生成 → UnifiedFrame 转换 → PyNite 3D 分析 → 选关键柱）

### 7. 对话记录到 dev-notes
- **每次有重要技术决策、架构变更、Bug 根因分析、或用户明确要求时**，将关键对话内容输出到 `dev-notes/` 目录
- 子文件夹结构：
  - `dev-notes/decisions/` — 技术决策、方案对比、API 设计讨论
  - `dev-notes/architecture/` — 架构文档、系统设计
  - `dev-notes/reference/` — 需求、路线图、Bug 记录等参考资料
  - 其他子文件夹按需创建
- 文件名格式：`YYYY-MM-DD-简短描述.md`
- 内容要点：问题/需求描述 → 分析过程 → 最终方案和关键代码变更 → 遗留问题
- 避免 dump 原始对话，要提炼有价值的技术内容

## 用户联系
- 语言偏好：中文（但代码用英文）
- 期望：尽快发挥价值，功能要实用
- 频繁要求：宽对话框、简洁标签、可读日志、持久化状态
