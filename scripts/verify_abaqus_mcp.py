"""One-shot verification of the DS <-> Abaqus 2026 link THROUGH THE MCP LAYER.

This mirrors exactly what the gateway hub (CAIAOClientHub) does when the
frontend calls an Abaqus tool:

  1. Spawn `<gateway>/venv/Scripts/python.exe server.py` as an MCP stdio subprocess
  2. initialize() + list_tools()
  3. call_tool("create_rectangular_column", ...)
     -> server.py lazily launches the persistent Abaqus kernel
        (abq2026.bat cae noGUI=abaqus_driver.py) and routes the call through
        the file-based IPC channel (task_<id>.json / result_<id>.json)
  4. Print the outcome and shut everything down gracefully

Run with the gateway venv Python (it needs the `mcp` package):

    "d:\\GitHub Dev\\Demolition-Simulator\\gateway\\venv\\Scripts\\python.exe" ^
        scripts\\verify_abaqus_mcp.py
"""

import asyncio
import json
import os
import sys

# Windows console defaults to GBK; force UTF-8 so Chinese output is readable.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATEWAY_DIR = os.path.join(PROJECT_DIR, "gateway")
VENV_PYTHON = os.path.join(GATEWAY_DIR, "venv", "Scripts", "python.exe")
SERVER_SCRIPT = os.path.join(
    PROJECT_DIR, "caiao_servers", "abaqus_session_server", "server.py"
)
SERVER_DIR = os.path.dirname(SERVER_SCRIPT)


def _require(p: str, what: str) -> None:
    if not os.path.isfile(p):
        print(f"[FAIL] Missing {what}: {p}")
        sys.exit(1)


async def main() -> int:
    _require(VENV_PYTHON, "gateway venv python")
    _require(SERVER_SCRIPT, "abaqus_session_server/server.py")

    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.session import ClientSession

    params = StdioServerParameters(command=VENV_PYTHON, args=[SERVER_SCRIPT], cwd=SERVER_DIR)
    print("[1/4] Spawning MCP server (same as gateway hub):")
    print(f"      {VENV_PYTHON} {SERVER_SCRIPT}")

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            names = [t.name for t in tools_result.tools]
            print(f"[2/4] MCP initialized — {len(names)} tools: {', '.join(names)}")

            if "create_rectangular_column" not in names:
                print("[FAIL] create_rectangular_column not exposed by server.py")
                return 1

            print("[3/4] Calling create_rectangular_column via MCP (kernel boot ~30-60s)...")
            # Client-side hard cap so a wedged kernel can never block us forever.
            # server.py itself fails fast after KERNEL_BOOT_TIMEOUT_S (180s) if the
            # kernel never writes ready.flag, so this is just a belt-and-braces cap.
            print("      (server will fail fast at 180s if the kernel never boots)")
            try:
                result = await asyncio.wait_for(
                    session.call_tool(
                        "create_rectangular_column",
                        arguments={
                            "name": "verify_col",
                            "length": 4.0,
                            "width": 0.5,
                            "depth": 0.5,
                            "rebar_dia": 0.012,
                            "cover": 0.05,
                        },
                    ),
                    timeout=int(os.environ.get("ABAQUS_MCP_CLIENT_TIMEOUT_S", 420)),
                )
            except asyncio.TimeoutError:
                print(f"[FAIL] MCP call_tool timed out after "
                      f"{int(os.environ.get('ABAQUS_MCP_CLIENT_TIMEOUT_S', 420))}s — "
                      f"kernel is wedged.")
                print("       Check driver.log / kernel.log in the newest abaqus_session_*")
                print("       directory under %TEMP%.")
                return 1
            print("[4/4] MCP result received:")
            texts = []
            for item in result.content:
                text = item.text if hasattr(item, "text") else str(item)
                texts.append(text)
                print(text)

            failed = any('"error"' in t for t in texts)
            return 1 if failed else 0


if __name__ == "__main__":
    code = asyncio.run(main())
    if code == 0:
        print("\nRESULT: MCP_LINK_OK  (gateway hub can drive Abaqus 2026)")
    else:
        print("\nRESULT: MCP_LINK_FAILED")
    sys.exit(code)
