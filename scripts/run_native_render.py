"""Host-side driver for native Abaqus viewport rendering.

Usage (gateway venv python):
  python run_native_render.py cooling_tower|concrete_stack [--field STATUS|PEEQ|S]
      [--n-targets N] [--wait-max S] [--no-compose]
Steps: wait for .lck release -> write config -> abq cae noGUI render ->
report parse -> compose MP4s (1280x720, 10fps) -> deploy to frontend ->
verify (frame diffs + PNG sanity).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np
from PIL import Image

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(PROJECT_DIR, "scripts")
RENDER_DIR = os.path.join(SCRIPTS_DIR, "_native_render")
ENV_JSON = os.path.join(PROJECT_DIR, "caiao_servers", "abaqus_environment_server",
                        "abaqus_env.json")
RESOURCE_DIR = os.path.join(PROJECT_DIR, "frontend", "public", "resource", "Abaqus")
KERNEL_SCRIPT = os.path.join(SCRIPTS_DIR, "render_native_frames.py")

MODELS = {
    "cooling_tower": {
        "odb": os.path.join(PROJECT_DIR, "abaqus_projects", "cooling_tower_fine",
                            "results", "tower_job_run.odb"),
        "out_dir": os.path.join(RENDER_DIR, "cooling_tower"),
        "mp4": {"side": "cooling_tower_collapse_native.mp4",
                "top": "cooling_tower_collapse_top_native.mp4"},
    },
    "concrete_stack": {
        "odb": os.path.join(PROJECT_DIR, "abaqus_projects", "concrete_stack",
                            "results", "stack_job_run.odb"),
        "out_dir": os.path.join(RENDER_DIR, "concrete_stack"),
        "mp4": {"side": "concrete_stack_side_native.mp4",
                "top": "concrete_stack_top_native.mp4"},
    },
}

W, H = 1280, 720
FPS = 10
T0, T1 = 0.5, 8.0
RENDER_W, RENDER_H = 1920, 1080
POLL_S = 20


def wait_odb_ready(cfg, wait_max):
    odb = cfg["odb"]
    lck = odb + ".lck"
    if not os.path.exists(lck):
        return "odb ready, no lck"
    print("lck present, waiting for solver to release (max %ds)" % wait_max, flush=True)
    t0 = time.time()
    while os.path.exists(lck) and time.time() - t0 < wait_max:
        time.sleep(POLL_S)
        print("  waited %.0fs for .lck release" % (time.time() - t0), flush=True)
    if os.path.exists(lck):
        print("WARNING: lck still present after %ds, proceeding anyway" % wait_max,
              flush=True)
        return "lck still present after wait"
    return "lck released after %.0fs" % (time.time() - t0)


def run_kernel(cfg, n_targets, field):
    os.makedirs(RENDER_DIR, exist_ok=True)
    config = {
        "odb_path": cfg["odb"],
        "out_dir": cfg["out_dir"],
        "field": field,
        "views": ["side", "top"],
        "n_targets": n_targets,
        "t0": T0, "t1": T1,
        "azim": -25.0, "elev": 8.0,
        "fov": 35.0,
        "deform_scale": 1.0,
        "width": RENDER_W, "height": RENDER_H,
        "num_intervals": 2 if field == "STATUS" else 9,
    }
    cpath = os.path.join(RENDER_DIR, "config.json")
    with open(cpath, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=1)
    data = json.load(open(ENV_JSON, encoding="utf-8"))
    launcher = data["paths"]["launcher"]
    env = os.environ.copy()
    env["ABAQUSLM_LICENSE_FILE"] = data["license"]["server"]
    env["NATIVE_RENDER_CFG"] = cpath
    cmd = '"%s" cae noGUI="%s"' % (launcher, KERNEL_SCRIPT)
    log = os.path.join(RENDER_DIR, "kernel.log")
    t0 = time.time()
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.Popen(cmd, cwd=RENDER_DIR, stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, shell=True,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            rc = proc.wait(timeout=3600)
        except subprocess.TimeoutExpired:
            proc.kill()
            print("KERNEL TIMEOUT after 3600s", flush=True)
            sys.exit(1)
    dt = time.time() - t0
    print("kernel exit=%d in %.0fs" % (rc, dt), flush=True)
    rp = os.path.join(RENDER_DIR, "report.txt")
    if os.path.exists(rp):
        print(open(rp, encoding="utf-8", errors="replace").read(), flush=True)
    else:
        tail = open(log, encoding="utf-8", errors="replace").read()[-3000:]
        print("no report, kernel log tail:\n" + tail, flush=True)
        sys.exit(1)
    for view in ("side", "top"):
        vdir = os.path.join(cfg["out_dir"], view)
        n_png = len([f for f in os.listdir(vdir) if f.endswith(".png")]) \
            if os.path.isdir(vdir) else 0
        print("%s: %d pngs" % (view, n_png), flush=True)
        if n_png != n_targets:
            print("EXPECTED %d pngs for %s, got %d" % (n_targets, view, n_png), flush=True)
            sys.exit(1)
    return rp


def compose(cfg, n_targets):
    import imageio
    sizes = {}
    for view in ("side", "top"):
        vdir = os.path.join(cfg["out_dir"], view)
        pngs = sorted(f for f in os.listdir(vdir) if f.endswith(".png"))
        if len(pngs) != n_targets:
            print("compose %s: expected %d, got %d" % (view, n_targets, len(pngs)),
                  flush=True)
            sys.exit(1)
        out = os.path.join(RESOURCE_DIR, cfg["mp4"][view])
        frames = []
        for fp in pngs:
            im = Image.open(os.path.join(vdir, fp)).convert("RGB")
            sizes[im.size] = sizes.get(im.size, 0) + 1
            if im.size != (W, H):
                im = im.resize((W, H), Image.LANCZOS)
            frames.append(np.asarray(im))
        if os.path.exists(out):
            os.remove(out)
        t0 = time.time()
        with imageio.get_writer(out, fps=FPS, codec="libx264", pixelformat="yuv420p",
                                quality=8) as w:
            for fr in frames:
                w.append_data(fr)
        print("compose %s -> %s (%ds, %d bytes)" % (
            view, out, time.time() - t0, os.path.getsize(out)), flush=True)
    print("source png sizes: %s" % dict(sizes), flush=True)


def verify(cfg):
    import imageio
    for view in ("side", "top"):
        path = os.path.join(RESOURCE_DIR, cfg["mp4"][view])
        r = imageio.get_reader(path)
        fr = np.stack([r.get_data(i) for i in range(r.count_frames())])
        n = fr.shape[0]
        j = min(24, n - 1)
        d01 = float(np.abs(fr[0].astype(np.int32) - fr[j].astype(np.int32)).mean())
        d02 = float(np.abs(fr[0].astype(np.int32) - fr[n - 1].astype(np.int32)).mean())
        p0 = fr[0].astype(int)
        colorful = (np.abs(p0[..., 0] - p0[..., 2]) > 40).mean()
        dark = (p0.sum(2) < 250).mean()
        print("%s %s: frames=%d diffs 1-mid=%.2f 1-last=%.2f colorful=%.3f dark=%.3f" % (
            view, os.path.basename(path), n, d01, d02, colorful, dark), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model", choices=sorted(MODELS))
    ap.add_argument("--field", default="STATUS")
    ap.add_argument("--n-targets", type=int, default=50)
    ap.add_argument("--wait-max", type=int, default=3000)
    ap.add_argument("--no-compose", action="store_true")
    args = ap.parse_args()
    cfg = MODELS[args.model]

    if not os.path.exists(cfg["odb"]):
        print("ODB missing: %s" % cfg["odb"], flush=True)
        sys.exit(1)
    print(wait_odb_ready(cfg, args.wait_max), flush=True)
    t0 = time.time()
    run_kernel(cfg, args.n_targets, args.field)
    print("render total %.0fs" % (time.time() - t0), flush=True)
    if not args.no_compose:
        compose(cfg, args.n_targets)
        verify(cfg)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
