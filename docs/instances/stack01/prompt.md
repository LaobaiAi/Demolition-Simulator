# 实例 stack01 —— 化工混凝土烟囱（H=100m）自重倒塌，验收基线

> 实例库第一个实例。本文件是 LLM 使用该实例的说明书（"单实例使用版"）；方法论、39 轮调优经验与全部坑的完整推导见 `dev-notes/abaqus/2026-08-24-stack-collapse-runbook.md`（手册）。数据来源：`abaqus_projects/concrete_stack_run39/run_stack_collapse.py`、`results/metrics_run39.txt`、`todo/abaqus-stack.md` 索引，均逐项核对。

## 一句话定位

化工混凝土烟囱（H=100m、底半径 4.5m、顶半径 2.5m、壁厚 0.30m）机械拆除（初始几何开洞）→ 自重倒塌，Abaqus/Explicit 显式动力学，用户已验收的基线实例。run 号（run 39 等）是内部过程产物，对外统一用实例名 stack01。

## 技术实体

- 求解脚本：`abaqus_projects/concrete_stack_run39/run_stack_collapse.py`（宿主侧：参数常量 + 宿主拼 INP + 手术 + 提交 + 监控 + 自动记 run_log）
- ODB：`abaqus_projects/concrete_stack_run39/results/stack_job_run.odb`
- 指标：`abaqus_projects/concrete_stack_run39/results/metrics_run39.txt`（实测值）；探针 `concrete_stack_run39/metrics_probe.py`（内核侧，改 ODB/OUT 硬编码路径后 `abq2026.bat cae noGUI=` 批跑）
- run_log：`concrete_stack_run39/results/run_log.md`；历史全记录：`todo/abaqus-stack.md`（run 1–39 速查表）
- **run 39 与 run 32 物理参数完全一致**，仅时间轴不同：Collapse 12.0→7.6s、场输出 0.6s→0.15s/帧（21→52 帧）。run 32 为 12s 档（完整删除率/占地口径），run 39 为 7.6s 密帧档（触地前验收帧），两者 0–6s 数据逐帧吻合。

## 基线参数表（常量名见 run_stack_collapse.py）

### 几何与开口

| 参数 | 值 | 常量名 |
|---|---|---|
| 塔高 | 100.0 m | STACK_HEIGHT |
| 底半径 | 4.5 m | STACK_BASE_RADIUS |
| 顶半径 | 2.5 m（直线锥，2% 收分） | STACK_TOP_RADIUS |
| 壁厚 | 0.30 m | WALL_THICKNESS |
| 洞口底标高 | 15.0 m | OPENING_BOTTOM |
| 洞口高度 | 1.5 m（run 31 从 2.5m 收敛） | OPENING_HEIGHT |
| 洞口圆心角 | 231.4°（18 列开洞，half=115.7°） | OPENING_ANGLE_DEG |
| 开洞单元数 | 54（18 列 × 3 行） | _opening_element_labels 计算 |
| 洞口方位 | +X（硬编码 0°，无常量） | — |

### 弱环与特殊截面（run 32 引入）

| 参数 | 值 | 说明 |
|---|---|---|
| 弱环 WeakRing | 32.5–34.5m（3 行 84 单元） | 弯矩峰值带 25–37.5m / 文献断裂 ~1/3H |
| 弱环配筋 | 钢筋 0.0012 → **0.0001/面** | 删除提前但铰未切断（run 32） |
| 顶部环 TopRing | 0.185 C30 / 0.185 C30 纯混凝土无筋 | run 23 起无损伤筋已取消 |
| 塔身复合截面 | 0.15 C30(3 点) / 0.0012 Rebar(1 点) / 0.15 C30(3 点) / 0.0012 Rebar(1 点) | All_Stack，每层积分点必须奇数 |

### 材料

| 材料 | 关键参数 |
|---|---|
| C30_Stack 混凝土 | ρ=2500、E=3e10、ν=0.2；CDP (30, 0.1, 1.16, 0.6667, 0)；*Concrete Failure **0.012 / 0.035**；受压硬化 10 点表（峰 20.10e6@8e-4）；受拉刚化 12 点表（开裂 2.01e6，软化尾段延至开裂应变 0.04，等效断裂能 ~2100 N/m） |
| RebarSteel 钢筋 | ρ=7800、E=2e11、ν=0.3；HRB335 双线性 3.35e8/0 → 4.36e8/0.0483；**DUCTILE 损伤起始 0.08 + DISPLACEMENT 演化 0.05**（run 29 有效单变量） |
| RIGID_MAT 地面 | ρ=7850、E=1e10（run 19 软化，防回弹储能）、ν=0.3 |

### 网格 / 求解 / 输出 / CPU

| 参数 | 值 |
|---|---|
| 环向网格 | N_THETA=28（列宽 12.857°） |
| 子午站距 | 1m（开洞带 0.5m 加密） |
| 地面 | C3D8R 实体 5m 网格，x,z ∈ [-260,260]（105×2×105 节点 = 10816 单元，全节点 ENCASTRE）——覆盖不足即穿模（run 17/18 教训） |
| 求解器 | Dynamic, Explicit, nlgeom=YES |
| 步 1 TowerGravity | 1.0s，重力缓启 SMOOTH STEP，*Dload GRAV 9.8 -Y |
| 步 2 Collapse | **7.6s**（run 39 密帧档；run 32 为 12s） |
| 质量缩放 | *Fixed Mass Scaling dt=1e-5（仅极端畸变安全网） |
| 接触 | Collapse 步 *Contact ALL EXTERIOR + StackGround 摩擦 **0.8**（run 30 有效单变量） |
| 场输出 | time interval=**0.15s**（52 帧）；S, E, STATUS, STATUSMP, PEEQ + U, V, A |
| CPU/内存 | cpus=4 memory=80 |
| 倒塌判据 | max_displacement > 40m（=STACK_HEIGHT×0.4） |
| 硬预算 | GLOBAL_BUDGET_S=9000 / SOLVE_HARD_CAP_S=6000 / MONITOR 30s；.sta 为求解权威 |
| license | 单用户，脚本内置等待最长 40min |

### run 39 实测（验收数据）

| 指标 | 实测值 |
|---|---|
| 求解 MAIN | 395s，.sta COMPLETED |
| 验收帧 | f=50 t=7.50s：min_y=-96.263（最低点仅 3.7m 悬空）、failed 1024（7.49%）、塔身完整 |
| 触地瞬间 | ≈7.55–7.6s（f=51 t=7.60 min_y=-98.230 已贴地，failed 1445 = 10.57%） |
| 末帧 | max_radius=59.40、p95=49.22、max_y=100.00、min_y=0.000（无穿模 OK） |
| 残根 | r<12m 且 y>5m 节点 716，原位站立段保留 |
| 与 run 32 一致性 | 0–6s 逐帧吻合，触地略提前 0.1–0.2s；方向/过程一致 |

## 可调参数及建议范围

### 值得调

| 参数 | 建议范围 | 依据 |
|---|---|---|
| 时长 TOTAL_SIM_TIME | 7.6s 密帧档（验收帧/展示）或 12s 完整档（删除率/占地口径） | r32 12s 档 + r39 7.6s 密帧档；验收帧必须密帧（r39 教训） |
| 输出帧率 | 验收/展示用 0.15s/帧（52 帧）；例行诊断 0.6s/帧即可 | 0.6s/帧会跳过触地瞬间（r32：7.2s 悬空 23m / 7.8s 已触地无中间帧） |
| 弱环位置与失效应变 | 弱环在弯矩峰值带 25–37.5m 内有效（r32 删除提前）；调它只影响删除时序，不改变倒塌机制 | r26 55m 处证伪（力矩不足）；r36/37 带内失效应变 0.006/0.003 证伪（铰仍不剪断） |
| 更慢倒塌 | 受拉软化表拉尾（等效断裂能 ≤ ~2100 N/m） | r14 有效减速 16 倍；r15 已到收益平台，勿再拉尾 |
| 碎块留存（未来） | 续跑 run 38 预碎补丁（40m 以上拆 2×2 块 + 独立节点 + ALL EXTERIOR，机制确定未验证） | 元素删除 = 碎块消失是机制根因 |

### 已证伪勿调（调了无意义）

| 参数 | 结论 | 轮次 |
|---|---|---|
| 顶部加质量（*Mass 卡 / 密度路径） | *Mass 卡被静默丢弃；密度路径鞭甩加剧（max_y +17%）——尖端惯性放大弹性回弹 | r33 / r34 |
| 无筋断裂带 30–37m | 抛射恶化（max_radius +67%）、带不剪断 | r35 |
| 失效应变降低线（0.02/0.05 → 0.015/0.04 → 0.012/0.035） | 与上轮几乎同解——断裂早已越门槛，删除率由钢筋 DUCTILE/触地冲击主导 | r27 / r28 |
| 带内失效应变 0.006 / 0.003 | 删除提前但铰仍不剪断，鞭甩无改善 | r36 / r37 |
| 开洞高度 2.5→1.5m | 与 r30 几乎同解（删除率 15.36% vs 15.1%）——文献分歧，实测仲裁无差别；基线已取 1.5m | r31 |
| 压缩失效应变 0.05→0.02 逼压溃铰 | 压缩删除激活但不扩展，压溃铰从未形成，形态更垂直 | r16 |
| 鞭甩（350–390m 顶部抛射）根治 | 六轮全证伪——鞭甩是模型级弹性回弹；展示视频截断于扑倒完成（t≈8s）规避，根治需换建模思路（分段倒塌/多缝）或 Rayleigh 阻尼（候选未验证） | r27–37 |

## 验收数值判据

| 指标 | 验收值 | 说明 |
|---|---|---|
| 方向 | 与洞口方位（+X）一致 | COM 方位 +X 附近（r17 起逐轮一致） |
| 删除率 | 15–17% | r27–37 实测区间（15.1–18.0%） |
| p95 | 55–66m | r30–37 区间（55.2–66.1m）；r39 末帧 49.22 为密帧档含残根口径，以 r32 12s 档为准 |
| 穿模 | min_y ≥ -0.5（OK） | metrics 末行自动判定 |
| 触地前密帧 | 0.15s 输出下存在"悬空 <5m 且塔身完整"帧 | run 39 落地：f=50 t=7.50s 悬空 3.7m、failed 7.49% |

**已知伪影（可接受）**：尾部飞抛（max_radius 170–290m / max_y 308–365m）——展示视频截断于扑倒完成规避。

## 禁止项

| 禁止 | 原因 | 规避 |
|---|---|---|
| *Mass 卡 | 单值行被 Abaqus 2026 静默丢弃（*Elset 是单元集非节点集；pre.exe 通过但无回显无效果，run 33 无效轮） | 集中质量走密度路径（新材料，注意格式 "{:g}.," 防双小数点） |
| 内核 assembly.Set | 2026 内核 one-shot assembly.Set 崩溃（"Feature creation failed"） | 烟囱线恒走宿主 fallback：宿主拼 INP + 手术 + `abq2026.bat job=` 提交 |
| writeAVI 挂起 | 内核侧 AVI 输出会挂起 | 用逐帧截图（extract 脚本渲染链路） |
| 复合壳每层积分点数偶数 | 2 点被 pre.exe 拒 | 3/1/3/1 奇数配置 |
| 密度格式双小数点（"8000.0.,"） | pre.exe distribution 错 | `{:g}.,` 格式 |
| 长任务直接裸跑 | 电源计划空闲睡眠中断 | 所有 >5min 任务用 `python scripts/run_with_wake.py <命令>` 包裹 |
| Popen 不带 stdin=DEVNULL | Abaqus 子进程继承 MCP 管道阻塞假活 | stdin=DEVNULL |

## 调用方式

- **平台 LLM 入口**：参数化快速分析工具 `scripts/stack_quick_analysis.py` 已由 CAIAO Server `stack_analysis_server` 薄封装为工具 `stack_run_analysis`（前端对话可调用，lazy 按需启动）——加载本实例参数、改指定参数、复用 run39 目录为新实例。CLI 同功能（下）。
- **当前入口**：Claude Code 宿主脚本链路（6 步）：
  1. 复制 run39 目录为新目录（严禁覆盖旧轮），改 RESULTS_DIR（run_stack_collapse.py 48-49 行）
  2. 求解：`python scripts/run_with_wake.py gateway/venv/Scripts/python.exe run_stack_collapse.py`（预计 MAIN 400–1900s，脚本自动排队 license/监控/.sta/记 run_log；内嵌 _inp_sanity 8 项断言先看再放行）
  3. 指标：改 metrics_probe.py 的 ODB/OUT 硬编码 → `abq2026.bat cae noGUI=metrics_probe.py` → 读 metrics_runXX.txt
  4. 对照验收判据检查清单
  5. 回填 todo/abaqus-stack.md
  6. 已达标 → 出展示视频（extract + render + compose + deploy，渲染源选 run 32 档，视频截断于扑倒完成 t≈8s）
- 环境：宿主 Python `gateway/venv/Scripts/python.exe`；Abaqus launcher 路径在 `caiao_servers/abaqus_environment_server/abaqus_env.json` paths.launcher（路径含空格需引号）；内核侧脚本无独立 python.exe，只能 `abq2026.bat cae noGUI=<脚本>` 批跑。

## 结果判读（指标含义）

| 指标 | 含义 | 判读 |
|---|---|---|
| 删除率（failed 累计 %） | 材料点全失效删除的单元占比（复合壳需混凝土+钢筋全点失效） | 验收 15–17%；由钢筋 DUCTILE/触地冲击主导（r28），不是失效应变 |
| 方向（COM / 最远节点方位） | 倒塌主体与最远碎块方位角 | 与洞口 +X 一致；方向由洞口方位决定，不需要调参 |
| p95 / max_radius | 碎块半径 95 分位 / 最远距离 | p95 55–66m 真实量级；max_radius 170–290m 属鞭甩伪影 |
| max_y / 顶部高度 | 末帧最高点 y | **鞭甩标志**：308–365m = 模型级弹性回弹伪影（可接受，展示截断规避）；r34 顶部加质量会 +17% |
| min_y | 全模型最低点 | 穿模判据：≥ -0.5 为 OK（metrics 末行自动判定） |
| maxV | 峰值速度 | 触地/鞭甩速度（r32 档 71.5 m/s）；鞭甩时 88+ m/s |
| 残根 | r<12m 且 y>5m 的节点数 | 根段原位站立保留（run 39 为 716） |
| 验收帧 | 悬空 <5m 且 failed 尚未跳增的帧 | 展示素材取此帧（run 39 为 f=50 t=7.50s） |

## 附录：模拟窗口与验收判据（默认档 vs 验收档）

**stack01 基线有双档定义**，默认与验收场景分开：

| 档位 | 求解时长 | 特点 | 用途 | 指标表现 |
|---|---|---|---|---|
| 展示档（默认） | `--sim-time 7.6` | 触地前停、0.15s 密帧（52 帧）；求解快（约 4 分钟） | 看过程/方向/触地前姿态，出展示帧与视频 | 删除率约 7.5%（未触地，破坏未充分），p95 低于验收窗 |
| 验收档（备选） | `--sim-time 12.0` | 全时段（触地+鞭甩），0.6s 帧；求解约 7 分钟 | 数值验收、轮次横向对比 | 删除率 15.23%、p95 58m——验收判据（15–17% / 55–66m）按此档定义 |

**设计规则（有意为之，非 bug）**：
1. 工具默认 `--sim-time 7.6`——因为 stack01 实例 = run 39 = 用户验收的展示形态，默认值跟实例基线走
2. 验收判据（删除率 15–17%、p95 55–66m）恒按 12s 全时段定义，不随窗口改动——保证所有轮次可横向对比
3. 窗口短于判据定义阶段时，JSON 会如实标 FAIL 并附提示"要验收档数值用 `--sim-time 12.0`"——此时 FAIL 的含义是"这轮没跑到判据定义的阶段"，**不是仿真失败**
4. 使用规则：默认档跑分析、展示；需要验收数值或轮次对比时显式 `--sim-time 12.0`

**为什么不能把判据改成短窗口**：判据是横向对比工具，若随窗口浮动，轮次之间（如 7.6s 与 12s）无法比较，LLM 会被误导。如实报告 + 提示是正确行为。

## 附录：烟囱线验收沉淀清单（2026-08-24）

run 39 验收通过后固化的四件套，烟囱线闭环交付物：

1. **索引**：`todo/abaqus-stack.md` 顶部——run 1–39 全量速查表（参数变更/结果/结论/状态）+ 10 条经验要点（run 24/25 历史缺口已标注未编造）
2. **调优手册**：`dev-notes/abaqus/2026-08-24-stack-collapse-runbook.md`——8 章方法论（基线参数表含常量名行号/快速分析 6 步/39 轮证伪清单/调优决策规则/验收标准/坑速查）+ 实例库章节
3. **实例库**：`docs/instances/`——库说明（新增实例流程：验收→命名→写 prompt→登记）+ stack01 prompt（8 章：定位/基线参数/可调范围/验收判据/禁止项/调用方式/结果判读）
4. **双形态工具**：`scripts/stack_quick_analysis.py`——核心函数 `run_stack_analysis()`（已由 `stack_analysis_server` 薄封装为平台 LLM 工具 `stack_run_analysis`，经前端对话可调用）+ CLI（宿主侧用），默认 stack01 基线，稳定 JSON 输出（schema v1）带验收判据逐项 PASS/FAIL，dry-run 验证通过（含非默认参数复测）

关系：手册=方法论（全部历史），实例 prompt=单实例使用说明书（LLM 日常入口），工具=执行器（怎么跑），索引=历史速查（轮次对比）。
