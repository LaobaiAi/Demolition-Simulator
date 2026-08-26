# 冷却塔倒塌仿真 — 完整 Prompt 流程

> 场景名：`cooling_tower_collapse` ｜ 类别：mechanics ｜ 模式：仿真模式（Abaqus）｜ 渲染：Abaqus 面板
> 70m 双曲线钢筋混凝土冷却塔，实拍校准参数。完整 Abaqus 显式倒塌仿真，求解典型 30-60 分钟、最长约 60 分钟，完整流程（求解+提帧+渲染）预估最长约 90 分钟。

## 1. 触发话术（用户可只给部分参数，缺失项助手用默认值补全）

| 语言 | 话术示例 |
|---|---|
| 中文 | 模拟一座 70 米高的双曲线冷却塔倒塌，底半径大概 28 米，壁厚 12 厘米左右 / 模拟冷却塔倒塌（全部用默认） |
| English | Simulate a 70m hyperboloid cooling tower collapse, base radius ~28m / Simulate a cooling tower collapse (use defaults) |

## 2. 完整对话流（仿真模式，参数确认先行）

| 轮次 | 说话方 | 内容 |
|---|---|---|
| 1 | 用户 | 给出项目概述与部分参数（塔高、底半径、壁厚、洞口位置等，可不全、可不精确；说"默认"则全部用默认值） |
| 2 | 助手 | 复述完整参数表：用户给出的保留，缺失项用实拍校准默认值补全（height=70, base_radius=28.5, throat_radius=16.0, throat_elevation=51.0, top_radius=17.1, wall_thickness=0.12, opening_bottom_elevation=11.0, opening_height=3.0, opening_angle_deg=98.0, settle_time=1.0, time_period=12.0, cpus=4）。说明预计时长：求解最长约 60 分钟，完整流程（求解+提帧+渲染）最长约 90 分钟。请求用户确认后再提交 |
| 3 | 用户 | 确认参数（或指出需调整的参数） |
| 4 | 助手 | (调用 setup_tower_collapse，传确认后的参数) 作业已异步提交，返回 job_id 与预计时长 |
| 5 | 助手 | (调用 get_collapse_status(job_id, wait_seconds=150) 反复轮询，直到 status=completed) 求解完成，倒塌已发生 |
| 6 | 助手 | (调用 extract_collapse_frames 提取帧，1-3 分钟) 帧提取完成 |
| 7 | 助手 | (调用 render_collapse_video 渲染 2 个 MP4 + 占地报告，3-8 分钟) 视频已输出到前端 Abaqus 面板（侧面/俯视），占地报告含 max/p95 半径、倒塌方向、最终高度 |

## 3. 工具调用链（后端视角）

| # | 阶段 | 工具调用 | 后端实现 |
|---|---|---|---|
| 1 | 创建+求解 | `setup_tower_collapse` | `abaqus_session_server`，提交即返回 job_id，永不等待 |
| 2 | 轮询 | `get_collapse_status`（多次，wait_seconds=150） | 后台求解，38856 单元全塔典型 30-60 分钟，最长约 60 分钟 |
| 3 | 提帧 | `extract_collapse_frames` | ODB → data.npz（50 帧） |
| 4 | 渲染 | `render_collapse_video` | 2 个 MP4 + footprint JSON → 前端 Abaqus 面板（无需 Abaqus license） |
| 5 | 中止（可选） | `stop_collapse` | 终止求解 + 清理 .lck |

## 4. 场景参数明细（实拍校准默认值，已验证基准）

| 参数 | 值 |
|---|---|
| 几何 | height=70m, base_radius=28.5m, throat_radius=16.0m, throat_elevation=51.0m, top_radius=17.1m |
| 壁厚 | 0.12m（S4R 壳，C30 CDP + 钢筋复合截面） |
| 洞口 | 底部开洞：底标高 11.0m，高 3.0m，圆心角 98° |
| 求解 | settle_time=1.0s, time_period=12.0s, cpus=4 |
| strategy | self_weight（自重倒塌） |
| viz_mode | abaqus（前端 Abaqus 视频面板） |

## 5. 各环节输入→输出明细

| 环节 | 输入 | 输出 | 耗时参考 |
|---|---|---|---|
| 提交作业 | 参数集 | job_id + estimated_duration_s | 秒级 |
| 求解 | job_id | .sta 进度 + completed/terminated/failed | 典型 30-60 分钟，最长约 60 分钟 |
| 提取帧 | ODB | `_tower_frames/data.npz` 50 帧 | 1-3 分钟 |
| 渲染 | 帧数据 | 2 MP4 + footprint JSON | 3-8 分钟 |

## 6. 要点

- **确认先行**：任何参数必须先经用户确认（用户说的保留、缺失项用默认值补全）才提交求解；时长（最长约 90 分钟）在确认时一并告知。
- **一次请求只提交一次求解**（setup_tower_collapse 二次调用会重启 60 分钟级求解）；改参数重跑需用户明确要求。
- 轮询用 get_collapse_status(job_id, wait_seconds=150)，绝不在单次调用内同步等待。
- 超时类错误可重试一次；其余错误如实报告并停止。
- 用户随时要求中止 → 调 stop_collapse(job_id)。
- 完成后视频与占地报告自动显示在界面 Abaqus 选项卡；占地方向应与洞口方位一致。
- 实测参考：全塔（38856 单元）最长 54.4 分钟，本预估已含排队与重试富裕度。
