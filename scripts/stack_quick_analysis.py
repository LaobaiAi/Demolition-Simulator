"""Stack collapse quick analysis: dual-form tool (importable library + CLI).

One-shot parameterized RC chimney run built on the accepted baseline
abaqus_projects/concrete_stack_run39 (instance name stack01). Run numbers
(concrete_stack_runXX) are internal artifacts; the public name for users/LLM
is the instance name -- stack01 is the chimney baseline.

What it does (create mode):
  1. validates params, refuses to overwrite an existing run directory
  2. copies only run_stack_collapse.py + metrics_probe.py from the baseline
     into abaqus_projects/<run-name>/ (no results/ artifacts)
  3. substitutes in the copies: RESULTS_DIR path, TOTAL_SIM_TIME, the
     Collapse step duration, *Output field interval, OPENING_HEIGHT, N_THETA,
     and the weak-ring elevation / weak-ring rebar (the weak ring band is a
     hardcoded expression inside _stack_inp, so the tool injects a
     WEAK_RING_ELEV constant and rewrites the band to reference it)
  4. imports the substituted copy (free syntax check), assembles the INP
     with the baseline's own helpers and runs _inp_sanity (validation)
  5. solves: launches the copied script through run_with_wake.py (power-sleep
     guard) with absolute paths, polls the .sta file until "the analysis has
     completed successfully" or the global budget expires
  6. rewrites metrics_probe.py ODB/OUT paths (plus an exact element-count
     denominator and a collapse-direction block), runs it via
     `cmd /c "cd /d <run> && <abq2026.bat> cae noGUI=metrics_probe.py"`
  7. parses the metrics, checks the four acceptance criteria against the
     stack01 baseline, writes results/quick_result.json, prints a summary.

CLI (all defaults = stack01 / run39 baseline):
  python scripts/stack_quick_analysis.py --run-name <name> [options]
  --opening-height, --weak-ring-elev, --weak-ring-cf, --sim-time,
  --output-interval, --n-theta, --no-solve, --solve-only, --metrics-only

Real solves must be wrapped against power sleep:
  python scripts/run_with_wake.py gateway/venv/Scripts/python.exe \
      scripts/stack_quick_analysis.py --run-name concrete_stack_run40

Module API (future platform LLM via a thin CAIAO server tool -- load this
file with importlib from scripts/, or add scripts/ to sys.path):
  from stack_quick_analysis import run_stack_analysis
  result = run_stack_analysis("stack_v2", sim_time=12.0, n_theta=32)
  # -> stable dict, also mirrored to <run>/results/quick_result.json

quick_result.json schema (stable machine contract, v1):
  run_name, instance, baseline, mode, params{...}, dry_run, solved,
  solve_elapsed_s, final_step_time, final_total_time, total_elements,
  inp_sanity{...}, metrics_ok, completed, frames, last_frame{t,min_y,failed},
  deletion_pct, max_radius, p95, max_y, whip_flag, penetration_ok,
  direction{com_azimuth_deg, far_azimuth_deg}, acceptance{...}, notes[],
  error, results_dir, schema
"""

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ABAQUS_PROJECTS = os.path.join(REPO_ROOT, "abaqus_projects")
BASELINE_RUN_NAME = "concrete_stack_run39"
INSTANCE_NAME = "stack01"
BASELINE_DIR = os.path.join(ABAQUS_PROJECTS, BASELINE_RUN_NAME)
VENV_PYTHON = os.path.join(REPO_ROOT, "gateway", "venv", "Scripts", "python.exe")
WAKE_SCRIPT = os.path.join(REPO_ROOT, "scripts", "run_with_wake.py")
ENV_JSON = os.path.join(REPO_ROOT, "caiao_servers", "abaqus_environment_server",
                        "abaqus_env.json")

GLOBAL_BUDGET_S = 9000
MONITOR_INTERVAL_S = 30
METRICS_TIMEOUT_S = 1200
GROUND_ELEMENTS = 10816
ACCEPTANCE = {
    "deletion_pct": "15-17%",
    "p95": "55-66m",
    "direction": "com_azimuth within +-60deg of +X (opening faces +X)",
    "penetration": "min_y >= -0.5 (no tunneling)",
}

DEFAULTS = {
    "opening_height": 1.5,
    "weak_ring_elev": 33.5,
    "weak_ring_cf": 0.0001,
    "sim_time": 7.6,
    "output_interval": 0.15,
    "n_theta": 28,
}

_DIRECTION_BLOCK = """
# --- quick_analysis injected: collapse direction (opening faces +X) ---
_q_cx = sum(p[0] for p in coords.values()) / len(coords)
_q_cz = sum(p[2] for p in coords.values()) / len(coords)
_q_com_az = math.degrees(math.atan2(_q_cz, _q_cx))
_q_far = max(coords.items(), key=lambda kv: math.hypot(kv[1][0], kv[1][2]))
_q_far_az = math.degrees(math.atan2(_q_far[1][2], _q_far[1][0]))
log("direction: com_azimuth=%.1f  far_azimuth=%.1f  (opening faces +X, azimuth 0)" %
    (_q_com_az, _q_far_az))
"""


def _no_window():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _tail(path, n=15):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return "(no log file: " + str(path) + ")"
    return "\n".join(lines[-n:])


def _validate_run_name(run_name):
    if not re.match(r"^[A-Za-z0-9_]+$", run_name):
        return "invalid run name {!r}: only letters/digits/underscore".format(run_name)
    run_dir = os.path.join(ABAQUS_PROJECTS, run_name)
    if os.path.exists(run_dir):
        return "run directory already exists: " + run_dir
    return None


def _validate_params(p):
    if not 0.1 <= p["opening_height"] <= 30.0:
        return "opening_height out of range [0.1, 30]: {}".format(p["opening_height"])
    if not 2.0 <= p["weak_ring_elev"] <= 98.0:
        return "weak_ring_elev out of range [2, 98]: {}".format(p["weak_ring_elev"])
    if not 1e-5 <= p["weak_ring_cf"] <= 0.01:
        return "weak_ring_cf out of range [1e-5, 0.01] (0 = unsupported ply removal): {}".format(p["weak_ring_cf"])
    if not 1.0 <= p["sim_time"] <= 30.0:
        return "sim_time out of range [1, 30]: {}".format(p["sim_time"])
    if not 0.01 <= p["output_interval"] <= 1.0:
        return "output_interval out of range [0.01, 1]: {}".format(p["output_interval"])
    if not 12 <= p["n_theta"] <= 96:
        return "n_theta out of range [12, 96]: {}".format(p["n_theta"])
    return None


def _sub(text, old, new, tag, expect=1):
    n = text.count(old)
    if n != expect:
        raise RuntimeError("template mismatch for {}: expected {} occurrence(s) of {!r}, found {}".format(
            tag, expect, old, n))
    return text.replace(old, new)


def _sub_re(text, pattern, new, tag):
    new_text, n = re.subn(pattern, lambda m: new, text, count=1, flags=re.M)
    if n != 1:
        raise RuntimeError("template mismatch for {}".format(tag))
    return new_text


def _substitute_run_script(text, run_name, p):
    text = _sub(text, '"concrete_stack_run39"', '"{}"'.format(run_name),
                "RESULTS_DIR run name")
    text = _sub(text, "TOTAL_SIM_TIME = 7.6",
                "TOTAL_SIM_TIME = {:.1f}".format(p["sim_time"]),
                "TOTAL_SIM_TIME")
    text = _sub(text, '("Collapse", 7.6)',
                '("Collapse", {:.1f})'.format(p["sim_time"]),
                "Collapse step duration")
    text = _sub(text, "*Output, field, time interval=0.15",
                "*Output, field, time interval={:g}".format(p["output_interval"]),
                "field output interval")
    text = _sub(text, "OPENING_HEIGHT = 1.5",
                "OPENING_HEIGHT = {:.4g}".format(p["opening_height"]),
                "OPENING_HEIGHT")
    text = _sub(text, "N_THETA = 28",
                "N_THETA = {}\nWEAK_RING_ELEV = {:.4g}  # weak ring band center (band = elev +/- 1.0 m), quick_analysis param".format(
                    p["n_theta"], p["weak_ring_elev"]),
                "N_THETA / WEAK_RING_ELEV injection")
    text = _sub(text,
                "    weak_rows = [r for r in range(len(stations) - 1)\n"
                "                 if 32.5 - 1e-9 <= 0.5 * (stations[r] + stations[r + 1]) <= 34.5 + 1e-9]",
                "    weak_rows = [r for r in range(len(stations) - 1)\n"
                "                 if WEAK_RING_ELEV - 1.0 - 1e-9 <= 0.5 * (stations[r] + stations[r + 1])\n"
                "                 <= WEAK_RING_ELEV + 1.0 + 1e-9]",
                "weak ring band expression")
    text = _sub(text, "0.0001, 1, RebarSteel, 0.",
                "{:g}, 1, RebarSteel, 0.".format(p["weak_ring_cf"]),
                "weak ring rebar thickness", expect=2)
    return text


def _substitute_metrics_script(text, run_dir, run_name, total_elements=None):
    """Idempotent: safe to call again after the element total is known."""
    results_dir = os.path.join(run_dir, "results")
    odb = os.path.join(results_dir, "stack_job_run.odb")
    out = os.path.join(results_dir, "metrics_" + run_name + ".txt")
    text = _sub_re(text, r'^ODB = r".*"$', 'ODB = r"{}"'.format(odb), "metrics ODB path")
    text = _sub_re(text, r'^OUT = r".*"$', 'OUT = r"{}"'.format(out), "metrics OUT path")
    if total_elements is not None:
        text = _sub(text, "13666.0", "%.1f" % total_elements, "metrics element denominator")
    if "_q_com_az" not in text:
        text = _sub(text, "pen = min(ys)",
                    _DIRECTION_BLOCK + "\npen = min(ys)",
                    "direction block injection")
    return text


def _load_module(path):
    spec = importlib.util.spec_from_file_location("stack_quick_run", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load module: " + path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _compute_total_elements(mod):
    funcs = mod._extract_functions()
    stations, opening_labels = mod._host_geometry(funcs)
    stack = (len(stations) - 1) * mod.N_THETA
    return stack - len(opening_labels) + GROUND_ELEMENTS


def _assemble_inp(mod, results_dir):
    funcs = mod._extract_functions()
    stations, opening_labels = mod._host_geometry(funcs)
    text = mod._stack_inp(funcs, stations, opening_labels)
    out, modified = funcs["_tower_inp_surgery"](text, mod.STACK_NAME, opening_labels)
    out = mod._move_concrete_failure_under_cdp(out)
    out = mod._strip_empty_opening_elset(out)
    out = mod._collapse_blank_lines(out)
    inp_path = os.path.join(results_dir, mod.JOB_NAME + ".inp")
    with open(inp_path, "w", encoding="utf-8") as fh:
        fh.write(out)
    sanity = mod._inp_sanity(inp_path)
    sanity["surgery_modified"] = modified
    return inp_path, sanity


def _sta_progress(sta_path):
    info = {"step_time": None, "total_time": None, "completed": False}
    try:
        with open(sta_path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return info
    info["completed"] = "the analysis has completed successfully" in text.lower()
    for row in text.splitlines():
        f = row.split()
        if len(f) >= 4 and f[0].isdigit() and re.match(r"^\d+\.?\d*E[+-]\d+$", f[1]):
            info["step_time"] = float(f[1])
            info["total_time"] = float(f[2])
    return info


def _sta_completed(sta_path, log_path):
    if _sta_progress(sta_path)["completed"]:
        return True
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            low = fh.read().lower()
    except OSError:
        return False
    return "abaqus job" in low and "completed" in low


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


def _kill_tree(proc):
    try:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, timeout=15)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _solve(run_dir, results_dir, run_script, job_name):
    info = {"solved": False, "error": None, "solve_elapsed_s": None,
            "final_step_time": None, "final_total_time": None, "notes": []}
    cmd = [VENV_PYTHON, WAKE_SCRIPT, VENV_PYTHON, run_script]
    wrapper_log = os.path.join(run_dir, "solve_wrapper.log")
    progress_log = os.path.join(results_dir, "progress.log")
    log_fh = open(wrapper_log, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, cwd=run_dir, stdin=subprocess.DEVNULL,
                            stdout=log_fh, stderr=subprocess.STDOUT,
                            creationflags=_no_window())
    sta_path = os.path.join(results_dir, job_name + ".sta")
    log_path = os.path.join(results_dir, job_name + ".log")
    lck_path = os.path.join(results_dir, job_name + ".lck")
    t0 = time.monotonic()
    deadline = t0 + GLOBAL_BUDGET_S
    last_report = 0.0
    solve_start = None
    try:
        while time.monotonic() < deadline:
            if _sta_completed(sta_path, log_path):
                info["solved"] = True
                break
            now = time.monotonic()
            prog = _sta_progress(sta_path)
            if now - last_report >= MONITOR_INTERVAL_S:
                last_report = now
                if prog["step_time"] is not None:
                    if solve_start is None:
                        solve_start = now
                    print("[solve] running {:.0f}s step_time={} total_time={} "
                          "(solve started {:.0f}s ago)".format(
                              now - t0, prog["step_time"], prog["total_time"],
                              now - solve_start if solve_start else 0), flush=True)
            if proc.poll() is not None and now - t0 > 60 and \
                    not os.path.exists(lck_path) and not _solver_alive():
                info["error"] = ("solver wrapper exited (rc={}) before completion and "
                                 "no solver process is alive. progress.log tail:\n{}\n"
                                 "wrapper log tail:\n{}").format(
                                     proc.returncode,
                                     _tail(progress_log), _tail(wrapper_log))
                break
            time.sleep(5)
        if not info["solved"] and not info["error"]:
            _kill_tree(proc)
            subprocess.run(["taskkill", "/F", "/IM", "explicit.exe"],
                           capture_output=True, timeout=15)
            info["error"] = "solve did not finish within GLOBAL_BUDGET_S={:.0f}s".format(GLOBAL_BUDGET_S)
        if info["solved"]:
            prog = _sta_progress(sta_path)
            info["final_step_time"] = prog["step_time"]
            info["final_total_time"] = prog["total_time"]
            if solve_start is not None:
                info["solve_elapsed_s"] = round(time.monotonic() - solve_start, 1)
    finally:
        try:
            log_fh.close()
        except Exception:
            pass
    return info


def _env_info():
    with open(ENV_JSON, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    launcher = data.get("paths", {}).get("launcher")
    lic = data.get("license", {}).get("server", "")
    if not launcher or not os.path.isfile(launcher):
        raise RuntimeError("Abaqus launcher not found: " + str(launcher))
    return launcher, lic


def _run_metrics(run_dir, run_name):
    info = {"metrics_ok": False, "error": None, "text": ""}
    launcher, lic = _env_info()
    inner = 'cd /d "{}" && "{}" cae noGUI=metrics_probe.py'.format(run_dir, launcher)
    env = os.environ.copy()
    if lic:
        env["ABAQUSLM_LICENSE_FILE"] = lic
    log_path = os.path.join(run_dir, "metrics_cae.log")
    out_path = os.path.join(run_dir, "results", "metrics_" + run_name + ".txt")
    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
            subprocess.run(["cmd", "/c", inner], cwd=run_dir, env=env,
                           stdin=subprocess.DEVNULL, stdout=fh,
                           stderr=subprocess.STDOUT, timeout=METRICS_TIMEOUT_S,
                           creationflags=_no_window())
    except subprocess.TimeoutExpired:
        info["error"] = "metrics kernel did not finish within {}s".format(METRICS_TIMEOUT_S)
        return info
    if not os.path.exists(out_path):
        info["error"] = "metrics output missing: {}\ncae log tail:\n{}".format(
            out_path, _tail(log_path))
        return info
    with open(out_path, "r", encoding="utf-8", errors="replace") as fh:
        info["text"] = fh.read()
    if "METRICS_DONE" not in info["text"]:
        info["error"] = "metrics did not complete (no METRICS_DONE marker). cae log tail:\n{}".format(
            _tail(log_path))
        return info
    info["metrics_ok"] = True
    return info


def _parse_metrics(text):
    m = {}
    step = re.search(r"^step=\S+ frames=(\d+)", text, re.M)
    if step:
        m["frames"] = int(step.group(1))
    frame_re = re.compile(r"^f=(\d+) t=([-\d.]+) maxU=[-\d.]+ maxV=[-\d.]+ "
                          r"failed=(\d+) \(cum ([\d.]+)%\) min_y=([-\d.]+)")
    last = None
    for line in text.splitlines():
        fm = frame_re.match(line)
        if fm:
            last = {"t": float(fm.group(2)), "failed": int(fm.group(3)),
                    "min_y": float(fm.group(5))}
            m["deletion_pct"] = float(fm.group(4))
    m["last_frame"] = last
    fin = re.search(r"^final: max_radius=([-\d.]+)\s+p95_radius=([-\d.]+)\s+"
                    r"max_y=([-\d.]+)\s+min_y=([-\d.]+)", text, re.M)
    if fin:
        m["max_radius"] = float(fin.group(1))
        m["p95"] = float(fin.group(2))
        m["max_y"] = float(fin.group(3))
        m["min_y"] = float(fin.group(4))
    pen = re.search(r"^penetration min_y=([-\d.]+) (OK|PENETRATED)", text, re.M)
    if pen:
        m["penetration_min_y"] = float(pen.group(1))
        m["penetration_ok"] = pen.group(2) == "OK"
    d = re.search(r"^direction: com_azimuth=([-\d.]+)\s+far_azimuth=([-\d.]+)", text, re.M)
    if d:
        m["direction"] = {"com_azimuth_deg": float(d.group(1)),
                          "far_azimuth_deg": float(d.group(2))}
    return m


def _build_acceptance(m):
    acc = {}
    acc["deletion_pct_ok"] = m["deletion_pct"] is not None and 15.0 <= m["deletion_pct"] <= 17.0
    acc["p95_ok"] = m["p95"] is not None and 55.0 <= m["p95"] <= 66.0
    d = m.get("direction")
    acc["direction_ok"] = d is not None and abs(d["com_azimuth_deg"]) <= 60.0
    acc["penetration_ok"] = bool(m.get("penetration_ok"))
    acc["all_pass"] = all(acc.values())
    acc["criteria"] = ACCEPTANCE
    return acc


def _new_result(run_name, params, mode, results_dir):
    return {
        "schema": "stack-quick-analysis/v1",
        "run_name": run_name,
        "instance": INSTANCE_NAME,
        "baseline": BASELINE_RUN_NAME,
        "mode": mode,
        "params": dict(params),
        "dry_run": mode == "dry_run",
        "solved": False,
        "solve_elapsed_s": None,
        "final_step_time": None,
        "final_total_time": None,
        "total_elements": None,
        "inp_sanity": None,
        "metrics_ok": False,
        "completed": False,
        "frames": None,
        "last_frame": None,
        "deletion_pct": None,
        "max_radius": None,
        "p95": None,
        "max_y": None,
        "min_y": None,
        "whip_flag": None,
        "penetration_ok": None,
        "direction": None,
        "acceptance": None,
        "notes": [],
        "error": None,
        "results_dir": results_dir,
    }


def _write_json(path, result):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)


def run_stack_analysis(run_name, opening_height=None, weak_ring_elev=None,
                       weak_ring_cf=None, sim_time=None, output_interval=None,
                       n_theta=None, no_solve=False, solve_only=False,
                       metrics_only=False):
    """Create/run a stack collapse run on top of the stack01 baseline.

    Returns the stable result dict (also written to
    abaqus_projects/<run-name>/results/quick_result.json); on failure the
    dict carries a non-null "error" (CLI maps it to a nonzero exit code).
    """
    params = {}
    for k, v in DEFAULTS.items():
        params[k] = DEFAULTS[k] if locals()[k] is None else locals()[k]

    run_dir = os.path.join(ABAQUS_PROJECTS, run_name)
    results_dir = os.path.join(run_dir, "results")
    mode = "dry_run" if no_solve else ("solve_only" if solve_only else
                                       ("metrics_only" if metrics_only else "full"))
    result = _new_result(run_name, params, mode, results_dir)

    try:
        if not solve_only and not metrics_only:
            err = _validate_run_name(run_name)
            if err:
                result["error"] = err
                return result
        err = _validate_params(params)
        if err:
            result["error"] = err
            return result

        if solve_only or metrics_only:
            for f in ("run_stack_collapse.py", "metrics_probe.py"):
                if not os.path.isfile(os.path.join(run_dir, f)):
                    result["error"] = "run dir exists but missing {}: {}".format(f, run_dir)
                    return result
            mod = _load_module(os.path.join(run_dir, "run_stack_collapse.py"))
        else:
            os.makedirs(run_dir)
            shutil.copy2(os.path.join(BASELINE_DIR, "run_stack_collapse.py"),
                         os.path.join(run_dir, "run_stack_collapse.py"))
            shutil.copy2(os.path.join(BASELINE_DIR, "metrics_probe.py"),
                         os.path.join(run_dir, "metrics_probe.py"))
            run_script_path = os.path.join(run_dir, "run_stack_collapse.py")
            metrics_path = os.path.join(run_dir, "metrics_probe.py")
            with open(run_script_path, "r", encoding="utf-8") as fh:
                text = fh.read()
            text = _substitute_run_script(text, run_name, params)
            with open(run_script_path, "w", encoding="utf-8") as fh:
                fh.write(text)
            with open(metrics_path, "r", encoding="utf-8") as fh:
                mtext = fh.read()
            mtext = _substitute_metrics_script(mtext, run_dir, run_name)
            with open(metrics_path, "w", encoding="utf-8") as fh:
                fh.write(mtext)
            os.makedirs(results_dir)
            mod = _load_module(run_script_path)
            expected = _compute_total_elements(mod)
            inp_path, sanity = _assemble_inp(mod, results_dir)
            total = sanity.get("element_count")
            if total != expected:
                result["notes"].append(
                    "element count mismatch: inp={} computed={}".format(total, expected))
            result["total_elements"] = total
            result["inp_sanity"] = sanity
            with open(metrics_path, "r", encoding="utf-8") as fh:
                mtext = fh.read()
            mtext = _substitute_metrics_script(mtext, run_dir, run_name, total)
            with open(metrics_path, "w", encoding="utf-8") as fh:
                fh.write(mtext)
            if no_solve:
                result["notes"].append("dry-run: scripts copied, params substituted, "
                                       "INP assembled and validated; no solve")
                _write_json(os.path.join(results_dir, "quick_result.json"), result)
                return result

        if metrics_only:
            mres = _run_metrics(run_dir, run_name)
            if mres["error"]:
                result["error"] = mres["error"]
            else:
                m = _parse_metrics(mres["text"])
                result.update({k: m.get(k) for k in
                               ("frames", "last_frame", "deletion_pct", "max_radius",
                                "p95", "max_y", "min_y", "penetration_ok", "direction")})
                result["whip_flag"] = m.get("max_y") is not None and m["max_y"] > mod.STACK_HEIGHT + 1e-6
                result["metrics_ok"] = True
                result["acceptance"] = _build_acceptance(m)
                result["completed"] = True
            _write_json(os.path.join(results_dir, "quick_result.json"), result)
            return result

        sinfo = _solve(run_dir, results_dir,
                       os.path.join(run_dir, "run_stack_collapse.py"), mod.JOB_NAME)
        result["solved"] = sinfo["solved"]
        result["solve_elapsed_s"] = sinfo["solve_elapsed_s"]
        result["final_step_time"] = sinfo["final_step_time"]
        result["final_total_time"] = sinfo["final_total_time"]
        result["notes"].extend(sinfo["notes"])
        if sinfo["error"]:
            result["error"] = sinfo["error"]
        elif solve_only:
            result["completed"] = True
            _write_json(os.path.join(results_dir, "quick_result.json"), result)
            return result

        if result["solved"]:
            mres = _run_metrics(run_dir, run_name)
            if mres["error"]:
                result["error"] = mres["error"]
            else:
                m = _parse_metrics(mres["text"])
                result.update({k: m.get(k) for k in
                               ("frames", "last_frame", "deletion_pct", "max_radius",
                                "p95", "max_y", "min_y", "penetration_ok", "direction")})
                result["whip_flag"] = m.get("max_y") is not None and m["max_y"] > mod.STACK_HEIGHT + 1e-6
                result["metrics_ok"] = True
                result["acceptance"] = _build_acceptance(m)
                if params["sim_time"] <= 8.0 and not result["acceptance"]["all_pass"]:
                    result["notes"].append(
                        "sim_time={:.1f}s is the dense-frame (run39) regime: deletion/p95 "
                        "measure lower than the 12s acceptance window; use --sim-time 12.0 "
                        "for the acceptance regime".format(params["sim_time"]))
                result["completed"] = True
        _write_json(os.path.join(results_dir, "quick_result.json"), result)
        return result
    except Exception as exc:
        result["error"] = "{}: {}".format(type(exc).__name__, exc)
        try:
            _write_json(os.path.join(results_dir, "quick_result.json"), result)
        except Exception:
            pass
        return result


def _print_summary(r):
    def ok(v):
        return "PASS" if v is True else ("n/a" if v is None else "FAIL")
    print("==== stack quick analysis ====")
    print("run_name      : {} (instance {}, baseline {})".format(
        r["run_name"], r.get("instance"), r.get("baseline")))
    print("mode          : {}".format(r.get("mode")))
    p = r["params"]
    print("params        : opening_height={} weak_ring_elev={} weak_ring_cf={} "
          "sim_time={} output_interval={} n_theta={}".format(
              p["opening_height"], p["weak_ring_elev"], p["weak_ring_cf"],
              p["sim_time"], p["output_interval"], p["n_theta"]))
    print("results_dir   : {}".format(r.get("results_dir")))
    s = r.get("inp_sanity")
    if s:
        print("inp sanity    : {} elements, concrete_failure={} field_output={} "
              "statusmp={} gravity={} contact={} surgery={}".format(
                  s.get("element_count"), s.get("has_concrete_failure"),
                  s.get("has_field_output"), s.get("has_status_mp"),
                  s.get("has_gravity"), s.get("has_contact"),
                  s.get("surgery_modified")))
    if r.get("solved") or r.get("solve_elapsed_s") is not None:
        print("solve         : {} ({}s, step_time={})".format(
            "completed" if r.get("solved") else "FAILED",
            r.get("solve_elapsed_s"), r.get("final_step_time")))
    if r.get("metrics_ok"):
        lf = r["last_frame"]
        a = r["acceptance"]
        print("last_frame    : t={} min_y={} failed={}".format(lf["t"], lf["min_y"], lf["failed"]))
        print("deletion_pct  : {:.2f}% (acceptance {}: {})".format(
            r["deletion_pct"], a["criteria"]["deletion_pct"], ok(a["deletion_pct_ok"])))
        print("p95           : {:.2f} m (acceptance {}: {})".format(
            r["p95"], a["criteria"]["p95"], ok(a["p95_ok"])))
        print("max_radius    : {:.2f} m".format(r["max_radius"]))
        print("max_y         : {:.2f} m (whip flag: {})".format(
            r["max_y"], "yes" if r.get("whip_flag") else "no"))
        d = r["direction"]
        print("direction     : com_azimuth={:.1f}deg far_azimuth={:.1f}deg "
              "(expect +X: {})".format(d["com_azimuth_deg"], d["far_azimuth_deg"],
                                       ok(a["direction_ok"])))
        print("penetration   : min_y={} ({})".format(
            r["min_y"], "OK" if r.get("penetration_ok") else "PENETRATED"))
        print("acceptance    : {}/4 passed - deletion={} p95={} direction={} penetration={}".format(
            sum(1 for k in ("deletion_pct_ok", "p95_ok", "direction_ok", "penetration_ok")
                if a.get(k) is True),
            ok(a["deletion_pct_ok"]), ok(a["p95_ok"]), ok(a["direction_ok"]),
            ok(a["penetration_ok"])))
    if r.get("notes"):
        for n in r["notes"]:
            print("note          : " + n)
    if r.get("error"):
        print("ERROR         : " + r["error"])
    print("result json   : {}".format(os.path.join(r.get("results_dir", ""), "quick_result.json")))
    print("==== END ====")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Stack collapse quick analysis on top of the stack01 "
                    "(concrete_stack_run39) baseline. Real solves: wrap the "
                    "whole command in scripts/run_with_wake.py against power sleep.")
    ap.add_argument("--run-name", required=True,
                    help="new run directory name under abaqus_projects/ "
                         "(must not exist; letters/digits/underscore)")
    ap.add_argument("--opening-height", type=float, default=None,
                    help="opening band height in m (default 1.5, stack01 baseline)")
    ap.add_argument("--weak-ring-elev", type=float, default=None,
                    help="weak ring band center elevation in m (default 33.5)")
    ap.add_argument("--weak-ring-cf", type=float, default=None,
                    help="weak ring rebar thickness per face in m (default 0.0001)")
    ap.add_argument("--sim-time", type=float, default=None,
                    help="collapse step duration in s (default 7.6)")
    ap.add_argument("--output-interval", type=float, default=None,
                    help="field output interval in s (default 0.15)")
    ap.add_argument("--n-theta", type=int, default=None,
                    help="circumferential mesh density (default 28)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--no-solve", action="store_true",
                   help="dry run: copy + substitute + assemble/validate INP only")
    g.add_argument("--solve-only", action="store_true",
                   help="existing run: solve only (no metrics)")
    g.add_argument("--metrics-only", action="store_true",
                   help="existing run: metrics only (ODB must exist)")
    args = ap.parse_args(argv)

    result = run_stack_analysis(
        args.run_name,
        opening_height=args.opening_height,
        weak_ring_elev=args.weak_ring_elev,
        weak_ring_cf=args.weak_ring_cf,
        sim_time=args.sim_time,
        output_interval=args.output_interval,
        n_theta=args.n_theta,
        no_solve=args.no_solve,
        solve_only=args.solve_only,
        metrics_only=args.metrics_only,
    )
    _print_summary(result)
    if result.get("error"):
        return 1
    if result.get("dry_run") or result.get("completed"):
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
