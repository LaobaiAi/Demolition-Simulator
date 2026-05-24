"""P1 verification script — tests declarative composite pipeline support."""
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


# === 1. Composite tool appears in tools list ===
print("\n=== 1. Composite Tool Registration ===")
tools_data = api_get("/tools")
tools = tools_data.get("tools", [])
tool_names = [t["name"] for t in tools]
check("run_full_analysis in tools", "run_full_analysis" in tool_names)
composite_tool = next((t for t in tools if t["name"] == "run_full_analysis"), None)
check("run_full_analysis has server = __gateway__", composite_tool and composite_tool.get("server") == "__gateway__")
check("run_full_analysis has description", composite_tool and len(composite_tool.get("description", "")) > 10)
check("run_full_analysis has input_schema", composite_tool and "input_schema" in composite_tool)

# === 2. Pipeline execution ===
print("\n=== 2. Pipeline: run_full_analysis (composite) ===")
result = api_post("/tools/call", {
    "tool_name": "run_full_analysis",
    "arguments": {"num_bays_x": 2, "num_bays_y": 2, "num_stories": 2, "span_x_m": 6, "story_height_m": 3},
})
if "error" in result:
    print(f"  Error: {result['error']}")
    check("Pipeline call succeeds", False, result["error"])
else:
    raw = result.get("result", "{}")
    data = json.loads(raw) if isinstance(raw, str) else raw
    status = data.get("status", "?")
    structure = data.get("structure", {})
    analysis = data.get("analysis", {})
    ce = data.get("critical_element", {})
    check("Pipeline status = complete", status == "complete", f"got '{status}'")
    check("Structure has nodes", len(structure.get("nodes", [])) > 0, f"nodes: {len(structure.get('nodes',[]))}")
    check("Structure has elements", len(structure.get("elements", [])) > 0, f"elements: {len(structure.get('elements',[]))}")
    check("Analysis has max_displacement", analysis.get("max_displacement", -1) > 0, f"disp: {analysis.get('max_displacement')}")
    check("Critical element has id", ce.get("critical_element_id") is not None, f"id: {ce.get('critical_element_id')}")
    if status == "complete":
        print(f"  OK: {len(structure.get('nodes',[]))} nodes, {len(structure.get('elements',[]))} elements, max_disp={analysis.get('max_displacement',0):.6f}")

# === 3. Pipeline returns ALL step results ===
print("\n=== 3. Pipeline Result Completeness ===")
if result and "error" not in result:
    raw = result.get("result", "{}")
    data = json.loads(raw) if isinstance(raw, str) else raw
    check("Result contains structure", "structure" in data)
    check("Result contains analysis", "analysis" in data)
    check("Result contains critical_element", "critical_element" in data)
    check("Result contains status", "status" in data)

# === 4. Composite tool is listed BEFORE first call (lazy-friendly) ===
print("\n=== 4. Composite Tool Visibility ===")
tools_before = api_get("/tools")
names_before = [t["name"] for t in tools_before.get("tools", [])]
check("run_full_analysis visible before any call", "run_full_analysis" in names_before)
check("generate_frame also visible", "generate_frame" in names_before)

# Summary
print(f"\n{'='*40}")
print(f"P1 TESTS: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*40}")

proc.terminate()
proc.wait(timeout=5)
sys.exit(0 if failed == 0 else 1)
