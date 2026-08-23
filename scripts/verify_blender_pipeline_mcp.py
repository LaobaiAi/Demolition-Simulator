"""Smoke test: connect to blender_pipeline_server over MCP stdio and exercise its tools.

This validates the exact transport the LLM agent uses (mcp client -> server).
Usage:
    python scripts/verify_blender_pipeline_mcp.py [--run-build]
"""
import asyncio
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(REPO, "caiao_servers", "blender_pipeline_server")
SERVER_PY = os.path.join(SERVER_DIR, "server.py")
GATEWAY_PY = os.path.join(REPO, "gateway", "venv", "Scripts", "python.exe")

# Force UTF-8 stdout/stderr so Chinese output survives any console codepage
# (e.g. gateway venv's Python 3.13 defaults stdout to GBK on Chinese Windows).
for _s in (sys.stdout, sys.stderr):
    getattr(_s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    run_build = "--run-build" in sys.argv
    server_cmd = sys.executable if sys.executable else GATEWAY_PY
    params = StdioServerParameters(
        command=server_cmd,
        args=[SERVER_PY],
        cwd=SERVER_DIR,
        env=None,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await asyncio.wait_for(session.initialize(), timeout=30)
            print("[OK] MCP initialize:", init.serverInfo)

            tools = await asyncio.wait_for(session.list_tools(), timeout=30)
            names = [t.name for t in tools.tools]
            print("[OK] list_tools:", names)
            expected = {"run_full_pipeline", "run_pipeline_stage", "check_blender_environment"}
            if not expected.issubset(set(names)):
                print("[FAIL] missing tools:", expected - set(names))
                return 1

            # 1) environment check
            res = await asyncio.wait_for(
                session.call_tool("check_blender_environment", {}), timeout=60
            )
            text = res.content[0].text if res.content else "{}"
            env = json.loads(text)
            print("[ENV]", json.dumps(env, ensure_ascii=False, indent=2))
            if not env.get("blender_found"):
                print("[FAIL] blender not found")
                return 1

            # 2) build stage (optional, slow)
            if run_build:
                print("[BUILD] running build stage via MCP (may take 1-3 min)...")
                res = await asyncio.wait_for(
                    session.call_tool(
                        "run_pipeline_stage",
                        {"stage": "build", "config_override": {"building": {"stories": 3, "bays_x": 2, "bays_y": 2}}},
                    ),
                    timeout=600,
                )
                text = res.content[0].text if res.content else "{}"
                out = json.loads(text)
                ok = out.get("success")
                print("[BUILD]", json.dumps(out, ensure_ascii=False, indent=2)[:2000])
                if not ok:
                    print("[FAIL] build stage failed")
                    return 1
                print("[OK] build stage succeeded ->", out.get("blend_file"))

    print("[OK] blender pipeline MCP smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
