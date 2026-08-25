"""Task 4 continuation: footprint report + video composition only (frames done)."""

import json
import os
import subprocess
import sys
import tempfile

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_JSON = os.path.join(PROJECT_DIR, "caiao_servers", "abaqus_environment_server",
                        "abaqus_env.json")


def main():
    with open(ENV_JSON, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    launcher = data["paths"]["launcher"]
    lic = data["license"]["server"]
    env = os.environ.copy()
    env["ABAQUSLM_LICENSE_FILE"] = lic
    workdir = tempfile.mkdtemp(prefix="tower_finish_")
    script = os.path.join(PROJECT_DIR, "scripts", "footprint_report.py")
    cmd = '{} cae noGUI="{}"'.format('"' + launcher + '"', script)
    log_path = os.path.join(workdir, "footprint.log")
    with open(log_path, "w", encoding="utf-8", errors="replace") as log_fh:
        rc = subprocess.Popen(cmd, cwd=workdir, stdout=log_fh, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, env=env, shell=True,
                              creationflags=subprocess.CREATE_NO_WINDOW).wait()
    print("footprint exit=%d" % rc, flush=True)
    if rc != 0:
        print(open(log_path, encoding="utf-8", errors="replace").read()[-3000:], flush=True)
        return 1

    rc = subprocess.call([sys.executable,
                          os.path.join(PROJECT_DIR, "scripts", "compose_videos.py")])
    print("compose exit=%d" % rc, flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
