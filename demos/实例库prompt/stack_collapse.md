# 烟囱倒塌仿真 — 完整 Prompt 流程

> 场景名：`stack_collapse` ｜ 类别：mechanics ｜ 模式：仿真模式（Abaqus）｜ 渲染：Abaqus 面板
> 100m 化工混凝土烟囱（实例 stack01），基于已验收 run-39 基准的自重倒塌。一次性分析，求解典型 5-35 分钟、最长约 35 分钟，含许可排队与重试总预估最长约 60 分钟，按验收准则返回 PASS/FAIL。

## 1. 触发话术（用户可只给部分参数，缺失项助手用默认值补全）

| 语言 | 话术示例 |
|---|---|
| 中文 | 模拟一座 100 米高的化工烟囱倒塌，底部开洞开在 15 米左右 / 模拟烟囱倒塌（全部用默认） |
| English | Simulate a 100m concrete chimney collapse, opening around 15m up / Simulate a chimney collapse (use defaults) |

## 2. 完整对话流（仿真模式，参数确认先行）

| 轮次 | 说话方 | 内容 |
|---|---|---|
| 1 | 用户 | 给出项目概述与部分参数（高度、洞口位置、模拟时长等，可不全、可不精确；说"默认"则全部用默认值） |
| 2 | 助手 | 复述完整参数表：用户给出的保留，缺失项用 run-39 验收基准默认值补全（H=100m 化工混凝土烟囱 stack01，sim_time=7.6 显示模式，opening_height / weak_ring_elev / weak_ring_cf / output_interval / n_theta 默认）。说明预计时长：求解最长约 35 分钟，含许可排队与重试总预估最长约 60 分钟。建议先用 no_solve 秒级干跑校验参数。请求用户确认后再提交 |
| 3 | 用户 | 确认参数（或指出需调整的参数） |
| 4 | 助手 | （可选干跑）调 stack_run_analysis 传 no_solve=true 做秒级干跑（只组装并校验 INP，不提交求解），确认参数无误 |
| 5 | 助手 | (调用 stack_run_analysis，run_name=新建唯一名称，传确认后的参数) 该调用阻塞至完成，返回 JSON，含各准则 PASS/FAIL 验收结果 |
| 6 | 助手 | 汇总：删除率、p95 落点距离、倒塌方向、最终高度；对照验收准则（删除 15-17%、p95 55-66m）给出结论 |

## 3. 工具调用链（后端视角）

| # | 阶段 | 工具调用 | 后端实现 |
|---|---|---|---|
| 1 | 一次性分析 | `stack_run_analysis`（仅一次） | `stack_analysis_server`，阻塞 5-35 分钟（no_solve=true 秒级干跑） |
| 2 | 验收 | 返回 JSON | schema v1，逐准则 PASS/FAIL（删除率 / p95 / 方向 / 高度） |

## 4. 场景参数明细（run-39 验收基准默认值）

| 参数 | 值 |
|---|---|
| 几何 | 化工混凝土烟囱，H=100m（实例 stack01） |
| 默认 | 复现 run-39 基准：sim_time=7.6（显示模式） |
| 验收模式 | sim_time=12.0，验收数值：删除 15-17%、p95 55-66m |
| 其他 | opening_height, weak_ring_elev, weak_ring_cf, output_interval, n_theta（默认即可） |
| strategy | self_weight（自重倒塌） |
| viz_mode | abaqus（前端 Abaqus 视频面板） |

## 5. 各环节输入→输出明细

| 环节 | 输入 | 输出 | 耗时参考 |
|---|---|---|---|
| 干跑（可选） | 参数 + no_solve=true | INP 组装 + 校验结果 | 秒级 |
| 正式求解 | run_name + sim_time | PASS/FAIL 验收 JSON（schema v1） | 典型 5-35 分钟，最长约 35 分钟 |
| 参数手册 | 实例指南 | docs/instances/stack01/prompt.md | — |

## 6. 要点

- **确认先行**：任何参数必须先经用户确认（用户说的保留、缺失项用 run-39 基准默认值补全）才提交求解；时长（最长约 60 分钟）在确认时一并告知。
- **一次请求只调一次 stack_run_analysis**；重跑必须换新 run_name（run 一经完成即定稿，不可覆盖）。
- 调用阻塞数分钟——期间不要并行调用其他工具。
- 建议先用 no_solve=true 干跑确认参数无误，再提交正式 run。
- 每次新建 run_name（仅字母/数字/下划线，且不得与已有 run 重名）。
- 实测参考：求解最长 30.6 分钟（含 CPU 抢占），许可排队最长 44 分钟；本预估已含排队与重试富裕度。
