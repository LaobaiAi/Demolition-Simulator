# XuanwuAI Demolition Simulator — 项目状态报告

**日期**: 2026-05-22
**总体完成度**: 约 85%（Day 1–8 基本完成，Day 9–10 已完成，剩余为可测试性问题）

---

## 一、原始计划的 10 天 MVP 对照

### Day 1: MCP Bus + demo_calculator ✅ 完成
- demo_calculator MCP server（add/subtract/multiply/divide 4 个工具）
- MCP SDK stdio transport 通信正常

### Day 2: FastAPI Gateway ✅ 完成
- FastAPI 应用入口（main.py），lifespan 管理 MCP 生命周期
- REST API: `/health`, `/tools`, `/tools/call`, `/verify`, `/ws/chat`
- WebSocket 实时通信
- CORS 中间件

### Day 3: OpenAI LLM + Agent Loop ✅ 完成
- LLMEngine 封装 OpenAI SDK（AsyncOpenAI）
- ReAct Agent Loop（think → act → observe → repeat，最多 5 轮）
- 支持 tool calling 自动路由

### Day 4: anaStruct 结构分析 ✅ 完成
- generate_simple_frame: 生成 2D 矩形框架（节点、单元、支座、荷载）
- analyze_frame: 线性弹性分析，返回位移和内力
- select_critical_element: 基于最大轴力选择关键柱

### Day 5: Unity C# 脚本 + Unity 模拟器 MCP ⚠️ 部分完成
- SimulationController.cs: TCP 监听 → JSON 指令解析 → 物理拆除/重置
- FrameBuilder.cs: Editor 工具，自动构建框架几何体和关节连接
- WebRTCStreamer.cs: 摄像头捕获 → WebRTC 推流
- unity_simulator MCP server: apply_demolition_action / reset_simulation
- **但**: 未在 Unity Editor 中实际测试，无场景文件、无预制件

### Day 6: AI 自主拆除循环 ✅ 完成
- SYSTEM_PROMPT 包含完整拆除工作流
- select_critical_element 工具实现
- 前端 MechanicalSummary 面板
- E2E 管道验证通过

### Day 7: OpenSees 高精度分析 ⚠️ 部分完成
- opensees_server 已实现，API 正确
- **但**: Windows 上 OpenSeesPy DLL 加载失败，服务器以降级模式运行
- `/verify` 端点目前使用 demo 模式（模拟扰动数据）

### Day 8: 前端 Chat + Verification UI ✅ 完成
- Next.js 三栏布局（Chat 30% | Viz 50% | Status 20%）
- WebSocket 实时通信 + 自动重连
- VerificationPanel: 双轨对比 + recharts 柱状图
- MechanicalSummary: 结构力学指标实时展示
- Agent Log Stream（可暂停/恢复）

### Day 9: Demo 脚本打磨 + UI 优化 ✅ 完成
- quickActions 更新为结构分析提示词（"Analyze a 2-story 2-bay frame" 等）
- 拆除确认对话框（红色脉冲按钮 → 确认弹窗含关键柱信息和轴向力）
- AI 思考时显示步骤进度（"Generating frame..." → "Analyzing structure..." → "Identifying critical column..."）
- 输入框占位符更新
- 系统提示词重构：AI 不再自动触发拆除，等待用户确认

### Day 10: 文档 + CI 设置 ✅ 完成
- Git 仓库初始化 + `.gitignore`（Python/Node/Unity/IDE/OS）
- GitHub Actions CI 配置（backend: pytest, frontend: tsc + lint + vitest + build）
- `/verify` 端点清理：移除假随机数据，改为 OpenSees 真实比较尝试 + "unavailable" 状态
- `PROJECT_STATUS.md` 完整项目状态文档（320 行）
- 初始 commit：54 文件

---

## 二、超出原始计划完成的内容

1. **WebRTC 视频流支持**: `WebRTCStreamer.cs` 实现 Unity 摄像头捕获并通过 WebRTC 推流到前端，包含 SDP 协商逻辑
2. **mem0 持久化记忆系统**: `memory.py` 实现 SessionMemory 类，支持存储/搜索/上下文注入，使用 SQLite 后端
3. **VerificationPanel 核验面板**: 带有红色辉光脉冲按钮、对比表格、recharts 双轨对比柱状图、偏差图 + 5% 阈值线
4. **MechanicalSummary 机械摘要面板**: 实时展示最大位移(mm)、最大轴力(kN)、关键柱信息、拆除目标列表
5. **Agent Log Stream**: 底部终端风格日志流，支持暂停/恢复、自动滚动
6. **前端快速操作按钮**: 预设计算表达式一键填入
7. **WebSocket 自动重连**: 2 秒间隔自动重连
8. **前端暗色主题**: 深色 (#0f172a) + 青色强调 (#22d3ee) 配色
9. **Markdown 渲染**: AI 回复支持 **粗体**、`代码` 和内联标记
10. **select_critical_element 工具**: 几何判定（同 x 坐标为柱）+ 轴力排序的柱选择算法

---

## 三、已完成但有问题的部分

### 3.1 OpenSees 在 Windows 上不可用
- **状态**: openseespy 依赖的 DLL 无法加载
- **影响**: 高精度分析降级为 demo 模拟模式（使用随机扰动生成对比数据）
- **解决方案**: 在 Linux/macOS 上部署可正常使用，或使用 WSL2

### 3.2 Unity C# 脚本未实际测试
- **状态**: 3 个 .cs 文件已编写但未在 Unity Editor 中运行
- **缺少**: `.unity` 场景文件、`.prefab` 预制件、`Assets/Scenes/` 为空
- **依赖**: `com.unity.webrtc` 包需要手动安装
- **原因**: 当前环境无 Unity Editor 2021.3 LTS

### 3.3 mem0 记忆系统需要 OpenAI API Key
- **状态**: 初始化失败时静默降级，返回空上下文
- **影响**: 跨会话记忆功能实际不可用
- **日志**: `mem0 init failed: Missing credentials`

### 3.4 MCP SDK 在 Windows 上的 cancel scope 问题
- **现象**: uvicorn reload 模式下偶发 `RuntimeError: Attempted to exit cancel scope in a different task`
- **影响**: 开发时重启偶发崩溃，生产环境（无 reload）不受影响

### 3.5 没有配置 LLM API Key
- **状态**: 代码支持通过环境变量 `OPENAI_API_KEY` 或构造函数参数传入
- **影响**: Agent 循环无法实际调用 LLM，前端对话功能不可用
- **测试**: 所有 LLM 相关测试使用 mock，测试通过但不代表真实可用

### 3.6 前端 quickActions 仍是旧版数学题
- **状态**: 快速操作按钮显示 "3 + 4"、"10 * 5.5" 等数学题
- **应该**: 更新为结构分析相关的提示词（如 "Analyze a 2-story 3-bay frame"）

---

## 四、跳过/略过的内容

1. **MCP server 单元测试**: 全部 4 个 `mcp_servers/*/tests/` 目录为空，未编写任何测试
2. **Unity 场景搭建**: 无 `.unity` 场景文件，无材质配置，无物理参数调优
3. **WebRTC 信令服务**: WebRTCStreamer 只生成了 SDP offer，前端侧无对应的 WebRTC answer 消费逻辑
4. **OpenSees 真实对比验证**: `/verify` 端点使用模拟数据而非真实 OpenSees 分析结果
5. **拆除动画的渐进式坍塌**: SimulationController 只有简单的爆炸力施加，无逐帧坍塌传播模拟
6. **确认对话框/安全机制**: 拆除操作直接执行，无二次确认
7. **多用户会话隔离**: 单例 Agent/Memory，无多用户支持
8. **前端路由**: 仅单页应用，无多页面路由（Next.js App Router 未充分利用）
9. **错误边界组件**: 前端无 ErrorBoundary
10. **国际化 (i18n)**: 仅英文

---

## 五、启动方式

### 5.1 环境要求
- Python 3.11+（含 venv）
- Node.js 20+
- Unity Editor 2021.3 LTS（仅 Unity 模拟器需要）
- Windows 10+ / Linux / macOS

### 5.2 启动 Gateway 后端

```bash
# 进入 gateway 目录
cd gateway

# 创建并激活虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/macOS

# 安装依赖
pip install -r requirements.txt

# 启动 Gateway
python main.py
# Gateway 运行在 http://localhost:8000
```

### 5.3 启动前端

```bash
# 进入 frontend 目录
cd frontend

# 安装依赖
npm install

# 开发模式启动
npm run dev
# 前端运行在 http://localhost:3000
```

### 5.4 配置 LLM API Key

在 gateway 目录下创建 `.env` 文件或设置环境变量：

```bash
export OPENAI_API_KEY="sk-your-key-here"
export OPENAI_BASE_URL="https://api.openai.com/v1"  # 可选，自定义端点
```

### 5.5 启动 Unity 模拟器（可选）

1. 用 Unity Editor 2021.3 LTS 打开 `unity_project/` 目录
2. 导入 `com.unity.webrtc` 包（通过 Package Manager → Add from git URL）
3. 在场景中创建 GameObject，挂载 `SimulationController` 和 `FrameBuilder`
4. 运行场景（SimulationController 自动在 5005 端口监听 TCP 连接）
5. 右键 FrameBuilder 组件 → Build Frame 生成框架

### 5.6 验证启动

```bash
# 检查 Gateway 健康状态
curl http://localhost:8000/health

# 查看已注册工具
curl http://localhost:8000/tools

# 测试框架生成
curl -X POST http://localhost:8000/tools/call \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"generate_simple_frame","arguments":{"spans":2,"stories":2}}'
```

---

## 六、注意事项

1. **端口冲突**: Gateway 使用 8000 端口，前端 3000，Unity TCP 5005。启动前确保端口未被占用。使用 `taskkill /F /IM python.exe` 清理残留进程。

2. **不要同时运行多个 Gateway 实例**: MCP server 通过 stdio 子进程管理，多个 Gateway 实例会导致端口冲突和 MCP server 双重启动。

3. **uvicorn reload 模式**: 开发时默认启用，文件变更自动重启。但偶尔触发 MCP SDK 的 cancel scope 竞态条件导致崩溃——重新手动启动即可。

4. **OpenSees 仅在 Linux/macOS 可用**: Windows 上的 `openseespy` 依赖的 DLL（`openseespywin`）缺少 Visual C++ 运行时组件。服务器会自动降级。

5. **Unity 模拟器 TCP 无加密**: `localhost:5005` 的 TCP 通信为明文 JSON，仅限本机使用。

6. **WebSocket 未认证**: `/ws/chat` 端点无身份认证，不应暴露到公网。

7. **前端热重载**: `npm run dev` 使用 Turbopack，修改代码后自动刷新。

8. **Python 路径中的空格**: 项目路径包含空格（`Claude code workspace`），部分工具可能有问题。venv 位于 `gateway/venv/`。

9. **mem0 静默失败**: 无 OpenAI key 时，记忆功能静默禁用，不影响其他功能。

---

## 七、测试覆盖情况

### 7.1 已通过测试

| 模块 | 测试文件 | 测试数 | 状态 |
|------|---------|--------|------|
| gateway/mcp_hub | tests/test_mcp_hub.py | 7 | ✅ 全部通过 |
| gateway/llm_engine | tests/test_llm_engine.py | 9 | ✅ 全部通过 |
| gateway/agent_loop | tests/test_agent_loop.py | 6 | ✅ 全部通过 |
| gateway/api | tests/test_api.py | 5 | ✅ 全部通过（需 gateway 运行中） |
| gateway/memory | tests/test_memory.py | 5 | ✅ 全部通过 |
| demo_calculator | tests/test_server.py | 9 | ✅ 全部通过 |
| anastruct_server | tests/test_server.py | 19 | ✅ 全部通过 |
| frontend/page | __tests__/page.test.tsx | 7 | ✅ 全部通过 |
| frontend/summary | __tests__/mechanical-summary.test.tsx | 9 | ✅ 全部通过 |
| opensees_server | tests/ | 0 | ❌ 空目录 |
| unity_simulator | tests/ | 0 | ❌ 空目录 |
| **合计** | | **76** | **全部通过** |

### 7.2 未测试内容

| 内容 | 原因 |
|------|------|
| opensees_server / unity_simulator | tests/ 目录为空；unity_simulator 依赖 TCP socket mock |
| Unity C# 脚本 | 无 Unity Editor 环境，无法运行 |
| WebSocket 实时消息流 | 无 WebSocket 集成测试 |
| E2E 用户场景 | 无端到端测试框架 |
| OpenSees 分析 | 当前环境不可用 |
| WebRTC 视频流 | 缺少 Unity Editor + 前端信令实现 |
| VerificationPanel | 需要 mock API 调用 + recharts 的 ResponsiveContainer |

### 7.3 手动验证通过的内容

- generate_simple_frame → analyze_frame → select_critical_element 完整管道
- Gateway 4 个 MCP server 同时启动（10 个工具注册）
- 前端 TypeScript 编译 + 生产构建
- REST API 全部端点响应正确

---

## 八、未来扩展开发注意事项

### 8.1 架构层面

1. **MCP server 脱离 gateway 进程**: 当前 MCP server 作为子进程由 gateway 管理。如需分布式部署，考虑将 MCP server 独立部署并通过 HTTP/SSE transport 连接。

2. **移除 demo 模拟代码**: `/verify` 端点和 `quickActions` 中仍有硬编码的 demo 数据，生产部署时应替换为真实 OpenSees 分析或删除。

3. **WebSocket 消息协议版本化**: 当前 WebSocket JSON 消息无版本字段，前后端协议变更时可能不兼容。建议添加 `version` 字段。

4. **Agent 状态持久化**: 当前 Agent 循环状态（history、pending steps）仅存于内存，进程重启后丢失。可考虑持久化到数据库或 Redis。

### 8.2 前端

5. **组件拆分**: `page.tsx` 已膨胀到 ~400 行，建议将 Chat 面板、Log Stream、Right Sidebar 拆分为独立组件。

6. **状态管理**: 当前使用多个 useState，跨组件通信困难。对于复杂应用可考虑 Zustand 或 Jotai。

7. **WebRTC 消费端未实现**: 前端目前无 WebRTC answer 生成逻辑。需要实现 RTCPeerConnection 接收 Unity 视频流。

8. **响应式布局**: 当前三栏布局使用固定百分比宽度，小屏幕体验差。建议添加移动端适配。

### 8.3 Unity

9. **物理参数需要标定**: 当前 Rigidbody mass=500kg、linearDamping=0.1 等参数为随意设置，需要与真实结构物理特性对标。

10. **拆除力学模型过于简化**: 仅施加爆炸力 + 禁用关节。真实的渐进式坍塌需要：材料非线性、接触检测、碎片化、连锁失效传播。

11. **WebRTC 包依赖**: `com.unity.webrtc` 需要确认版本兼容性（Unity 2021.3 + WebRTC 3.x）。

### 8.4 测试

12. **MCP server 测试空白**: 4 个 server 的 `tests/` 目录为空。建议至少添加工具函数的单元测试（mock 掉 anaStruct/OpenSees 依赖）。

13. **前端组件测试不足**: 仅 1 个测试文件 7 个测试。MechanicalSummary、VerificationPanel 无测试。

14. **添加 E2E 测试**: 使用 Playwright 或 Cypress 覆盖完整用户流程。

### 8.5 安全

15. **WebSocket 无认证**: 生产环境需要 JWT 或 session 认证。

16. **Unity TCP 无认证**: `localhost:5005` 的 JSON 协议无安全机制。如果 Unity 和 Gateway 不在同一机器，需要添加 TLS + 认证。

17. **输入校验**: REST API 的 tool arguments 未做深度校验，依赖 MCP server 内部处理。建议在 gateway 层添加 schema 验证。

---

## 九、其他交代事项

1. **项目无 git 仓库**: 当前项目目录未初始化 git（`is a git repository: false`）。强烈建议立即初始化并提交所有代码。

2. **venv 路径**: gateway 的虚拟环境在 `gateway/venv/`，MCP server 也使用同一 venv 的 Python（`VENV_PYTHON` 常量引用）。不要删除此 venv。

3. **litellm → openai 迁移**: 原始计划使用 litellm，但因安装问题切换为 openai SDK。如果后续需要支持多种 LLM 提供商（Anthropic, Azure 等），可以考虑重新引入 litellm（在非 Windows 环境）。

4. **deepseek-v4-pro 模型**: 当前会话使用的模型是 deepseek-v4-pro，但代码中默认配置为 gpt-4o。更改模型需修改 `llm_engine.py` 的默认参数或设置环境变量。

5. **ANASTRUCT_API_FIXES**: anaStruct 的 API 有多个陷阱（`ss.node_map` 不是 `ss.nodes`、位移键 `uy` 不是 `uz`、`get_element_results` 不是 `get_element_result_range`），已全部修正。升级 anaStruct 版本时需重新验证。

6. **Unity 项目缺少工程文件**: `unity_project/` 目录下只有 `Assets/Scripts/` 中的 .cs 文件。缺少 `.sln`、`.csproj`、`ProjectSettings/`、`Packages/manifest.json` 等 Unity 项目骨架。需要在 Unity Editor 中创建项目后手动导入这些脚本。
