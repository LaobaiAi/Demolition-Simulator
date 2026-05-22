"""
End-to-end test suite for XuanwuAI Demolition Simulator.
Tests the full progressive demolition flow via REST API + WebSocket.

Usage: python tests/test_full_flow.py
"""
import asyncio
import json
import sys
import time
import websockets

GATEWAY = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws/chat"

passed = 0
failed = 0

def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS {name}")
    else:
        failed += 1
        print(f"  FAIL {name} — {detail}")

def req(method: str, path: str, body: dict | None = None):
    """Synchronous HTTP request using urllib."""
    import urllib.request
    url = f"{GATEWAY}{path}"
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(r, timeout=10)
        return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def test_health():
    print("\n=== 1. Health Check ===")
    r = req("GET", "/health")
    check("Gateway responds", r.get("status") == "ok", str(r))


def test_tools():
    print("\n=== 2. Tools Available ===")
    r = req("GET", "/tools")
    tools = r.get("tools", [])
    check("Tools list returned", len(tools) > 0, str(r))
    names = [t["name"] for t in tools]
    check("generate_simple_frame exists", "generate_simple_frame" in names)
    check("analyze_frame exists", "analyze_frame" in names)
    check("select_critical_element exists", "select_critical_element" in names)
    check("apply_demolition_action exists", "apply_demolition_action" in names)
    check("high_fidelity_analysis exists", "high_fidelity_analysis" in names)


def test_generate_frame():
    print("\n=== 3. Generate Frame ===")
    r = req("POST", "/tools/call", {
        "tool_name": "generate_simple_frame",
        "arguments": {"stories": 2, "bays": 2, "span_length": 5, "story_height": 3}
    })
    result_str = r.get("result", "")
    try:
        data = json.loads(result_str) if isinstance(result_str, str) else result_str
        check("Has nodes", len(data.get("nodes", [])) > 0)
        check("Has elements", len(data.get("elements", [])) > 0)
        check("Has loads", len(data.get("loads", [])) > 0)
        check("Has supports", len(data.get("supports", [])) > 0)
        node_count = len(data.get("nodes", []))
        elem_count = len(data.get("elements", []))
        print(f"  INFO: {node_count} nodes, {elem_count} elements generated")
        return data
    except Exception as e:
        check("Valid result", False, str(e))
        return None


def test_analyze_frame(structure: dict):
    print("\n=== 4. Analyze Frame (anaStruct) ===")
    r = req("POST", "/tools/call", {
        "tool_name": "analyze_frame",
        "arguments": {"structure": structure}
    })
    result_str = r.get("result", "")
    try:
        data = json.loads(result_str) if isinstance(result_str, str) else result_str
        check("Has max_displacement", "max_displacement" in data)
        check("Has max_axial_force", "max_axial_force" in data)
        check("Has node_displacements", len(data.get("node_displacements", [])) > 0)
        check("Has element_forces", len(data.get("element_forces", [])) > 0)
        disp = data.get("max_displacement", 0)
        axial = data.get("max_axial_force", 0)
        print(f"  INFO: max_disp={disp:.6f} m, max_axial={axial:.1f} N")
        return data
    except Exception as e:
        check("Valid result", False, str(e))
        return None


def test_select_critical(structure: dict, analysis: dict):
    print("\n=== 5. Select Critical Element ===")
    r = req("POST", "/tools/call", {
        "tool_name": "select_critical_element",
        "arguments": {"structure": structure, "analysis_result": analysis}
    })
    result_str = r.get("result", "")
    try:
        data = json.loads(result_str) if isinstance(result_str, str) else result_str
        check("Has critical_element_id", "critical_element_id" in data)
        crit_id = data.get("critical_element_id")
        check("Critical element ID is valid", crit_id is not None and crit_id > 0)
        print(f"  INFO: critical element = #{crit_id}, axial = {data.get('critical_axial_force_N', 0):.1f} N")
        return data
    except Exception as e:
        check("Valid result", False, str(e))
        return None


def test_verify(structure: dict, analysis: dict):
    print("\n=== 6. OpenSees Verification ===")
    import urllib.request
    url = f"{GATEWAY}/verify"
    body = json.dumps({"fast_result": analysis, "structure": structure}).encode()
    r = urllib.request.Request(url, data=body, method="POST")
    r.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(r, timeout=30)
        data = json.loads(resp.read().decode())
        status = data.get("status", "unknown")
        check("Verify returns status", status in ("verified", "warning", "unavailable"), status)
        if status == "verified":
            print(f"  INFO: Verified! disp_diff={data['comparison']['max_displacement']['diff_percent']}%")
        elif status == "warning":
            print(f"  INFO: Warning - deviation detected")
        else:
            msg = data.get("message", "")
            print(f"  INFO: Unavailable — {msg[:100]}")
        return data
    except Exception as e:
        check("Verify call succeeds", False, str(e))
        return None


def test_demolish(structure: dict, critical_element_id: int, round_num: int = 1):
    print(f"\n=== 7. Demolish Round {round_num} (Element #{critical_element_id}) ===")
    r = req("POST", "/tools/call", {
        "tool_name": "apply_demolition_action",
        "arguments": {
            "failed_elements": [critical_element_id],
            "force_multiplier": 1.5,
            "structure": structure,
            "round": round_num,
        }
    })
    result_str = r.get("result", "")
    try:
        data = json.loads(result_str) if isinstance(result_str, str) else result_str
        check("Demolish completes", "error" not in data, str(data.get("error", "")))
        check("Has failed_elements", "failed_elements" in data)
        collapsed = data.get("collapsed", False)
        remaining = data.get("remaining_columns", 0)
        modified = data.get("modified_structure")
        check("Has modified_structure", modified is not None)
        print(f"  INFO: collapsed={collapsed}, remaining_columns={remaining}")
        return data
    except Exception as e:
        check("Valid result", False, str(e))
        return None


def test_progressive_demolish(structure: dict, first_critical: int):
    """Test full progressive collapse: demolish repeatedly until collapse."""
    print("\n=== 8. Progressive Demolition Test ===")
    current_structure = structure
    crit_id = first_critical
    failed_set = set()
    rounds = 0
    max_rounds = 10

    while rounds < max_rounds:
        rounds += 1

        # Demolish
        demolish_result = test_demolish(current_structure, crit_id, rounds)
        if not demolish_result:
            check(f"Progressive round {rounds}", False, "demolish failed")
            return

        failed_set.add(crit_id)

        if demolish_result.get("collapsed"):
            print(f"  INFO: Structure collapsed after {rounds} rounds!")
            check(f"Collapsed at round {rounds}", True)
            return

        # Get modified structure
        modified = demolish_result.get("modified_structure")
        if not modified:
            check(f"Modified structure round {rounds}", False, "no modified_structure")
            return

        # Re-analyze (may fail if structure became unstable)
        analysis = test_analyze_frame(modified)
        unstable = False
        if not analysis or analysis.get("max_displacement", 0) == 0:
            unstable = True
            print(f"  INFO: Re-analysis indicates structural instability (round {rounds})")
            # Analysis failure means structure is unstable — continue demolition
            # but find next column to remove from the remaining elements
            elements = modified.get("elements", [])
            nodes = modified.get("nodes", [])
            node_coords = {n["id"]: (n["x"], n["y"]) for n in nodes}
            # Find remaining columns (vertical elements not yet failed)
            remaining_cols = []
            for e in elements:
                if e["id"] not in failed_set:
                    ni = node_coords.get(e.get("node_i"))
                    nj = node_coords.get(e.get("node_j"))
                    if ni and nj and abs(ni[0] - nj[0]) < 0.01:
                        remaining_cols.append(e["id"])
            if not remaining_cols:
                print(f"  INFO: No more columns remain — structure collapsed at round {rounds}!")
                check(f"No more columns at round {rounds}", True)
                return
            crit_id = remaining_cols[0]
            print(f"  INFO: Round {rounds} complete (unstable). Next column to remove: #{crit_id}")
            current_structure = modified
            continue

        # Find next critical
        critical = test_select_critical(modified, analysis)
        if not critical:
            check(f"Re-select critical round {rounds}", False, "select failed")
            return

        next_crit = critical.get("critical_element_id")
        if next_crit is None or next_crit == 0:
            print(f"  INFO: No more critical elements — structure collapsed!")
            check(f"No more critical elements at round {rounds}", True)
            return

        print(f"  INFO: Round {rounds} complete. Next critical: #{next_crit}")
        current_structure = modified
        crit_id = next_crit

    check("Progressive demolition completes within max rounds", rounds < max_rounds,
          f"hit max rounds {max_rounds}")


def test_memory():
    print("\n=== 9. Agent Memory ===")
    r = req("GET", "/settings/memory/status")
    check("Memory status available", r.get("status") in ("ok", "unavailable"), str(r))
    if r.get("status") == "ok":
        print(f"  INFO: provider={r.get('provider')}, entries={r.get('entries')}")


def test_llm_settings():
    print("\n=== 10. LLM Settings ===")
    r = req("GET", "/settings/llm")
    check("LLM config readable", "model" in r, str(r))
    print(f"  INFO: model={r.get('model')}, has_api_key={r.get('has_api_key')}")


def main():
    global passed, failed

    print("=" * 60)
    print("XuanwuAI Demolition Simulator — Full Flow Test")
    print("=" * 60)

    test_health()
    test_tools()
    test_llm_settings()
    test_memory()

    # Core flow
    structure = test_generate_frame()
    if not structure:
        print("\nFATAL: Cannot generate frame, aborting")
        print(f"\n{'='*40}\nResults: {passed} passed, {failed} failed\n{'='*40}")
        sys.exit(1)

    analysis = test_analyze_frame(structure)
    if not analysis:
        print("\nFATAL: Cannot analyze frame, aborting")
        print(f"\n{'='*40}\nResults: {passed} passed, {failed} failed\n{'='*40}")
        sys.exit(1)

    critical = test_select_critical(structure, analysis)
    if not critical:
        print("\nFATAL: Cannot select critical element, aborting")
        print(f"\n{'='*40}\nResults: {passed} passed, {failed} failed\n{'='*40}")
        sys.exit(1)

    test_verify(structure, analysis)

    crit_id = critical["critical_element_id"]
    test_progressive_demolish(structure, crit_id)

    print(f"\n{'='*60}")
    print(f"ALL TESTS COMPLETE: {passed} passed, {failed} failed")
    print(f"{'='*60}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
