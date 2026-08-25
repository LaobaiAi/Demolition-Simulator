"""Direct driver launch test — pure stdlib, no MCP.

Launches abq2026.bat cae noGUI=<abaqus_driver.py> exactly like server.py does,
then waits for ready.flag, submits a real create_rectangular_column task and
waits for the result. Used to isolate whether the wedged kernel is caused by the
driver script itself or by the MCP plumbing.

Optional --driver <path> lets you point at a copy on a space-free path to test
the "spaces in path" hypothesis (default: the real driver in the repo).

Usage:
    python scripts/verify_abaqus_driver_direct.py [--driver <path>]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(PROJECT_DIR, "caiao_servers", "abaqus_session_server")
ENV_JSON = os.path.join(
    PROJECT_DIR, "caiao_servers", "abaqus_environment_server", "abaqus_env.json"
)
BOOT_TIMEOUT_S = 150
TASK_TIMEOUT_S = 120


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", default=os.path.join(SERVER_DIR, "abaqus_driver.py"))
    args = ap.parse_args()

    with open(ENV_JSON, "r", encoding="utf-8") as f:
        env_data = json.load(f)
    launcher = env_data.get("paths", {}).get("launcher")
    if not launcher or not os.path.isfile(launcher):
        print(f"[FAIL] launcher not found: {launcher}")
        return 1
    driver_path = os.path.abspath(args.driver)
    print(f"[0/5] launcher={launcher}")
    print(f"[0/5] driver  ={driver_path}")
    print(f"[0/5] driver has spaces in path: {' ' in driver_path}")

    workdir = tempfile.mkdtemp(prefix="abaqus_direct_")
    kernel_log = os.path.join(workdir, "kernel.log")
    ready_flag = os.path.join(workdir, "ready.flag")

    env = os.environ.copy()
    lic = env_data.get("license", {}).get("server", "")
    if lic:
        env["ABAQUSLM_LICENSE_FILE"] = lic
    env["ABAQUS_DRIVER_WORKDIR"] = workdir
    env["ABAQUS_DRIVER_SERVERDIR"] = SERVER_DIR

    cmd = f'"{launcher}" cae noGUI="{driver_path}"'
    print(f"[1/5] launching: {cmd}")
    print(f"      workdir={workdir}")
    log_fh = open(kernel_log, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        cmd,
        cwd=workdir,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        env=env,
        shell=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    # ---- wait for ready.flag ----
    t0 = time.monotonic()
    ready = False
    while time.monotonic() - t0 < BOOT_TIMEOUT_S:
        if proc.poll() is not None:
            break
        if os.path.exists(ready_flag):
            ready = True
            break
        time.sleep(0.5)
    elapsed = time.monotonic() - t0
    print(f"[2/5] ready after {elapsed:.1f}s (ready={ready}, alive={proc.poll() is None})")

    if not ready:
        print("[5/5] RESULT: DRIVER_WEDGED")
        _print_tail(kernel_log)
        _kill_tree(proc)
        return 1

    # ---- submit a task ----
    import uuid

    task_id = uuid.uuid4().hex
    task_path = os.path.join(workdir, f"task_{task_id}.json")
    request = {
        "id": task_id,
        "tool": "create_rectangular_column",
        "arguments": {
            "name": "verify_col",
            "length": 4.0,
            "width": 0.5,
            "depth": 0.5,
            "rebar_dia": 0.012,
            "cover": 0.05,
        },
    }
    with open(task_path, "w", encoding="utf-8") as f:
        json.dump(request, f)
    print(f"[3/5] submitted task_{task_id}.json")

    result_path = os.path.join(workdir, f"result_{task_id}.json")
    t1 = time.monotonic()
    result = None
    while time.monotonic() - t1 < TASK_TIMEOUT_S:
        if proc.poll() is not None:
            break
        if os.path.exists(result_path):
            with open(result_path, "r", encoding="utf-8") as f:
                result = json.load(f)
            break
        time.sleep(0.5)
    if result is None:
        print(f"[4/5] no result within {TASK_TIMEOUT_S}s")
        print("[5/5] RESULT: TASK_TIMEOUT")
        _print_tail(kernel_log)
        _kill_tree(proc)
        return 1

    print(f"[4/5] result after {time.monotonic() - t1:.1f}s")
    ok = result.get("success")
    if ok:
        keys = list(result.get("result", {}).keys())
        print(f"      success={ok} result_keys={keys}")
    else:
        print(f"      success={ok} error={result.get('error')}")
        print("      " + str(result.get("traceback", ""))[:500])
    print("[5/5] RESULT: DRIVER_OK" if ok else "[5/5] RESULT: DRIVER_TOOL_ERROR")
    # graceful exit
    try:
        with open(os.path.join(workdir, "exit.flag"), "w") as f:
            f.write("exit")
        proc.wait(timeout=15)
    except Exception:
        _kill_tree(proc)
    return 0 if ok else 1


def _kill_tree(proc):
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            timeout=15,
        )
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _print_tail(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    print("--- kernel.log tail ---")
    for line in lines[-25:]:
        print(line)
    print("-----------------------")


if __name__ == "__main__":
    sys.exit(main())
