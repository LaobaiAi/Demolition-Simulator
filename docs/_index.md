# XuanwuAI Demolition Simulator — 项目文档

> AI 驱动的渐进式建筑倒塌分析系统

## 目录

| 章节 | 内容 |
|------|------|
| [01 — WebSocket 通信机制](01-websocket/README.md) | 前后端 WebSocket 通信架构、保活机制、断线重连、状态管理 |
| [02 — 系统架构](02-architecture/README.md) | 整体架构设计、CAIAO 服务器模式、数据流 |
| [03 — 结构求解器](03-analysis-solvers/README.md) | anaStruct 快速分析、OpenSees 高精度验证、多求解器共识 |
| [04 — 拆除引擎](04-demolition/README.md) | 渐进式拆除逻辑、关键柱识别、倒塌判定 |
| [05 — Unity 3D 集成](05-unity/README.md) | Unity 物理引擎、WebRTC 推流、场景搭建 |
| [06 — 前端可视化](06-frontend/README.md) | SVG 框架模型、应力云图、倒塌动画、状态恢复 |
| [07 — 部署与运维](07-deployment/README.md) | 启动方式、环境配置、进程看门狗、故障排除 |

## 快速导航

- **代码仓库根目录**: `E:\Claude code workspace\XuanwuAI Demolition Simulator`
- **CLAUDEMD 总纲**: [CLAUDE.md](../CLAUDE.md) — 项目核心设计原则和用户指令
- **架构总纲**: [ARCHITECTURE.md](../ARCHITECTURE.md)
- **开发笔记**: [dev-notes/](../dev-notes/)
- **Git 提交规范**: 遵循 conventional commits (`feat/fix/chore/refactor`)
