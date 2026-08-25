"""Cooling tower self-weight collapse run (task 3) against a real Abaqus 2026 kernel.

Reuses the file-IPC kernel protocol from verify_cooling_tower_build.py
(ready.flag / task_<id>.json / result_<id>.json / exit.flag).

Primary path: one-shot setup_tower_collapse (build -> INP surgery -> submit -> wait).
Fallback path: if the kernel tool fails or the job does not complete, generate the
tower INP on the host (same pure functions extracted from abaqus_session.py), run
the real _tower_inp_surgery, and submit via `abq2026.bat job=...` from the host.

All progress is also mirrored to <workdir>/progress.log so a hard bash timeout
(600s) does not lose the story. The script self-aborts before that deadline when
the solve is clearly infeasible (guard against hanging the machine).
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
TODO_MD = os.path.join(PROJECT_DIR, "todo", "abaqus-cooling-tower.md")

BOOT_TIMEOUT_S = 180
GLOBAL_BUDGET_S = 555
SOLVE_HARD_CAP_S = 380
MONITOR_INTERVAL_S = 30
TOTAL_SIM_TIME = 8.0
JOB_NAME = "tower_job_run"
TOWER_NAME = "Tower"

TOWER_HEIGHT = 70.0
TOWER_BASE_RADIUS = 28.5
TOWER_THROAT_RADIUS = 16.0
TOWER_THROAT_ELEVATION = 51.0
TOWER_TOP_RADIUS = 17.1
WALL_THICKNESS = 0.12
OPENING_BOTTOM = 11.0
OPENING_HEIGHT = 3.0
OPENING_ANGLE_DEG = 98.0
N_THETA = 128

_FUNCS = ("_tower_stations", "_tower_radius_at", "_tower_inp_surgery",
          "_opening_element_labels")

_WORKDIR = None


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


def _log(msg):
    print(msg, flush=True)
    try:
        with open(os.path.join(_WORKDIR, "progress.log"), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except Exception:
        pass


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
    stations = funcs["_tower_stations"](TOWER_HEIGHT, OPENING_BOTTOM, OPENING_HEIGHT)
    radius_at = funcs["_tower_radius_at"]
    n = N_THETA
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


def _job_progress(workdir):
    base = os.path.join(workdir, JOB_NAME)
    info = {"lck": os.path.exists(base + ".lck"),
            "odb": os.path.exists(base + ".odb"),
            "msg_size": 0,
            "step_time": None, "total_time": None, "increments": None}
    for ext in (".msg", ".sta"):
        path = base + ext
        if not os.path.exists(path):
            continue
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if ext == ".msg":
            # 2026 batch wrapper may write per-cpu message files .msg.N
            try:
                for fname in sorted(os.listdir(workdir)):
                    if fname.startswith(JOB_NAME + ".msg."):
                        try:
                            text += "\n" + open(os.path.join(workdir, fname), "r",
                                                encoding="utf-8",
                                                errors="replace").read()
                        except OSError:
                            pass
            except OSError:
                pass
            info["msg_size"] = len(text)
        if ext == ".sta":
            # explicit .sta rows: inc, step time, total time, wall clock, dtime, ...
            for row in text.splitlines():
                fields = row.split()
                if len(fields) >= 4 and fields[0].isdigit() and \
                        re.match(r"^\d+\.?\d*E[+-]\d+$", fields[1]):
                    info["increments"] = int(fields[0])
                    info["step_time"] = float(fields[1])
                    info["total_time"] = float(fields[2])
        else:
            step = re.findall(r"STEP\s+TIME(?: COMPLETED)?\s*[:=]?\s*([-+\d.eE]+)", text)
            total = re.findall(r"TOTAL\s+TIME(?: COMPLETED)?\s*[:=]?\s*([-+\d.eE]+)", text)
            inc = re.findall(r"INCREMENT(?: NUMBER)?\s*[:=]?\s*(\d+)", text)
            if step:
                info["step_time"] = float(step[-1])
            if total:
                info["total_time"] = float(total[-1])
            if inc:
                info["increments"] = int(inc[-1])
        if info["step_time"] is not None:
            break
    return info


def _sta_completed(workdir):
    base = os.path.join(workdir, JOB_NAME)
    for path, markers in ((base + ".sta", ("the analysis has completed successfully",)),
                          (base + ".log", ("abaqus job", "completed"))):
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read().lower()
        except OSError:
            continue
        if all(m in text for m in markers):
            return True
    return False


def _solver_alive():
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return True
    for line in out.splitlines():
        name = line.split('","')[0].strip('"').lower()
        if any(k in name for k in ("explicit", "standard", "package")):
            return True
    return False


def _mem_mb():
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return 0
    total = 0
    for line in out.splitlines():
        parts = line.split('","')
        if len(parts) < 6:
            continue
        name = parts[0].strip('"').lower()
        if any(k in name for k in ("smapython", "explicit", "standard",
                                   "abaqus", "pre.exe", "cae")):
            try:
                kb = int(parts[4].replace(",", "").replace('"', "").strip().split()[0])
                total += kb
            except Exception:
                pass
    return total // 1024


def _watchdog(solve_elapsed, p):
    if not p["step_time"]:
        return None
    frac = p["step_time"] / TOTAL_SIM_TIME
    rate = p["step_time"] / solve_elapsed if solve_elapsed > 0 else 0.0
    eta = (TOTAL_SIM_TIME - p["step_time"]) / rate if rate > 0 else float("inf")
    if solve_elapsed > SOLVE_HARD_CAP_S and frac < 0.5:
        return "solve too slow: {:.0%} of {:.0f}s done after {:.0f}s, eta {:.0f}s".format(
            frac, TOTAL_SIM_TIME, solve_elapsed, eta)
    if solve_elapsed > SOLVE_HARD_CAP_S + 90:
        return "solve exceeded hard cap ({:.0f}s)".format(solve_elapsed)
    return None


def _submit_monitored(proc, workdir, tool, args, deadline, monitor=False, job_base=None):
    task_id = uuid.uuid4().hex
    task_path = os.path.join(workdir, "task_{}.json".format(task_id))
    result_path = os.path.join(workdir, "result_{}.json".format(task_id))
    with open(task_path, "w", encoding="utf-8") as fh:
        json.dump({"id": task_id, "tool": tool, "arguments": args}, fh)
    t0 = time.monotonic()
    last_report = 0.0
    solve_start = None
    while True:
        now = time.monotonic()
        if now >= deadline:
            return None, "{} did not finish within the global budget".format(tool), None
        if proc is not None and proc.poll() is not None:
            return None, "kernel exited while waiting for {}".format(tool), None
        if os.path.exists(result_path):
            with open(result_path, "r", encoding="utf-8") as fh:
                result = json.load(fh)
            try:
                os.remove(result_path)
            except OSError:
                pass
            solve_elapsed = (now - solve_start) if solve_start else None
            return result, None, solve_elapsed
        if monitor and job_base and now - last_report >= MONITOR_INTERVAL_S:
            last_report = now
            p = _job_progress(workdir)
            if p["lck"] or p["odb"] or p["msg_size"]:
                if solve_start is None:
                    solve_start = now
                    _log("      [solve] started (job files appeared)")
                _log("      [solve] lck={} odb={} step_time={} total_time={} "
                     "increments={} msg={}B mem={}MB".format(
                         p["lck"], p["odb"], p["step_time"], p["total_time"],
                         p["increments"], p["msg_size"], _mem_mb()))
                verdict = _watchdog(now - solve_start, p)
                if verdict:
                    return None, verdict, now - solve_start
        time.sleep(2.0)


def _submit_quick(proc, workdir, tool, args, timeout=90):
    task_id = uuid.uuid4().hex
    task_path = os.path.join(workdir, "task_{}.json".format(task_id))
    result_path = os.path.join(workdir, "result_{}.json".format(task_id))
    with open(task_path, "w", encoding="utf-8") as fh:
        json.dump({"id": task_id, "tool": tool, "arguments": args}, fh)
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if proc.poll() is not None:
            return None, "kernel exited"
        if os.path.exists(result_path):
            with open(result_path, "r", encoding="utf-8") as fh:
                result = json.load(fh)
            try:
                os.remove(result_path)
            except OSError:
                pass
            return result, None
        time.sleep(0.5)
    return None, "timed out after {}s".format(timeout)


def _print_tail(path, label):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    _log("--- {} tail ---".format(label))
    for line in lines[-20:]:
        _log(line)
    _log("------------------")


def _kill_tree(proc):
    try:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, timeout=15)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _shutdown(proc, workdir):
    try:
        with open(os.path.join(workdir, "exit.flag"), "w") as fh:
            fh.write("exit")
        proc.wait(timeout=25)
        _log("kernel exited gracefully")
    except Exception:
        _log("graceful exit failed, force-killing process tree")
        _kill_tree(proc)


def _job_status(workdir):
    base = os.path.join(workdir, JOB_NAME)
    status = {"completed": False, "details": [], "final_step_time": None,
              "final_total_time": None}
    for ext in (".sta", ".log", ".dat", ".msg"):
        path = base + ext
        if not os.path.exists(path):
            continue
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if ext == ".msg":
            try:
                for fname in sorted(os.listdir(workdir)):
                    if fname.startswith(JOB_NAME + ".msg."):
                        try:
                            text += "\n" + open(os.path.join(workdir, fname), "r",
                                                encoding="utf-8",
                                                errors="replace").read()
                        except OSError:
                            pass
            except OSError:
                pass
        low = text.lower()
        if "analysis has completed successfully" in low or "completed successfully" in low:
            status["completed"] = True
        step = re.findall(r"STEP\s+TIME(?: COMPLETED)?\s*[:=]?\s*([-+\d.eE]+)", text)
        total = re.findall(r"TOTAL\s+TIME(?: COMPLETED)?\s*[:=]?\s*([-+\d.eE]+)", text)
        if ext == ".sta":
            for row in text.splitlines():
                fields = row.split()
                if len(fields) >= 4 and fields[0].isdigit() and \
                        re.match(r"^\d+\.?\d*E[+-]\d+$", fields[1]):
                    step = [fields[1]]
                    total = [fields[2]]
        if step:
            status["final_step_time"] = float(step[-1])
        if total:
            status["final_total_time"] = float(total[-1])
        for m in re.finditer(r"^.*(?:ERROR|error in job|terminated|aborted|failed).*$",
                             text, re.MULTILINE):
            s = m.group(0).strip()
            if "internal error" in s.lower():
                continue
            if len(s) < 400 and s not in status["details"]:
                status["details"].append(s)
            if len(status["details"]) >= 6:
                break
    return status


def _warnings_summary(workdir):
    base = os.path.join(workdir, JOB_NAME)
    msg_path = base + ".msg"
    if not os.path.exists(msg_path):
        return {}
    try:
        text = open(msg_path, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        return {}
    low = text.lower()
    return {
        "excessive_distortion": low.count("excessive distortion"),
        "distortion_mentions": low.count("distort"),
        "stable_time_inc_mentions": low.count("stable time increment"),
        "mass_scaling_mentions": low.count("mass scaling"),
        "warning_lines": low.count("warning"),
    }


def _verify_odb(proc, workdir):
    odb_path = os.path.join(workdir, JOB_NAME + ".odb")
    if not os.path.exists(odb_path):
        return {"odb_exists": False, "odb_path": odb_path,
                "max_displacement": None, "error": "odb missing"}
    size_mb = os.path.getsize(odb_path) / 1048576.0
    result, err = _submit_quick(proc, workdir, "get_max_displacement",
                                {"odb_path": odb_path})
    if err or result is None or not result.get("success"):
        err_text = err or (result or {}).get("error", "unknown")
        return {"odb_exists": True, "odb_path": odb_path, "odb_size_mb": size_mb,
                "max_displacement": None, "error": "get_max_displacement: {}".format(err_text)}
    r = result["result"]
    return {"odb_exists": True, "odb_path": odb_path, "odb_size_mb": size_mb,
            "max_displacement": r.get("max_displacement"),
            "step": r.get("step"),
            "error": None}


def _inp_sanity(inp_path):
    try:
        text = open(inp_path, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        return {"missing": True}
    elem_count = 0
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
                elem_count += 1
    return {
        "missing": False,
        "element_count": elem_count,
        "has_concrete_failure": "*Concrete Failure" in text,
        "has_field_output": "*Output, field" in text,
        "has_status_mp": "STATUSMP," in text,
        "has_opening_elset": "*Elset, elset=OpeningHole" in text,
        "has_gravity": "*Dload" in text,
        "has_contact": "*Contact Inclusions" in text,
    }


def _tower_inp(funcs, stations, opening_labels):
    radius_at = funcs["_tower_radius_at"]
    n = N_THETA
    L = []
    L.append("*Heading")
    L.append("** Cooling tower collapse -- host-assembled INP (fallback path)")
    L.append("*Preprint, echo=NO, model=NO, history=NO, contact=NO")
    L.append("")
    L.append("*Part, name=" + TOWER_NAME)
    L.append("*Node")
    for s, z in enumerate(stations):
        r = radius_at(z, TOWER_HEIGHT, TOWER_BASE_RADIUS, TOWER_THROAT_RADIUS,
                      TOWER_THROAT_ELEVATION, TOWER_TOP_RADIUS)
        for j in range(n):
            th = j * 2.0 * math.pi / n
            L.append("{:>6d}, {:.6e}, {:.6e}, {:.6e}".format(
                s * n + j + 1, r * math.cos(th), z, r * math.sin(th)))
    total_elem = (len(stations) - 1) * n
    L.append("*Element, type=S4R")
    for i in range(1, total_elem + 1):
        row = (i - 1) // n
        j = (i - 1) % n
        jn = (j + 1) % n
        L.append("{:>6d}, {:>6d}, {:>6d}, {:>6d}, {:>6d}".format(
            i, row * n + j + 1, (row + 1) * n + j + 1,
            (row + 1) * n + jn + 1, row * n + jn + 1))
    L.append("*Elset, elset=All_Tower, generate")
    L.append("1, {}, 1".format(total_elem))
    L.append("*Elset, elset=OpeningHole")
    for k in range(0, len(opening_labels), 16):
        chunk = opening_labels[k:k + 16]
        L.append(", ".join(str(x) for x in chunk) +
                 ("," if k + 16 < len(opening_labels) else ""))
    ring_first = next(r for r in range(len(stations) - 1)
                      if 0.5 * (stations[r] + stations[r + 1]) >= TOWER_HEIGHT - 1.5 - 1e-9) * n + 1
    L.append("*Elset, elset=TopRing, generate")
    L.append("{}, {}, 1".format(ring_first, total_elem))
    L.append("*Shell Section, elset=All_Tower, composite")
    # 2026 data-line order: thickness, numIntPts, material, orientation
    L.append("{:.4f}, 3, C30_Tower, 0.".format(WALL_THICKNESS / 2))
    L.append("0.0005, 1, RebarSteel, 0.")
    L.append("{:.4f}, 3, C30_Tower, 0.".format(WALL_THICKNESS / 2))
    L.append("*Shell Section, elset=TopRing, composite")
    L.append("0.1850, 3, C30_Tower, 0.")
    L.append("0.1850, 3, C30_Tower, 0.")
    L.append("*End Part")
    L.append("")
    L.append("*Part, name=Ground")
    nx, ny, nz = 37, 2, 37
    L.append("*Node")
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                idx = 1 + i + nx * (j + ny * k)
                L.append("{:>6d}, {:.6e}, {:.6e}, {:.6e}".format(
                    idx, i * 5.0, -2.0 + j * 2.0, -90.0 + k * 5.0))
    L.append("*Element, type=C3D8R")
    for i in range(nx - 1):
        for j in range(ny - 1):
            for k in range(nz - 1):
                def gl(x, y, z):
                    return 1 + x + nx * (y + ny * z)
                n1 = gl(i, j, k)
                n2 = gl(i + 1, j, k)
                n3 = gl(i + 1, j + 1, k)
                n4 = gl(i, j + 1, k)
                n5 = gl(i, j, k + 1)
                n6 = gl(i + 1, j, k + 1)
                n7 = gl(i + 1, j + 1, k + 1)
                n8 = gl(i, j + 1, k + 1)
                eidx = 1 + i + (nx - 1) * (j + (ny - 1) * k)
                L.append("{:>6d}, {:>6d}, {:>6d}, {:>6d}, {:>6d}, {:>6d}, "
                         "{:>6d}, {:>6d}, {:>6d}".format(
                             eidx, n1, n2, n3, n4, n5, n6, n7, n8))
    L.append("*Elset, elset=AllGround, generate")
    L.append("1, {}, 1".format((nx - 1) * (ny - 1) * (nz - 1)))
    L.append("*Solid Section, elset=AllGround, material=RIGID_MAT")
    L.append("*End Part")
    L.append("")
    L.append("*Assembly, name=Assembly-1")
    L.append("*Instance, name=" + TOWER_NAME + "-1, part=" + TOWER_NAME)
    L.append("*End Instance")
    L.append("*Instance, name=Ground-1, part=Ground")
    L.append("*End Instance")
    L.append("*Nset, nset=TowerBase, instance=" + TOWER_NAME + "-1, generate")
    L.append("1, {}, 1".format(n))
    L.append("*Nset, nset=AllGroundNodes, instance=Ground-1, generate")
    L.append("1, {}, 1".format(nx * ny * nz))
    L.append("*End Assembly")
    L.append("")
    L.append("*Material, name=C30_Tower")
    L.append("*Density")
    L.append("2500.,")
    L.append("*Elastic")
    L.append("  3e+10, 0.2")
    L.append("*Concrete Damaged Plasticity")
    L.append("30., 0.1, 1.16, 0.6667, 0.")
    L.append("*Concrete Compression Hardening")
    for stress, strain in ((14.07e6, 0.0), (19.09e6, 4.0e-4), (20.10e6, 8.0e-4),
                           (19.36e6, 1.2e-3), (17.92e6, 1.6e-3), (16.35e6, 2.0e-3),
                           (14.84e6, 2.4e-3), (11.18e6, 3.6e-3), (8.40e6, 5.0e-3),
                           (4.22e6, 1.0e-2)):
        L.append("{:.4e}, {:.4e}".format(stress, strain))
    L.append("*Concrete Tension Stiffening")
    for stress, strain in ((2.01e6, 0.0), (1.52e6, 1.0e-4), (0.756e6, 3.0e-4),
                           (0.4e6, 6.0e-4), (0.2e6, 1.0e-3)):
        L.append("{:.4e}, {:.4e}".format(stress, strain))
    L.append("*Material, name=RebarSteel")
    L.append("*Density")
    L.append("7850.,")
    L.append("*Elastic")
    L.append("  2.1e+11, 0.3")
    L.append("*Plastic")
    L.append("3.35e+08, 0.")
    L.append("4.36e+08, 0.048")
    L.append("*Damage Initiation, criterion=DUCTILE")
    L.append("0.03, 0., 0.")
    L.append("*Damage Evolution, type=DISPLACEMENT")
    L.append("0.03")
    L.append("*Material, name=RIGID_MAT")
    L.append("*Density")
    L.append("7850.,")
    L.append("*Elastic")
    L.append("  2e+15, 0.3")
    L.append("")
    L.append("*Boundary")
    L.append("TowerBase, ENCASTRE")
    L.append("*Boundary")
    L.append("AllGroundNodes, ENCASTRE")
    L.append("")
    L.append("*Amplitude, name=GravRamp, definition=SMOOTH STEP")
    L.append("0., 0., 1., 1.")
    L.append("")
    for name, t in (("TowerGravity", 1.0), ("Collapse", 7.0)):
        L.append("*Step, name={}, nlgeom=YES".format(name))
        L.append("*Dynamic, Explicit")
        L.append(", {:.1f}".format(t))
        # ground (E=2e15) caps dt at ~3e-6 s; scale only elements below 4e-4
        # (tower shell natural dt ~3.6e-4, so only mild scaling in elastic phase)
        L.append("*Fixed Mass Scaling, type=Below Min, dt=4e-4")
        if name == "TowerGravity":
            L.append("*Dload, amplitude=GravRamp")
            L.append(", GRAV, 9.8, 0., -1., 0.")
        if name == "Collapse":
            L.append("*Contact, op=NEW")
            L.append("*Contact Inclusions, ALL EXTERIOR")
        L.append("*Output, field")
        L.append("*Element Output, directions=YES")
        L.append("S, E, STATUS, STATUSMP, PEEQ,")
        L.append("*Node Output")
        L.append("U, V, A,")
        L.append("*Output, history, frequency=0")
        L.append("*End Step")
        L.append("")
    return "\n".join(L) + "\n"


def _collapse_blank_lines(text):
    import re
    return re.sub(r"\n\s*\n", "\n", text)


def _strip_empty_opening_elset(text):
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("*Elset, elset=OpeningHole"):
            j = i + 1
            while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith("*"):
                j += 1
            if j == i + 1:
                i = j
                continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _move_concrete_failure_under_cdp(text):
    block_start = text.find("*Concrete Failure")
    if block_start < 0:
        return text
    block_end = text.find("*", block_start + len("*Concrete Failure"))
    if block_end < 0:
        return text
    block = text[block_start:block_end].strip("\n")
    text = text[:block_start] + text[block_end:]
    cdp = text.find("*Concrete Damaged Plasticity")
    if cdp < 0:
        return text[:block_start] + block + text[block_start:]
    data_end = text.find("*", cdp + len("*Concrete Damaged Plasticity"))
    if data_end < 0:
        return text[:block_start] + block + text[block_start:]
    return text[:data_end] + "\n" + block + "\n" + text[data_end:]


def _run_fallback(launcher, env, workdir, funcs, stations, opening_labels, deadline):
    _log("--- fallback: host INP assembly + surgery + abq job ---")
    for f in os.listdir(workdir):
        if f.startswith(JOB_NAME + ".") and not f.endswith(".inp"):
            try:
                os.remove(os.path.join(workdir, f))
            except OSError:
                pass
    text = _tower_inp(funcs, stations, opening_labels)
    out, modified = funcs["_tower_inp_surgery"](text, TOWER_NAME, opening_labels)
    out = _move_concrete_failure_under_cdp(out)
    out = _strip_empty_opening_elset(out)
    out = _collapse_blank_lines(out)
    inp_path = os.path.join(workdir, JOB_NAME + ".inp")
    with open(inp_path, "w", encoding="utf-8") as fh:
        fh.write(out)
    sanity = _inp_sanity(inp_path)
    _log("      INP {} bytes, elements={}, concrete_failure={}, field_output={}, "
         "statusmp={}, gravity={}, contact={}, surgery_modified={}".format(
             os.path.getsize(inp_path), sanity.get("element_count"),
             sanity.get("has_concrete_failure"), sanity.get("has_field_output"),
             sanity.get("has_status_mp"), sanity.get("has_gravity"),
             sanity.get("has_contact"), modified))
    cmd = '{} job={} cpus=4 memory=80'.format('"' + launcher + '"', JOB_NAME)
    _log("      submit: " + cmd)
    job_proc = subprocess.Popen(cmd, cwd=workdir, env=env, shell=True,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    t0 = time.monotonic()
    solve_start = None
    last_report = 0.0
    while True:
        now = time.monotonic()
        if now >= deadline:
            _kill_tree(job_proc)
            subprocess.run(["taskkill", "/F", "/IM", "explicit.exe"],
                           capture_output=True, timeout=15)
            return {"fallback": True, "error": "fallback solve did not finish within budget"}
        p = _job_progress(workdir)
        # .sta is the solve authority: completion marker wins, regardless of
        # wrapper-side noise (run 10: packager "internal error" while the solve
        # continued as an orphan and completed)
        if _sta_completed(workdir):
            return {"fallback": True,
                    "solve_elapsed": (now - solve_start) if solve_start else None}
        # the launcher wrapper can exit while the solver keeps running, so only
        # give up when no .sta ever appeared and no solver process is alive
        if now - t0 > 60 and job_proc.poll() is not None and not p["lck"] and \
                not os.path.exists(os.path.join(workdir, JOB_NAME + ".sta")) and \
                not _solver_alive():
            log_path = os.path.join(workdir, JOB_NAME + ".log")
            tail = ""
            try:
                tail = open(log_path, "r", encoding="utf-8",
                            errors="replace").read()[-1200:]
            except OSError:
                pass
            return {"fallback": True,
                    "error": "solver exited before starting (launcher returned {}). "
                             "log tail: {}".format(job_proc.returncode, tail)}
        if now - last_report >= MONITOR_INTERVAL_S:
            last_report = now
            if p["lck"] or p["odb"] or p["msg_size"]:
                if solve_start is None:
                    solve_start = now
                    _log("      [solve] started")
                _log("      [solve] lck={} odb={} step_time={} total_time={} "
                     "increments={} msg={}B mem={}MB".format(
                         p["lck"], p["odb"], p["step_time"], p["total_time"],
                         p["increments"], p["msg_size"], _mem_mb()))
                verdict = _watchdog(now - solve_start, p)
                if verdict:
                    terminate_cmd = '{} terminate job={}'.format('"' + launcher + '"',
                                                                  JOB_NAME)
                    subprocess.run(terminate_cmd, cwd=workdir, env=env, shell=True,
                                   timeout=30, capture_output=True)
                    _kill_tree(job_proc)
                    subprocess.run(["taskkill", "/F", "/IM", "explicit.exe"],
                                   capture_output=True, timeout=15)
                    return {"fallback": True, "error": verdict}
        time.sleep(2.0)


def _todo_header_count():
    try:
        with open(TODO_MD, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return 0
    return text.count("冷却塔仿真运行记录（2026-08-22")


def _todo_header_exists():
    return _todo_header_count() > 0


def _todo_run_number():
    return _todo_header_count() + 1


def _report_and_record(summary):
    _log("")
    _log("==== TOWER COLLAPSE RUN SUMMARY ====")
    for k, v in summary.items():
        _log("{}: {}".format(k, v))
    _log("==== END ====")
    if _todo_header_exists():
        section = "\n\n## 冷却塔仿真运行记录（2026-08-22, run {})\n\n".format(
            _todo_run_number())
    else:
        section = "\n\n## 冷却塔仿真运行记录（2026-08-22）\n\n"
    section += "本次真实运行：Abaqus 2026 内核 + 显式求解（任务 3，自重倒塌，默认参数）。\n\n"
    for k, v in summary.items():
        section += "- {}：{}\n".format(k, v)
    try:
        with open(TODO_MD, "a", encoding="utf-8") as fh:
            fh.write(section)
        _log("recorded to " + TODO_MD)
    except OSError as exc:
        _log("could not write " + TODO_MD + ": " + str(exc))


def main():
    global _WORKDIR
    t_start = time.monotonic()
    deadline = t_start + GLOBAL_BUDGET_S
    summary = {"attempt": "unknown", "job_status": "not_submitted",
               "timings": {}, "odb": {}, "warnings": {}, "notes": []}
    if not os.path.isfile(ENV_JSON):
        _log("[FAIL] missing " + ENV_JSON)
        return 1
    with open(ENV_JSON, "r", encoding="utf-8") as fh:
        env_data = json.load(fh)
    launcher = env_data.get("paths", {}).get("launcher")
    lic = env_data.get("license", {}).get("server", "")
    if not launcher or not os.path.isfile(launcher):
        _log("[FAIL] launcher not found: " + str(launcher))
        return 1

    funcs = _extract_functions()
    stations, opening_labels = _host_geometry(funcs)
    _log("[0] host geometry: {} stations x {} -> {} elements, opening labels={}".format(
        len(stations), N_THETA, (len(stations) - 1) * N_THETA, len(opening_labels)))
    summary["opening_elements_expected"] = len(opening_labels)

    _WORKDIR = tempfile.mkdtemp(prefix="tower_collapse_")
    kernel_log = os.path.join(_WORKDIR, "kernel.log")
    ready_flag = os.path.join(_WORKDIR, "ready.flag")
    _log("[0] workdir=" + _WORKDIR)

    env = os.environ.copy()
    if lic:
        env["ABAQUSLM_LICENSE_FILE"] = lic
    env["ABAQUS_DRIVER_WORKDIR"] = _WORKDIR
    env["ABAQUS_DRIVER_SERVERDIR"] = SERVER_DIR

    cmd = '{} cae noGUI="{}"'.format('"' + launcher + '"',
                                     os.path.join(SERVER_DIR, "abaqus_driver.py"))
    log_fh = open(kernel_log, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, cwd=_WORKDIR, stdout=log_fh, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=env, shell=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)

    try:
        t0 = time.monotonic()
        ready = False
        while time.monotonic() - t0 < BOOT_TIMEOUT_S and time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            if os.path.exists(ready_flag):
                ready = True
                break
            time.sleep(0.5)
        boot_elapsed = time.monotonic() - t0
        _log("[1] kernel ready after {:.0f}s (ready={}, alive={})".format(
            boot_elapsed, ready, proc.poll() is None))
        if not ready:
            summary["attempt"] = "kernel_boot_failed"
            summary["notes"].append("kernel did not become ready within {}s".format(BOOT_TIMEOUT_S))
            _print_tail(kernel_log, "kernel.log")
            _print_tail(os.path.join(_WORKDIR, "driver.log"), "driver.log")
            _report_and_record(summary)
            return 1
        summary["timings"]["boot"] = round(boot_elapsed, 1)

        # ---- primary: one-shot setup_tower_collapse ----
        _log("[2] calling setup_tower_collapse (one-shot)")
        t_task = time.monotonic()
        result, err, solve_elapsed = _submit_monitored(
            proc, _WORKDIR, "setup_tower_collapse",
            {"name": TOWER_NAME, "height": TOWER_HEIGHT,
             "base_radius": TOWER_BASE_RADIUS, "throat_radius": TOWER_THROAT_RADIUS,
             "throat_elevation": TOWER_THROAT_ELEVATION, "top_radius": TOWER_TOP_RADIUS,
             "settle_time": 1.0, "time_period": 7.0,
             "project_dir": _WORKDIR},
            deadline=deadline, monitor=True, job_base=JOB_NAME)
        task_elapsed = time.monotonic() - t_task
        summary["timings"]["task_total"] = round(task_elapsed, 1)

        ok = result is not None and result.get("success")
        if not ok:
            err_text = err or ((result or {}).get("error") or "unknown")
            summary["attempt"] = "primary_failed"
            summary["job_status"] = "not_submitted"
            summary["notes"].append("setup_tower_collapse failed: " + str(err_text))
            if result and result.get("traceback"):
                summary["notes"].append("traceback head: " +
                                        result["traceback"][:600].replace("\n", " | "))
            _log("[2] FAIL setup_tower_collapse ({:.0f}s): {}".format(
                task_elapsed, err_text))
            _print_tail(kernel_log, "kernel.log")
            _print_tail(os.path.join(_WORKDIR, "driver.log"), "driver.log")
            summary["timings"]["solve"] = round(solve_elapsed, 1) if solve_elapsed else None
        else:
            r = result["result"]
            summary["timings"]["solve"] = round(solve_elapsed, 1) if solve_elapsed else \
                r.get("elapsed_seconds")
            _log("[2] PASS setup_tower_collapse in {:.0f}s (job_status={})".format(
                task_elapsed, r.get("job_status")))
            _log("      total_elements={} opening_elements={} inp_modified={}".format(
                r.get("total_elements"), r.get("opening_elements"), r.get("inp_modified")))
            inp_path = r.get("inp_path") or os.path.join(_WORKDIR, "tower_job.inp")
            sanity = _inp_sanity(inp_path)
            _log("      INP sanity: " + json.dumps(sanity))
            summary["inp_sanity"] = sanity
            jstatus = _job_status(_WORKDIR)
            summary["job_status"] = "completed" if jstatus["completed"] else \
                ("terminated" if jstatus["details"] else "unknown")
            summary["job_details"] = jstatus["details"][:6]
            summary["final_step_time"] = jstatus["final_step_time"]
            summary["final_total_time"] = jstatus["final_total_time"]
            if not jstatus["completed"]:
                summary["notes"].append(
                    "solver did not report successful completion; details: " +
                    "; ".join(jstatus["details"][:4]))

        # ---- fallback trigger ----
        if summary["job_status"] != "completed":
            remaining = deadline - time.monotonic()
            if remaining < 240:
                summary["notes"].append(
                    "fallback skipped (only {:.0f}s of budget left)".format(remaining))
            else:
                _log("[3] primary job not completed; switching to fallback")
                fresult = _run_fallback(launcher, env, _WORKDIR, funcs, stations,
                                        opening_labels, deadline)
                if fresult.get("error"):
                    summary["attempt"] = "fallback_failed"
                    summary["notes"].append("fallback: " + fresult["error"])
                    summary["timings"]["fallback_solve"] = fresult.get("solve_elapsed")
                else:
                    summary["attempt"] = "fallback"
                    summary["timings"]["fallback_solve"] = fresult.get("solve_elapsed")
                    jstatus = _job_status(_WORKDIR)
                    summary["job_status"] = "completed" if jstatus["completed"] else "terminated"
                    summary["job_details"] = jstatus["details"][:6]
                    summary["final_step_time"] = jstatus["final_step_time"]
                    summary["final_total_time"] = jstatus["final_total_time"]
                    summary["inp_sanity"] = _inp_sanity(
                        os.path.join(_WORKDIR, JOB_NAME + ".inp"))
        if summary["attempt"] == "unknown":
            summary["attempt"] = "primary"

        # ---- verification ----
        odb_info = _verify_odb(proc, _WORKDIR)
        summary["odb"] = odb_info
        summary["warnings"] = _warnings_summary(_WORKDIR)
        summary["collapse_happened"] = (
            odb_info.get("max_displacement") is not None and
            odb_info["max_displacement"] > TOWER_HEIGHT * 0.4)
        summary["total_elapsed"] = round(time.monotonic() - t_start, 1)
    except Exception as exc:
        _log("[EXC] " + str(exc))
        summary["notes"].append("script exception: " + str(exc))
    finally:
        if os.path.exists(os.path.join(_WORKDIR, JOB_NAME + ".lck")):
            terminate_cmd = '{} terminate job={}'.format('"' + launcher + '"', JOB_NAME)
            subprocess.run(terminate_cmd, cwd=_WORKDIR, env=env, shell=True,
                           timeout=30, capture_output=True)
        _shutdown(proc, _WORKDIR)
        try:
            log_fh.close()
        except Exception:
            pass
    _report_and_record(summary)
    return 0 if summary["job_status"] == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
