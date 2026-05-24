# 前端可视化

_文档待完善_

## 主要功能

| 功能 | 组件 | 说明 |
|------|------|------|
| 框架可视化 | `frame-visualization.tsx` | SVG 2D 结构模型 + 应力云图 + 倒塌动画 |
| Unity 3D | `unity-video-panel.tsx` | WebRTC 视频流（Unity 运行时） |
| 双轨验证 | `verification-panel.tsx` | Displacements / Forces / Compare / Dev |
| 机械摘要 | `mechanical-summary.tsx` | 关键指标卡片 |
| 工具栏 | `floating-toolbar.tsx` | 浮动操作面板 |
| 侧边栏 | `sidebar.tsx` | 设置、记忆管理 |

## 关键特性

- **应力云图配色**: 绿(<30%) / 黄(30-60%) / 橙(60-85%) / 红(>85%)
- **倒塌动画**: SVG + requestAnimationFrame（Unity 不可用时 fallback）
- **状态恢复**: `restoreStateFromMessages()` 重载完整对话状态
- **国际化**: 中英双语 (`lib/i18n.ts`)
- **存储管理**: 清空对话、清空记忆、导出备份
