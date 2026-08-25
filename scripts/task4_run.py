"""Task 4 host orchestration: render frames (viewer) -> footprint report (kernel)
-> compose MP4s (imageio-ffmpeg). Same launcher/quoting as abaqus_driver.py.
Run with the gateway venv python.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(PROJECT_DIR, "scripts")
ENV_JSON = os.path.join(PROJECT_DIR, "caiao_servers", "abaqus_environment_server",
                        "abaqus_env.json")
RESOURCE_DIR = os.path.join(PROJECT_DIR, "frontend", "public", "resource", "Abaqus")

RENDER_SCRIPT = os.path.join(SCRIPTS_DIR, "render_collapse_views.py")
FOOTPRINT_SCRIPT = os.path.join(SCRIPTS_DIR, "footprint_report.py")
COMPOSE_SCRIPT = os.path.join(SCRIPTS_DIR, "compose_videos.py")


def _load_env():
    with open(ENV_JSON, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data


def _run_abaqus(launcher, mode, script, cwd, env, log_path):
    cmd = '{} {} noGUI="{}"'.format('"' + launcher + '"', mode, script)
    with open(log_path, "w", encoding="utf-8", errors="replace") as log_fh:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=log_fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, shell=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        rc = proc.wait()
    return rc


def main():
    data = _load_env()
    launcher = data["paths"]["launcher"]
    lic = data["license"]["server"]
    env = os.environ.copy()
    env["ABAQUSLM_LICENSE_FILE"] = lic

    workdir = tempfile.mkdtemp(prefix="tower_render_")
    print("workdir=" + workdir, flush=True)

    side_dir = os.path.join(RESOURCE_DIR, "frames", "side")
    top_dir = os.path.join(RESOURCE_DIR, "frames", "top")
    for d in (side_dir, top_dir):
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            if f.endswith(".png") or f.endswith(".done"):
                os.remove(os.path.join(d, f))

    rc = _run_abaqus(launcher, "cae", RENDER_SCRIPT, workdir, env,
                     os.path.join(workdir, "viewer.log"))
    print("viewer exit=%d" % rc, flush=True)
    if rc != 0 or not os.path.exists(os.path.join(side_dir, "side.done")) or \
            not os.path.exists(os.path.join(top_dir, "top.done")):
        rpy = os.path.join(workdir, "abaqus.rpy")
        tail = ""
        if os.path.exists(rpy):
            tail = open(rpy, encoding="utf-8", errors="replace").read()[-3000:]
        else:
            tail = open(os.path.join(workdir, "viewer.log"), encoding="utf-8",
                        errors="replace").read()[-3000:]
        print("render log tail:\n" + tail, flush=True)
        return 1

    rc = _run_abaqus(launcher, "cae", FOOTPRINT_SCRIPT, workdir, env,
                     os.path.join(workdir, "footprint.log"))
    print("footprint exit=%d" % rc, flush=True)
    report_json = os.path.join(RESOURCE_DIR, "cooling_tower_footprint.json")
    if rc != 0 or not os.path.exists(report_json):
        flog = open(os.path.join(workdir, "footprint.log"), encoding="utf-8",
                    errors="replace").read()
        print("footprint log tail:\n" + flog[-3000:], flush=True)
        return 1

    rc = subprocess.call([sys.executable, COMPOSE_SCRIPT])
    print("compose exit=%d" % rc, flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
