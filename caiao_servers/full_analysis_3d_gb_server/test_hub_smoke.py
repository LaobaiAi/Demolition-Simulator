"""Gateway hub in-process smoke test (plan §4.3 + §4.5).

Builds the same CAIAOClientHub as gateway/main.py, verifies:
  - full_analysis_3d_gb and quick_analysis are discovered
  - lazy start on demand (no server process on port 8010 before/after)
  - full_analysis_3d_gb contract completeness
  - quick_analysis end-to-end still returns complete

Must run from the repo root with gateway/venv/Scripts/python.exe.
"""

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "gateway"))

logging.basicConfig(level=logging.WARNING)

from caiao import CAIAOClientHub  # noqa: E402
from caiao_config import discover_server_configs  # noqa: E402

_PORT = 8010


def port_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def port_netstat(port: int) -> bool:
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10).stdout
        return any(port in line.split() and "LISTENING" in line for line in out.splitlines())
    except Exception:
        return False


async def main() -> int:
    before = port_listening(_PORT) or port_netstat(_PORT)
    print(f"port {_PORT} listening BEFORE hub smoke: {before}")

    configs = discover_server_configs()
    names = sorted(c["name"] for c in configs)
    assert "full_analysis_3d_gb_server" in names, f"server not discovered: {names}"
    assert "quick_analysis_server" in names, f"server not discovered: {names}"
    gb_cfg = next(c for c in configs if c["name"] == "full_analysis_3d_gb_server")
    print(f"discovered {len(configs)} servers; full_analysis_3d_gb lazy={gb_cfg.get('lazy', False)}")

    hub = CAIAOClientHub(
        configs,
        trim_field_blacklist={"chain_rounds", "animation_sequence", "body_states",
                              "keyframes", "steps", "nodes", "elements", "element_forces"},
        load_checker=lambda: 0.01,
    )
    await hub.start_all()

    tools = await hub.list_tools()
    tool_names = {t["name"] for t in tools}
    assert "full_analysis_3d_gb" in tool_names, f"tool not in list_tools: {tool_names}"
    assert "quick_analysis" in tool_names
    print(f"tools advertised: {len(tool_names)} (full_analysis_3d_gb, quick_analysis present)")

    # ── full_analysis_3d_gb: lazy start + contract ──
    resp = await hub.call_tool("full_analysis_3d_gb",
                               {"num_bays_x": 2, "num_bays_y": 2, "num_stories": 2})
    assert "error" not in resp, f"call error: {resp.get('error')}"
    r = json.loads(resp["result"])
    assert r.get("status") == "complete", r.get("status")
    s = r["structure"]
    assert s and s["nodes"] and s["elements"], "structure missing nodes/elements"
    a = r["analysis"]
    assert a["node_displacements"], "analysis.node_displacements empty"
    assert len(a["element_forces"]) == len(s["elements"]), "element_forces count mismatch"
    assert all("stress_ratio" in ef for ef in a["element_forces"]), "element_forces missing stress_ratio"
    assert a["max_displacement"] > 0 and a["max_axial_force"] > 0
    assert r["critical_element"]["critical_element_id"] >= 0, "critical_element invalid"
    cc = r["code_check"]
    assert cc["elements"] and cc["summary"]["total_elements"] == len(s["elements"])
    print(f"full_analysis_3d_gb: complete | {len(s['nodes'])} nodes / {len(s['elements'])} elements "
          f"| solver={a['solver']} | max_disp={a['max_displacement']:.3e} m "
          f"| critical={r['critical_element']['critical_element_id']}")

    # ── quick_analysis end-to-end (plan §4.5) ──
    resp2 = await hub.call_tool("quick_analysis", {"num_stories": 3, "num_bays": 3})
    assert "error" not in resp2, f"quick_analysis error: {resp2.get('error')}"
    r2 = json.loads(resp2["result"])
    assert r2.get("status") == "complete", r2.get("status")
    print(f"quick_analysis: complete | structure nodes={len(r2.get('structure', {}).get('nodes', []))}")

    after = port_listening(_PORT) or port_netstat(_PORT)
    print(f"port {_PORT} listening AFTER hub smoke: {after}")
    assert not after, "port 8010 must NOT be listening after in-process hub calls"

    await hub.shutdown_all() if hasattr(hub, "shutdown_all") else None
    print("\nHUB SMOKE: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
