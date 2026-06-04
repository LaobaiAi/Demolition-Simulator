# XuanwuAI Demolition Simulator — Project Record

## 🔴 最高约束（必须遵守）
**严禁在对话窗口输出任何代码。** 任何时候都不得出现代码块（markdown 代码 fence）、内联代码、命令示例。不得使用任何编程语言的真实语法。如果必须提及技术内容，只能用自然语言文字描述算法、逻辑或步骤。这条约束没有例外——即使对方要求举例，也只能用纯文字类比说明。

所有代码变更只通过文件编辑工具（Edit/Write）静默完成。对话中只描述要做什么、做了什么，不展示代码片段。

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

### 5. 国际化
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
  abaqus_collapse_pipeline/   ← Abaqus 倒塌全流程编排 (composite)
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

### 6. 对话记录到 dev-notes
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
