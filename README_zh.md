<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://img.shields.io/badge/XuanwuAI-0891b2?style=for-the-badge">
    <img alt="XuanwuAI" src="https://img.shields.io/badge/XuanwuAI-0e7490?style=for-the-badge">
  </picture>
</p>

<h1 align="center">玄武AI 拆除模拟器</h1>

<p align="center">
  <b>AI 驱动的渐进式建筑结构拆除模拟器</b><br/>
  自然语言 → 框架生成 → 结构分析 → 关键柱识别 → 物理级倒塌
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/next.js-16-black?logo=next.js" alt="Next.js">
  <img src="https://img.shields.io/badge/unity-2021.3_LTS-222?logo=unity" alt="Unity">
  <img src="https://img.shields.io/badge/fastapi-0.115-009688?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/tailwind-css-06b6d4?logo=tailwindcss" alt="Tailwind">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
</p>

<p align="center">
  <a href="#玄武--品牌哲学">品牌哲学</a> ·
  <a href="#架构">架构</a> ·
  <a href="#核心功能">核心功能</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#项目结构">项目结构</a> ·
  <a href="#文档">文档</a> ·
  <a href="#贡献指南">贡献指南</a>
</p>

---

## 玄武 · 品牌哲学

<p align="center">
  <i>渊默之算 · Abyssal Computation</i>
</p>

> **智算万物，稳控乾坤。**
> **Wisdom computes all things; Stability governs heaven and earth.**

**玄武**，北境之神，其形为龟蛇合体，是中国神话中"至稳"与"至变"的完美统一。

| 象征 | 含义 | 在玄武AI中 |
|------|------|-----------|
| 🛡️ **神龟** (Aegis) | 绝对防御、稳固与秩序 | 坚不可摧的物理引擎内核与精确的规则系统 |
| 🐍 **灵蛇** (Python) | 灵活应变、智慧与执行 | 自主规划、动态调整、制定最优拆除策略的高级 AI 算法 |

> 神龟象征绝对防御、稳固与秩序，代表模拟器坚不可摧的物理引擎内核；灵蛇象征灵活应变、智慧与执行，代表运行于其上的高级 AI 算法，在复杂环境中自主规划、动态调整，制定最优拆除策略。

玄武AI是**四象AI**家族的一员，各司其德：

| 神兽 | 五行 | 核心德性 | 领域 |
|------|------|---------|------|
| **青龙AI** | 木 | 创生之智 · 生成式创造 | 生成式 AI、创意智能 |
| **朱雀AI** | 火 | 燎原之火 · 连接之焰 | 智能交互、人机体验 |
| **白虎AI** | 金 | 肃金之盾 · 净化之卫 | AI 原生安全、对抗防御 |
| **玄武AI** | 水 | **渊默之算 · 深度计算** | 复杂模拟、战略决策 |

---

## 玄武AI 拆除模拟器是什么？

玄武AI 拆除模拟器是一个融合了 **LLM 驱动的 Agent 工作流**与**物理模拟引擎**的智能结构工程模拟器。您只需用自然语言描述一个建筑框架，AI 即可自主完成生成、结构力学分析、关键承重柱识别以及渐进式拆除模拟——并支持 2D SVG、3D Unity 物理和**照片级 Blender 渲染动画**的可视化。

系统支持**多引擎管线**：快速 2D 线弹性分析（anaStruct）、高保真非线性分析（OpenSeesPy）、3D 有限元（PyNite/FAPP）、工业级 **Abaqus CAE** 求解器，以及完整的 **Blender 自动化管线**——程序化构建场景、集成机械模型、动画化拆除序列，并从多角度渲染。

工作流遵循**多轮渐进式拆除**：每次拆除某根柱子后，剩余结构被重新分析并识别下一根关键柱，循环直至整体倒塌。统一的 **CAIAO 协议**连接 30+ 工具服务器，**Blender 帧服务器**将渲染帧直接传输到浏览器。

> UI 支持**中英文双语切换**，通过设置面板切换语言（`frontend/lib/i18n.ts`）。

---

## 架构

```
┌──────────┐    WebSocket   ┌──────────────────────────────────────────────────┐
│          │◄──────────────►│                网关 (FastAPI)                    │
│ 前端     │                │                                                  │
│ (Next.js)│                │  ┌──────────┐  ┌───────┐  ┌─────────┐           │
│          │                │  │LLM 引擎  │  │Agent  │  │ 记忆    │           │
│ • 对话   │                │  │(OpenAI   │  │Loop   │  │ (mem0 + │           │
│ • 2D SVG │                │  │ SDK)     │  │(ReAct)│  │ local)  │           │
│ • Unity  │                │  └──────────┘  └───────┘  └─────────┘           │
│   WebRTC │                │         │                                        │
│ • Blender│                │    CAIAO Hub (stdio 子进程)                      │
│   输出   │                │         │                                        │
└──────────┘                └─────────┼────────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────────┐
          │                           │                               │
          ▼                           ▼                               ▼
  ┌───────────────┐   ┌───────────────────────┐   ┌────────────────────────┐
  │ 结构分析      │   │ 模拟与物理            │   │ 可视化管线              │
  │               │   │                       │   │                        │
  │ • anaStruct   │   │ • Unity 模拟器        │   │ • Blender 管线          │
  │ • OpenSeesPy  │   │   (TCP :5005)         │   │   (frame_server.py)    │
  │ • PyNite 3D   │   │                       │   │   • 环境场景构建        │
  │ • FAPP 3D     │   │ • Abaqus 求解器       │   │   • 机械模型集成        │
  │               │   │   (session + env)     │   │   • 拆除动画            │
  │ • Quick       │   │                       │   │   • 多角度渲染          │
  │   Analysis ⚡  │   │ • 物理引擎            │   │                        │
  │ • Full 3D ⚡   │   │   (Rigidbody)         │   │                        │
  └───────────────┘   └───────────────────────┘   └────────────────────────┘
          │                       │                           │
          ▼                       ▼                           ▼
  ┌───────────────┐   ┌───────────────────┐   ┌──────────────────────────┐
  │ BIM / IFC     │   │ Unity 3D 引擎     │   │ 输出: JPG / MP4 /        │
  │ 模型服务      │   │ • 刚体物理        │   │ WebRTC / 流式帧          │
  │               │   │ • 可配置关节      │   │                          │
  │ 场景规划器    │   │ • WebRTC 流       │   │ 前端面板:                │
  │               │   │                   │   │ • Unity 视频             │
  └───────────────┘   └───────────────────┘   │ • Blender 视频           │
                                               │ • Abaqus 视频            │
                                               │ • Effects AI (视频/图片) │
                                               └──────────────────────────┘
```

### CAIAO 协议

CAIAO 协议是本项目的**统一服务抽象**——每个求解器、模拟器和外部工具都作为独立的 CAIAO Server 子进程运行，通过 stdio JSON-RPC 通信。网关的 `CAIAOClientHub` 管理所有服务器的生命周期，并按名称路由工具调用。该架构保证了隔离性（一个崩溃不会级联）、语言无关性（任何支持 stdio 的语言都可以成为 CAIAO Server）以及即插即用的可扩展性（添加一个求解器只需要写一个文件）。

> CAIAO Server 底层使用标准 MCP Python SDK（`from mcp.server import Server`）进行传输。"CAIAO"是本项目的命名规范，而非独立的协议标准。详见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

### 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | Next.js 16, TypeScript, Tailwind CSS, shadcn/ui, Recharts |
| **网关** | FastAPI, WebSocket, OpenAI SDK, ReAct Agent Loop |
| **CAIAO 总线** | CAIAO 协议 (MCP SDK stdio 传输), 30+ 工具服务器, 60+ 工具 |
| **2D 分析** | anaStruct (线弹性), OpenSeesPy (非线性) |
| **3D 有限元** | PyNite (3D), FAPP (3D), 多求解器深度验证 |
| **3D 物理** | Unity 2021.3 LTS, C# 刚体 + 可配置关节 |
| **Blender 管线** | Blender 4.x 无头模式, 脚本化场景构建, 拆除动画, 多角度渲染 |
| **Abaqus** | Abaqus CAE 会话管理, 环境求解器, 结构分析 |
| **BIM** | IFC 模型导入, BIM-to-模拟 桥接 |
| **AI 视频/图片** | Agnes AI API — 图生视频, 图生图真实渲染 |
| **3D 查看器** | Three.js / @react-three/fiber 交互式 WebGL 3D 查看器, 自定义 H 型钢几何 |
| **流传输** | WebRTC (Unity → 浏览器), WebSocket (Agent 步骤), 帧服务器 (Blender → 浏览器) |
| **记忆** | mem0 (SQLite) + 本地 JSON 回退 |

---

## ⚡ CAIAOServerizer 范式

> **CAIAO Server 是系统的最小原子单元，类比 LLM 的 token。**

### 服务合并

就像 BPE 把高频 token 对合并为新 token一样，我们把高频的 Server 调用序列合并为新的原子 Server。

```
                     ┌──────────────────┐
                     │     TOKEN 1      │
                     │  generate_frame  │
                     └────────┬─────────┘
                              │
                     ┌────────▼─────────┐
                     │     TOKEN 2      │
                     │  analyze_frame   │
                     └────────┬─────────┘
                              │
                     ┌────────▼─────────┐
                     │     TOKEN 3      │
                     │select_critical   │
                     └────────┬─────────┘
                              │
                 ═════════════╪═══════════════
                   CAIAOServerizer MERGE ⚡
                 ═════════════╪═══════════════
                              │
                     ┌────────▼─────────┐
                     │ ⚡ 合并后的服务   │
                     │ quick_analysis   │
                     │ ┌─────────────┐  │
                     │ │ generate    │  │
                     │ │ analyze     │  │
                     │ │ select crit │  │
                     │ └─────────────┘  │
                     └──────────────────┘
```

**管线 A** (`quick_analysis_server`) 是 CAIAOServerizer 的第一个产物：`generate_frame` + `analyze_frame` + `select_critical_element` 三个原子 Server 被合并为一个调用。不仅减少了 LLM 的决策成本，更消除了两次子进程通信和 JSON 序列化。

| 对比维度 | 合并前 (3 次调用) | 合并后 (1 次调用) |
|---------|-----------------|-----------------|
| 子进程通信 | 3 次 stdio round-trip | 1 次 |
| JSON 序列化 | 3 次 | 1 次 |
| 延迟估算 | ~900ms + IPC 开销 | ~300ms |
| 原子性 | 部分步骤可能失败 | 全有或全无 |
| LLM 决策 | 3 次 tool call | 1 次 |

> **路线图:** 管线 A 只是第一步。接下来将合并 3D 全分析管线（`generate_frame_3d → pynite_analysis`）、多求解器验证套件（4 求解器共识）、以及拆除循环（`apply_demolition → re-analyze → select_critical`）。
>
> 详见 [`CAIAO_PROTOCOL.md`](CAIAO_PROTOCOL.md)（完整参考）、[`ARCHITECTURE.md`](ARCHITECTURE.md) 和 `dev-notes/architecture/2026-05-25-caiaoserverizer-first-merge.md`

---

## 核心功能

### 核心工作流
- **自然语言输入** — 描述一个框架（"2层3跨框架，跨度6m"），AI 自动处理一切
- **渐进式多轮拆除** — 逐根拆除关键柱直至倒塌，每轮自动重新分析
- **双轨验证** — 快速（anaStruct 线弹性） vs. 高保真（OpenSees 非线性），偏差分析（5% 阈值）
- **AI 自主循环** — Agent 思考 → 行动（调用 CAIAO 工具）→ 观察结果 → 重复

### 可视化与用户体验
- **SVG 框架可视化** — 2D 结构视图，含变形叠加、节点/单元标签、应力比热力图（绿<30% → 黄30-60% → 橙60-85% → 红>85%）
- **SVG 物理倒塌动画** — 基于 `requestAnimationFrame` 的重力、速度和地面碰撞物理
- **Unity 3D 流** — 实时 WebRTC 视频，3D 刚体拆除（自动回退到 2D SVG）
- **Blender 视频面板** — 通过 Blender 帧服务器传输的照片级渲染拆除动画
- **Abaqus 视频面板** — 来自 Abaqus CAE 的工业级 FEA 输出可视化
- **3D 框架可视化** — 支持旋转缩放的交互式 WebGL 3D 结构浏览器
- **IFC 模型查看器** — 导入并查看 IFC 格式的 BIM 模型
- **深色主题 UI** — Slate (#0f172a) 背景 + cyan (#22d3ee) 高亮
- **Agent 日志流** — 实时终端风格日志查看器，支持暂停/恢复
- **动画时间线编辑器** — 控制拆除动画序列的可视化时间线

### 数据与持久化
- **完整会话恢复** — 切换或重载对话恢复结构模型、分析结果、倒塌动画和应力热力图
- **持久化记忆** — mem0 支持的跨会话上下文记忆，含 `local_memory.json` 回退
- **配置持久化** — LLM 密钥和模型设置在网关重启后保留（`llm_config.json`）
- **存储控制** — 清除对话、清除记忆、导出备份（JSON 下载）

### 分析与工程
- **关键柱识别** — 基于几何的柱检测 + 轴力排名
- **力学摘要面板** — 实时显示最大位移、最大轴力、关键柱和拆除目标
- **多求解器深度验证** — 对比最多 4 个求解器结果：anaStruct (2D)、OpenSees (2D)、PyNite (3D)、FAPP (3D)，含共识值和异常检测
- **Abaqus CAE 集成** — 通过 Abaqus 会话 + 环境求解器进行工业级有限元分析
- **BIM/IFC 桥接** — 导入 IFC 建筑模型并转换为模拟就绪几何
- **场景规划** — 定义拆除序列、拆除目标和模拟参数

### Blender 管线
- **程序化场景构建** — 从模拟数据自动生成详细的 3D 环境
- **机械集成** — 放置拆除挖掘机、起重机和设备
- **拆除动画** — 基于物理的倒塌动画，含灰尘/碎片效果
- **多角度渲染** — 同时从多个摄像机位置渲染
- **帧服务器** — 将渲染帧实时传输到浏览器（`frame_server.py`）
- **蒸汽轮机建筑** — 完整的工业拆除演示项目

### AI 特效管线（视频与图片）
- **Agnes AI 视频生成** — 基于多视角模型截图的图生视频，支持画质预设（低/中/高/电影）和实时进度追踪
- **Agnes AI 图片渲染** — 图生图真实渲染：将线框模型截图转为照片级建筑可视化，基于 Agnes Image 2.1 Flash
- **多角度截图采集** — 自动采集正面、侧面、45° 和俯视图作为参考帧
- **交互式 3D 查看器** — 基于 Three.js 的 WebGL 3D 模型查看器，支持轨道控制、着色/线框/X-Ray 显示模式、点击选柱
- **自定义 H 型钢几何** — 精确的 HW/HM 钢截面网格，实现真实的结构可视化
- **自动保存到项目** — 生成的视频和图片自动保存到每个任务的项目文件夹，附带元数据
- **历史记录与回放** — 从 localStorage 浏览、重命名、删除和回放已生成的视频和图片
- **画质预设** — 低（384p，最快）→ 中（512p）→ 高（768p，推荐）→ 电影（1080p，最慢）

---

## 快速开始

### 前置要求

- **Python 3.11+** with `venv`
- **Node.js 20+**
- **Unity Editor 2021.3 LTS**（可选，用于 3D 模拟）

### 1. 克隆与配置

```bash
git clone <repo-url> && cd "XuanwuAI Demolition Simulator"

# 设置 LLM 配置（方式 A: 配置文件）
cp gateway/llm_config.example.json gateway/llm_config.json
# 编辑 gateway/llm_config.json，填入 API key 和模型
```

| 服务商 | 模型 | Base URL |
|--------|------|----------|
| DeepSeek | `deepseek-chat`, `deepseek-v4-flash`, `deepseek-v4-pro` | `https://api.deepseek.com` |
| OpenAI | `gpt-4o`, `gpt-4o-mini` | `https://api.openai.com/v1` |

> 启动两个服务后，也可通过应用内 UI 配置 LLM 设置。

### 2. 启动后端

```bash
cd gateway
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
python main.py               # → http://localhost:8000
```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev                  # → http://localhost:3000
```

### 4. 验证

```bash
curl http://localhost:8000/health   # {"status":"ok"}
curl http://localhost:8000/tools    # 列出已注册的 CAIAO 工具
```

### 5. （可选）启动 Unity 3D

> 用于通过 WebRTC 进行 3D 物理模拟。若 Unity 未运行，自动回退到 2D SVG。

1. 在 Unity Editor 2021.3 LTS 中打开 `unity_project/`
2. 通过 Package Manager 安装 `com.unity.webrtc`（从 git URL 添加）
3. 点击 **Tools → XuanwuAI → Setup Scene** 自动构建模拟环境
4. 进入 Play 模式——控制器在 `localhost:5005` 监听 TCP 指令

---

## 项目结构

| 目录 | 描述 |
|------|------|
| `gateway/` | FastAPI 后端 — REST API、WebSocket、LLM 引擎、ReAct Agent Loop、CAIAO Hub、路由、服务 |
| `caiao_servers/` | 30+ 个 CAIAO 工具服务器 — 结构分析 (anaStruct、OpenSees、PyNite、FAPP)、Blender 管线 (构建、动画、渲染、环境、机械)、Abaqus (会话、环境)、Unity 模拟、BIM/IFC、场景规划、物理引擎、**Agnes 视频/图片生成**、**钢框架 3D 生成器** 等 |
| `blender_pipeline/` | Blender 自动化 — 便携 Blender 4.x、程序化建筑生成、拆除动画、多角度渲染、帧流服务器 |
| `frontend/` | Next.js 16 SPA — 3D/SVG 可视化、Unity/Blender/Abaqus 视频面板、**Effects AI 视频/图片面板**、**Three.js 3D 结构查看器**、Agent 对话、IFC 查看器、时间线编辑器、服务器管理、双语 i18n |
| `unity_project/` | Unity C# 脚本 — SimulationController (TCP)、FrameBuilder (程序化)、WebRTC 流、一键场景搭建 |
| `scripts/` | 工具脚本 — 编码修复、优化、资源守护 |
| `tests/` | 集成测试 |
| `docs/` | 设计与规划文档 |
| `demos/` | 演示脚本与示例 |

关键文档: [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`CAIAO_PROTOCOL.md`](CAIAO_PROTOCOL.md) · [`PROJECT_STATUS.md`](PROJECT_STATUS.md) · [`CONTRIBUTING.md`](CONTRIBUTING.md)

---

## 测试

```bash
# 后端
cd gateway && pytest tests/ -v              # 33 个测试

# CAIAO 服务器
cd caiao_servers/anastruct_server && pytest tests/ -v   # 19 个测试
cd caiao_servers/demo_calculator && pytest tests/ -v    # 9 个测试

# 前端
cd frontend && npx vitest run                # 16 个测试
```

**总计: 82 个测试通过** (截至 2026 年 5 月)

---

## 功能状态

| 功能 | 状态 |
|------|------|
| 框架生成 + 快速分析 | 已完成 |
| 关键柱识别 | 已完成 |
| 渐进式多轮拆除 | 已完成 |
| 应力比热力图可视化 | 已完成 |
| SVG 物理倒塌动画 | 已完成 |
| OpenSees 高保真验证 | 已完成 (Linux/macOS) |
| 完整会话状态恢复 | 已完成 |
| Unity 3D 物理 (WebRTC 流) | 已完成 |
| 一键 Unity 场景搭建 | 已完成 |
| 中英文双语 UI | 已完成 |
| 持久化 LLM 配置 | 已完成 |
| 本地记忆回退 | 已完成 |
| 多求解器深度验证 (4 求解器) | 已完成 |
| ⚡ CAIAOServerizer 合并 #1 (管线 A) | 已完成 — `quick_analysis`: 3 次调用 → 1 次 |
| ⚡ CAIAOServerizer 合并 #2 (管线 B) | 已完成 — `full_analysis_3d`: 3D 几何 → PyNite → 关键 |
| Blender 管线 — 建筑生成 | 已完成 |
| Blender 管线 — 拆除动画 | 已完成 |
| Blender 管线 — 多角度渲染 | 已完成 |
| Blender 帧服务器 (流式传输到浏览器) | 已完成 |
| Abaqus CAE 会话 + 环境求解器 | 已完成 |
| BIM / IFC 模型导入 | 已完成 |
| 场景规划器 + 拆除规划 | 已完成 |
| 蒸汽轮机建筑演示项目 | 已完成 |
| CAIAO 服务器管理器 (生命周期 UI) | 已完成 |
| 动画时间线编辑器 | 已完成 |
| **Effects AI 视频生成 (Agnes)** | **已完成** |
| **Effects AI 图片渲染 (img2img)** | **已完成** |
| **交互式 3D 结构查看器 (Three.js)** | **已完成** |
| **自定义 H 型钢几何** | **已完成** |
| **钢框架 3D 生成器** | **已完成** |
| **Demo 项目 (exports)** | **已完成** |
| 移动端响应式布局 | 计划中 |
| 多用户会话隔离 | 计划中 |

---

## 文档

| 文档 | 描述 |
|------|------|
| [CAIAO_PROTOCOL.md](CAIAO_PROTOCOL.md) | **完整 CAIAO 参考** — 服务注册表, 合并路线图, 独立原则, 命名规范, 协议 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | CAIAO 总线技术细节, 协议规范 |
| [CLAUDE.md](CLAUDE.md) | 项目记录, 架构, 关键文件, 用户指令 |
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | 10 天 MVP 进度, 已知问题, 测试覆盖, 未来计划 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 提交规范, 代码风格, PR 流程, 分支策略 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 常见问题与解决方案 |

---

## 已知限制

- **OpenSees on Windows**: `openseespy` DLL 依赖问题 — 服务器以降级模式运行，状态为 `"unavailable"`。请在 Linux/macOS 或 WSL2 上使用以获得完整精度。
- **Unity scripts**: C# 脚本已完成编写和结构设计，但尚未在 Unity Editor 完整场景中验证。
- **单用户**: 无多租户会话隔离 — Agent 和记忆是单实例的。
- **无认证**: WebSocket 和 REST 端点未保护 — 生产环境部署前需添加认证。
- 详见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。

---

## 贡献指南

欢迎贡献！请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 了解：

- 提交规范（Conventional Commits，含项目特有作用域）
- 代码风格指南（Black for Python, Prettier + ESLint for TypeScript）
- Pull Request 检查清单
- 分支策略

---

## 许可证

MIT
