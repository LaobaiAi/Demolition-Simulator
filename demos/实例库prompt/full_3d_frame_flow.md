# 3D 框架全流程 — 完整 Prompt 流程

> 内置 Demo ｜ 3D 钢框架 ｜ 渲染：WebGL 3D
> 3×4 柱网（X 向 3 跨、Y 向 4 跨）、4 层、Q355 钢，双向跨度，生成 → 静力分析 → 识别关键柱 → 渐进式拆除。

## 1. 触发话术

| 语言 | 话术 |
|---|---|
| English | Build a 3D steel frame with a 3x4 column grid (3 spans in X, 4 spans in Y), 4 stories, 6m span in both directions, 3m story height, Q355 steel. Use the frame generator tool to create the model, run static analysis, identify critical columns, and demolish them progressively. |
| 中文 | 创建一个三维钢框架：3×4 柱网（X 向 3 跨、Y 向 4 跨）、4 层、双向 6m 跨度、3m 层高、Q355 钢，运行静力分析，识别关键柱并渐进式拆除 |

## 2. 完整对话流（3D Model → Analyze → ID Critical → Demolish）

```
用户:  Build a 3D steel frame with a 3x4 column grid...
━━━ Phase 1 · 3D 建模（3D Model）━━━
助手:  (调用 generate_frame_3d / steel_frame_3d_generator)
       ✅ 已生成 3D 框架：3×4 柱网（X 3 跨 + Y 4 跨）× 4 层
       - 柱 / 梁（X 向 + Y 向）/ 节点数据
━━━ Phase 2 · 分析（Analyze）━━━
助手:  (调用 full_analysis_3d — PyNite 3D FEM)
       ✅ 3D 有限元静力分析完成
━━━ Phase 3 · 识别关键柱（ID Critical）━━━
助手:  ✅ 关键柱已识别（受力最不利柱）
━━━ Phase 4 · 拆除（Demolish）━━━
助手:  ✅ 触发渐进式拆除（关键柱移除 → 连锁倒塌动画）
```

## 3. 工具调用链（后端视角）

| # | 阶段 | 工具调用 | 后端实现 |
|---|---|---|---|
| 1 | 3D Model | `generate_frame_3d`（X/Y 双向跨度） | `caiao_servers/frame_generator/server.py` 或 `caiao_servers/steel_frame_3d_generator/server.py` |
| 2 | Analyze | `full_analysis_3d`（PyNite 3D FEM） | `caiao_servers/full_analysis_3d_server/server.py`（geometry → UnifiedFrame 转换 → 求解） |
| 3 | ID Critical | 关键柱识别 | PyNite 结果中最大内力/位移柱 |
| 4 | Demolish | 渐进式拆除 | 移除关键柱 → 连锁反应动画 |

## 4. 参数明细

| 参数 | 值 |
|---|---|
| grid_x | [6, 6, 6]（X 向 3 跨） |
| grid_y | [6, 6, 6, 6]（Y 向 4 跨） |
| num_stories | 4（4 层） |
| story_heights | [3, 3, 3, 3] |
| material | Q355（钢） |
| viz_mode | 3d（WebGL 可视化） |

## 5. 各环节输入→输出明细

| 环节 | 输入 | 输出 |
|---|---|---|
| 3D 建模 | 柱网 grid_x / grid_y + 层高 | 3D 几何（nodes / columns / beams_x / beams_y） |
| 静力分析 | UnifiedFrame（nodes / elements / loads / supports） | 节点位移 + 内力（PyNite） |
| 关键柱 | 分析结果 | 关键柱列表 |
| 渐进式拆除 | 关键柱 + 结构 | 连锁倒塌动画（3D） |
