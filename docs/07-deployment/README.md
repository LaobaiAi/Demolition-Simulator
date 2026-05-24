# 部署与运维

## 启动方式

### 开发模式（推荐）
```bash
start_dev.bat
```
启动 Gateway (watchdog) + Frontend

### 完整模式（含 Unity）
```bash
XuanwuAI Launcher.bat
```
选择对应选项启动

### 手动启动
```bash
# Gateway
cd gateway && venv/Scripts/python.exe main.py

# 或带看门狗
cd gateway && venv/Scripts/python.exe watchdog.py

# Frontend
cd frontend && npm run dev
```

## 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.12+ | venv 位于 `gateway/venv/` |
| Node.js | 18+ | 用于 Next.js 前端 |
| Unity (可选) | 2022.3+ | 3D 物理引擎 |

## 进程管理

| 进程 | 端口 | 说明 |
|------|------|------|
| Gateway | 8000 | FastAPI + WebSocket |
| Frontend | 3000 | Next.js 开发服务器 |
| Unity | 5005 (TCP) | 物理引擎通信 |
| 资源监控 | - | `_resource_guard.ps1` 每 30-60s 检查 |

## 故障排除

见各功能模块文档的「故障排查」章节。
