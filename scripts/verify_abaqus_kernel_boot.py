"""Minimal Abaqus 2026 kernel-boot diagnostic — pure stdlib, no MCP/abaqus imports.

Answers one question: does `abq2026.bat cae noGUI=<script>` actually start and
run a script on THIS machine right now?  The MCP path failed with a 0-byte
kernel.log and an unconsumed task file, so we first need to isolate whether the
kernel itself is booting.

It launches the same command server.py uses, waits for a result file (or the
process to exit), prints the outcome, and force-kills the process tree on timeout.

Usage:
    python scripts/verify_abaqus_kernel_boot.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_JSON = os.path.join(
    PROJECT_DIR, "caiao_servers", "abaqus_environment_server", "abaqus_env.json"
)
BOOT_TIMEOUT_S = 180  # a healthy boot is 30-60s; give it 3x headroom
KILL_TIMEOUT_S = 15


def _read_launcher():
    if not os.path.isfile(ENV_JSON):
        print(f"[FAIL] Missing {ENV_JSON}")
        sys.exit(1)
    with open(ENV_JSON, "r", encoding="utf-8") as f:
        env = json.load(f)
    launcher = env.get("paths", {}).get("launcher")
    if not launcher or not os.path.isfile(launcher):
        print(f"[FAIL] paths.launcher missing/invalid in {ENV_JSON}")
        sys.exit(1)
    return launcher, env


def main():
    launcher, env_data = _read_launcher()
    workdir = tempfile.mkdtemp(prefix="abaqus_boottest_")
    probe = os.path.join(workdir, "boot_probe.py")
    out = os.path.join(workdir, "probe_result.json")
    kernel_log = os.path.join(workdir, "kernel.log")

    probe_code = (
        "import json, os, sys\n"
        f"out = {out!r}\n"
        "with open(out, 'w') as f:\n"
        "    json.dump({'pyver': sys.version.split()[0], 'status': 'BOOT_OK'}, f)\n"
        "print('PROBE_RAN')\n"
    )
    with open(probe, "w", encoding="utf-8") as f:
        f.write(probe_code)

    env = os.environ.copy()
    license_server = env_data.get("license", {}).get("server", "")
    if license_server:
        env["ABAQUSLM_LICENSE_FILE"] = license_server

    cmd = f'"{launcher}" cae noGUI="{probe}"'
    print(f"[1/3] Launching: {cmd}")
    print(f"      workdir={workdir}")
    log_fh = open(kernel_log, "w", encoding="utf-8", errors="replace")
    t0 = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=workdir,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        env=env,
        shell=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    booted = False
    while time.monotonic() - t0 < BOOT_TIMEOUT_S:
        if proc.poll() is not None:
            break
        if os.path.exists(out):
            booted = True
            break
        time.sleep(1)

    elapsed = time.monotonic() - t0
    log_fh.close()

    if booted:
        with open(out, "r", encoding="utf-8") as f:
            result = json.load(f)
        print(f"[2/3] BOOT_OK in {elapsed:.1f}s — pyver={result.get('pyver')} status={result.get('status')}")
        # grace: let it exit on its own, then clean up
        try:
            proc.wait(timeout=KILL_TIMEOUT_S)
        except Exception:
            _kill_tree(proc)
        print("[3/3] RESULT: KERNEL_BOOT_OK")
        return 0

    # did the process die with an error instead?
    if proc.poll() is not None:
        print(f"[2/3] Process exited rc={proc.returncode} after {elapsed:.1f}s (no result file)")
    else:
        print(f"[2/3] TIMEOUT after {BOOT_TIMEOUT_S}s — kernel never ran the probe script")
        _kill_tree(proc)
    print(f"[3/3] RESULT: KERNEL_BOOT_FAILED — see {kernel_log}")
    _print_tail(kernel_log)
    return 1


def _kill_tree(proc):
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            timeout=KILL_TIMEOUT_S,
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
    for line in lines[-30:]:
        print(line)
    print("-----------------------")


if __name__ == "__main__":
    sys.exit(main())
