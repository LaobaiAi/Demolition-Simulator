"""Verify simulation analysis mode — layer 1 only: no Abaqus process, no LLM API.

Three checks:
 1. Prompt injection position in gateway/main.py (after user_echo and memory
    retrieval, guarded by analysis_mode == "simulation", absent from llm_engine).
 2. Keyword filtering: simulation-mode prompt text hits the "abaqus" keyword and
    returns all 23 Abaqus tools (TOOL_KEYWORD_MAP["abaqus"]).
 3. Tool listing: hub.list_tools() exposes the 23 Abaqus tool names without
    starting the lazy abaqus_session_server.
"""
import asyncio
import ast
import os
import sys

# Force UTF-8 stdout/stderr so Chinese output survives any console codepage.
for _s in (sys.stdout, sys.stderr):
    getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace")

REPO = r"d:/GitHub Dev/Demolition-Simulator"
GATEWAY = os.path.join(REPO, "gateway")
sys.path.insert(0, GATEWAY)

from caiao_config import discover_server_configs
from caiao import CAIAOClientHub
from agent_loop import TOOL_KEYWORD_MAP, _filter_tools_by_message

SIM_PROMPT = (
    "[Simulation mode is active. Use Abaqus tools ONLY when the user "
    "explicitly requests simulation / collapse analysis; otherwise do "
    "not call Abaqus tools.]"
)
SIM_PROMPT_FRAGMENT = "Simulation mode is active. Use Abaqus tools ONLY when the user"
ABAQUS_SERVER = "abaqus_session_server"

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def check_prompt_injection_position() -> None:
    main_src = open(os.path.join(GATEWAY, "main.py"), encoding="utf-8").read()
    llm_src = open(os.path.join(GATEWAY, "llm_engine.py"), encoding="utf-8").read()

    pos_echo = main_src.find('"type": "user_echo"')
    pos_memory = main_src.find("memory.get_memory_context")
    pos_sim_guard = main_src.find('analysis_mode == "simulation"')
    pos_inject = main_src.find(SIM_PROMPT_FRAGMENT)

    ordered = pos_echo != -1 and pos_memory != -1 and pos_sim_guard != -1 \
        and pos_echo < pos_memory < pos_sim_guard < pos_inject
    record(
        "1a 拼接顺序(user_echo < 记忆检索 < simulation 分支 < 注入)",
        ordered,
        f"positions echo={pos_echo} memory={pos_memory} guard={pos_sim_guard} inject={pos_inject}",
    )

    tree = ast.parse(main_src)
    sim_if = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.If) and ast.unparse(n.test) == "analysis_mode == 'simulation'"),
        None,
    )
    record(
        "1b 注入受 simulation 模式守卫(if 语句, 非无条件)",
        sim_if is not None,
        f"simulation if at line {getattr(sim_if, 'lineno', 'N/A')}",
    )

    # The injection must come after the user_echo send and the memory retrieval
    # *within the message-handler block* — find the enclosing
    # "msg_type == 'message'" if and confirm both calls sit in earlier lines.
    msg_if = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.If) and ast.unparse(n.test) == "msg_type == 'message'"),
        None,
    )
    block_lines = set(range(msg_if.lineno, msg_if.end_lineno)) if msg_if else set()
    sim_line = getattr(sim_if, "lineno", -1)
    same_block = sim_line in block_lines
    echo_line = next(
        (n.lineno for n in ast.walk(msg_if)
         if isinstance(n, ast.Constant) and n.value == "user_echo"),
        -1,
    )
    mem_line = next(
        (n.lineno for n in ast.walk(msg_if)
         if isinstance(n, ast.Attribute) and n.attr == "get_memory_context"),
        -1,
    )
    record(
        "1c 回显/记忆检索在同一消息处理块内且早于注入",
        same_block and echo_line != -1 and mem_line != -1 and echo_line < mem_line < sim_line,
        f"echo={echo_line} memory={mem_line} sim_if={sim_line}",
    )

    record(
        "1d 仿真提示未注入 llm_engine(仅 main.py 持有, 其他模式无该文本)",
        SIM_PROMPT_FRAGMENT not in llm_src,
        "fragment absent from llm_engine.py",
    )

    record(
        "1e 提示文本含 abaqus 关键词(命中过滤必需)",
        "abaqus" in SIM_PROMPT.lower(),
        "keyword 'abaqus' in prompt",
    )


async def check_hub_listing() -> None:
    configs = discover_server_configs()
    abaqus_cfg = next((c for c in configs if c["name"] == ABAQUS_SERVER), None)
    cfg_lazy = bool(abaqus_cfg and abaqus_cfg.get("lazy"))
    cfg_tools = list(abaqus_cfg.get("tools", [])) if abaqus_cfg else []

    record(
        "3a abaqus_session_server 配置为 lazy(不启动即可列工具)",
        cfg_lazy,
        f"lazy={abaqus_cfg.get('lazy') if abaqus_cfg else 'MISSING'} "
        f"tools_in_yaml={len(cfg_tools)}",
    )

    hub = CAIAOClientHub(configs)
    # No start_all(): hub.list_tools() enumerates lazy config tools statically,
    # so zero subprocesses are spawned — Abaqus never boots.
    tools = await hub.list_tools()
    names = {t["name"] for t in tools}
    missing = [t for t in cfg_tools if t not in names]
    record(
        "3b hub.list_tools 含全部 23 个 Abaqus 工具(未启动任何进程)",
        len(missing) == 0 and len(cfg_tools) == 23,
        f"listed={len(names)} expected={len(cfg_tools)} missing={missing}",
    )

    # Cross-check: keyword map matches the server manifest tool list.
    kws = set(TOOL_KEYWORD_MAP["abaqus"])
    record(
        "3c TOOL_KEYWORD_MAP[abaqus] 与 caiao.yaml 工具表一致(23 个)",
        kws == set(cfg_tools) and len(kws) == 23,
        f"keyword_map={len(kws)} yaml={len(cfg_tools)}",
    )

    # Simulate the gateway filter path (agent_loop.py:169-175) for both modes.
    llm_tools = [
        {"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": {}}}
        for t in tools
    ]

    sim_filtered = _filter_tools_by_message(SIM_PROMPT, llm_tools)
    sim_names = {t["function"]["name"] for t in sim_filtered} if sim_filtered else set()
    record(
        "2a 仿真提示命中 abaqus 关键词, 过滤结果含全部 23 个工具",
        len(llm_tools) >= 20 and sim_names >= kws,
        f"total_tools={len(llm_tools)} filtered={len(sim_names)} missing={sorted(kws - sim_names)}",
    )

    plain_filtered = _filter_tools_by_message("analyze this frame", llm_tools)
    plain_names = {t["function"]["name"] for t in plain_filtered} if plain_filtered else set()
    record(
        "2b 普通模式(无 abaqus 关键词)不暴露 Abaqus 工具",
        not (kws & plain_names),
        f"filtered={len(plain_names)} abaqus_overlap={sorted(kws & plain_names)}",
    )

    no_kw_filtered = _filter_tools_by_message("hello", llm_tools)
    record(
        "2c 无关键词消息保持全量可见(过滤仅收窄, 不新增暴露)",
        len(no_kw_filtered) == len(llm_tools) if no_kw_filtered else False,
        f"returned={len(no_kw_filtered)} of {len(llm_tools)}",
    )


async def main() -> int:
    print("== verify_simulation_mode.py (layer 1: no Abaqus, no LLM API) ==")
    check_prompt_injection_position()
    await check_hub_listing()

    print()
    fails = [n for n, ok, _ in results if not ok]
    passed = len(results) - len(fails)
    print(f"RESULT: {passed}/{len(results)} passed, {len(fails)} failed: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
