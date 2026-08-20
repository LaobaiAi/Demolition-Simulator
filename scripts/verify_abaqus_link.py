"""One-shot verification of the DS <-> Abaqus 2026 link.

Reproduces exactly what server.py does:
  1. Locate abq*.bat launcher from abaqus_env.json
  2. Launch `abq2026.bat cae noGUI=abaqus_driver.py` (persistent kernel)
  3. Write task_<id>.json for create_rectangular_column
  4. Poll result_<id>.json and print the outcome
  5. Gracefully stop the kernel via exit.flag

Usage:
    python scripts\\verify_abaqus_link.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_JSON = os.path.join(
    _PROJECT_DIR, "caiao_servers", "abaqus_environment_server", "abaqus_env.json"
)
_DRIVER = os.path.join(
    _PROJECT_DIR, "caiao_servers", "abaqus_session_server", "abaqus_driver.py"
)
_SERVER_DIR = os.path.dirname(_DRIVER)

_TIMEOUT_S = 600


def find_launcher():
    with open(_ENV_JSON, "r", encoding="utf-8") as f:
        env = json.load(f)
    paths = env.get("paths", {})
    launcher = paths.get("launcher")
    if launcher and os.path.isfile(launcher):
        return launcher, env
    commands_dir = paths.get("commands")
    for name in ("abq2026.bat", "abaqus.bat"):
        candidate = os.path.join(commands_dir, name)
        if os.path.isfile(candidate):
            return candidate, env
    raise RuntimeError("Abaqus launcher not found in abaqus_env.json")


def main():
    launcher, env_data = find_launcher()
    workdir = tempfile.mkdtemp(prefix="abaqus_verify_")
    kernel_log = open(os.path.join(workdir, "kernel.log"), "w", encoding="utf-8", errors="replace")

    env = os.environ.copy()
    license_server = env_data.get("license", {}).get("server", "")
    if license_server:
        env["ABAQUSLM_LICENSE_FILE"] = license_server
    env["ABAQUS_DRIVER_WORKDIR"] = workdir
    env["ABAQUS_DRIVER_SERVERDIR"] = _SERVER_DIR

    cmdline = f'"{launcher}" cae noGUI="{_DRIVER}"'
    print(f"[1/4] Launching Abaqus kernel: {cmdline}")
    print(f"      workdir={workdir}  (license={license_server})")
    proc = subprocess.Popen(
        cmdline,
        cwd=workdir,
        stdout=kernel_log,
        stderr=subprocess.STDOUT,
        env=env,
        shell=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    req_id = uuid.uuid4().hex
    task_path = os.path.join(workdir, f"task_{req_id}.json")
    result_path = os.path.join(workdir, f"result_{req_id}.json")
    request = {
        "id": req_id,
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
        json.dump(request, f, ensure_ascii=False)
    print("[2/4] Request queued: create_rectangular_column(length=4.0, width=0.5, depth=0.5)")

    deadline = time.monotonic() + _TIMEOUT_S
    result = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            print("[FAIL] Abaqus kernel exited early. See kernel.log:", os.path.join(workdir, "kernel.log"))
            sys.exit(1)
        if os.path.exists(result_path):
            with open(result_path, "r", encoding="utf-8") as f:
                result = json.load(f)
            break
        time.sleep(0.5)

    if result is None:
        print("[FAIL] Timed out after", _TIMEOUT_S, "s. See kernel.log:", os.path.join(workdir, "kernel.log"))
        sys.exit(1)

    print("[3/4] Result received:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    try:
        with open(os.path.join(workdir, "exit.flag"), "w", encoding="utf-8") as f:
            f.write("exit")
        proc.wait(timeout=60)
        print("[4/4] Kernel stopped cleanly.")
    except Exception:
        proc.kill()

    kernel_log.close()
    if "error" in result:
        print("\nRESULT: LINK_FAILED")
        sys.exit(1)
    print("\nRESULT: LINK_OK  (DS <-> Abaqus 2026 linked)")


if __name__ == "__main__":
    main()
