"""Cooling tower collapse quick analysis: dual-form tool (importable library
+ CLI). One-shot parameterized cooling tower run on top of the accepted
baseline abaqus_projects/cooling_tower_r26c_full (instance coolingtower01).
Run numbers (cooling_tower_quickXX) are internal artifacts; the public name
for users/LLM is the instance name -- coolingtower01 is the baseline.

What it does (create mode):
  1. validates params, refuses to overwrite an existing run directory
  2. copies only the run script (full_run_r26c.py, or half_run_r26c.py for
     --half) + tower_metrics_probe.py into abaqus_projects/<run-name>/
  3. substitutes in the copies: ductile, sim_time (Collapse window),
     n_theta, initial_velocity, top_ring_rebar, criteria (opening/tower
     failure-strain pairs), the Collapse frame count, the solve budgets
     (SOLVE_HARD_CAP_S / GLOBAL_BUDGET_S), and rewrites the value-specific
     baseline guard lines to check the substituted values through a
     _QA_EXPECT dict (the baseline guards hardcode r26c values and would
     fail on any non-default parameter)
  4. imports the substituted copy (free syntax check), assembles the INP
     with the baseline's own helpers (_host_geometry + _assemble_inp),
     runs the patched baseline guards + R._inp_sanity, and (for default
     params) compares the INP sha256 against the baseline's own
     results/tower_job_run.inp
  5. solves: launches the copied script through run_with_wake.py (power-sleep
     guard) with --solve (the copy re-assembles the INP identically, runs
     the patched guards, submits via the baseline half-run solver), polls
     results/tower_job_run.sta until "the analysis has completed
     successfully" or the global budget expires
  6. runs the metrics probe via `cmd /c "cd /d <run> && <abq2026.bat> cae
     noGUI=tower_metrics_probe.py"`, parses the text metrics, checks the six
     acceptance criteria against the coolingtower01 baseline, writes
     results/quick_result.json, prints a summary.

CLI (all defaults = coolingtower01 / r26c_full baseline):
  python scripts/tower_quick_analysis.py --run-name <name> [options]
  --ductile, --sim-time, --n-theta, --initial-velocity, --top-ring-rebar,
  --criteria-opening-lo/hi, --criteria-tower-lo/hi, --half,
  --no-solve, --solve-only, --metrics-only

Real solves must be wrapped against power sleep:
  python scripts/run_with_wake.py gateway/venv/Scripts/python.exe \
      scripts/tower_quick_analysis.py --run-name cooling_tower_quick01

Module API (future platform LLM via a thin CAIAO server tool -- load this
file with importlib from scripts/, or add scripts/ to sys.path):
  from tower_quick_analysis import run_tower_analysis
  result = run_tower_analysis("cooling_tower_quick01", ductile=0.03)
  # -> stable dict, also mirrored to <run>/results/quick_result.json

quick_result.json schema (stable machine contract, tower-quick-analysis/v1):
  run_name, instance, baseline, half, mode, params{ductile, sim_time,
  n_theta, initial_velocity, top_ring_rebar, criteria{opening,tower}},
  dry_run, solved, solve_elapsed_s, final_step_time, final_total_time,
  total_elements, inp_sanity{...}, guards_all_pass, inp_matches_baseline,
  baseline_expected{...}, metrics_ok, completed, frames, hinge{...},
  first_touch{...}, fold_angle_last_deg, direction{...}, penetration{...},
  pre_touch{...}, band_deletion{...}, trajectories{...}, acceptance{...},
  notes[], error, results_dir, schema

Acceptance criteria (see dev-notes/abaqus/instances/coolingtower01/prompt.md
section 5):
  hinge 2-6 s / fold >= 60 deg / |COM azimuth| <= 30 deg vs +X /
  min_z >= -0.1 m / pre-touch-1 s fold 40-75 deg + top ring mean > 10 m /
  first touch exists and after the acceptance frame. Band deletion is
  reported but NOT gated: broad concrete deletion is a known limitation
  (FB-2026-08-25-01).
"""

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ABAQUS_PROJECTS = os.path.join(REPO_ROOT, "abaqus_projects")
BASELINE_RUN_NAME = "cooling_tower_r26c_full"
HALF_BASELINE_RUN_NAME = "cooling_tower_r26c_half"
INSTANCE_NAME = "coolingtower01"
BASELINE_DIR = os.path.join(ABAQUS_PROJECTS, BASELINE_RUN_NAME)
HALF_BASELINE_DIR = os.path.join(ABAQUS_PROJECTS, HALF_BASELINE_RUN_NAME)
VENV_PYTHON = os.path.join(REPO_ROOT, "gateway", "venv", "Scripts", "python.exe")
WAKE_SCRIPT = os.path.join(REPO_ROOT, "scripts", "run_with_wake.py")
ENV_JSON = os.path.join(REPO_ROOT, "caiao_servers", "abaqus_environment_server",
                        "abaqus_env.json")
PROBE_SRC = os.path.join(REPO_ROOT, "scripts", "tower_metrics_probe.py")

GLOBAL_BUDGET_S = 7000
SOLVE_HARD_CAP_S = 6000
HALF_GLOBAL_BUDGET_S = 4200
HALF_SOLVE_HARD_CAP_S = 3200
MONITOR_INTERVAL_S = 30
METRICS_TIMEOUT_S = 1800
GROUND_ELEMENTS = 2304
TOP_RING_WALL_T = 0.25

ACCEPTANCE = {
    "hinge": "opening band conc deletion first >= 5% at 2-6 s (baseline 4.9 s)",
    "collapse": "last-frame fold angle >= 60 deg (baseline 91.15 deg)",
    "direction": "|COM azimuth| <= 30 deg vs +X opening (baseline 349.4 deg = -10.6)",
    "penetration": "min_z >= -0.1 m at last frame (baseline 0)",
    "posture": "pre-touch-1 s: fold 40-75 deg and top-ring mean > 10 m (baseline 62.25 deg / 26.5 m)",
    "first_touch": "exists and after the acceptance frame (baseline 13.4 s)",
}

DEFAULTS = {
    "ductile": 0.05,
    "sim_time": 14.0,
    "n_theta": 256,
    "initial_velocity": 0.5,
    "top_ring_rebar": 0.0025,
    "criteria_opening": (0.005, 0.015),
    "criteria_tower": (0.01, 0.03),
}

BASELINE_EXPECTED = {
    "hinge_s": 4.9,
    "first_touch_s": 13.4,
    "fold_last_deg": 91.15,
    "com_direction_deg_0_360": 349.4,
    "pre_touch": {"t": 12.4, "fold_deg": 62.25, "top_ring_mean_m": 26.475},
    "penetration": "min_z >= -0.1 PASS",
    "conc_deletion_total_pct": 82.9,
}


def _no_window():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _tail(path, n=15):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return "(no log file: " + str(path) + ")"
    return "\n".join(lines[-n:])


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_run_name(run_name):
    if not re.match(r"^[A-Za-z0-9_]+$", run_name):
        return "invalid run name {!r}: only letters/digits/underscore".format(run_name)
    run_dir = os.path.join(ABAQUS_PROJECTS, run_name)
    if os.path.exists(run_dir):
        return "run directory already exists: " + run_dir
    return None


def _validate_params(p):
    if not 0.01 <= p["ductile"] <= 0.2:
        return "ductile out of range [0.01, 0.2]: {}".format(p["ductile"])
    if not 5.0 <= p["sim_time"] <= 30.0:
        return "sim_time out of range [5, 30]: {}".format(p["sim_time"])
    if not 64 <= p["n_theta"] <= 512 or p["n_theta"] % 2 != 0:
        return "n_theta out of range [64, 512] and even: {}".format(p["n_theta"])
    if not 0.0 <= p["initial_velocity"] <= 2.0:
        return "initial_velocity out of range [0, 2]: {}".format(p["initial_velocity"])
    if not 0.0005 <= p["top_ring_rebar"] <= 0.01:
        return "top_ring_rebar out of range [0.0005, 0.01]: {}".format(p["top_ring_rebar"])
    for tag, (lo, hi) in (("criteria_opening", p["criteria"]["opening"]),
                          ("criteria_tower", p["criteria"]["tower"])):
        if not (1e-4 <= lo < hi <= 0.2):
            return "{} out of range (1e-4 <= lo < hi <= 0.2): {} / {}".format(tag, lo, hi)
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


def _substitute_run_script(text, run_name, p, half):
    nint = max(10, int(round(p["sim_time"] / 0.1)))
    tpr = p["top_ring_rebar"]
    top_conc = TOP_RING_WALL_T - 2.0 * tpr
    expect = {
        "ductile": p["ductile"],
        "sim_time": p["sim_time"],
        "nint_collapse": nint,
        "init_vx": p["initial_velocity"],
        "top_ring_rebar": tpr,
        "top_ring_conc": top_conc,
        "cf_tower": "{:.4f}, {:.4f}, 0., 0.".format(*p["criteria"]["tower"]),
        "cf_opening": "{:.4f}, {:.4f}, 0., 0.".format(*p["criteria"]["opening"]),
    }
    if half:
        cap = HALF_SOLVE_HARD_CAP_S
        budget = HALF_GLOBAL_BUDGET_S
        n_ring = p["n_theta"] // 2 + 1
        n_row = p["n_theta"] // 2
    else:
        cap = SOLVE_HARD_CAP_S
        budget = GLOBAL_BUDGET_S
        n_ring = p["n_theta"]
        n_row = p["n_theta"]

    text = _sub(text, "REBAR_DUCTILE_STRAIN = 0.05",
                "REBAR_DUCTILE_STRAIN = {:.2f}   # quick_analysis param".format(p["ductile"]),
                "REBAR_DUCTILE_STRAIN")
    text = _sub(text, "H.TOTAL_SIM_TIME = 15.0",
                "H.TOTAL_SIM_TIME = {:.1f}   # quick_analysis: settle 1.0 + Collapse".format(
                    1.0 + p["sim_time"]),
                "TOTAL_SIM_TIME")
    text = _sub(text, "H.COLLAPSE_TIME = 14.0",
                "H.COLLAPSE_TIME = {:.1f}   # quick_analysis param".format(p["sim_time"]),
                "COLLAPSE_TIME")
    text = _sub(text, '("Collapse", H.COLLAPSE_TIME, 140)',
                '("Collapse", H.COLLAPSE_TIME, {})'.format(nint),
                "Collapse frame count")

    guard_subs = [
        ('inp_text.count("0.0025, 3") == 2',
         'inp_text.count("{:.4f}, 3".format(_QA_EXPECT["top_ring_rebar"])) == 2',
         "guard topring_rebar"),
        ('"0.2450, 5, C30_Tower, 0." in inp_text',
         '"{:.4f}, 5, C30_Tower, 0.".format(_QA_EXPECT["top_ring_conc"]) in inp_text',
         "guard topring_conc"),
        ('"*Concrete Failure\\n0.0100, 0.0300, 0., 0." in inp_text',
         '"*Concrete Failure\\n" + _QA_EXPECT["cf_tower"] in inp_text',
         "guard tower_cf"),
        ('"*Concrete Failure\\n0.0050, 0.0150, 0., 0." in inp_text',
         '"*Concrete Failure\\n" + _QA_EXPECT["cf_opening"] in inp_text',
         "guard opening_cf"),
        ('and "0.05, 0., 0." in inp_text',
         'and "{:.2f}, 0., 0.".format(_QA_EXPECT["ductile"]) in inp_text',
         "guard ductile"),
        ('        "no_ductile_0.1": "0.10, 0., 0." not in inp_text,',
         '        "no_ductile_0.1": True,  # quick_analysis: ductile is a param',
         "guard no_ductile"),
        ('and ", 14.0" in inp_text,',
         'and ", {:.1f}".format(_QA_EXPECT["sim_time"]) in inp_text,',
         "guard collapse_step"),
        ('"number interval=140" in inp_text,',
         '"number interval={}".format(_QA_EXPECT["nint_collapse"]) in inp_text,',
         "guard frames_collapse"),
        ('and "AllTowerNodes, 1, 0.50" in inp_text,',
         'and "AllTowerNodes, 1, {:.2f}".format(_QA_EXPECT["init_vx"]) in inp_text,',
         "guard init_velocity"),
        ('        "no_r24_criteria": "0.0040, 0.0200" not in inp_text '
         'and "0.0020, 0.0120" not in inp_text,',
         '        "no_r24_criteria": True,  # quick_analysis: criteria are params',
         "guard no_r24_criteria"),
    ]
    for old, new, tag in guard_subs:
        text = _sub(text, old, new, tag)

    if half:
        text = _sub(text,
                    '        "no_r26b_90frames": "number interval=90" not in inp_text,',
                    '        "no_r26b_90frames": True,  # quick_analysis: nint derives from sim_time',
                    "guard no_90_frames")
    else:
        text = _sub(text,
                    '        "no_90_frames": "number interval=90" not in inp_text,',
                    '        "no_90_frames": True,  # quick_analysis: nint derives from sim_time',
                    "guard no_90_frames")

    if half:
        injection = (
            "\n# --- quick_analysis injected: params / budgets / guard expectations ---\n"
            "R.N_THETA = {}\n"
            "R.INITIAL_VELOCITY_X = {:.2f}\n"
            "H.N_RING_NODES = {}\n"
            "H.N_ROW_ELEMS = {}\n"
            "H.BAND_REBAR_T[\"TopRing\"] = {:.4f}\n"
            "H.C30_T_CF = ({:.4f}, {:.4f})\n"
            "H.C30_O_CF = ({:.4f}, {:.4f})\n"
            "H.SOLVE_HARD_CAP_S = {}\n"
            "H.GLOBAL_BUDGET_S = {}\n"
            "import half_run_r24 as _qa_r24\n"
            "_qa_r24.N_RING_NODES = {}\n"
            "_qa_r24.N_ROW_ELEMS = {}\n"
            "_QA_EXPECT = {}\n".format(
                p["n_theta"], p["initial_velocity"], n_ring, n_row, tpr,
                p["criteria"]["tower"][0], p["criteria"]["tower"][1],
                p["criteria"]["opening"][0], p["criteria"]["opening"][1],
                cap, budget, n_ring, n_row, expect))
        text = _sub(text, "R = B.R      # run23 helper namespace",
                    "R = B.R      # run23 helper namespace" + injection,
                    "param injection")
    else:
        text = _sub(text, "BAND_REBAR_T[\"TopRing\"] = 0.0025",
                    "BAND_REBAR_T[\"TopRing\"] = {:.4f}   # quick_analysis param".format(tpr),
                    "BAND_REBAR_T TopRing")
        text = _sub(text, "N_RING_NODES = R.N_THETA",
                    "N_RING_NODES = {}".format(n_ring),
                    "N_RING_NODES")
        text = _sub(text, "N_ROW_ELEMS = R.N_THETA",
                    "N_ROW_ELEMS = {}".format(n_row),
                    "N_ROW_ELEMS")
        text = _sub(text, "C30_T_CF = (R.FAILURE_STRAIN_TENSION, R.FAILURE_STRAIN_COMPRESSION)",
                    "C30_T_CF = ({:.4f}, {:.4f})   # quick_analysis param".format(
                        *p["criteria"]["tower"]),
                    "C30_T_CF")
        text = _sub_re(text,
                       r"C30_O_CF = \(R\.OPENING_FAILURE_STRAIN_TENSION,\s*"
                       r"R\.OPENING_FAILURE_STRAIN_COMPRESSION\)",
                       "C30_O_CF = ({:.4f}, {:.4f})   # quick_analysis param".format(
                           *p["criteria"]["opening"]),
                       "C30_O_CF")
        injection = (
            "\n# --- quick_analysis injected: params / budgets / guard expectations ---\n"
            "R.N_THETA = {}\n"
            "R.INITIAL_VELOCITY_X = {:.2f}\n"
            "H.SOLVE_HARD_CAP_S = {}\n"
            "H.GLOBAL_BUDGET_S = {}\n"
            "_QA_EXPECT = {}\n".format(
                p["n_theta"], p["initial_velocity"], cap, budget, expect))
        text = _sub(text, "R = H.R  # run23 (full-tower geometry + helpers)",
                    "R = H.R  # run23 (full-tower geometry + helpers)" + injection,
                    "param injection")
    return text


def _substitute_metrics_script(text, run_dir, run_name):
    results_dir = os.path.join(run_dir, "results")
    odb = os.path.join(results_dir, "tower_job_run.odb")
    out = os.path.join(results_dir, "metrics_" + run_name + ".txt")
    out_json = os.path.join(results_dir, "metrics_" + run_name + ".json")
    text = _sub(text, r"<placeholder-odb>", odb, "metrics ODB path")
    text = _sub(text, r"<placeholder-out>", out, "metrics OUT path")
    text = _sub(text, r"<placeholder-out-json>", out_json, "metrics OUT_JSON path")
    text = _sub(text, r"<placeholder-run>", run_name, "metrics RUN_NAME")
    return text


def _load_module(path):
    spec = importlib.util.spec_from_file_location("tower_quick_run", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load module: " + path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _compute_total_elements(mod, half):
    funcs = mod.R._extract_functions()
    if half:
        stations, opening_labels, _sym = mod.H._host_geometry_half(funcs)
        n_row = mod.H.N_ROW_ELEMS
    else:
        stations, opening_labels = mod.R._host_geometry(funcs)
        n_row = mod.N_ROW_ELEMS
    return 3 * ((len(stations) - 1) * n_row - len(opening_labels)) + GROUND_ELEMENTS


def _assemble_inp(mod, results_dir, half):
    funcs = mod.R._extract_functions()
    if half:
        stations, opening_labels, sym_plane = mod.H._host_geometry_half(funcs)
        out, modified = mod.H._assemble_inp(funcs, stations, opening_labels, sym_plane)
    else:
        stations, opening_labels = mod.R._host_geometry(funcs)
        out, modified = mod._assemble_inp(funcs, stations, opening_labels)
    inp_path = os.path.join(results_dir, mod.H.JOB_NAME + ".inp")
    with open(inp_path, "w", encoding="utf-8") as fh:
        fh.write(out)
    sanity = mod.R._inp_sanity(inp_path)
    sanity["surgery_modified"] = modified
    return inp_path, sanity


def _run_guards(mod, half):
    funcs = mod.R._extract_functions()
    if half:
        stations, opening_labels, sym_plane = mod.H._host_geometry_half(funcs)
        out, _ = mod.H._assemble_inp(funcs, stations, opening_labels, sym_plane)
        guards = mod.H._half_guards_r26(out, stations, opening_labels, sym_plane)
    else:
        stations, opening_labels = mod.R._host_geometry(funcs)
        out, _ = mod._assemble_inp(funcs, stations, opening_labels)
        guards = mod._full_guards_r26c(out, stations, opening_labels)
    return {k: v for k, v in guards.items() if isinstance(v, bool)}


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


def _solve(run_dir, results_dir, run_script, job_name, budget):
    info = {"solved": False, "error": None, "solve_elapsed_s": None,
            "final_step_time": None, "final_total_time": None, "notes": []}
    cmd = [VENV_PYTHON, WAKE_SCRIPT, VENV_PYTHON, run_script, "--solve"]
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
    deadline = t0 + budget
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
            info["error"] = "solve did not finish within GLOBAL_BUDGET_S={:.0f}s".format(budget)
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
    inner = 'cd /d "{}" && "{}" cae noGUI=tower_metrics_probe.py'.format(run_dir, launcher)
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


def _f(v):
    return float(v) if v is not None and v != "None" else None


def _parse_metrics(text):
    m = {}
    step = re.search(r"^step=(\S+) frames=(\d+)", text, re.M)
    if step:
        m["frames"] = int(step.group(2))
    nodes = re.search(r"^nodes: tower=(\d+) conc_elems=(\d+) rebar_elems=(\d+)", text, re.M)
    if nodes:
        m["nodes"] = {"tower": int(nodes.group(1)),
                      "conc_elems": int(nodes.group(2)),
                      "rebar_elems": int(nodes.group(3))}
    hinge = re.search(r"^hinge: first_ge_5pct=(\S+) max_jump_t=(\S+) max_jump_pct=([-\d.]+)",
                      text, re.M)
    if hinge:
        m["hinge"] = {"first_ge_5pct": _f(hinge.group(1)),
                      "max_jump_t": _f(hinge.group(2)),
                      "max_jump_pct": float(hinge.group(3))}
    touch = re.search(r"^first_touch: top_ring_1m=(\S+)", text, re.M)
    if touch:
        m["first_touch"] = {"top_ring_1m": _f(touch.group(1))}
    fold = re.search(r"^fold: last=(\S+) 2s_earlier=(\S+)", text, re.M)
    if fold:
        m["fold"] = {"last_deg": _f(fold.group(1)), "earlier_deg": _f(fold.group(2))}
    d = re.search(r"^direction: com_azimuth=([-\d.]+) far_azimuth=([-\d.]+)", text, re.M)
    if d:
        m["direction"] = {"com_azimuth_deg": float(d.group(1)),
                          "com_azimuth_abs_deg": abs(float(d.group(1))),
                          "far_azimuth_deg": float(d.group(2))}
    pen = re.search(r"^penetration: min_z=([-\d.]+) underground_nodes=(\d+) gate=(OK|PENETRATED)",
                    text, re.M)
    if pen:
        m["penetration"] = {"min_z": float(pen.group(1)),
                            "underground_nodes": int(pen.group(2)),
                            "gate_pass": pen.group(3) == "OK"}
    posture = re.search(
        r"^posture: t=(\S+) fold_angle=(\S+) top_ring_mean=(\S+) top_ring_max=(\S+) "
        r"conc_total=(\S+) rebar_total=(\S+)", text, re.M)
    if posture:
        m["pre_touch"] = {"t": _f(posture.group(1)),
                          "fold_angle_deg": _f(posture.group(2)),
                          "top_ring_mean_m": _f(posture.group(3)),
                          "top_ring_max_m": _f(posture.group(4)),
                          "conc_total_deleted_pct": _f(posture.group(5)),
                          "rebar_total_deleted_pct": _f(posture.group(6))}
    band_re = re.compile(
        r"^band_conc_last: RootBottom=([-\d.]+) RootUpper=([-\d.]+) OpeningBand=([-\d.]+) "
        r"MidTower=([-\d.]+) TopRing=([-\d.]+) total=([-\d.]+)", re.M)
    bm = band_re.search(text)
    if bm:
        m["band_conc_last"] = {
            "RootBottom_pct": float(bm.group(1)), "RootUpper_pct": float(bm.group(2)),
            "OpeningBand_pct": float(bm.group(3)), "MidTower_pct": float(bm.group(4)),
            "TopRing_pct": float(bm.group(5)), "total_pct": float(bm.group(6))}
    band_rebar_re = re.compile(
        r"^band_rebar_last: RootBottom=([-\d.]+) RootUpper=([-\d.]+) OpeningBand=([-\d.]+) "
        r"MidTower=([-\d.]+) TopRing=([-\d.]+) total=([-\d.]+)", re.M)
    br = band_rebar_re.search(text)
    if br:
        m["band_rebar_last"] = {
            "RootBottom_pct": float(br.group(1)), "RootUpper_pct": float(br.group(2)),
            "OpeningBand_pct": float(br.group(3)), "MidTower_pct": float(br.group(4)),
            "TopRing_pct": float(br.group(5)), "total_pct": float(br.group(6))}
    frame_re = re.compile(
        r"^per_frame: t=([-\d.]+) RootBottom=([-\d.]+) RootUpper=([-\d.]+) "
        r"OpeningBand=([-\d.]+) MidTower=([-\d.]+) TopRing=([-\d.]+) total=([-\d.]+)", re.M)
    frame_rebar_re = re.compile(
        r"^per_frame_rebar: t=([-\d.]+) RootBottom=([-\d.]+) RootUpper=([-\d.]+) "
        r"OpeningBand=([-\d.]+) MidTower=([-\d.]+) TopRing=([-\d.]+) total=([-\d.]+)", re.M)
    ring_re = re.compile(
        r"^ring: t=([-\d.]+) mean=([-\d.]+) max=([-\d.]+) pct_below_1m=([-\d.]+) "
        r"pct_below_5m=([-\d.]+)", re.M)
    fold_hist_re = re.compile(r"^fold_hist: t=([-\d.]+) angle=(\S+)", re.M)
    if frame_re.search(text) is not None:
        names = ("RootBottom_pct", "RootUpper_pct", "OpeningBand_pct",
                 "MidTower_pct", "TopRing_pct")
        m["trajectories"] = {
            "per_frame_conc": [dict(zip(
                ("t",) + names + ("total_pct",),
                [float(x) for x in fr.groups()])) for fr in frame_re.finditer(text)],
            "per_frame_rebar": [dict(zip(
                ("t",) + names + ("total_pct",),
                [float(x) for x in fr.groups()])) for fr in frame_rebar_re.finditer(text)],
            "top_ring": [dict(zip(
                ("t", "mean", "max", "pct_below_1m", "pct_below_5m"),
                [float(x) for x in r.groups()])) for r in ring_re.finditer(text)],
            "fold_hist": [{"t": float(fr.group(1)), "angle_deg": _f(fr.group(2))}
                          for fr in fold_hist_re.finditer(text)],
        }
    return m


def _build_acceptance(m, half):
    acc = {}
    hinge = m.get("hinge") or {}
    t_h = hinge.get("first_ge_5pct")
    acc["hinge_ok"] = t_h is not None and 2.0 <= t_h <= 6.0
    fold = m.get("fold") or {}
    acc["collapse_ok"] = fold.get("last_deg") is not None and fold["last_deg"] >= 60.0
    d = m.get("direction")
    acc["direction_ok"] = (d is not None and
                           abs(d.get("com_azimuth_deg", 999.0)) <= 30.0)
    pen = m.get("penetration")
    acc["penetration_ok"] = (pen is not None and pen.get("min_z") is not None and
                             pen["min_z"] >= -0.1)
    pre = m.get("pre_touch")
    acc["posture_ok"] = (pre is not None and pre.get("fold_angle_deg") is not None
                         and 40.0 <= pre["fold_angle_deg"] <= 75.0
                         and pre.get("top_ring_mean_m") is not None
                         and pre["top_ring_mean_m"] > 10.0)
    touch = (m.get("first_touch") or {}).get("top_ring_1m")
    acc["first_touch_ok"] = (touch is not None and pre is not None and
                             pre.get("t") is not None and pre["t"] < touch - 0.5)
    acc["all_pass"] = all(acc.values())
    acc["criteria"] = ACCEPTANCE
    return acc


def _new_result(run_name, params, mode, results_dir, half):
    return {
        "schema": "tower-quick-analysis/v1",
        "run_name": run_name,
        "instance": INSTANCE_NAME,
        "baseline": HALF_BASELINE_RUN_NAME if half else BASELINE_RUN_NAME,
        "half": half,
        "mode": mode,
        "params": dict(params),
        "dry_run": mode == "dry_run",
        "solved": False,
        "solve_elapsed_s": None,
        "final_step_time": None,
        "final_total_time": None,
        "total_elements": None,
        "inp_sanity": None,
        "guards_all_pass": None,
        "inp_matches_baseline": None,
        "baseline_expected": BASELINE_EXPECTED,
        "metrics_ok": False,
        "completed": False,
        "frames": None,
        "hinge": None,
        "first_touch": None,
        "fold_angle_last_deg": None,
        "direction": None,
        "penetration": None,
        "pre_touch": None,
        "band_deletion": None,
        "trajectories": None,
        "acceptance": None,
        "notes": [],
        "error": None,
        "results_dir": results_dir,
    }


def _write_json(path, result):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)


def run_tower_analysis(run_name, ductile=None, sim_time=None, n_theta=None,
                       initial_velocity=None, top_ring_rebar=None,
                       criteria_opening=None, criteria_tower=None,
                       half=False, no_solve=False, solve_only=False,
                       metrics_only=False):
    """Create/run a cooling tower collapse run on top of the coolingtower01
    baseline (r26c_full; half_run_r26c when half=True).

    Returns the stable result dict (also written to
    abaqus_projects/<run-name>/results/quick_result.json); on failure the
    dict carries a non-null "error" (CLI maps it to a nonzero exit code).
    """
    params = {}
    for k, v in DEFAULTS.items():
        params[k] = DEFAULTS[k] if locals()[k] is None else locals()[k]
    params["criteria"] = {
        "opening": tuple(params.pop("criteria_opening")),
        "tower": tuple(params.pop("criteria_tower")),
    }

    run_dir = os.path.join(ABAQUS_PROJECTS, run_name)
    results_dir = os.path.join(run_dir, "results")
    mode = "dry_run" if no_solve else ("solve_only" if solve_only else
                                       ("metrics_only" if metrics_only else "full"))
    result = _new_result(run_name, params, mode, results_dir, half)
    baseline_dir = HALF_BASELINE_DIR if half else BASELINE_DIR
    run_script_name = "half_run_r26c.py" if half else "full_run_r26c.py"

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
            for f in (run_script_name, "tower_metrics_probe.py"):
                if not os.path.isfile(os.path.join(run_dir, f)):
                    result["error"] = "run dir exists but missing {}: {}".format(f, run_dir)
                    return result
            mod = _load_module(os.path.join(run_dir, run_script_name))
        else:
            os.makedirs(run_dir)
            shutil.copy2(os.path.join(baseline_dir, run_script_name),
                         os.path.join(run_dir, run_script_name))
            shutil.copy2(PROBE_SRC, os.path.join(run_dir, "tower_metrics_probe.py"))
            run_script_path = os.path.join(run_dir, run_script_name)
            metrics_path = os.path.join(run_dir, "tower_metrics_probe.py")
            with open(run_script_path, "r", encoding="utf-8") as fh:
                text = fh.read()
            text = _substitute_run_script(text, run_name, params, half)
            with open(run_script_path, "w", encoding="utf-8") as fh:
                fh.write(text)
            with open(metrics_path, "r", encoding="utf-8") as fh:
                mtext = fh.read()
            mtext = _substitute_metrics_script(mtext, run_dir, run_name)
            with open(metrics_path, "w", encoding="utf-8") as fh:
                fh.write(mtext)
            os.makedirs(results_dir)
            mod = _load_module(run_script_path)
            expected = _compute_total_elements(mod, half)
            inp_path, sanity = _assemble_inp(mod, results_dir, half)
            total = sanity.get("element_count")
            if total != expected:
                result["notes"].append(
                    "element count mismatch: inp={} computed={}".format(total, expected))
            result["total_elements"] = total
            result["inp_sanity"] = sanity
            guards = _run_guards(mod, half)
            failed = [k for k, v in guards.items() if v is not True]
            result["guards_all_pass"] = len(failed) == 0
            if failed:
                result["notes"].append(
                    "baseline guards failed: {}".format(", ".join(failed)))
            baseline_inp = os.path.join(baseline_dir, "results", "tower_job_run.inp")
            if os.path.isfile(baseline_inp):
                result["inp_matches_baseline"] = _sha256(inp_path) == _sha256(baseline_inp)
                if result["inp_matches_baseline"] is False and \
                        params == dict(DEFAULTS, criteria={
                            "opening": tuple(DEFAULTS["criteria_opening"]),
                            "tower": tuple(DEFAULTS["criteria_tower"])}):
                    result["notes"].append(
                        "default params but INP differs from the baseline "
                        "results/tower_job_run.inp (sha256 mismatch)")
            if no_solve:
                result["notes"].append(
                    "dry-run: scripts copied, params substituted, INP assembled "
                    "and validated (baseline guards + sanity); no solve")
                _write_json(os.path.join(results_dir, "quick_result.json"), result)
                return result

        if metrics_only:
            mres = _run_metrics(run_dir, run_name)
            if mres["error"]:
                result["error"] = mres["error"]
            else:
                m = _parse_metrics(mres["text"])
                result.update(_metrics_to_result(m))
                result["metrics_ok"] = True
                result["acceptance"] = _build_acceptance(m, half)
                result["completed"] = True
            _write_json(os.path.join(results_dir, "quick_result.json"), result)
            return result

        sinfo = _solve(run_dir, results_dir,
                       os.path.join(run_dir, run_script_name),
                       mod.H.JOB_NAME,
                       HALF_GLOBAL_BUDGET_S if half else GLOBAL_BUDGET_S)
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
                result.update(_metrics_to_result(m))
                result["metrics_ok"] = True
                result["acceptance"] = _build_acceptance(m, half)
                result["notes"].append(
                    "band deletion reported as information only (not gated): "
                    "broad concrete deletion is the known limitation "
                    "FB-2026-08-25-01")
                if half:
                    result["notes"].append(
                        "half-tower test bench: fold/top-ring absolute values are "
                        "directional only (antisymmetric modes split, runbook "
                        "section 4); confirm with a full 360-deg run")
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


def _metrics_to_result(m):
    return {
        "frames": m.get("frames"),
        "hinge": m.get("hinge"),
        "first_touch": m.get("first_touch"),
        "fold_angle_last_deg": (m.get("fold") or {}).get("last_deg"),
        "direction": m.get("direction"),
        "penetration": m.get("penetration"),
        "pre_touch": m.get("pre_touch"),
        "band_deletion": {"conc": m.get("band_conc_last"),
                          "rebar": m.get("band_rebar_last")},
        "trajectories": m.get("trajectories"),
    }


def _print_summary(r):
    def ok(v):
        return "PASS" if v is True else ("n/a" if v is None else "FAIL")
    print("==== tower quick analysis ====")
    print("run_name      : {} (instance {}, baseline {}{})".format(
        r["run_name"], r.get("instance"), r.get("baseline"),
        ", half" if r.get("half") else ""))
    print("mode          : {}".format(r.get("mode")))
    p = r["params"]
    print("params        : ductile={} sim_time={} n_theta={} "
          "initial_velocity={} top_ring_rebar={}".format(
              p["ductile"], p["sim_time"], p["n_theta"],
              p["initial_velocity"], p["top_ring_rebar"]))
    print("criteria      : opening={} tower={}".format(
        p["criteria"]["opening"], p["criteria"]["tower"]))
    print("results_dir   : {}".format(r.get("results_dir")))
    s = r.get("inp_sanity")
    if s:
        print("inp sanity    : {} elements, concrete_failure={} field_output={} "
              "statusmp={} gravity={} contact={} surgery={}".format(
                  s.get("element_count"), s.get("has_concrete_failure"),
                  s.get("has_field_output"), s.get("has_status_mp"),
                  s.get("has_gravity"), s.get("has_contact"),
                  s.get("surgery_modified")))
        print("guards        : {} ({} guard items)".format(
            "ALL PASS" if r.get("guards_all_pass") is True else
            ("FAIL" if r.get("guards_all_pass") is False else "n/a"),
            "patched"))
    if r.get("inp_matches_baseline") is not None:
        print("inp vs base   : {}".format(
            "identical sha256" if r.get("inp_matches_baseline") else "DIFFERS"))
    if r.get("solved") or r.get("solve_elapsed_s") is not None:
        print("solve         : {} ({}s, step_time={})".format(
            "completed" if r.get("solved") else "FAILED",
            r.get("solve_elapsed_s"), r.get("final_step_time")))
    if r.get("metrics_ok"):
        a = r["acceptance"]
        print("hinge         : {}s (acceptance 2-6s: {})".format(
            (r["hinge"] or {}).get("first_ge_5pct"), ok(a["hinge_ok"])))
        print("fold last     : {} deg (acceptance >= 60: {})".format(
            r["fold_angle_last_deg"], ok(a["collapse_ok"])))
        d = r["direction"]
        print("direction     : com_azimuth={} deg (acceptance |az|<=30: {}), "
              "far={} deg".format(
                  d["com_azimuth_deg"], ok(a["direction_ok"]), d["far_azimuth_deg"]))
        pen = r["penetration"]
        print("penetration   : min_z={} ({} nodes below -0.1; {})".format(
            pen["min_z"], pen["underground_nodes"], ok(a["penetration_ok"])))
        pre = r["pre_touch"]
        print("first touch   : {}s ({})".format(
            (r["first_touch"] or {}).get("top_ring_1m"), ok(a["first_touch_ok"])))
        print("pre-touch     : t={}s fold={} deg top_ring_mean={} m (acceptance "
              "40-75 deg / >10 m: {})".format(
                  (pre or {}).get("t"), (pre or {}).get("fold_angle_deg"),
                  (pre or {}).get("top_ring_mean_m"), ok(a["posture_ok"])))
        bd = r["band_deletion"]
        print("band deletion : conc total={}% OpeningBand={}% MidTower={}% "
              "rebar total={}% (info only, FB-2026-08-25-01)".format(
                  (bd["conc"] or {}).get("total_pct"),
                  (bd["conc"] or {}).get("OpeningBand_pct"),
                  (bd["conc"] or {}).get("MidTower_pct"),
                  (bd["rebar"] or {}).get("total_pct")))
        print("acceptance    : {}/6 passed - hinge={} collapse={} direction={} "
              "penetration={} posture={} first_touch={}".format(
                  sum(1 for k in ("hinge_ok", "collapse_ok", "direction_ok",
                                  "penetration_ok", "posture_ok", "first_touch_ok")
                      if a.get(k) is True),
                  ok(a["hinge_ok"]), ok(a["collapse_ok"]), ok(a["direction_ok"]),
                  ok(a["penetration_ok"]), ok(a["posture_ok"]), ok(a["first_touch_ok"])))
    if r.get("notes"):
        for n in r["notes"]:
            print("note          : " + n)
    if r.get("error"):
        print("ERROR         : " + r["error"])
    print("result json   : {}".format(os.path.join(r.get("results_dir", ""), "quick_result.json")))
    print("==== END ====")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Cooling tower quick analysis on top of the coolingtower01 "
                    "(r26c_full) baseline. Real solves: wrap the whole command "
                    "in scripts/run_with_wake.py against power sleep.")
    ap.add_argument("--run-name", required=True,
                    help="new run directory name under abaqus_projects/ "
                         "(must not exist; letters/digits/underscore)")
    ap.add_argument("--ductile", type=float, default=None,
                    help="rebar ductile fracture trigger strain (default 0.05)")
    ap.add_argument("--sim-time", type=float, default=None,
                    help="Collapse step duration in s (default 14.0; frames 0.1 s)")
    ap.add_argument("--n-theta", type=int, default=None,
                    help="circumferential mesh density (default 256; 128 = explore tier)")
    ap.add_argument("--initial-velocity", type=float, default=None,
                    help="initial Vx in m/s, +X opening direction (default 0.5)")
    ap.add_argument("--top-ring-rebar", type=float, default=None,
                    help="TopRing hoop rebar thickness per face in m (default 0.0025)")
    ap.add_argument("--criteria-opening-lo", type=float, default=None,
                    help="opening band failure strain low (default 0.005)")
    ap.add_argument("--criteria-opening-hi", type=float, default=None,
                    help="opening band failure strain high (default 0.015)")
    ap.add_argument("--criteria-tower-lo", type=float, default=None,
                    help="root/mid/top failure strain low (default 0.01)")
    ap.add_argument("--criteria-tower-hi", type=float, default=None,
                    help="root/mid/top failure strain high (default 0.03)")
    ap.add_argument("--half", action="store_true",
                    help="half-tower test bench (z>=0 mirror, ~35 min/round) "
                         "instead of the full 360-deg tower")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--no-solve", action="store_true",
                   help="dry run: copy + substitute + assemble/validate INP only")
    g.add_argument("--solve-only", action="store_true",
                   help="existing run: solve only (no metrics)")
    g.add_argument("--metrics-only", action="store_true",
                   help="existing run: metrics only (ODB must exist)")
    args = ap.parse_args(argv)

    criteria_opening = None
    criteria_tower = None
    if args.criteria_opening_lo is not None or args.criteria_opening_hi is not None:
        lo = args.criteria_opening_lo if args.criteria_opening_lo is not None \
            else DEFAULTS["criteria_opening"][0]
        hi = args.criteria_opening_hi if args.criteria_opening_hi is not None \
            else DEFAULTS["criteria_opening"][1]
        criteria_opening = (lo, hi)
    if args.criteria_tower_lo is not None or args.criteria_tower_hi is not None:
        lo = args.criteria_tower_lo if args.criteria_tower_lo is not None \
            else DEFAULTS["criteria_tower"][0]
        hi = args.criteria_tower_hi if args.criteria_tower_hi is not None \
            else DEFAULTS["criteria_tower"][1]
        criteria_tower = (lo, hi)

    result = run_tower_analysis(
        args.run_name,
        ductile=args.ductile,
        sim_time=args.sim_time,
        n_theta=args.n_theta,
        initial_velocity=args.initial_velocity,
        top_ring_rebar=args.top_ring_rebar,
        criteria_opening=criteria_opening,
        criteria_tower=criteria_tower,
        half=args.half,
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
