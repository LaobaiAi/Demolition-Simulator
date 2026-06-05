# XuanwuAI Demolition Simulator — 项目状态报告

**日期**: 2026-06-05（最后更新）
**总体完成度**: 功能全集已闭环，架构重构进行中（CAIAO 化 Phase 1-2 完成 65%）
**Git**: 54 commits，14 个测试文件（gateway 7 + caiao_server 5 + 前端 2），CI 已完善（含 manifest 校验 + server 测试）

---

## 一、原始计划的 10 天 MVP 对照

### Day 1: CAIAO Bus + demo_calculator ✅ 完成
- demo_calculator CAIAO server（add/subtract/multiply/divide 4 个工具）
- CAIAO SDK stdio transport 通信正常

### Day 2: FastAPI Gateway ✅ 完成
- FastAPI 应用入口（main.py），lifespan 管理 CAIAO 生命周期
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

### Day 5: Unity C# 脚本 + Unity 模拟器 CAIAO ✅ 完成
- SimulationController.cs: TCP 监听 → JSON 指令解析 → 物理拆除/重置
- FrameBuilder.cs: Editor 工具，自动构建框架几何体和关节连接
- WebRTCStreamer.cs: 摄像头捕获 → WebRTC 推流
- unity_simulator CAIAO server: apply_demolition_action / reset_simulation
- XuanwuAISceneSetup.cs: Unity Editor → Tools → XuanwuAI → Setup Scene 一键场景搭建
- 前端一键 Launch Unity（自动启动 Editor + Setup Scene + Play）

### Day 6: AI 自主拆除循环 ✅ 完成
- SYSTEM_PROMPT 包含完整拆除工作流
- select_critical_element 工具实现
- 前端 MechanicalSummary 面板
- E2E 管道验证通过

### Day 7: OpenSees 高精度分析 ⚠️ 部分完成
- opensees_server 已实现，API 正确
- **但**: Windows 上 OpenSeesPy DLL 加载失败，服务器以降级模式运行
- `/verify` 端点：尝试调用 OpenSees 真实对比，不可用时返回 "unavailable" 状态（不再生成假数据）

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
6. **拆除确认对话框**: 红色脉冲按钮 → Dialog 弹窗（显示关键柱 ID、轴向力、Unity 运行提示）→ 确认后发送拆除指令
7. **AI 步骤进度指示器**: 思考时实时展示当前步骤（Generating frame... → Analyzing structure... → Identifying critical column...）
8. **WebSocket 自动重连**: 2 秒间隔自动重连
9. **前端暗色主题**: 深色 (#0f172a) + 青色强调 (#22d3ee) 配色
10. **Markdown 渲染**: AI 回复支持 **粗体**、`代码` 和内联标记
11. **select_critical_element 工具**: 几何判定（同 x 坐标为柱）+ 轴力排序的柱选择算法
12. **ErrorBoundary 组件**: React class component 错误兜底 + Try Again 按钮
13. **GitHub Actions CI**: backend pytest + frontend tsc/lint/vitest/build 自动运行
14. **系统提示词重构**: AI 分析完报告结果并提示用户点击 Demolish 按钮，不再自动触发拆除
15. **JSON 序列化三层防护**: 全局 `json.dumps` 猴子补丁 + `_sanitize_for_json` 递归清洗 + `_normalize_content` LLM 内容规范化，彻底解决 TextContent 等非标准对象序列化问题
16. **浮动工具栏 FloatingToolbar**: 可自由拖动的浮动面板（CSS 变量方案，SSR 安全），含 Gateway 连接状态、工具数量、LLM 设置入口、清空聊天、快捷分析指令
17. **按模型记忆 LLM 配置**: localStorage 以 model 为 key 存储 `{api_key, base_url}`，切换模型自动回填 URL/Key
18. **DeepSeek 思维链兼容**: 保留并回传 `reasoning_content` 字段，支持 DeepSeek v4-pro 等推理模型

### 2026-05-22 之后新增完成的内容

19. **CAIAOServerizer 复合 Server**: quick_analysis_server（frame_generator + anastruct + select_critical 合并为单次调用）、full_analysis_3d_server（3D 生成 → UnifiedFrame 转换 → PyNite 3D 分析 → 选关键柱）
20. **30 个 CAIAO Server 全部 caiao.yaml 化**: 覆盖率 100%，legacy 硬编码 SERVER_CONFIGS（175 行）已删除
21. **4 个 Composite Pipeline**: full_bim_demolition、run_full_analysis（已废弃）、visual_demolition（mechanics/topology 合并）、abaqus_collapse_pipeline（已删除，单步骤透传无编排价值）
22. **Abaqus 倒塌仿真集成**: abaqus_environment_server（环境发现 + 校验）、abaqus_session_server（CAE 持久会话，15 个建模/分析/拆除工具）
23. **Blender 可视化管线**: 6 个 Blender CAIAO server（environment、build、animate、machinery、render、pipeline）+ animation_control_server + physics_server
24. **Unity 3D 集成完善**: WebRTC 视频流面板、前端一键 Launch Unity（自动启动 Editor + Setup Scene + Play 模式）、SVG 2D 降级方案自动 fallback
25. **BIM 模型 Server**: bim_model_server（2087 行，7 个工具）支持 IFC 格式
26. **3D 框架可视化**: frame-visualization-3d.tsx（925 行）Three.js 3D 渲染
27. **拆除动画系统**: timeline-editor、demolition-controller、animation-exporter 三个前端组件 + 4 个 CAIAO composite server
28. **Gateway 架构拆分**: main.py 从 1298 行拆分为 routers/（6 文件）+ services/pipeline_service.py + main.py（453 行）
29. **PyPI caiao 包迁移**: Gateway 不再维护自己的 Hub 实现，改用 PyPI `caiao` 包
30. **CAIAO Manager Server**: manager_server（3045 行，24 个工具）——元 Server：创建/扩展/健康检查/迁移/检索/编排
31. **中英文双语支持**: frontend/lib/i18n.ts（684 行），所有用户可见文字走 `t(key, lang)` 调用
32. **场景选择器**: scenario-picker.tsx 支持多种结构类型和拆除策略
33. **CI 完善**: 并发控制、pip 缓存、caiao.yaml 清单校验、CAIAO server 测试自动发现执行

---

## 三、当前已知问题

### 3.1 OpenSees 在 Windows 上不可用
- **状态**: openseespy 依赖的 DLL 无法加载；opensees_server 启动时捕获异常后以降级模式运行
- **影响**: 高精度分析不可用；`/verify` 端点返回 "unavailable" 状态
- **解决方案**: 在 Linux/macOS 上部署可正常使用，或使用 WSL2

### 3.2 测试覆盖率偏低
- **状态**: 30 个 server 中仅 5 个有测试（17%），核心组件 frame-visualization.tsx（1422 行）零覆盖
- **估算覆盖率**: 约 6%
- **前端 page.tsx**: 2793 行单文件，尚未提取自定义 hook

### 3.3 部分 Server 存在功能重叠
- **分析求解器**: 4 个（anastruct/opensees/pynite/fapp），fapp 无 pipeline 引用
- **visual_demolition**: mechanics 和 topology 两个 pipeline 仅差 2 个 FEM 步骤
- **comparison_server**: 直接从 planning_server 导入函数，违反 Server 独立原则

### 3.4 CAIAO SDK 在 Windows 上的 cancel scope 问题
- **现象**: uvicorn reload 模式下偶发 `RuntimeError: Attempted to exit cancel scope in a different task`
- **影响**: 开发时重启偶发崩溃，生产环境（无 reload）不受影响

### 3.5 部分 Server 调用链路不清晰（孤岛）
- planning_server（1562 行）、scenario_server（420 行）、comparison_server（552 行）的前端/LLM 可达性待审查

---

## 四、跳过/略过的内容

1. **opensees_server / unity_simulator 单元测试**: 仍为空（opensees 需特定平台，unity 需 TCP mock）
2. **24 个 CAIAO server 无测试**: 多数为 Blender/Abaqus/composite，依赖外部工具或纯编排
3. **OpenSees 真实对比验证**: Windows 上不可用，`/verify` 端点返回 "unavailable"
4. **多用户会话隔离**: 单例 Agent/Memory，无多用户支持
5. **前端路由**: 仅单页应用，无多页面路由（Next.js App Router 未充分利用）
6. **frame-visualization.tsx 测试**: 核心 SVG/Canvas 组件（1422 行）零覆盖
7. **E2E 测试**: 关键数据流（生成→分析→拆除→动画）无自动化覆盖

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

2. **不要同时运行多个 Gateway 实例**: CAIAO server 通过 stdio 子进程管理，多个 Gateway 实例会导致端口冲突和 CAIAO server 双重启动。

3. **uvicorn reload 模式**: 开发时默认启用，文件变更自动重启。但偶尔触发 CAIAO SDK 的 cancel scope 竞态条件导致崩溃——重新手动启动即可。

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
| gateway/caiao_hub | tests/test_caiao_hub.py | 7 | ✅ 全部通过 |
| gateway/llm_engine | tests/test_llm_engine.py | 9 | ✅ 全部通过 |
| gateway/agent_loop | tests/test_agent_loop.py | 6 | ✅ 全部通过 |
| gateway/api | tests/test_api.py | 5 | ✅ 全部通过（需 gateway 运行中） |
| gateway/memory | tests/test_memory.py | 5 | ✅ 全部通过 |
| gateway/data_flow | tests/test_data_flow.py | 11 | ✅ 全部通过 |
| gateway/textcontent | tests/test_textcontent_fix.py | 1 | ✅ 全部通过 |
| anastruct_server | tests/test_server.py | 19 | ✅ 全部通过 |
| demo_calculator | tests/test_server.py | 4 | ✅ 全部通过 |
| frame_generator | tests/test_core.py | 8+ | ✅ 全部通过 |
| full_analysis_3d_server | test_server.py | 6+ | ✅ 全部通过 |
| manager_server | test_manager.py | 20+ | ✅ 全部通过 |
| frontend/page | __tests__/page.test.tsx | 7 | ✅ 全部通过 |
| frontend/summary | __tests__/mechanical-summary.test.tsx | 8 | ✅ 全部通过 |
| **合计** | **14 个测试文件** | **~120** | **全部通过** |

### 7.2 未测试内容

| 内容 | 原因 |
|------|------|
| 25 个 CAIAO server | 无测试文件（多数为 Blender/Abaqus/composite，依赖外部工具） |
| frame-visualization.tsx（1422 行） | 核心 SVG/Canvas 组件，零覆盖 |
| verification-panel.tsx（743 行） | 需要 mock API + recharts |
| Unity C# 脚本 | 无 Unity Editor 测试框架 |
| WebSocket 实时消息流 | 无 WebSocket 集成测试 |
| E2E 用户场景（生成→分析→拆除→动画） | 无端到端测试 |
| i18n 翻译 key 完整性 | 无自动校验 |

### 7.3 手动验证通过的内容

- generate_simple_frame → analyze_frame → select_critical_element 完整管道
- Gateway 4 个 CAIAO server 同时启动（10 个工具注册）
- 前端 TypeScript 编译 + 生产构建
- REST API 全部端点响应正确

---

## 八、未来扩展开发注意事项

### 8.1 架构层面

1. **Gateway services 层补齐**: routers/ 已完成拆分，但 services/ 只有 pipeline_service.py。chat service、verify service、unity manager service 仍需提取。

2. **前端 page.tsx 拆分**: 当前 2793 行，需提取 useChat/useStructure/usePipeline 三个自定义 hook，目标是 500 行以内。

3. **CAIAO Server 去重**: 分析求解器 4 个（anastruct/opensees/pynite/fapp），visual_demolition pipeline 2 个（mechanics/topology 仅差 2 步），需做取舍。

4. **孤岛 Server 处置**: planning_server、scenario_server、comparison_server 的调用链需要打通或标记为 deprecated。

5. **WebSocket 消息协议版本化**: 当前 WebSocket JSON 消息无版本字段，前后端协议变更时可能不兼容。

6. **Agent 状态持久化**: 当前 Agent 循环状态仅存于内存，进程重启后丢失。

### 8.2 前端

7. **frame-visualization.tsx 测试**: 核心组件（1422 行）零覆盖，至少需要应力比颜色分段、杆件分类、倒塌判定逻辑的单元测试。

8. **状态管理**: 当前使用多个 useState，跨组件通信困难。提取 hook 后可考虑 Context 或轻量状态库。

9. **i18n key 完整性校验**: 当前无自动检查确保所有 key 在 EN/ZH 翻译文件中都存在，需添加 CI 校验脚本。

### 8.3 测试

10. **关键数据流 E2E 测试**: 生成→分析→关键柱识别→渐进拆除→倒塌可视化 的完整链路需要自动化测试。

11. **CAIAO server 连通性测试**: 24 个 server 零覆盖，至少需要 MCP ping 级别的连通性测试。

### 8.4 安全

12. **WebSocket 无认证**: 生产环境需要 JWT 或 session 认证。

13. **Unity TCP 无认证**: `localhost:5005` 的 JSON 协议无安全机制。

14. **输入校验**: REST API 的 tool arguments 未做深度校验，依赖 CAIAO server 内部处理。

---

## 九、其他交代事项

1. **Git 仓库**: 54 个 commits，已配置 GitHub Actions CI（并发控制、pip 缓存、caiao.yaml 清单校验、CAIAO server 测试自动发现）。

2. **venv 路径**: gateway 的虚拟环境在 `gateway/venv/`，CAIAO server 也使用同一 venv 的 Python。不要删除此 venv。

3. **LLM 配置**: 默认模型为 gpt-4o，可通过前端 Settings 对话框或环境变量覆盖。支持 DeepSeek v4-pro 等兼容 OpenAI SDK 的模型。

4. **CAIAO Server 清单**: 全部 30 个 server 都有 caiao.yaml，新增 server 需遵循 `_template/` 模板和 `CAIAO_PROTOCOL.md` 规范。

5. **Unity 集成**: 前端一键 Launch Unity（自动启动 Editor + Setup Scene + Play），WebRTC 视频流面板已实现。Unity 不可用时自动 fallback 到 SVG 2D 动画。

6. **项目评估报告**: 完整项目评估见 `dev-notes/reference/2026-06-05-project-assessment.md`。
