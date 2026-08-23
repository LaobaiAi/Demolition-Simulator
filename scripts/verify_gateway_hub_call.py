"""Simulate the LLM agent's exact call path: hub.call_tool() directly (no HTTP middleware).

This mirrors gateway/agent_loop.py:274 (`await self.hub.call_tool(...)`) which is the
real LLM->Blender integration path, bypassing FastAPI/Starlette middleware.
"""
import asyncio
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


async def main() -> int:
    configs = discover_server_configs()
    hub = CAIAOClientHub(configs, trim_field_blacklist={
        "chain_rounds", "animation_sequence", "body_states", "keyframes",
        "steps", "nodes", "elements", "element_forces"})
    print("[1] starting hub (all eager servers)...")
    await hub.start_all()

    try:
        print("[2] calling check_blender_environment (fast)...")
        r1 = await hub.call_tool("check_blender_environment", {})
        print("[2] =>", str(r1)[:400])

        print("[3] calling run_pipeline_stage(build) — this is the LLM's real call...")
        r2 = await hub.call_tool("run_pipeline_stage", {
            "stage": "build",
            "config_override": {"building": {"stories": 3, "bays_x": 2, "bays_y": 2}},
        })
        print("[3] =>", str(r2)[:800])

        ok1 = isinstance(r1, dict) and "error" not in r1
        ok2 = isinstance(r2, dict) and "error" not in r2
        print()
        print("RESULT: check_env ok=%s | build ok=%s" % (ok1, ok2))
        return 0 if (ok1 and ok2) else 1
    finally:
        await hub.stop_all()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
