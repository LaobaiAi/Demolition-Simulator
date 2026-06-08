
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://img.shields.io/badge/XuanwuAI-0891b2?style=for-the-badge">
    <img alt="XuanwuAI" src="https://img.shields.io/badge/XuanwuAI-0e7490?style=for-the-badge">
  </picture>
</p>

<h1 align="center">XuanwuAI Demolition Simulator</h1>

<p align="center">
  <b>AI-powered progressive structural demolition simulator</b><br/>
  Natural language → frame generation → structural analysis → critical column identification → physics-based collapse
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
  <a href="#玄武--brand-philosophy">Philosophy</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#key-features">Features</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#project-structure">Structure</a> ·
  <a href="#documentation">Docs</a> ·
  <a href="#contributing">Contributing</a>
</p>

---

## 玄武 · Brand Philosophy

<p align="center">
  <i>渊默之算 · Abyssal Computation</i>
</p>

> **智算万物，稳控乾坤。**<br/>
> **Wisdom computes all things; Stability governs heaven and earth.**

**玄武 (Xuanwu)**, the god of the North in Chinese mythology, is a divine hybrid of **tortoise and serpent** — the perfect embodiment of *ultimate stability* and *adaptive intelligence* in unity.

| Symbol | Meaning | In XuanwuAI |
|--------|---------|-------------|
| 🛡️ **Tortoise** (Aegis) | Absolute defense, order, and unshakable foundation | The rock-solid physics engine kernel and precise rule system that anchor every simulation |
| 🐍 **Serpent** (Python) | Agility, wisdom, and precise execution | The high-level AI algorithms that autonomously plan, adapt, and devise optimal demolition strategies in complex environments |

> **玄武，北境之神，其形为龟蛇合体，是中国神话中"至稳"与"至变"的完美统一。**<br/>
> 神龟象征绝对防御、稳固与秩序，代表模拟器坚不可摧的物理引擎内核；灵蛇象征灵活应变、智慧与执行，代表运行于其上的高级 AI 算法，在复杂环境中自主规划、动态调整，制定最优拆除策略。

XuanwuAI is part of the **Four Symbols AI** (四象AI) family, each embodying a cardinal virtue:

| Deity | Element | Virtue | Domain |
|-------|---------|--------|--------|
| **QinglongAI** 青龙 | 木 Wood | 创生之智 · Generative Creation | Generative AI, creative intelligence |
| **ZhuqueAI** 朱雀 | 火 Fire | 燎原之火 · Connective Flame | Intelligent interaction, human-AI experience |
| **BaihuAI** 白虎 | 金 Metal | 肃金之盾 · Purifying Shield | AI-native security, adversarial defense |
| **XuanwuAI** 玄武 | 水 Water | **渊默之算 · Abyssal Computation** | Complex simulation, strategic decision-making |

> Xuanwu corresponds to the **Water element** — depth, wisdom, and the power to mirror reality within digital worlds. As the foundation of the Four Symbols, it provides the computational bedrock upon which creation, connection, and defense are built.

---

## What is XuanwuAI Demolition Simulator?

XuanwuAI Demolition Simulator is an intelligent structural engineering simulator that combines **LLM-driven agent workflows** with **physics-based simulation engines**. You describe a building frame in natural language, and the AI autonomously generates it, analyzes structural mechanics, identifies the most critical load-bearing column, and simulates progressive demolition — with 2D SVG, 3D Unity physics, and **photorealistic Blender animation** visualization.

The system supports a **multi-engine pipeline**: fast 2D linear analysis (anaStruct), high-fidelity nonlinear (OpenSeesPy), 3D FEM (PyNite/FAPP), industrial-grade **Abaqus CAE** solvers, and a full **Blender automation pipeline** that procedurally builds environments, integrates machinery models, animates demolition sequences, and renders from multiple camera angles.

The workflow follows **multi-round progressive demolition**: after each column removal, the remaining structure is re-analyzed and the next critical column is identified, continuing until total collapse. The unified **CAIAO protocol** connects 30+ tool servers, and the **Blender frame server** streams rendered frames directly to the browser.

> UI supports **bilingual Chinese/English** switching via the settings panel (`frontend/lib/i18n.ts`).

---

## Architecture

```
┌──────────┐    WebSocket   ┌──────────────────────────────────────────────────┐
│          │◄──────────────►│                Gateway (FastAPI)                 │
│ Frontend │                │                                                  │
│ (Next.js)│                │  ┌──────────┐  ┌───────┐  ┌─────────┐           │
│          │                │  │LLM Engine│  │Agent  │  │ Memory  │           │
│ • Chat   │                │  │(OpenAI   │  │Loop   │  │ (mem0 + │           │
│ • 2D SVG │                │  │ SDK)     │  │(ReAct)│  │ local)  │           │
│ • Unity  │                │  └──────────┘  └───────┘  └─────────┘           │
│   WebRTC │                │         │                                        │
│ • Blender│                │    CAIAO Hub (stdio subprocesses)                │
│   Output │                │         │                                        │
└──────────┘                └─────────┼────────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────────┐
          │                           │                               │
          ▼                           ▼                               ▼
  ┌───────────────┐   ┌───────────────────────┐   ┌────────────────────────┐
  │ Analysis      │   │ Simulation & Physics  │   │ Visualization Pipeline │
  │               │   │                       │   │                        │
  │ • anaStruct   │   │ • Unity Simulator     │   │ • Blender Pipeline     │
  │ • OpenSeesPy  │   │   (TCP :5005)         │   │   (frame_server.py)   │
  │ • PyNite 3D   │   │                       │   │   • Environmental      │
  │ • FAPP 3D     │   │ • Abaqus Solvers      │   │     scene building     │
  │               │   │   (session + env)     │   │   • Machinery models   │
  │ • Quick       │   │                       │   │   • Demolition anim    │
  │   Analysis ⚡  │   │ • Physics Engine      │   │   • Multi-angle render │
  │ • Full 3D ⚡   │   │   (Rigidbody)         │   │                        │
  └───────────────┘   └───────────────────────┘   └────────────────────────┘
          │                       │                           │
          ▼                       ▼                           ▼
  ┌───────────────┐   ┌───────────────────┐   ┌──────────────────────────┐
  │ BIM / IFC     │   │ Unity 3D Engine   │   │ Output: JPG / MP4 /      │
  │ Model Server  │   │ • Rigidbody phys  │   │ WebRTC / stream frames   │
  │               │   │ • Config Joint    │   │                          │
  │ Scenario      │   │ • WebRTC stream   │   │ Frontend Panels:         │
  │ Planner       │   │                   │   │ • Unity Video            │
  │               │   │                   │   │ • Blender Video          │
  └───────────────┘   └───────────────────┘   │ • Abaqus Video           │
                                               └──────────────────────────┘
```

### CAIAO Protocol

The CAIAO protocol is the project's **unified server abstraction** — every solver, simulator, and external tool runs as an independent CAIAO Server subprocess communicating via stdio JSON-RPC. The Gateway's `CAIAOClientHub` manages all server lifecycles and routes tool calls by name. This architecture ensures isolation (one crash doesn't cascade), language agnosticism (any language with stdio can be a CAIAO Server), and plug-and-play extensibility (add a solver by writing one file).

> Under the hood, CAIAO Servers use the standard MCP Python SDK (`from mcp.server import Server`) for transport. "CAIAO" is our project's naming convention, not a separate protocol standard. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full contract.

### Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 16, TypeScript, Tailwind CSS, shadcn/ui, Recharts |
| **Gateway** | FastAPI, WebSocket, OpenAI SDK, ReAct agent loop |
| **CAIAO Bus** | CAIAO protocol (MCP SDK stdio transport), 30+ tool servers, 60+ tools |
| **2D Analysis** | anaStruct (linear elastic), OpenSeesPy (nonlinear) |
| **3D FEM** | PyNite (3D), FAPP (3D), multi-solver deep verify |
| **3D Physics** | Unity 2021.3 LTS, C# Rigidbody + ConfigurableJoint |
| **Blender Pipeline** | Blender 4.x headless, scripted scene building, demolition animation, multi-angle rendering |
| **Abaqus** | Abaqus CAE session management, environment solver, structural analysis |
| **BIM** | IFC model import, BIM-to-simulation bridge |
| **Streaming** | WebRTC (Unity → browser), WebSocket (agent steps), frame server (Blender → browser) |
| **Memory** | mem0 (SQLite) with local JSON fallback |

---

## ⚡ CAIAOServerizer Paradigm

> **CAIAO Server 是系统的最小原子单元，类比 LLM 的 token。**

### The Server Merge

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
                     │ ⚡ MERGED SERVER │
                     │ quick_analysis   │
                     │ ┌─────────────┐  │
                     │ │ generate    │  │
                     │ │ analyze     │  │
                     │ │ select crit │  │
                     │ └─────────────┘  │
                     └──────────────────┘
```

**Pipeline A** (`quick_analysis_server`) 是 CAIAOServerizer 的第一个产物：
`generate_frame` + `analyze_frame` + `select_critical_element` 三个原子 Server
被合并为一个调用。不仅减少了 LLM 的决策成本，更消除了两次子进程通信和 JSON 序列化。

| 对比维度 | 合并前 (3 次调用) | 合并后 (1 次调用) |
|---------|-----------------|-----------------|
| 子进程通信 | 3 次 stdio round-trip | 1 次 |
| JSON 序列化 | 3 次 | 1 次 |
| 延迟估算 | ~900ms + IPC 开销 | ~300ms |
| 原子性 | 部分步骤可能失败 | 全有或全无 |
| LLM 决策 | 3 次 tool call | 1 次 |

> **Roadmap:** Pipeline A 只是第一步。接下来将合并 3D 全分析管线（`generate_frame_3d → pynite_analysis`）、
> 多求解器验证套件（4 求解器共识）、以及拆除循环（`apply_demolition → re-analyze → select_critical`）。
>
> 详见 [`CAIAO_PROTOCOL.md`](CAIAO_PROTOCOL.md)（完整参考）、[`ARCHITECTURE.md`](ARCHITECTURE.md#caiaoserverizer-paradigm-token-merge)
> 和 `dev-notes/architecture/2026-05-25-caiaoserverizer-first-merge.md`

---

## Key Features

### Core Workflow
- **Natural Language Input** — Describe a frame ("2-story 3-bay frame with 6m spans") and the AI handles everything
- **Progressive Multi-Round Demolition** — Remove critical columns one by one until collapse, with automatic re-analysis after each round
- **Dual-Track Verification** — Fast (anaStruct linear) vs. High-Fidelity (OpenSees nonlinear) with deviation analysis against a 5% threshold
- **AI Autonomous Loop** — Agent thinks → acts (calls CAIAO tools) → observes results → repeats

### Visualization & UX
- **SVG Frame Visualization** — 2D structure view with deformation overlay, node/element labels, and stress-ratio heatmap (green <30% → yellow 30-60% → orange 60-85% → red >85%)
- **SVG Physics Collapse Animation** — `requestAnimationFrame`-driven collapse with gravity, velocity, and ground-impact physics
- **Unity 3D Stream** — Real-time WebRTC video of the 3D Rigidbody-based demolition (with automatic 2D SVG fallback)
- **Blender Video Panel** — Photorealistic rendered demolition animations streamed from the Blender frame server
- **Abaqus Video Panel** — Industrial-grade FEA output visualization from Abaqus CAE
- **3D Frame Visualization** — Interactive WebGL-based 3D structure viewer with rotation and zoom
- **IFC Model Viewer** — Import and inspect BIM models in IFC format
- **Dark-Themed UI** — Slate (#0f172a) background with cyan (#22d3ee) accents
- **Agent Log Stream** — Real-time terminal-style log viewer with pause/resume
- **Animation Timeline Editor** — Visual timeline for controlling demolition animation sequences

### Data & Persistence
- **Full Session Restoration** — Switching or reloading a conversation recovers structure model, analysis results, collapse animation, and stress heatmap
- **Persistent Memory** — mem0-backed context memory across sessions, with `local_memory.json` fallback
- **Config Persistence** — LLM keys and model settings survive gateway restarts (`llm_config.json`)
- **Storage Controls** — Clear conversations, clear memory, export backup (JSON download)

### Analysis & Engineering
- **Critical Column Identification** — Geometry-based column detection + axial force ranking
- **Mechanical Summary Panel** — Live display of max displacement, max axial force, critical column, and demolition targets
- **Multi-Solver Deep Verify** — Compare results from up to 4 solvers: anaStruct (2D), OpenSees (2D), PyNite (3D), FAPP (3D), with consensus value and outlier detection
- **Abaqus CAE Integration** — Industrial-grade finite element analysis via Abaqus session + environment solvers
- **BIM/IFC Bridge** — Import IFC building models and convert to simulation-ready geometry
- **Scenario Planning** — Define demolition sequences, demolition targets, and simulation parameters

### Blender Pipeline
- **Procedural Scene Building** — Auto-generate detailed 3D environments from simulation data
- **Machinery Integration** — Place demolition excavators, cranes, and equipment
- **Demolition Animation** — Physics-informed collapse animation with dust/debris effects
- **Multi-Angle Rendering** — Render from multiple camera positions simultaneously
- **Frame Server** — Stream rendered frames to the browser in real-time (`frame_server.py`)
- **Steam Turbine Building** — Complete industrial demolition demo project

---

## Quick Start

### Prerequisites

- **Python 3.11+** with `venv`
- **Node.js 20+**
- **Unity Editor 2021.3 LTS** (optional, for 3D simulation)

### 1. Clone & Configure

```bash
git clone <repo-url> && cd "XuanwuAI Demolition Simulator"

# Set up LLM config (option A: config file)
cp gateway/llm_config.example.json gateway/llm_config.json
# Edit gateway/llm_config.json with your API key and model
```

| Provider | Model | Base URL |
|----------|-------|----------|
| DeepSeek | `deepseek-chat`, `deepseek-v4-flash`, `deepseek-v4-pro` | `https://api.deepseek.com` |
| OpenAI | `gpt-4o`, `gpt-4o-mini` | `https://api.openai.com/v1` |

> You can also configure LLM settings via the in-app UI after starting both services.

### 2. Start Backend

```bash
cd gateway
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
python main.py               # → http://localhost:8000
```

### 3. Start Frontend

```bash
cd frontend
npm install
npm run dev                  # → http://localhost:3000
```

### 4. Verify

```bash
curl http://localhost:8000/health   # {"status":"ok"}
curl http://localhost:8000/tools    # list of registered CAIAO tools
```

### 5. (Optional) Launch Unity 3D

> For 3D physics simulation via WebRTC. Falls back to 2D SVG if Unity is not running.

1. Open `unity_project/` in Unity Editor 2021.3 LTS
2. Install `com.unity.webrtc` via Package Manager (Add from git URL)
3. Click **Tools → XuanwuAI → Setup Scene** to auto-build the simulation environment
4. Enter Play mode — the controller listens on `localhost:5005` for TCP commands

---

## Project Structure

| Directory | Description |
|-----------|-------------|
| `gateway/` | FastAPI backend — REST API, WebSocket, LLM engine, ReAct agent loop, CAIAO hub, routers, services |
| `caiao_servers/` | 30+ CAIAO tool servers — structural analysis (anaStruct, OpenSees, PyNite, FAPP), Blender pipeline (build, animate, render, environment, machinery), Abaqus (session, environment), Unity simulation, BIM/IFC, scenario planning, physics, etc. |
| `blender_pipeline/` | Blender automation — portable Blender 4.x, procedural building generation, demolition animation, multi-angle rendering, frame streaming server |
| `frontend/` | Next.js 16 SPA — 3D/SVG visualization, Unity/Blender/Abaqus video panels, agent chat, IFC viewer, timeline editor, server manager, bilingual i18n |
| `unity_project/` | Unity C# scripts — SimulationController (TCP), FrameBuilder (procedural), WebRTC streaming, one-click scene setup |
| `scripts/` | Utility scripts — encoding fix, optimizer, resource guard |
| `tests/` | Integration tests |
| `docs/` | Design & planning documents |
| `demos/` | Demo scripts & examples |

Key docs: [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`CAIAO_PROTOCOL.md`](CAIAO_PROTOCOL.md) · [`PROJECT_STATUS.md`](PROJECT_STATUS.md) · [`CONTRIBUTING.md`](CONTRIBUTING.md)

---

## Testing

```bash
# Backend
cd gateway && pytest tests/ -v              # 33 tests

# Gateway integration
cd gateway && pytest tests/ -v              # API + agent + memory + CAIAO hub

# CAIAO servers
cd caiao_servers/anastruct_server && pytest tests/ -v   # 19 tests
cd caiao_servers/demo_calculator && pytest tests/ -v    # 9 tests

# Frontend
cd frontend && npx vitest run                # 16 tests
```

**Total: 82 tests passing** (as of May 2026)

---

## Feature Status

| Feature | Status |
|---------|--------|
| Frame generation + fast analysis | Done |
| Critical column identification | Done |
| Progressive multi-round demolition | Done |
| Stress-ratio heatmap visualization | Done |
| SVG physics collapse animation | Done |
| OpenSees high-fidelity verification | Done (Linux/macOS) |
| Full session state restoration | Done |
| Unity 3D physics (WebRTC streaming) | Done |
| One-click Unity scene bootstrap | Done |
| Bilingual Chinese/English UI | Done |
| Persistent LLM config | Done |
| Local memory fallback | Done |
| Multi-solver deep verify (4 solvers) | Done |
| ⚡ CAIAOServerizer merge #1 (Pipeline A) | Done — `quick_analysis`: 3 calls → 1 |
| ⚡ CAIAOServerizer merge #2 (Pipeline B) | Done — `full_analysis_3d`: 3D geometry → PyNite → critical |
| Blender pipeline — building generation | Done |
| Blender pipeline — demolition animation | Done |
| Blender pipeline — multi-angle rendering | Done |
| Blender frame server (stream to browser) | Done |
| Abaqus CAE session + environment solver | Done |
| BIM / IFC model import | Done |
| Scenario planner + demolition planning | Done |
| Steam turbine building demo project | Done |
| CAIAO server manager (lifecycle UI) | Done |
| Animation timeline editor | Done |
| Mobile responsive layout | Planned |
| Multi-user session isolation | Planned |

---

## Documentation

| Document | Description |
|----------|-------------|
| [CAIAO_PROTOCOL.md](CAIAO_PROTOCOL.md) | **Complete CAIAO reference** — server registry, merge roadmap, independence principle, naming, contract |
| [ARCHITECTURE.md](ARCHITECTURE.md) | CAIAO bus technical detail, protocol specification |
| [CLAUDE.md](CLAUDE.md) | Project record, architecture, key files, user directives |
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | 10-day MVP progress, known issues, test coverage, future plans |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Commit conventions, code style, PR process, branch strategy |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common issues and solutions |

---

## Known Limitations

- **OpenSees on Windows**: `openseespy` DLL dependency issues — the server degrades gracefully with `"unavailable"` status. Use Linux/macOS or WSL2 for full fidelity.
- **Unity scripts**: C# scripts written and structured but not yet validated inside Unity Editor with a full scene.
- **Single-user**: No multi-tenant session isolation — agent and memory are single-instance.
- **No authentication**: WebSocket and REST endpoints are unprotected — not for production exposure without auth.
- See [PROJECT_STATUS.md](PROJECT_STATUS.md) for full details.

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for:

- Commit conventions (Conventional Commits with project-specific scopes)
- Code style guidelines (Black for Python, Prettier + ESLint for TypeScript)
- Pull request checklist
- Branch strategy

---

## License

MIT
