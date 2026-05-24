# WebSocket 通信机制

## 概述

前端通过 WebSocket 与 Gateway 进行实时通信，用于：
- 发送用户消息到 LLM Agent
- 流式接收 Agent 的思考过程、工具调用、最终响应
- 工具调用结果实时推送

## 架构图

```
Frontend (page.tsx)                    Gateway (main.py)
       │                                     │
       │  connect()                           │  @app.websocket("/ws/chat")
       │  ws://localhost:8000/ws/chat          │
       ├─────────────────────────────────────►│
       │                                     │
       │  {"type":"message","content":"..."}  │
       ├─────────────────────────────────────►│  → AgentLoop → LLM stream
       │                                     │
       │  {"type":"thinking","content":"..."} │  ← streaming reasoning
       │◄─────────────────────────────────────┤
       │  {"type":"tool_call",...}            │  ← tool invocation
       │◄─────────────────────────────────────┤
       │  {"type":"tool_result",...}          │  ← tool result
       │◄─────────────────────────────────────┤
       │  {"type":"response","content":"..."} │  ← final answer
       │◄─────────────────────────────────────┤
```

## 消息类型

| type | 方向 | 说明 |
|------|------|------|
| `message` | Client → Server | 用户输入的消息 |
| `tool_call` | 双向 | 客户端触发的工具调用（预留） |
| `user_echo` | Server → Client | 服务端回显用户消息，前端用来重置状态 |
| `memory` | Server → Client | Agent 检索到的记忆片段 |
| `thinking` | Server → Client | LLM 推理过程的流式内容 |
| `tool_call` | Server → Client | Agent 决定调用的工具 |
| `tool_result` | Server → Client | 工具执行结果 |
| `response` | Server → Client | Agent 最终回复 |
| `error` | Server → Client | 错误信息 |
| `ping` | 双向 | 心跳保活消息（不触发任何 UI 更新） |

## 保活机制（三层防护）

### 1. 服务端心跳 (`gateway/main.py`)
```
每 15s → ws.send_json({"type": "ping"})
```
- 使用 `asyncio.create_task(_heartbeat())` 在 WebSocket 连接生命周期内运行
- WebSocket 断开时自动取消任务
- 保持中间代理/负载均衡器的连接不超时

### 2. 客户端保活 (`frontend/app/page.tsx`)
```
每 25s → ws.send(JSON.stringify({ type: "ping" }))
```
- 连接建立后启动定时器
- 连接断开时自动清除定时器
- 双向保活确保任何一端的超时策略都不会触发

### 3. Uvicorn WebSocket 配置
```python
uvicorn.run("main:app", ws_ping_interval=25, ws_ping_timeout=10)
```
- 协议层 ping 间隔 25s，等待 pong 超时 10s
- 与业务层心跳互不干扰

## 断线重连机制

```
指数退避策略：
  第 1 次: 1s   第 2 次: 2s   第 3 次: 4s
  第 4 次: 8s   第 5 次: 16s  第 6+ 次: 30s (cap)
```

关键实现 (`frontend/app/page.tsx`):
- `reconnectAttempts` 在连接成功时归零
- 最大延迟上限 30s，防止无限堆积
- `useEffect` 清理时清除定时器，防止组件卸载后重连

## 连接状态管理

三层状态转换：

```
disconnected ──connect()──► connected
      ◄──onclose──────      │
      ◄──onerror───────     │
                              │
                              ▼  onclose/onerror
                         reconnecting
                              │
                              ▼  connect() 成功
                         connected
```

UI 展示：
- **绿色** `connected` — WebSocket 已连接
- **黄色（闪烁）** `reconnecting` — 正在自动重连
- **红色** `disconnected` — 连接断开且未重连

## Gateway 进程看门狗

`gateway/watchdog.py` — 独立进程监控 gateway：
- 每 15s 检查 `GET /health`
- 如果进程退出或健康检查失败，自动重启
- 启动脚本 `start_dev.bat` 和 `XuanwuAI Launcher.bat` 已集成

```
[watchdog] Starting gateway watchdog...
[watchdog] Launching gateway...
[watchdog] Gateway is healthy.
[watchdog] Gateway exited with code -1, restarting...
[watchdog] Launching gateway...
```

## 关键代码位置

| 组件 | 文件 | 关键行 |
|------|------|--------|
| WebSocket 路由 | `gateway/main.py` | `@app.websocket("/ws/chat")` L745 |
| 心跳任务 | `gateway/main.py` | `_heartbeat()` L755 |
| Uvicorn 配置 | `gateway/main.py` | `uvicorn.run(...)` L853 |
| 前端连接 | `frontend/app/page.tsx` | `useEffect` L671 |
| 状态管理 | `frontend/app/page.tsx` | `wsConnected` 状态 L306 |
| 状态指示器 | `frontend/app/page.tsx` | L1718-1728 |
| 浮动工具栏 | `frontend/components/floating-toolbar.tsx` | `Gateway` 状态行 L192-207 |
| 看门狗 | `gateway/watchdog.py` | 完整文件 |

## 故障排查

| 现象 | 可能原因 | 解决方法 |
|------|---------|---------|
| 红点 "WS 断开" | Gateway 未运行 | 检查 `curl localhost:8000/health` |
| 黄点 "Reconnecting" | 网络抖动 / Gateway 重启 | 等待自动重连 |
| 发送消息无响应 | LLM 配置错误 | 检查 Settings → LLM 配置 |
| 频繁断开重连 | 网络不稳定 / 资源不足 | 检查系统资源，关闭无关应用 |
