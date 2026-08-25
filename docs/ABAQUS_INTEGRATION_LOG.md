# Abaqus 2026 联动改造全程记录

> 记录从版本选型 → 许可证修复 → 环境验证 → 架构改造 → 验证的全部决策与实施过程。
> 目的：让当前 Demolition-Simulator（DS）项目能够真实联动本机 Abaqus 2026。

---

## 1. 版本选型（2026 vs 2023）

| 维度 | Abaqus 2023 | Abaqus 2026 |
|---|---|---|
| 内核 Python | 2.7.15（本机实测） | 3.10.5（本机实测） |
| 深度 AI 联动友好度 | 低（Py2 生态割裂） | 高（Py3.10，与主流 AI 工具链一致） |
| 结论 | 备胎（Tosca/Isight 联合仿真） | **主战场，选定 2026** |

> 注：网上资料（含 DeepSeek 表格）曾误标 2023 为 Python 3.x，本机实测为 2.7.15，其"3.x"可能是被 `win_b64\tools\SMApy\python3.7` 目录误导。

## 2. 许可证冲突与修复（-140,148）

- **现象**：2026 启动报 `Bad message command. Feature: cae ... FlexNet Licensing error:-140,148`。
- **根因**：2023 残留服务 `SSQ FLEXLM Service`（`C:\SolidSQUAD_License_Servers\Bin\lmgrd.exe`）抢占 27800 端口；2026 服务 `ABAQUS Flexnet Server`（`C:\License\lmgrd.exe`）起不来（`debug.log` 铁证：`The TCP port number in the license, 27800, is already in use`）。
- **修复**（管理员 CMD 内联）：
  ```
  net stop "SSQ FLEXLM Service" & sc.exe delete "SSQ FLEXLM Service" & ping -n 5 127.0.0.1 >nul & net start "ABAQUS Flexnet Server"
  ```
- **验证**：`lmstat -a -c 27800@localhost` → server UP v11.19.6；`cae/explicit/standard` 各 9999 licenses 可检出。

## 3. 环境验证结论（关键）

**A 电脑与当前电脑安装形态完全一致**（实测对比）：

| 检查项 | A 电脑 | 当前电脑 |
|---|---|---|
| 安装根目录 | `D:\Program Files\SIMULIA\EstProducts\2026` | 相同 |
| `win_b64\code\python3.10\python.exe` | **不存在** | **不存在** |
| `code\bin` | 含 `3DExperienceNode.exe`/`CATIAENV.exe`/`SMAPython.exe` | 相同 |

核心事实（两台机器均成立）：

1. 安装形态是 **softgj 3DEXPERIENCE 整合版**，不是 SIMULIA 标准版，因此**没有独立的 `python.exe` 解释器**。
2. `from abaqus import mdb` 在外部进程直连被内核禁止（2024+ Python 3 内核通用限制，与整合版无关）：
   > `abaqus module may only be imported in the Abaqus kernel process`
3. **唯一可靠通路**：`abq2026.bat cae noGUI=<脚本.py>` 批跑。A 电脑此前"CodeBuddy 直接连验证通过"走的正是这条路（生成脚本 → 批跑 → 回读结果），并不依赖本框架代码。
4. 冒烟测试（建模+CDP+网格）在两台机器均 `SMOKE_TEST_PASSED`（内核 Python 3.10.5）。
5. 结论：**框架（caiao_servers）此前依赖"独立 Python + 进程内 import abaqus"，该假设在两台机器上都不成立，从未真正跑起来过**。不是移植抄错，是运行架构不匹配。

## 4. 架构改造方案

```
改造前（不可用）:
  python.exe 直连 → 进程内 from abaqus import mdb → 被内核拒绝

改造后（可用）:
  server.py(系统 Python) ──写 task_*.json──▶ abq2026.bat cae noGUI=abaqus_driver.py
      ▲                                        │ 常驻内核循环读取任务、执行 HANDLERS
      └──────读 result_*.json ◀───────────────┘ 写回结果、保留共享模型数据库
```

要点：
- `abaqus_session.py` 的 15 个工具处理函数（HANDLERS）**全部保留**，在 A 电脑验证过、API 兼容。
- 新增 `abaqus_driver.py`：在 Abaqus noGUI 内核中常驻运行，轮询 `task_*.json` → 执行对应 HANDLER → 写 `result_*.json`，并保留共享 `mdb` 模型数据库。
- `server.py` 启动层改为：`cmd /c abq2026.bat cae noGUI=<driver>` 拉起常驻内核进程；每次工具调用 = 写任务文件 + 轮询结果文件。
- 通信目录：`%TEMP%\abaqus_session_*`（tempfile.mkdtemp），含 `task_*.json` / `result_*.json` / `exit.flag` / `kernel.log`。

## 5. 改造实施

| 文件 | 动作 |
|---|---|
| `caiao_servers/abaqus_session_server/abaqus_driver.py` | 新增：内核常驻驱动 |
| `caiao_servers/abaqus_session_server/server.py` | 改造：启动层 noGUI 批跑 + 文件通道 |
| `caiao_servers/abaqus_environment_server/abaqus_env.json` | 更新：`paths.launcher` / `paths.python` 语义修正 |
| `caiao_servers/abaqus_environment_server/server.py` | 小幅：环境校验改为检查 launcher 而非 python.exe |
| `scripts/verify_abaqus_link.py` | 新增：一键验证联动（真实建柱→网格→出结果） |

## 6. 验证方法

```powershell
# 一键验证：真实调用 create_rectangular_column（建模+CDP+网格）并回读结果
python scripts\verify_abaqus_link.py
```

通过标志：脚本输出 `LINK_OK`，且 `result` 中包含 part 信息。

### 验证结果（2026-08-20，当前电脑实测通过）

```
[1/4] Launching Abaqus kernel: "D:\Program Files\SIMULIA\Commands\abq2026.bat" cae noGUI="...\abaqus_driver.py"
[2/4] Request queued: create_rectangular_column(length=4.0, width=0.5, depth=0.5)
[3/4] Result received:
{
  "success": true,
  "result": {
    "concrete_part": "verify_col_conc",
    "rebar_part": "verify_col_rebar",
    "message": "Column verify_col created: 4.0m height, 0.5x0.5m section"
  }
}
[4/4] Kernel stopped cleanly.
RESULT: LINK_OK  (DS <-> Abaqus 2026 linked)
```

### 改造中踩过的坑（重要）

| 坑 | 原因 | 解法 |
|---|---|---|
| `cmd /c` 列表参数报 `'\"...'` 不是命令 | `subprocess.Popen(["cmd","/c",cmdline])` 会把含引号的命令串二次转义成 `\"` | 改用 `subprocess.Popen(cmdline, shell=True)`，按交互式 cmd 引号规则解析 |
| `NameError: name '__file__' is not defined` | Abaqus noGUI 用 `exec()` 执行脚本，无 `__file__`；且 `os.environ.get(k, default)` 的 default 会先求值 | 环境变量 `ABAQUS_DRIVER_SERVERDIR` 优先，default 用 try/except 延迟求值 |
| 系统 `python` 是 WindowsApps 存根（9009） | 未安装官方 Python 时 PATH 里的是商店存根 | 用 `.workbuddy` 真实解释器运行验证脚本 |
| **MCP 路径内核假死：进程活着、`kernel.log` 0 字节、`ready.flag` 永不出现、干等半小时** | **MCP stdio 下 server.py 的 stdin 是协议管道；Popen 未指定 stdin 时 Abaqus 内核继承该管道并在启动早期阻塞读 stdin**（直接脚本/终端跑则继承控制台 stdin，不阻塞，所以"看起来同样的命令"怎么试都通） | Popen 加 `stdin=subprocess.DEVNULL`（内核立即读到 EOF，不再阻塞） |

### MCP 层验证结果（2026-08-20，当前电脑实测通过）

MCP stdio 层 = 网关 hub（`CAIAOClientHub`）拉起 `server.py` 的真实路径。用 `scripts/verify_abaqus_mcp.py`（gateway venv python）验证：

```
[1/4] Spawning MCP server (same as gateway hub):
      D:\GitHub Dev\...\gateway\venv\Scripts\python.exe ...\server.py
[2/4] MCP initialized — 15 tools: create_rectangular_column, ...
[3/4] Calling create_rectangular_column via MCP (kernel boot ~30-60s)...
INFO:abaqus_session:Abaqus kernel started (pid=32676)
INFO:abaqus_session:Abaqus kernel ready        ← 内核 2~3 秒就绪
[4/4] MCP result received:
{
  "concrete_part": "verify_col_conc",
  "rebar_part": "verify_col_rebar",
  "message": "Column verify_col created: 4.0m height, 0.5x0.5m section"
}
RESULT: MCP_LINK_OK  (gateway hub can drive Abaqus 2026)
```

至此 **前端 → 网关 → CAIAO Hub → MCP stdio → server.py → 文件通道 → Abaqus 常驻内核** 全链路打通，不再依赖 CodeBuddy 手动介入。

### 超时与防御机制（防"干等"）

- `_KERNEL_BOOT_TIMEOUT_S = 180`：内核必须在 180s 内写 `ready.flag`（driver 进入主循环才写），否则**报错并 `taskkill /T /F` 清理进程树**（`shell=True` 拿到的是 cmd.exe PID，直接 kill 会留 SMAPython 孤儿占许可证）。
- `_TOOL_TIMEOUT_S = 600`：单次工具调用上限（`setup_collapse` 求解器任务可到 10 分钟）。
- verify 脚本客户端另有 `asyncio.wait_for(..., 420)` 兜底。
- `driver.log`：driver 侧独立日志（noGUI 下 stdout 可能被吞，文件日志更可靠）。

## 7. 排障速查

| 现象 | 处理 |
|---|---|
| 许可证 `-140,148` | 检查 27800 端口被占用：`netstat -ano \| findstr 27800`；确保只有 `ABAQUS Flexnet Server` 在跑 |
| 内核启动即退 | 查看 `%TEMP%\abaqus_session_*\kernel.log` |
| **内核假死：进程活着、kernel.log 0 字节、无 ready.flag** | 确认 Popen 带 `stdin=subprocess.DEVNULL`（MCP 管道被继承所致）；`taskkill /T /F` 清理旧内核进程后再试 |
| 工具调用超时 | `setup_collapse` 等含求解器工具耗时长，默认超时 600s；确认 ODB/日志目录有产出 |
| driver 报 `Unknown tool` | 确认 `abaqus_session.py` 的 `HANDLERS` 键与 TOOLS 名称一致 |
| 内层通过但 MCP 层失败 | 隔离法：`scripts/verify_abaqus_kernel_boot.py`（内核能否跑）→ `scripts/verify_abaqus_driver_direct.py`（driver 能否跑）→ `scripts/verify_abaqus_mcp.py`（MCP 全链路） |
