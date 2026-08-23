# 框架生成器流水线 — 完整 Prompt 流程

> 内置 Demo ｜ 2D 参数化钢框架 ｜ 渲染：SVG 2D
> 3跨×4层 Q355 钢框架，6m 跨、3m 层高，生成 → 静力分析 → 识别关键柱 → 渐进式拆除。

## 1. 触发话术

| 语言 | 话术 |
|---|---|
| English | Generate a 3-bay 4-story steel frame using Q355 steel, 6m span, 3m story height. Use the frame generator to create the model, run static analysis with anaStruct, identify the critical column, and then demolish it. |
| 中文 | 用框架生成器创建一个 3跨4层 Q355 钢框架，6m 跨度、3m 层高，运行静力分析，识别关键柱，然后执行渐进式拆除 |

## 2. 完整对话流（Generate → Analyze → Demolish）

```
用户:  Generate a 3-bay 4-story steel frame using Q355 steel...
━━━ Phase 1 · 生成（Generate）━━━
助手:  (调用 generate_frame(num_bays_x=3, num_stories=4, span_x_m=6.0, story_height_m=3.0, steel_grade="Q355"))
       ✅ 已生成 2D 框架模型：3跨×4层 节点网格
       - 节点/杆件/荷载/支座数据已就绪（兼容 anaStruct/OpenSees）
━━━ Phase 2 · 分析（Analyze）━━━
助手:  (调用 anaStruct 线性静力分析)
       ✅ 静力分析完成：位移/弯矩/剪力/轴力分布
━━━ Phase 3 · 拆除（Demolish）━━━
助手:  (识别关键柱 → 移除触发渐进式拆除)
       ✅ 关键柱已标记（受力最不利柱），触发拆除动画
       （SVG 2D 可视化：变形云图 → 关键柱高亮 → 倒塌动画）
```

## 3. 工具调用链（后端视角）

| # | 阶段 | 工具调用 | 后端实现 |
|---|---|---|---|
| 1 | Generate | `generate_frame(...)` | `caiao_servers/frame_generator/server.py` → `core.py FrameGenerator.generate_2d_analysis_ready()` |
| 2 | Analyze | 静力分析（anaStruct） | `caiao_servers/anastruct_server/server.py` `_analyze_structure()` |
| 3 | Demolish | 关键柱识别 + 拆除 | `_select_critical_element()` → 移除关键柱触发渐进式拆除 |

**一步到位（Pipeline A）：** `quick_analysis` 原子调用 = generate_frame → _analyze_structure → _select_critical_element，一次返回 structure + analysis + critical_element（见 `caiao_servers/quick_analysis_server/caiao.yaml`）。

## 4. 参数明细

| 参数 | 值 |
|---|---|
| num_bays_x | 3（3 跨） |
| num_stories | 4（4 层） |
| span_x_m / span_y_m | 6.0 m |
| story_height_m | 3.0 m |
| steel_grade | Q355 |
| base_support | fixed |
| dead_load_kpa / live_load_kpa | 5.0 / 2.0 |
| viz_mode | svg（2D 可视化） |

## 5. 各环节输入→输出明细

| 环节 | 输入 | 输出 |
|---|---|---|
| 生成 | 框架参数（3×4、Q355、6m/3m） | nodes / elements / loads / supports |
| 分析 | 结构模型 | 节点位移 + 内力分布 |
| 关键柱 | 分析结果 | 最高利用率柱（critical_element） |
| 拆除 | 关键柱 + 结构 | 渐进式拆除动画（SVG 2D） |

## 6. demo 脚本

`demos/frame_generator/demo_generate_analyze.py` — 命令行端到端演示（生成 → 分析 → 关键柱）。
