# 实例库（Instances）

已验收仿真项目的集合。每个实例 = 一份"实例 prompt"（LLM 如何使用该实例）+ 参数/经验引用（不复制实体文件，指向 run 目录）。

## 概念

- **run 号是内部过程产物**（run 39 等，记录在 todo/abaqus-stack.md / abaqus_projects/ 目录）；面向用户与未来平台 LLM 的统一命名是**实例名**。
- 实例名规则：`<结构类型缩写><两位序号>`——烟囱 stack01、stack02…；冷却塔 coolingtower01、coolingtower02…（用户 2026-08-25 指定命名）。
- 未来新项目（新烟囱/新塔型）在验收基线实例基础上快速分析 = 新实例。实例实体文件不复制，只引用 run 目录（求解脚本/ODB/指标都在原目录）。

## 目录结构约定

```
docs/instances/
  README.md                ← 本文件（实例库说明 + 索引表）
  stack01/prompt.md        ← 实例 prompt（烟囱验收基线）
  coolingtower01/prompt.md ← 冷却塔验收基线（r26c_full，2026-08-25）
  ...
```

实例 prompt 标准结构（见 stack01/prompt.md 示范）：

1. 一句话定位（结构类型 + 关键尺寸 + 工况 + 求解器 + 角色）
2. 技术实体（run 目录引用：求解脚本/ODB/指标/历史记录）
3. 基线参数表（全部参数 + 常量名 + 值）
4. 可调参数及建议范围（含"已证伪勿调"项，避免重复试错）
5. 验收数值判据（方向/删除率/p95/穿模/密帧等）
6. 禁止项（已知坑与规避）
7. 调用方式（参数化快速分析工具 + Claude Code 宿主脚本链路）
8. 结果判读（各指标含义）

## 新增实例流程

1. **验收**：新 run 通过验收数值判据（对照实例 prompt 第五节），用户确认。
2. **命名**：烟囱线 stackNN、冷却塔线 coolingtowerNN（连续编号）。
3. **写 prompt**：复制 stack01/prompt.md 为模板，按新实例实际参数/经验改写（数据必须来自 run 目录与 todo 记录，不编造）。
4. **登记索引表**：在下方"当前实例清单"加一行。

## 当前实例清单

| 实例名 | 结构 | 技术实体 | 验收日期 | 说明 |
|---|---|---|---|---|
| stack01 | 化工混凝土烟囱 100m（自重倒塌，Abaqus/Explicit） | `abaqus_projects/concrete_stack_run39/`（run 39 与 run 32 同参，仅时间轴密帧化） | 2026-08-24 | 烟囱验收基线：删除率 15–17%、p95 55–66m、方向 +X、无穿模；prompt 见 `stack01/prompt.md` |
| coolingtower01 | 混凝土冷却塔 70m（自重扑倒，Abaqus/Explicit，洞口环缝铰 + 钢筋桥接机制） | `abaqus_projects/cooling_tower_r26c_full/`（r26c_full 定稿，140 帧加密） | 2026-08-25 | 冷却塔验收基线：铰 4.9s、首触地 13.4s、末帧折角 91.15°、方向 +X、无穿地；验收帧 12.4s 折角 62.25°；prompt 见 `coolingtower01/prompt.md`；已知局限 = 混凝土脱落范围偏大（FB-2026-08-25-01） |
