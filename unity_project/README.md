# XuanwuAI Unity 3D Physics Simulator

Unity 3D 物理倒塌模拟器 — 前端一键启动，无需手动操作 Unity Editor。

## 用户体验

```
前端 Unity 面板                     Gateway                        Unity Editor
  │                                    │                              │
  │ 点击 [Launch Unity]                │                              │
  │ ──── POST /unity/launch ──────→ 创建 auto_play.flag             │
  │                                   spawn Unity.exe ──────────→ 启动 Editor
  │                                   │                              │
  │                                    │    [InitializeOnLoad]       │
  │                                    │    检测 flag → Setup Scene   │
  │                                    │    → Enter Playmode         │
  │                                    │                              │
  │                                    │     WebRTCStreamer          │
  │                                    │     SDP offer ←─────────── 自动生成
  │                                    │                              │
  │                                    │  ← POST /webrtc/offer       │
  │                                    │                              │
  │  ← GET /unity/status (poll) ──── 返回 webrtc_offer_available    │
  │                                    │                              │
  │  创建 PeerConnection              │                              │
  │  POST /webrtc/answer ─────────→ 存储 answer                    │
  │                                    │                              │
  │                                    │  ← GET /webrtc/answer (poll)│
  │                                    │                              │
  │ ═══ WebRTC P2P Video Stream ═══════════════════════════════→ 显示 3D 画面
  │                                    │                              │
  │  自动切换到 Unity 标签页           │                              │
```

**用户只需要做一件事：点击前端面板中的「Launch Unity」按钮。** 其余全部自动完成。

## 组件说明

| 脚本 | 功能 |
|------|------|
| `SimulationController.cs` | TCP :5005 监听，接收 JSON 拆除/重置指令，施加爆炸力 |
| `FrameBuilder.cs` | 程序化生成 2D 框架（柱 + 梁 + ConfigurableJoint） |
| `WebRTCStreamer.cs` | 捕获 Camera 画面，创建 WebRTC SDP offer |
| `WebRTCSignaling.cs` | SDP offer → Gateway HTTP；轮询 answer → 建立 WebRTC |
| `Editor/XuanwuAISceneSetup.cs` | Editor 菜单 Tool，也是自动流程的核心 |
| `Editor/AutoPlayOnLoad.cs` | `[InitializeOnLoad]` — 检测 auto_play.flag，自动 Setup Scene + Enter Playmode |
| `Runtime/SceneBootstrap.cs` | `[RuntimeInitializeOnLoadMethod]` — 运行时兜底：如果场景未搭建则自动创建 |

## 自动流程详解（四个阶段，九个环节）

从点击按钮到 3D 画面显示，全流程约 15-30 秒（首次需编译 C# 脚本，后续约 10 秒）。

---

### 阶段 1：Gateway 启动 Unity 进程

#### 环节 1.1 — 前端发起请求

- **文件**：`frontend/components/unity-video-panel.tsx`
- **函数**：`launchUnity()`
- **动作**：用户点击「Launch Unity」→ `POST http://localhost:8000/unity/launch`
- **状态变化**：`phase = "launching"`，面板显示「Launching Unity Editor...」+ 旋转动画

#### 环节 1.2 — Gateway 定位 Unity.exe

- **文件**：`gateway/main.py`
- **函数**：`_find_unity_exe()`
- **动作**：
  1. 检查环境变量 `UNITY_PATH`（优先级最高）
  2. Windows：扫描 `C:\Program Files\Unity\Hub\Editor\*\Editor\Unity.exe`
  3. 降级：扫描 `C:\Program Files\Unity\*\Editor\Unity.exe`
  4. macOS：扫描 `/Applications/Unity/Hub/Editor/*/Unity.app/...`
  5. 按版本号倒序排列，取最新版本
- **失败处理**：返回 404 + 错误消息 → 前端显示「Unity Editor not found」+ 下载链接

#### 环节 1.3 — Gateway 写入 flag + spawn 进程

- **文件**：`gateway/main.py`
- **函数**：`launch_unity()`
- **动作**：
  1. `os.makedirs("unity_project/Temp", exist_ok=True)`
  2. 写入 `unity_project/Temp/auto_play.flag`（内容为 `"1"`）
  3. `subprocess.Popen(["Unity.exe", "-projectPath", "<绝对路径>/unity_project"])`
  4. 返回 `{"status": "launching", "pid": <进程ID>}`
- **关键参数**：`-projectPath` 让 Unity 直接打开指定项目，跳过 Hub 选择界面

---

### 阶段 2：Unity Editor 自动搭建 + 进入 Play 模式

#### 环节 2.1 — Editor 初始化回调触发

- **文件**：`unity_project/Assets/Scripts/Editor/AutoPlayOnLoad.cs`
- **入口**：`[InitializeOnLoad] static AutoPlayOnLoad()` → 注册 `EditorApplication.update += CheckOnce`
- **时机**：Unity Editor 完全加载后，第一次 update 循环时触发（此时 Editor 对象已可用）
- **动作**：检查 `Temp/auto_play.flag` 是否存在
  - **存在** → 进入自动流程
  - **不存在** → 什么都不做（手动打开项目时不会自动 Play）

#### 环节 2.2 — 搭建场景

- **文件**：`unity_project/Assets/Scripts/Editor/XuanwuAISceneSetup.cs`
- **函数**：`XuanwuAISceneSetup.SetupScene()`（static，同时挂载为菜单项 `Tools/XuanwuAI/Setup Scene`）
- **动作**：
  1. `GameObject.Find("XuanwuAISimulation")` → 存在则 `DestroyImmediate`（避免重复）
  2. 创建 `XuanwuAISimulation` root → 挂载 `SimulationController` + `FrameBuilder`
  3. 创建 `XuanwuAICamera` → 挂载 `Camera`（位置 6,4,-15 + LookAt 6,3,0）+ `WebRTCStreamer`
  4. 创建 `XuanwuAILight` → Directional Light（强度 1.2，软阴影）
  5. 创建 `GroundPlane` → 深色 Plane，挂到 root 下
  6. `FrameBuilder.BuildFrame()` → 生成默认 2-span × 2-story 框架
     - 柱：每层每列一根，共 (spans+1) × stories = 6 根
     - 梁：每层每跨一根，共 spans × stories = 4 根
     - 每个 element：Cube mesh + Rigidbody + ConfigurableJoint 连接
     - 结构自动注册到 `SimulationController.structuralElements`（通过反射赋值 private field）

#### 环节 2.3 — 清理 flag + 进入 Play 模式

- **文件**：`unity_project/Assets/Scripts/Editor/AutoPlayOnLoad.cs`
- **函数**：`CheckOnce()`
- **动作**：
  1. `File.Delete("Temp/auto_play.flag")` — 防止用户下次手动打开项目时又自动 Play
  2. `EditorApplication.EnterPlaymode()` — 等效于用户手动点击 Play 按钮

---

### 阶段 3：运行时启动服务

#### 环节 3.1 — 场景兜底检查

- **文件**：`unity_project/Assets/Scripts/Runtime/SceneBootstrap.cs`
- **入口**：`[RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]`
- **动作**：`GameObject.Find("XuanwuAISimulation")`
  - **找到** → return（场景已由 Editor 脚本搭建好）
  - **未找到** → 在运行时用 `GameObject` API 执行与 SetupScene 相同的逻辑（不含 `EditorApplication` / `Selection` / `DestroyImmediate` 等 Editor-only API）
- **存在意义**：如果用户将搭建好的场景保存为 `.unity` 文件后直接双击打开（不经过 Editor 自动流程），此兜底确保一切就绪

#### 环节 3.2 — WebRTC 推流启动

- **文件**：`unity_project/Assets/Scripts/WebRTCStreamer.cs`
- **函数**：`Start() → StartCoroutine(StartStreaming())`
- **动作**：
  1. `WebRTC.Initialize()` — 初始化 Unity WebRTC 库
  2. `new RenderTexture(1280, 720, 24, ARGB32)` — 创建离屏渲染目标
  3. `Camera.targetTexture = renderTexture` — 将相机输出重定向到 RT
  4. `Camera.CaptureStreamTrack(1280, 720, 30)` — 创建视频轨道
  5. `new MediaStream()` → `AddTrack(videoTrack)` — 构建媒体流
  6. `new RTCPeerConnection(config)` — 创建 P2P 连接（STUN: `stun.l.google.com:19302`）
  7. `AddTrack(track, stream)` — 将视频轨道加入 P2P 连接
  8. `CreateOffer()` → `SetLocalDescription(offer)` — 生成 SDP offer
  9. `Convert.ToBase64String(Encoding.UTF8.GetBytes(offer.sdp))` — Base64 编码
  10. `OnSdpOfferReady?.Invoke(base64Sdp)` — 通过 C# event 抛出

#### 环节 3.3 — SDP Offer 发送到 Gateway

- **文件**：`unity_project/Assets/Scripts/Editor/WebRTCSignaling.cs`
- **函数**：`Start() → _streamer.OnSdpOfferReady += OnOfferReady → StartCoroutine(PostOffer(base64Sdp))`
- **动作**：
  1. `JsonUtility.ToJson({ sdp: base64Sdp })` — 序列化为 JSON
  2. `UnityWebRequest.Post("http://localhost:8000/webrtc/offer", jsonBody, "application/json")`
  3. Gateway 收到 → 存入全局变量 `_webrtc_offer`，清空旧 `_webrtc_answer`
  4. 启动协程 `PollAnswer()`：每 2 秒 `GET /webrtc/answer`，直到取到 answer

#### 环节 3.4 — TCP 指令服务启动

- **文件**：`unity_project/Assets/Scripts/SimulationController.cs`
- **函数**：`Start()`
- **动作**：
  1. 保存所有 `structuralElements` 的初始 Transform + Rigidbody 状态（用于 Reset）
  2. `new Thread(ListenForCommands) { IsBackground = true }` — 后台线程
  3. `TcpListener(IPAddress.Any, 5005).Start()` — 监听 TCP :5005
  4. 循环 `AcceptTcpClient()` → 读取 JSON → `lock(_commandLock)` → 写入 `_pendingCommand`
  5. 主线程 `Update()` 检测 `_pendingCommand` → `ExecuteCommand()` — 施加物理力

---

### 阶段 4：前端建立 WebRTC 连接

#### 环节 4.1 — 轮询检测到 Offer

- **文件**：`frontend/components/unity-video-panel.tsx`
- **函数**：`useEffect` 中的 `setInterval` 轮询（每 2 秒）
- **动作**：
  1. `GET /unity/status` → 检查 `webrtc_offer_available` 字段
  2. 为 `true` → 清除轮询 → 调用 `establishWebRTC()`
  3. 面板显示「Unity starting — waiting for WebRTC...」

#### 环节 4.2 — WebRTC P2P 建联

- **文件**：`frontend/components/unity-video-panel.tsx`
- **函数**：`establishWebRTC()`
- **动作**：
  1. `GET /webrtc/offer` → 获取 `{ sdp: "<base64>" }`
  2. `atob(offerBase64)` → 解码 SDP
  3. `new RTCPeerConnection(STUN_SERVERS)` → 创建浏览器端 P2P 连接
  4. `pc.ontrack = (event) => { videoRef.current.srcObject = event.streams[0] }` — 视频回调
  5. `pc.setRemoteDescription({ type: "offer", sdp: offerSdp })` — 接收 Unity 的 offer
  6. `pc.createAnswer()` → `pc.setLocalDescription(answer)` — 生成 answer
  7. `btoa(answer.sdp)` → `POST /webrtc/answer` — 发送 answer 到 Gateway

#### 环节 4.3 — Answer 返回 Unity

- **文件**：`unity_project/Assets/Scripts/Editor/WebRTCSignaling.cs`
- **函数**：`PollAnswer()` 协程
- **动作**：
  1. `GET /webrtc/answer` 获取到 answer
  2. `Convert.FromBase64String(resp.sdp)` → 解码
  3. `_streamer.ApplyRemoteAnswer(base64Sdp)` → `pc.SetRemoteDescription(answer)`
  4. WebRTC 握手完成 — P2P 视频流开始传输

#### 环节 4.4 — 前端显示画面 + 自动切换标签

- **文件**：`frontend/components/unity-video-panel.tsx` + `frontend/app/page.tsx`
- **动作**：
  1. `pc.ontrack` 触发 → `<video srcObject>` 设置 → 浏览器渲染 3D 画面
  2. `setPhase("connected")` → 面板状态变为「Live」绿点
  3. `onStreamConnected?.()` → 回调到 `page.tsx` → `setVizMode("unity")`
  4. **页面自动从 SVG 标签切换到 Unity 标签**，3D 画面显示在中央面板

## 手动启动（备选）

如果需要手动操作 Unity Editor：

1. 打开 `unity_project/` 目录
2. **Tools → XuanwuAI → Setup Scene**
3. 按 **Play**

## 修改框架尺寸

在 Hierarchy 中选择 `XuanwuAISimulation`，Inspector 中 FrameBuilder 参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| Spans | 2 | 跨数 |
| Stories | 2 | 层数 |
| Span Length | 6m | 跨长 |
| Story Height | 3m | 层高 |

修改后右键 FrameBuilder → Build Frame。

## TCP 指令格式

Unity 监听 `127.0.0.1:5005`：

```json
{"action": "demolish", "failed_elements": [0, 3], "force_multiplier": 1.5}
{"action": "reset"}
```

## 降级策略

| 层级 | 条件 | 行为 |
|------|------|------|
| MCP Server | Unity 未运行 | `"status": "simulated"` |
| 前端面板 | 无 SDP offer | 显示 Launch 按钮 |
| 前端面板 | Unity 未安装 | 显示下载链接 |
| 整体 | Unity 不可用 | SVG 2D 视图正常工作 |

## 目录结构

```
unity_project/
├── Assets/
│   └── Scripts/
│       ├── SimulationController.cs      TCP 拆除指令接收
│       ├── FrameBuilder.cs              程序化框架建模
│       ├── WebRTCStreamer.cs            WebRTC 推流
│       ├── WebRTCSignaling.cs           SDP 信令桥接
│       ├── Editor/
│       │   ├── XuanwuAISceneSetup.cs    场景搭建（手动 + 自动流程）
│       │   └── AutoPlayOnLoad.cs        [InitializeOnLoad] 自动 Setup + Play
│       └── Runtime/
│           └── SceneBootstrap.cs        [RuntimeInitializeOnLoad] 运行时兜底
├── Packages/
│   └── manifest.json                    依赖：com.unity.webrtc 3.0.0-pre.7
├── ProjectSettings/                     Unity 项目配置
└── README.md                            本文件
```
