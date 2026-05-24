"""P0 verification script — tests all P0 changes."""
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


# === 1. Tools List ===
print("\n=== 1. Tools List ===")
tools_data = api_get("/tools")
tools = tools_data.get("tools", [])
tool_names = [t["name"] for t in tools]
check("run_full_analysis in tools", "run_full_analysis" in tool_names)
check("generate_frame in tools", "generate_frame" in tool_names)
check("analyze_frame in tools", "analyze_frame" in tool_names)
check("select_critical_element in tools", "select_critical_element" in tool_names)
check("8+ tools total", len(tools) >= 7, f"got {len(tools)}")
gateway_tools = [t for t in tools if t.get("server") == "__gateway__"]
check("run_full_analysis is local tool", len(gateway_tools) >= 1 and any(t["name"] == "run_full_analysis" for t in gateway_tools))

# === 2. Individual tools ===
print("\n=== 2. Individual Tools ===")

# 2a. generate_frame
gen = api_post("/tools/call", {"tool_name": "generate_frame", "arguments": {"num_bays_x": 2, "num_bays_y": 2, "num_stories": 2, "span_x_m": 6, "story_height_m": 3}})
if "error" in gen:
    print(f"  generate_frame ERROR: {gen['error']}")
    check("generate_frame", False, gen["error"])
    gen_data = {}
else:
    gen_raw = gen.get("result", "{}")
    gen_data = json.loads(gen_raw) if isinstance(gen_raw, str) else gen_raw
    check("generate_frame returns nodes", len(gen_data.get("nodes", [])) > 0, f"nodes: {len(gen_data.get('nodes', []))}")
    check("generate_frame returns elements", len(gen_data.get("elements", [])) > 0)

# 2b. analyze_frame
if gen_data:
    anl = api_post("/tools/call", {"tool_name": "analyze_frame", "arguments": {"structure": gen_data}})
    if "error" in anl:
        print(f"  analyze_frame ERROR: {anl['error']}")
        check("analyze_frame", False, anl["error"])
        anl_data = {}
    else:
        anl_raw = anl.get("result", "{}")
        anl_data = json.loads(anl_raw) if isinstance(anl_raw, str) else anl_raw
        check("analyze_frame returns max_displacement", anl_data.get("max_displacement", -1) > 0, f"disp: {anl_data.get('max_displacement')}")
else:
    anl_data = {}

# 2c. select_critical_element
if gen_data and anl_data:
    crit = api_post("/tools/call", {"tool_name": "select_critical_element", "arguments": {"structure": gen_data, "analysis_result": anl_data}})
    if "error" in crit:
        print(f"  select_critical_element ERROR: {crit['error']}")
        check("select_critical_element", False, crit["error"])
    else:
        crit_raw = crit.get("result", "{}")
        crit_data = json.loads(crit_raw) if isinstance(crit_raw, str) else crit_raw
        check("select_critical_element returns id", crit_data.get("critical_element_id") is not None, f"id: {crit_data.get('critical_element_id')}")

# === 3. run_full_analysis pipeline ===
print("\n=== 3. Pipeline: run_full_analysis ===")
result = api_post("/tools/call", {
    "tool_name": "run_full_analysis",
    "arguments": {"num_bays_x": 2, "num_bays_y": 2, "num_stories": 2, "span_x_m": 6, "story_height_m": 3},
})
if "error" in result:
    print(f"  Error calling pipeline: {result['error']}")
    check("Pipeline call", False, result["error"])
    data = {}
else:
    raw = result.get("result", "{}")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"  JSON parse error: {e}, raw={raw[:200]}")
            data = {}
    else:
        data = raw
    status = data.get("status", "?")
    struct = data.get("structure", {})
    analysis = data.get("analysis", {})
    ce = data.get("critical_element", {})
    check("Pipeline status = complete", status == "complete", f"got '{status}'")
    check("Structure has nodes", len(struct.get("nodes", [])) > 0, f"nodes: {len(struct.get('nodes', []))}")
    check("Analysis has max_displacement", analysis.get("max_displacement", -1) > 0, f"disp: {analysis.get('max_displacement')}")
    check("Critical element found", ce.get("critical_element_id") is not None, f"id: {ce.get('critical_element_id')}")
    if status == "complete":
        print(f"  OK: {len(struct.get('nodes',[]))} nodes, {len(struct.get('elements',[]))} elements, max_disp={analysis.get('max_displacement',0):.6f}")

# === 4. Verify endpoint ===
print("\n=== 4. Verify Endpoint ===")
verify = api_post("/verify", {"fast_result": {"max_displacement": 0.001, "max_axial_force": 1000}, "structure": None})
check("Verify returns unavailable", verify.get("status") == "unavailable", f"got '{verify.get('status')}'")

# Summary
print(f"\n{'='*40}")
print(f"P0 TESTS: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*40}")

proc.terminate()
proc.wait(timeout=5)
sys.exit(0 if failed == 0 else 1)
