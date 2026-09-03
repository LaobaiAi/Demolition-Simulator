"""Host-side: run an Abaqus kernel noGUI script via the env launcher (proven pattern).

Usage: gateway/venv/Scripts/python.exe scripts/run_abaqus_script.py <kernel_script.py> [workdir]
Mirrors render_tower_frames.run_extract: launcher + license env, noGUI, CREATE_NO_WINDOW.
"""

import json
import os
import subprocess
import sys
import time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_JSON = os.path.join(PROJECT_DIR, "caiao_servers", "abaqus_environment_server",
                        "abaqus_env.json")


def main():
    if len(sys.argv) < 2:
        print("usage: run_abaqus_script.py <kernel_script.py> [cwd]", flush=True)
        return 1
    script = os.path.abspath(sys.argv[1])
    cwd = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.dirname(script)
    data = json.load(open(ENV_JSON, encoding="utf-8"))
    launcher = data["paths"]["launcher"]
    env = os.environ.copy()
    if data.get("license", {}).get("server"):
        env["ABAQUSLM_LICENSE_FILE"] = data["license"]["server"]
    cmd = '"%s" cae noGUI="%s"' % (launcher, script)
    print("RUN: %s" % cmd, flush=True)
    t0 = time.time()
    with open(os.path.join(cwd, "kernel_run.log"), "w", encoding="utf-8",
              errors="replace") as fh:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, shell=True,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            rc = proc.wait(timeout=590)
        except subprocess.TimeoutExpired:
            proc.kill()
            print("TIMEOUT after 590s", flush=True)
            return 2
    print("exit=%d in %.0fs" % (rc, time.time() - t0), flush=True)
    print("log tail:", flush=True)
    with open(os.path.join(cwd, "kernel_run.log"), "r", encoding="utf-8",
              errors="replace") as fh:
        for line in fh.read().splitlines()[-40:]:
            print(line, flush=True)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
