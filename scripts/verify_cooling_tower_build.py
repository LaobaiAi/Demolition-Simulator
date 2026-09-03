"""Cooling tower model-build verification against a real Abaqus 2026 kernel.

Launches the persistent kernel exactly like verify_abaqus_driver_direct.py
(abq2026.bat cae noGUI=abaqus_driver.py + task/result JSON file IPC), then
runs the cooling-tower toolchain step by step WITHOUT submitting any job:

  a. create_cooling_tower   -> assert part node/element counts
  b. assign_tower_materials -> assert C30_Tower / RebarSteel + composite shell
  c. mesh_tower             -> assert OpeningHole set (~204 elements)
  d. INP surgery            -> kernel step API smoke check, then run the REAL
     _tower_inp_surgery (extracted from abaqus_session.py) against a synthetic
     INP that mimics Abaqus writeInput output, and assert element removal,
     elset rewrite, *Concrete Failure injection and STATUS/STATUSMP output.

Why a synthetic INP: the only kernel handler that writes an INP is
setup_tower_collapse, which then submits the job; this phase must not submit.

Expected values are constants at the top so the script stays reusable.
"""

import ast
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(PROJECT_DIR, "caiao_servers", "abaqus_session_server")
ENV_JSON = os.path.join(
    PROJECT_DIR, "caiao_servers", "abaqus_environment_server", "abaqus_env.json"
)

BOOT_TIMEOUT_S = 180
TASK_TIMEOUT_S = 240

TOWER_NAME = "Tower"
TOWER_HEIGHT = 70.0
TOWER_BASE_RADIUS = 25.5
TOWER_THROAT_RADIUS = 14.5
TOWER_THROAT_ELEVATION = 55.0
TOWER_TOP_RADIUS = 15.599
TOWER_N_THETA = 128
OPENING_BOTTOM = 11.0
OPENING_HEIGHT = 3.0
OPENING_TOP = OPENING_BOTTOM + OPENING_HEIGHT
OPENING_ANGLE_DEG = 86.0
WALL_THICKNESS = 0.12
REBAR_THICKNESS = 0.0005

EXPECTED_TOWER_ELEMENTS = 9600
EXPECTED_TOWER_NODES = 9728
# tracked from the parameter registry (90m run 31+): 86 deg removes 180
# elements on the 70m verify mesh (98 deg removed 204)
EXPECTED_OPENING_ELEMENTS = 180
# tracked from the parameter registry (90m run 28+): run 27 used 0.005/0.015
EXPECTED_CONCRETE_FAILURE = "0.01, 0.03"

_FUNCS = ("_tower_stations", "_tower_radius_at", "_tower_inp_surgery",
          "_opening_element_labels")


def _extract_functions():
    src_path = os.path.join(SERVER_DIR, "abaqus_session.py")
    with open(src_path, "r", encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source)
    ns = {}
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in _FUNCS and node.name not in found:
            seg = textwrap.dedent(ast.get_source_segment(source, node))
            exec(compile(seg, src_path, "exec"), ns)
            found[node.name] = ns[node.name]
    missing = sorted(set(_FUNCS) - set(found))
    if missing:
        raise RuntimeError("functions not found in abaqus_session.py: " + ", ".join(missing))
    return found


class _FakeNode:
    def __init__(self, x, y, z):
        self.coordinates = (x, y, z)


class _FakeElem:
    def __init__(self, label, nodes):
        self.label = label
        self._nodes = nodes

    def getNodes(self):
        return self._nodes


class _FakePart:
    def __init__(self, elements):
        self.elements = elements


def _host_geometry(funcs):
    """Replicate the kernel-side mesh math on plain objects so the REAL
    _opening_element_labels function can run host-side."""
    stations = funcs["_tower_stations"](TOWER_HEIGHT, OPENING_BOTTOM, OPENING_HEIGHT)
    n = TOWER_N_THETA
    radius_at = funcs["_tower_radius_at"]
    nodes = {}
    for s, z in enumerate(stations):
        r = radius_at(z, TOWER_HEIGHT, TOWER_BASE_RADIUS, TOWER_THROAT_RADIUS,
                      TOWER_THROAT_ELEVATION, TOWER_TOP_RADIUS)
        for j in range(n):
            th = j * 2.0 * math.pi / n
            nodes[s * n + j + 1] = _FakeNode(r * math.cos(th), z, r * math.sin(th))
    elems = []
    for i in range(1, (len(stations) - 1) * n + 1):
        row = (i - 1) // n
        j = (i - 1) % n
        jn = (j + 1) % n
        conn = (row * n + j + 1, (row + 1) * n + j + 1,
                (row + 1) * n + jn + 1, row * n + jn + 1)
        elems.append(_FakeElem(i, [nodes[l] for l in conn]))
    labels = funcs["_opening_element_labels"](_FakePart(elems), OPENING_BOTTOM,
                                              OPENING_HEIGHT, OPENING_ANGLE_DEG, 0.0)
    return stations, sorted(labels)


def _elset_lines(lines, lo, hi, n=TOWER_N_THETA):
    lo = max(lo, 1)
    for k in range(lo, hi + 1, 16):
        chunk = ", ".join(str(x) for x in range(k, min(k + 16, hi + 1)))
        lines.append(chunk + ("," if k + 16 <= hi else ""))


def _synthetic_inp(stations, radius_at):
    """Mimic Abaqus writeInput output for the tower model (format conventions
    observed in real Abaqus INPs: one node/element per line, 16 labels per
    elset data line, generate elset for the full part set)."""
    n = TOWER_N_THETA
    total_elem = (len(stations) - 1) * n
    total_node = len(stations) * n
    lines = []
    lines.append("*Heading")
    lines.append("** Synthetic INP: manual simulation of Abaqus writeInput for the cooling tower")
    lines.append("*Preprint, echo=NO, model=NO, history=NO, contact=NO")
    lines.append("")
    lines.append("** PARTS")
    lines.append(f"*Part, name={TOWER_NAME}")
    lines.append("*Node")
    for s, z in enumerate(stations):
        r = radius_at(z, TOWER_HEIGHT, TOWER_BASE_RADIUS, TOWER_THROAT_RADIUS,
                      TOWER_THROAT_ELEVATION, TOWER_TOP_RADIUS)
        for j in range(n):
            th = j * 2.0 * math.pi / n
            lines.append(f"{s * n + j + 1:>6d}, {r * math.cos(th):.6e}, "
                         f"{z:.6e}, {r * math.sin(th):.6e}")
    lines.append("*Element, type=S4R")
    for i in range(1, total_elem + 1):
        row = (i - 1) // n
        j = (i - 1) % n
        jn = (j + 1) % n
        lines.append(f"{i:>6d}, {row * n + j + 1:>6d}, {(row + 1) * n + j + 1:>6d}, "
                     f"{(row + 1) * n + jn + 1:>6d}, {row * n + jn + 1:>6d}")
    lines.append("*Elset, elset=All_Tower, generate")
    lines.append(f"1, {total_elem}, 1")
    for name, lo, hi in (("BottomBand", 1, 2 * n),
                         ("LowerZone", 8 * n + 1, 16 * n),
                         ("TopBand", 68 * n + 1, 75 * n)):
        lines.append(f"*Elset, elset={name}")
        _elset_lines(lines, lo, hi)
    lines.append("*Nset, nset=TowerNodes, generate")
    lines.append(f"1, {total_node}, 1")
    lines.append("*Shell Section, elset=All_Tower, composite, stackdirection=1")
    lines.append(f"{WALL_THICKNESS / 2}, C30_Tower, 0., 2")
    lines.append(f"{REBAR_THICKNESS}, RebarSteel, 0., 1")
    lines.append(f"{WALL_THICKNESS / 2}, C30_Tower, 0., 2")
    lines.append("*End Part")
    lines.append("")
    lines.append("** ASSEMBLY")
    lines.append("*Assembly, name=Assembly-1")
    lines.append("*Instance, name=Tower-1, part=Tower")
    lines.append("*End Instance")
    lines.append("*Nset, nset=TowerBase, instance=Tower-1")
    _elset_lines(lines, 1, n)
    lines.append("*End Assembly")
    lines.append("")
    lines.append("** MATERIALS")
    lines.append("*Material, name=C30_Tower")
    lines.append("*Density")
    lines.append("2500.,")
    lines.append("*Elastic")
    lines.append("  3e+10, 0.2")
    lines.append("*Concrete Damaged Plasticity")
    lines.append("30., 0.1, 1.16, 0.6667, 0.")
    lines.append("*Concrete Compression Hardening")
    lines.append("1.407e+07, 0.")
    lines.append("2.01e+07, 0.0008")
    lines.append("8.4e+06, 0.005")
    lines.append("*Concrete Tension Stiffening")
    lines.append("2.01e+06, 0.")
    lines.append("5.12e+05, 0.0005")
    lines.append("9.77e+04, 0.005")
    lines.append("*Material, name=RebarSteel")
    lines.append("*Density")
    lines.append("7850.,")
    lines.append("*Elastic")
    lines.append("  2.1e+11, 0.3")
    lines.append("*Plastic")
    lines.append("3.35e+08, 0.")
    lines.append("4.36e+08, 0.048")
    lines.append("")
    lines.append("** STEP: TowerGravity")
    lines.append("*Step, name=TowerGravity, nlgeom=YES")
    lines.append("*Dynamic, Explicit")
    lines.append(", 1.")
    lines.append("*Output, field")
    lines.append("*Element Output, directions=YES")
    for v in ("S,", "E,", "U,", "V,", "A,", "STATUS,", "STATUSMP,", "PEEQ,"):
        lines.append(v)
    lines.append("*Output, history, frequency=0")
    lines.append("*End Step")
    lines.append("")
    lines.append("** STEP: Collapse")
    lines.append("*Step, name=Collapse, nlgeom=YES")
    lines.append("*Dynamic, Explicit")
    lines.append(", 12.")
    lines.append("*Output, field")
    lines.append("*Element Output, directions=YES")
    for v in ("S,", "E,", "U,", "V,", "A,", "STATUS,", "STATUSMP,", "PEEQ,"):
        lines.append(v)
    lines.append("*Output, history, frequency=0")
    lines.append("*End Step")
    return "\n".join(lines) + "\n"


def _parse_element_labels(text):
    labels = []
    in_elem = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("*Element,"):
            in_elem = True
            continue
        if in_elem:
            if not s or s.startswith("*"):
                in_elem = False
                continue
            first = s.split(",")[0].strip()
            if first.isdigit():
                labels.append(int(first))
    return labels


def _parse_node_lines(text):
    count = 0
    in_node = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("*Node"):
            in_node = True
            continue
        if in_node:
            if not s or s.startswith("*"):
                in_node = False
                continue
            first = s.split(",")[0].strip()
            if first.isdigit():
                count += 1
    return count


def _parse_elsets(text):
    result = {}
    current = None
    in_el = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("*Elset"):
            m = re.match(r"\*Elset, elset=([^,\s]+)", s)
            current = m.group(1) if m else "?"
            result.setdefault(current, [])
            in_el = True
            continue
        if in_el:
            if not s or s.startswith("*"):
                in_el = False
                continue
            for tok in s.split(","):
                tok = tok.strip()
                if tok.isdigit():
                    result[current].append(int(tok))
    return result


def _elset_headers(text):
    return dict(
        (m.group(1), m.group(0))
        for m in re.finditer(r"^\*Elset, elset=([^,\s]+)([^\n]*)", text, re.MULTILINE)
    )


def _check_surgery(out, opening_labels, stations):
    n = TOWER_N_THETA
    total_elem = (len(stations) - 1) * n
    op_set = set(opening_labels)
    cf_re = r"\*Concrete Failure\s*\n\s*" + \
        r",\s*".join(v.replace(".", r"\.") for v in EXPECTED_CONCRETE_FAILURE.split(", ")) + \
        r"(?:,\s*0\.,\s*0\.)?"
    ok_cf = re.search(cf_re, out) is not None
    elem_labels = _parse_element_labels(out)
    elem_set = set(elem_labels)
    ok_elem = not (op_set & elem_set) and len(elem_labels) == total_elem - len(opening_labels)
    ok_nodes = _parse_node_lines(out) == len(stations) * n
    elset_map = _parse_elsets(out)
    ok_refs = all(elem_set.issuperset(set(labels)) for labels in elset_map.values())
    ok_count = len(elset_map.get("All_Tower", [])) == total_elem - len(opening_labels)
    ok_gen = ", generate" not in _elset_headers(out).get("All_Tower", "")
    ok_out = "*Output, field" in out and "STATUS," in out and "STATUSMP," in out
    return (ok_cf, ok_elem, ok_nodes, ok_refs, ok_count, ok_gen, ok_out)


def _submit(proc, workdir, tool, arguments, timeout=TASK_TIMEOUT_S):
    task_id = uuid.uuid4().hex
    task_path = os.path.join(workdir, f"task_{task_id}.json")
    result_path = os.path.join(workdir, f"result_{task_id}.json")
    with open(task_path, "w", encoding="utf-8") as f:
        json.dump({"id": task_id, "tool": tool, "arguments": arguments}, f)
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if proc.poll() is not None:
            return None, f"kernel exited while waiting for {tool}"
        if os.path.exists(result_path):
            with open(result_path, "r", encoding="utf-8") as f:
                result = json.load(f)
            try:
                os.remove(result_path)
            except OSError:
                pass
            return result, None
        time.sleep(0.5)
    return None, f"{tool} timed out after {timeout}s"


def _print_tail(path, label="kernel.log"):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    print(f"--- {label} tail ---")
    for line in lines[-25:]:
        print(line)
    print("----------------------")


def _kill_tree(proc):
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True, timeout=15,
        )
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _shutdown(proc, workdir):
    try:
        with open(os.path.join(workdir, "exit.flag"), "w") as f:
            f.write("exit")
        proc.wait(timeout=20)
        print("[8/8] kernel exited gracefully")
    except Exception:
        print("[8/8] graceful exit failed, force-killing process tree")
        _kill_tree(proc)


def _fail_step(failures, workdir, kernel_log, label, err_or_result):
    if isinstance(err_or_result, str):
        print(f"      error: {err_or_result}")
    else:
        print(f"      error: {err_or_result.get('error')}")
        tb = err_or_result.get("traceback", "")
        if tb:
            print("      " + tb[:800].replace("\n", "\n      "))
    _print_tail(kernel_log)
    _print_tail(os.path.join(workdir, "driver.log"), "driver.log")
    return failures + 1


def main():
    if not os.path.isfile(ENV_JSON):
        print(f"[FAIL] missing {ENV_JSON}")
        return 1
    with open(ENV_JSON, "r", encoding="utf-8") as f:
        env_data = json.load(f)
    launcher = env_data.get("paths", {}).get("launcher")
    lic = env_data.get("license", {}).get("server", "")
    if not launcher or not os.path.isfile(launcher):
        print(f"[FAIL] launcher not found: {launcher}")
        return 1
    print(f"[0/8] launcher={launcher}")
    print(f"[0/8] license={lic}")

    funcs = _extract_functions()
    stations, opening_labels = _host_geometry(funcs)
    host_total_elem = (len(stations) - 1) * TOWER_N_THETA
    host_total_node = len(stations) * TOWER_N_THETA
    print(f"[0/8] host geometry: {len(stations)} stations x {TOWER_N_THETA} -> "
          f"{host_total_elem} elements, {host_total_node} nodes, "
          f"opening labels={len(opening_labels)}")

    t_start = time.monotonic()
    workdir = tempfile.mkdtemp(prefix="tower_verify_")
    kernel_log = os.path.join(workdir, "kernel.log")
    ready_flag = os.path.join(workdir, "ready.flag")

    env = os.environ.copy()
    if lic:
        env["ABAQUSLM_LICENSE_FILE"] = lic
    env["ABAQUS_DRIVER_WORKDIR"] = workdir
    env["ABAQUS_DRIVER_SERVERDIR"] = SERVER_DIR

    cmd = f'"{launcher}" cae noGUI="{os.path.join(SERVER_DIR, "abaqus_driver.py")}"'
    print(f"[1/8] launching: {cmd}")
    print(f"      workdir={workdir}")
    log_fh = open(kernel_log, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        cmd, cwd=workdir, stdout=log_fh, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env, shell=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    failures = 0
    try:
        t0 = time.monotonic()
        ready = False
        while time.monotonic() - t0 < BOOT_TIMEOUT_S:
            if proc.poll() is not None:
                break
            if os.path.exists(ready_flag):
                ready = True
                break
            time.sleep(0.5)
        boot_elapsed = time.monotonic() - t0
        print(f"[2/8] ready after {boot_elapsed:.1f}s "
              f"(ready={ready}, alive={proc.poll() is None})")
        if not ready:
            print("[8/8] RESULT: KERNEL_BOOT_FAILED")
            _print_tail(kernel_log)
            _print_tail(os.path.join(workdir, "driver.log"), "driver.log")
            return 1

        # ---- a. create_cooling_tower ----
        st = time.monotonic()
        result, err = _submit(proc, workdir, "create_cooling_tower", {"name": TOWER_NAME})
        dt = time.monotonic() - st
        if result is None or not result.get("success"):
            print(f"[3/8] FAIL create_cooling_tower ({dt:.1f}s)")
            failures = _fail_step(failures, workdir, kernel_log, "create_cooling_tower",
                                  err or result)
        else:
            r = result["result"]
            n_el, n_no = r["total_elements"], r["total_nodes"]
            n_st, n_th = r["n_meridional_stations"], r["n_circumferential"]
            ok = (r["part_name"] == TOWER_NAME and r["instance_name"] == f"{TOWER_NAME}-1"
                  and abs(n_el - EXPECTED_TOWER_ELEMENTS) <= 1
                  and abs(n_no - EXPECTED_TOWER_NODES) <= 1
                  and n_th == TOWER_N_THETA and n_st == len(stations))
            print(f"[3/8] {'PASS' if ok else 'FAIL'} create_cooling_tower ({dt:.1f}s)")
            print(f"      elements={n_el} (expected {EXPECTED_TOWER_ELEMENTS})  "
                  f"nodes={n_no} (expected {EXPECTED_TOWER_NODES})")
            print(f"      stations={n_st} (host cross-check {len(stations)})  "
                  f"n_theta={n_th}  wall_t={r['wall_thickness']}")
            if not ok:
                failures += 1
            step_a_elements = n_el

        # ---- b. assign_tower_materials ----
        st = time.monotonic()
        result, err = _submit(proc, workdir, "assign_tower_materials",
                              {"part_name": TOWER_NAME})
        dt = time.monotonic() - st
        if result is None or not result.get("success"):
            print(f"[4/8] FAIL assign_tower_materials ({dt:.1f}s)")
            failures = _fail_step(failures, workdir, kernel_log, "assign_tower_materials",
                                  err or result)
        else:
            r = result["result"]
            mats = r["materials"]
            layers = r["layers"]
            ok = (r["section_name"] == f"Sec_{TOWER_NAME}"
                  and set(mats) == {"C30_Tower", "RebarSteel"}
                  and len(layers) == 3
                  and [l["thickness"] for l in layers]
                  == [WALL_THICKNESS / 2, REBAR_THICKNESS, WALL_THICKNESS / 2])
            print(f"[4/8] {'PASS' if ok else 'FAIL'} assign_tower_materials ({dt:.1f}s)")
            print(f"      section={r['section_name']}  materials={mats}")
            print(f"      layers={[(l['thickness'], l['material'], l['integration_points']) for l in layers]}")
            if not ok:
                failures += 1

        # ---- c. mesh_tower ----
        st = time.monotonic()
        result, err = _submit(proc, workdir, "mesh_tower", {"part_name": TOWER_NAME})
        dt = time.monotonic() - st
        if result is None or not result.get("success"):
            print(f"[5/8] FAIL mesh_tower ({dt:.1f}s)")
            failures = _fail_step(failures, workdir, kernel_log, "mesh_tower",
                                  err or result)
            kernel_opening = None
        else:
            r = result["result"]
            kernel_opening = r["opening_elements"]
            ok = (r["opening_set"] == "OpeningHole"
                  and abs(kernel_opening - EXPECTED_OPENING_ELEMENTS) <= 1
                  and r["total_elements"] == step_a_elements
                  and r["opening_elevation_range"] == [OPENING_BOTTOM, OPENING_TOP])
            print(f"[5/8] {'PASS' if ok else 'FAIL'} mesh_tower ({dt:.1f}s)")
            print(f"      OpeningHole elements={kernel_opening} "
                  f"(expected {EXPECTED_OPENING_ELEMENTS}, host cross-check {len(opening_labels)})")
            print(f"      part elements={r['total_elements']} (step a: {step_a_elements})  "
                  f"elevation range={r['opening_elevation_range']}")
            if not ok:
                failures += 1

        # ---- d1. kernel step API (ExplicitDynamicsStep + field output) ----
        st = time.monotonic()
        result, err = _submit(proc, workdir, "create_explicit_step",
                              {"step_name": "TowerGravity", "time_period": 1.0})
        dt = time.monotonic() - st
        if result is None or not result.get("success"):
            print(f"[6/8] FAIL create_explicit_step ({dt:.1f}s)")
            failures = _fail_step(failures, workdir, kernel_log, "create_explicit_step",
                                  err or result)
        else:
            r = result["result"]
            ok = r["step_name"] == "TowerGravity"
            print(f"[6/8] {'PASS' if ok else 'FAIL'} create_explicit_step ({dt:.1f}s)")
            print(f"      step={r['step_name']}  (STATUS/STATUSMP output via INP surgery, "
                  f"no output-request API in 2026 kernel)")
            if not ok:
                failures += 1

        # ---- d2. INP surgery on synthetic INP ----
        st = time.monotonic()
        syn_text = _synthetic_inp(stations, funcs["_tower_radius_at"])
        syn_path = os.path.join(workdir, "tower_synthetic.inp")
        with open(syn_path, "w", encoding="utf-8") as f:
            f.write(syn_text)
        out, modified = funcs["_tower_inp_surgery"](syn_text, TOWER_NAME, opening_labels)
        out_path = os.path.join(workdir, "tower_surgery.inp")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(out)
        dt = time.monotonic() - st
        if kernel_opening is not None and len(opening_labels) != kernel_opening:
            print(f"[7/8] FAIL INP surgery: host opening labels ({len(opening_labels)}) "
                  f"!= kernel count ({kernel_opening})")
            failures += 1
        (ok_cf, ok_elem, ok_nodes, ok_refs, ok_count, ok_gen, ok_out) = \
            _check_surgery(out, opening_labels, stations)
        ok = modified and ok_cf and ok_elem and ok_nodes and ok_refs and ok_count \
            and ok_gen and ok_out
        print(f"[7/8] {'PASS' if ok else 'FAIL'} INP surgery ({dt:.1f}s)")
        print(f"      modified={modified}")
        print(f"      *Concrete Failure {EXPECTED_CONCRETE_FAILURE} injected: {ok_cf}")
        print(f"      opening elements removed from *Element: {ok_elem} "
              f"(remaining={len(_parse_element_labels(out))})")
        print(f"      node block intact ({_parse_node_lines(out)} nodes): {ok_nodes}")
        print(f"      no orphan elset references: {ok_refs}")
        print(f"      All_Tower rewritten to explicit "
              f"({len(_parse_elsets(out).get('All_Tower', []))} labels): {ok_count and ok_gen}")
        print(f"      STATUS/STATUSMP field output present: {ok_out}")
        print(f"      artifacts: {syn_path}")
        print(f"                 {out_path}")
        if not ok:
            failures += 1
    except Exception as exc:
        print(f"[EXC] unexpected error: {exc}")
        _print_tail(kernel_log)
        failures += 1
    finally:
        _shutdown(proc, workdir)

    total = time.monotonic() - t_start
    print(f"[8/8] total elapsed {total:.1f}s, failures={failures}")
    print("[8/8] RESULT: " + ("ALL_PASS" if failures == 0 else f"{failures} STEP(S) FAILED"))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
