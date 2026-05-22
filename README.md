# XuanwuAI Demolition Simulator

AI-powered structural analysis and physics-based demolition simulation system. Natural language input drives a 2D frame analysis pipeline connected to a 3D Unity physics engine.

## Architecture

```
User → Frontend (Next.js) → Gateway (FastAPI) → MCP Bus → Tool Servers
                                │                      ├── demo_calculator
                                │                      ├── anastruct (2D frames)
                                │                      ├── opensees (high-fidelity)
                                │                      └── unity_simulator → Unity 3D
                                │
                                └── WebSocket ←→ Agent Loop (ReAct)
```

- **Frontend**: Next.js 16 + Tailwind + shadcn/ui, dark theme, WebSocket chat, recharts visualization
- **Gateway**: FastAPI, WebSocket, OpenAI tool-calling, mem0 persistent memory
- **MCP Servers**: 4 stdio-based tool servers (10 tools total) following Model Context Protocol
- **Unity**: C# Rigidbody + ConfigurableJoint physics, TCP command relay, WebRTC streaming

## Quick Start

### Prerequisites
- Python 3.11+ with venv
- Node.js 20+
- Unity Editor 2021.3 LTS (optional, for 3D simulation)

### Backend

```bash
cd gateway
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt

# Set your OpenAI API key
export OPENAI_API_KEY="sk-..."

python main.py
# → http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

### Verify

```bash
curl http://localhost:8000/health
curl http://localhost:8000/tools
```

## Testing

```bash
# Backend (33 tests)
cd gateway && pytest tests/ -v

# MCP servers (28 tests)
cd mcp_servers/demo_calculator && pytest tests/ -v
cd mcp_servers/anastruct_server && pytest tests/ -v

# Frontend (16 tests)
cd frontend && npx vitest run
```

## Project Structure

```
├── gateway/           FastAPI backend + agent loop + MCP hub
│   ├── tests/         33 pytest tests
│   └── requirements.txt
├── mcp_servers/       4 MCP tool servers (stdio transport)
│   ├── demo_calculator/    add/subtract/multiply/divide
│   ├── anastruct_server/   frame generation + analysis + critical selection
│   ├── opensees_server/    high-fidelity nonlinear analysis
│   └── unity_simulator/    demolition command relay (TCP → Unity)
├── frontend/          Next.js SPA (TypeScript + Tailwind)
│   └── __tests__/     16 vitest tests
├── unity_project/     Unity C# scripts (SimulationController, FrameBuilder, WebRTCStreamer)
└── .github/workflows/ CI pipeline (pytest + tsc + vitest + build)
```

## Key Features

- **AI Autonomous Workflow**: Natural language → generate frame → analyze → identify critical column → demolish
- **Dual-Track Verification**: Fast (anaStruct linear elastic) vs High-Fidelity (OpenSees nonlinear)
- **Physics Simulation**: Unity Rigidbody + ConfigurableJoint with demolition forces and reset
- **Real-time Streaming**: WebSocket agent steps, WebRTC Unity camera (pending frontend consumer)
- **Persistent Memory**: mem0 SQLite-backed session memory (requires OpenAI key)

## Limitations

- OpenSees unavailable on Windows (DLL dependency); use Linux/macOS for high-fidelity analysis
- Unity scripts untested in Unity Editor (scripts written, no scene files)
- LLM agent requires OpenAI API key (not included)
- Single-user session (no multi-tenant isolation)
- See `PROJECT_STATUS.md` for full details
