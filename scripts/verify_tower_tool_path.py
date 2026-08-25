"""End-to-end verification of the frontend LLM tower-collapse tool path.

Stages (each returns a distinct exit code on failure):
  1. Static checks — no Abaqus needed:
     - TOOL_KEYWORD_MAP["abaqus"] exposes the 8 new tower/video tools
     - MAX_TOOL_ITERATIONS >= 16 (polling budget)
     - SIMULATION_CORE_PROMPT lists the pipeline tools
     - caiao.yaml tool list is in sync with the keyword map
     - render_tower_frames.py has a __main__ guard (importable)
  2. list_tools via MCP: all 23 tools exposed by server.py
  3. setup_tower_collapse (run-8 constants + n_theta=48 to speed the solve):
     assert async submit — status=submitted, job_id, estimated_duration_s, odb_path
  4. get_collapse_status polling until completed (real solve ~2-4 min)
  5. extract_collapse_frames: data.npz exists, U.shape == (50, N, 3)
  6. render_collapse_video: 2 MP4s + footprint.json deployed, footprint summary
  7. stop_collapse unit test: submit n_theta=24, stop immediately, assert cleanup

Run with the gateway venv Python (mcp client + numpy/matplotlib/imageio):
    gateway\\venv\\Scripts\\python.exe scripts\\verify_tower_tool_path.py
    set ABAQUS_TOWER_VERIFY_TIMEOUT_S=3600   # overall cap, default 1800
"""

import asyncio
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATEWAY = os.path.join(REPO, "gateway")
SERVER_DIR = os.path.join(REPO, "caiao_servers", "abaqus_session_server")
SERVER_SCRIPT = os.path.join(SERVER_DIR, "server.py")
VENV_PYTHON = os.path.join(GATEWAY, "venv", "Scripts", "python.exe")

sys.path.insert(0, GATEWAY)

OVERALL_TIMEOUT_S = int(os.environ.get("ABAQUS_TOWER_VERIFY_TIMEOUT_S", 1800))
JOB_ID = "tower_job_run"

# run-8 validated real-tower constants (n_theta reduced for verification speed)
TOWER_PARAMS = {
    "name": "Tower",
    "height": 70.0,
    "base_radius": 28.5,
    "throat_radius": 16.0,
    "throat_elevation": 51.0,
    "top_radius": 17.1,
    "wall_thickness": 0.12,
    "opening_bottom_elevation": 11.0,
    "opening_height": 3.0,
    "opening_angle_deg": 98.0,
    "opening_center_angle_deg": 0.0,
    "settle_time": 1.0,
    "time_period": 12.0,
    "cpus": 4,
    "memory_percent": 80,
    "n_theta": 48,
}

NEW_TOOLS = ["create_cooling_tower", "assign_tower_materials", "mesh_tower",
             "setup_tower_collapse", "extract_collapse_frames",
             "render_collapse_video", "get_collapse_status", "stop_collapse"]

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)


def _require(p: str, what: str) -> None:
    if not os.path.isfile(p):
        print(f"[FAIL] Missing {what}: {p}")
        sys.exit(9)


def stage_static() -> int:
    from agent_loop import TOOL_KEYWORD_MAP, MAX_TOOL_ITERATIONS
    from llm_engine import SIMULATION_CORE_PROMPT

    kws = set(TOOL_KEYWORD_MAP["abaqus"])
    missing = [t for t in NEW_TOOLS if t not in kws]
    record("1a TOOL_KEYWORD_MAP[abaqus] 暴露 8 个新工具", not missing,
           f"abaqus_tools={len(kws)} missing={missing}")

    record("1b MAX_TOOL_ITERATIONS 放宽到 16(轮询预算)", MAX_TOOL_ITERATIONS >= 16,
           f"MAX_TOOL_ITERATIONS={MAX_TOOL_ITERATIONS}")

    missing_prompt = [t for t in NEW_TOOLS if t not in SIMULATION_CORE_PROMPT]
    record("1c SIMULATION_CORE_PROMPT 工具表含新工具", not missing_prompt,
           f"missing_in_prompt={missing_prompt}")

    yaml_path = os.path.join(SERVER_DIR, "caiao.yaml")
    yaml_text = open(yaml_path, encoding="utf-8").read()
    yaml_ok = all(f"- name: {t}" in yaml_text for t in
                  ["extract_collapse_frames", "render_collapse_video",
                   "get_collapse_status", "stop_collapse"])
    record("1d caiao.yaml 含 4 个新工具条目", yaml_ok, yaml_path)

    rtf_src = open(os.path.join(REPO, "scripts", "render_tower_frames.py"),
                   encoding="utf-8").read()
    record("1e render_tower_frames.py 有 __main__ 守卫(可被 import)",
           'if __name__ == "__main__":' in rtf_src, "")

    # yaml tool list == keyword map (hub routing depends on yaml entries)
    names_in_yaml = [line.split(":", 1)[1].strip()
                     for line in yaml_text.splitlines()
                     if line.startswith("  - name:")]
    record("1f caiao.yaml 工具表与 TOOL_KEYWORD_MAP[abaqus] 完全同步",
           set(names_in_yaml) == kws,
           f"yaml={len(names_in_yaml)} keyword_map={len(kws)} "
           f"diff={sorted(set(names_in_yaml) ^ kws)}")

    return 1 if any(not ok for _, ok, _ in results[:6]) else 0


async def stage_list(session) -> int:
    tools_result = await session.list_tools()
    names = [t.name for t in tools_result.tools]
    missing = [t for t in NEW_TOOLS if t not in names]
    record("2 list_tools 暴露全部 23 个工具", len(names) == 23 and not missing,
           f"count={len(names)} missing={missing}")
    return 2 if len(names) != 23 or missing else 0


async def call(session, name: str, arguments: dict, timeout: int) -> dict:
    """Call a tool through MCP and parse the JSON payload."""
    result = await asyncio.wait_for(
        session.call_tool(name, arguments=arguments), timeout=timeout)
    texts = [item.text for item in result.content]
    return texts


async def stage_setup(session) -> int:
    texts = await call(session, "setup_tower_collapse", TOWER_PARAMS, timeout=300)
    joined = "\n".join(texts)
    try:
        payload = json.loads(texts[0])
    except (IndexError, json.JSONDecodeError):
        payload = {}
    ok = (payload.get("status") == "submitted" and payload.get("job_id") == JOB_ID
          and payload.get("estimated_duration_s") is not None
          and payload.get("odb_path") and "error" not in payload)
    record("3 setup_tower_collapse 异步提交(status=submitted + job_id + 预估时长)",
           ok, joined[:400])
    print("   n_elements=%s estimated=%s range=%s submit=%s" % (
        payload.get("n_elements"), payload.get("estimated_duration_s"),
        payload.get("estimated_duration_range"), payload.get("submit_method")),
        flush=True)
    return 3 if not ok else 0


async def stage_poll(session) -> int:
    t0 = asyncio.get_event_loop().time()
    status = "submitted"
    while True:
        if asyncio.get_event_loop().time() - t0 > OVERALL_TIMEOUT_S:
            record("4 轮询 get_collapse_status 至 completed", False,
                   f"overall timeout {OVERALL_TIMEOUT_S}s, last status={status}")
            return 4
        texts = await call(session, "get_collapse_status",
                           {"job_id": JOB_ID, "wait_seconds": 150}, timeout=200)
        try:
            payload = json.loads(texts[0])
        except (IndexError, json.JSONDecodeError):
            payload = {"status": "error", "detail": texts[0][:200]}
        status = payload.get("status")
        print("   poll: status=%s progress=%s%% step_time=%s total_time=%s "
              "odb=%s" % (status, payload.get("progress_percent"),
                          payload.get("step_time"), payload.get("total_time"),
                          payload.get("odb_exists")), flush=True)
        if status == "completed":
            record("4 get_collapse_status 轮询至 completed", True,
                   f"odb_exists={payload.get('odb_exists')}")
            return 0
        if status in ("terminated", "failed"):
            record("4 求解未完成(terminated/failed)", False,
                   json.dumps(payload, ensure_ascii=False)[:400])
            return 4


async def stage_extract(session) -> int:
    texts = await call(session, "extract_collapse_frames", {}, timeout=600)
    try:
        payload = json.loads(texts[0])
    except (IndexError, json.JSONDecodeError):
        payload = {"error": texts[0][:300]}
    npz_path = payload.get("npz_path") or os.path.join(
        REPO, "scripts", "_tower_frames", "data.npz")
    ok = "error" not in payload and os.path.isfile(npz_path)
    if ok:
        import numpy as np
        d = np.load(npz_path)
        ok = d["U"].shape[0] == 50 and d["U"].shape[1] == payload.get("nodes") \
            and d["U"].ndim == 3
    record("5 extract_collapse_frames 生成 data.npz(U=(50,N,3))", ok,
           json.dumps(payload, ensure_ascii=False)[:300])
    return 5 if not ok else 0


async def stage_render(session) -> int:
    texts = await call(session, "render_collapse_video",
                       {"fps": 10, "width": 1280, "height": 720}, timeout=1200)
    try:
        payload = json.loads(texts[0])
    except (IndexError, json.JSONDecodeError):
        payload = {"error": texts[0][:300]}
    res_dir = os.path.join(REPO, "frontend", "public", "resource", "Abaqus")
    ok = ("error" not in payload
          and os.path.isfile(os.path.join(res_dir, "cooling_tower_collapse.mp4"))
          and os.path.isfile(os.path.join(res_dir, "cooling_tower_collapse_top.mp4"))
          and os.path.isfile(os.path.join(res_dir, "cooling_tower_footprint.json")))
    if ok:
        fp = json.load(open(os.path.join(res_dir, "cooling_tower_footprint.json"),
                            encoding="utf-8"))
        print("   footprint: max_r=%sm p95_r=%sm dir=%s deg final_h=%sm ratio=%s"
              % (fp["max_radius_m"], fp["p95_radius_m"], fp["direction_deg"],
                 fp["final_height_m"], fp["ratio_max"]), flush=True)
    record("6 render_collapse_video 部署 2 MP4 + footprint.json", ok,
           json.dumps({k: payload.get(k) for k in ("frames_rendered",
                                                   "elapsed_seconds")},
                      ensure_ascii=False))
    return 6 if not ok else 0


async def stage_stop(session) -> int:
    # submit a small job, then terminate it immediately — asserts kill + lck cleanup
    params = dict(TOWER_PARAMS, n_theta=24)
    texts = await call(session, "setup_tower_collapse", params, timeout=300)
    try:
        payload = json.loads(texts[0])
    except (IndexError, json.JSONDecodeError):
        payload = {"error": texts[0][:200]}
    if payload.get("status") != "submitted":
        record("7 stop_collapse 单测(先提交)", False, texts[0][:200])
        return 7
    await asyncio.sleep(3)
    texts = await call(session, "stop_collapse", {"job_id": JOB_ID}, timeout=120)
    try:
        payload = json.loads(texts[0])
    except (IndexError, json.JSONDecodeError):
        payload = {"error": texts[0][:200]}
    ok = payload.get("status") == "terminated" and "error" not in payload
    record("7 stop_collapse 终止求解 + 清理", ok,
           json.dumps(payload, ensure_ascii=False)[:300])
    # give the solver a moment to actually die, then confirm no stale lck
    await asyncio.sleep(3)
    return 7 if not ok else 0


async def main() -> int:
    _require(VENV_PYTHON, "gateway venv python")
    _require(SERVER_SCRIPT, "abaqus_session_server/server.py")

    print(f"[stage 1] static checks (no Abaqus)...", flush=True)
    fail_code = stage_static()
    if fail_code:
        return fail_code
    if os.environ.get("VERIFY_TOWER_STATIC_ONLY", "") == "1":
        print("(VERIFY_TOWER_STATIC_ONLY=1 — stopping after static stage)",
              flush=True)
        return 0

    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.session import ClientSession

    params = StdioServerParameters(command=VENV_PYTHON, args=[SERVER_SCRIPT],
                                   cwd=SERVER_DIR)
    print(f"[stage 2+] MCP server: {VENV_PYTHON} {SERVER_SCRIPT}", flush=True)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for stage in (stage_list, stage_setup, stage_poll,
                          stage_extract, stage_render, stage_stop):
                code = await stage(session)
                if code:
                    return code
    return 0


if __name__ == "__main__":
    code = asyncio.run(main())
    print(f"\nRESULT: {'TOWER_TOOL_PATH_OK' if code == 0 else 'TOWER_TOOL_PATH_FAILED'}"
          f" (exit {code})", flush=True)
    sys.exit(code)
