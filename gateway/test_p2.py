"""P2 verification script — tests semantic routing fallback."""
import json
import time
import subprocess
import sys
import os

# Start gateway
gateway_dir = os.path.dirname(os.path.abspath(__file__))
venv_python = os.path.join(gateway_dir, "venv", "Scripts", "python.exe")
if not os.path.exists(venv_python):
    venv_python = "python"

proc = subprocess.Popen(
    [venv_python, "main.py"],
    cwd=gateway_dir,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

import urllib.request
import urllib.error


def api_get(path):
    try:
        r = urllib.request.urlopen(f"http://localhost:8000{path}", timeout=5)
        return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def api_post(path, data):
    try:
        req = urllib.request.Request(
            f"http://localhost:8000{path}",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
        )
        r = urllib.request.urlopen(req, timeout=120)
        return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


# Wait for gateway to start
print("Waiting for gateway...")
for i in range(30):
    try:
        health = api_get("/health")
        if health.get("status") == "ok":
            print(f"Gateway ready (attempt {i+1})")
            break
    except Exception:
        pass
    time.sleep(1)
else:
    print("FAIL: Gateway did not start")
    proc.kill()
    sys.exit(1)

passed = 0
failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}  {detail}")


def has_error(resp: dict) -> bool:
    """Check if HTTP-level response indicates an error."""
    return "error" in resp or (isinstance(resp.get("result"), str) and '"error"' in resp["result"])


def get_result(resp: dict):
    """Extract the inner result from the HTTP response wrapper."""
    raw = resp.get("result", resp)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
    return raw


# === 1. Exact name matching still works (regression) ===
print("\n=== 1. Exact Name Match (regression) ===")
r1 = api_post("/tools/call", {"tool_name": "generate_frame", "arguments": {"num_bays_x": 2, "num_bays_y": 2, "num_stories": 1, "span_x_m": 6, "story_height_m": 3}})
check("generate_frame by exact name", not has_error(r1), str(r1.get("error", "")))

r2 = api_post("/tools/call", {"tool_name": "run_full_analysis", "arguments": {"num_bays_x": 2, "num_bays_y": 2, "num_stories": 1, "span_x_m": 6, "story_height_m": 3}})
check("run_full_analysis by exact name", not has_error(r2), str(r2.get("error", "")))
d2 = get_result(r2)
check("run_full_analysis returns complete", d2.get("status") == "complete", f"status={d2.get('status')}")

# === 2. Semantic routing — approximate names ===
print("\n=== 2. Semantic Routing (approximate names) ===")

# "generate frame" (space) → generate_frame
r3 = api_post("/tools/call", {"tool_name": "generate frame", "arguments": {"num_bays_x": 2, "num_bays_y": 2, "num_stories": 1, "span_x_m": 6, "story_height_m": 3}})
check("'generate frame' (space) routes to generate_frame", not has_error(r3), str(r3.get("error", "")))

# "analyse_frame" (British spelling variant) → analyze_frame
r4 = api_post("/tools/call", {"tool_name": "analyse_frame", "arguments": {"structure": {"nodes": [{"id": 1, "x": 0, "y": 0}, {"id": 2, "x": 6, "y": 0}], "elements": [{"id": 1, "node_i": 1, "node_j": 2, "E": 2e11, "A": 0.01, "Iz": 8.33e-6}], "loads": [{"node": 2, "Fx": 0, "Fy": -10000}], "supports": [{"node": 1, "type": "fixed"}]}}})
check("'analyse_frame' routes to analyze_frame", not has_error(r4), str(r4.get("error", ""))[:100])

# "critical_element" → routes to select_critical_element (tool-level error about empty data expected)
r5 = api_post("/tools/call", {"tool_name": "critical_element", "arguments": {"structure": {"nodes": [], "elements": []}, "analysis_result": {"element_forces": []}}})
r5_ok = "result" in r5  # routing succeeded (tool was called, returned result with error)
check("'critical_element' routes successfully", r5_ok, f"resp={json.dumps(r5)[:200]}")

# === 3. Semantic negatives — unrelated names should NOT match ===
print("\n=== 3. Semantic Negatives (should not match) ===")
r6 = api_post("/tools/call", {"tool_name": "play_minecraft", "arguments": {}})
check("'play_minecraft' returns error (no match)", has_error(r6), str(r6)[:200])

# === 4. Partial name match bonus ===
print("\n=== 4. Partial Name Match ===")
r7 = api_post("/tools/call", {"tool_name": "list_material", "arguments": {}})
check("'list_material' (partial) routes to list_materials", not has_error(r7), str(r7)[:200])

# === 5. Semantic routing preserves arguments ===
print("\n=== 5. Argument Preservation ===")
args_5 = {"num_bays_x": 1, "num_bays_y": 1, "num_stories": 1, "span_x_m": 5, "story_height_m": 3}
r8 = api_post("/tools/call", {"tool_name": "gen frame", "arguments": args_5})
check("'gen frame' routes with correct args", not has_error(r8), str(r8.get("error", "")))
if not has_error(r8):
    d8 = get_result(r8)
    nodes = len(d8.get("nodes", []))
    check("generated structure has correct node count for 1x1x1", 0 < nodes <= 10, f"nodes={nodes}")

# Summary
print(f"\n{'='*40}")
print(f"P2 TESTS: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*40}")

proc.terminate()
proc.wait(timeout=5)
sys.exit(0 if failed == 0 else 1)
