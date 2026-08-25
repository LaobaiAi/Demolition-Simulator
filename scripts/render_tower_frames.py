"""Host-side pipeline: extract ODB frames (abaqus noGUI) -> render PNGs -> compose MP4s -> verify.

Run with the gateway venv python:
  python render_tower_frames.py test      # frame 1 vs 25 pixel-diff check (also runs extraction if needed)
  python render_tower_frames.py all       # render all 50 frames x both views
  python render_tower_frames.py compose   # MP4s via imageio ffmpeg + deploy frames to frontend resource dir
  python render_tower_frames.py verify    # sample first/mid/last frames from MP4s, pairwise diffs
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from PIL import Image

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(PROJECT_DIR, "scripts")
FRAME_DIR = os.path.join(SCRIPTS_DIR, "_tower_frames")
DATA_PATH = os.path.join(FRAME_DIR, "data.npz")
EXTRACT_SCRIPT = os.path.join(SCRIPTS_DIR, "extract_tower_frames.py")
ENV_JSON = os.path.join(PROJECT_DIR, "caiao_servers", "abaqus_environment_server",
                        "abaqus_env.json")
RESOURCE_DIR = os.path.join(PROJECT_DIR, "frontend", "public", "resource", "Abaqus")
SIDE_DIR = os.path.join(FRAME_DIR, "side")
TOP_DIR = os.path.join(FRAME_DIR, "top")
SIDE_RAW_DIR = os.path.join(FRAME_DIR, "side_raw")
TOP_RAW_DIR = os.path.join(FRAME_DIR, "top_raw")

W, H = 1280, 720
FPS = 10
N_FRAMES = 50
GROUND_R = 45.0
U_MIN, U_MAX = 0.0, 75.0
SIDE_ELEV, SIDE_AZ = 8.0, -25.0


def run_extract():
    data = json.load(open(ENV_JSON, encoding="utf-8"))
    launcher = data["paths"]["launcher"]
    env = os.environ.copy()
    env["ABAQUSLM_LICENSE_FILE"] = data["license"]["server"]
    os.makedirs(FRAME_DIR, exist_ok=True)
    cmd = '"%s" cae noGUI="%s"' % (launcher, EXTRACT_SCRIPT)
    log = os.path.join(FRAME_DIR, "extract.log")
    t0 = time.time()
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.Popen(cmd, cwd=FRAME_DIR, stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, shell=True,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            rc = proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            print("EXTRACT TIMEOUT after 300s", flush=True)
            sys.exit(1)
    print("extract exit=%d in %.0fs" % (rc, time.time() - t0), flush=True)
    if rc != 0 or not os.path.exists(DATA_PATH):
        tail = open(log, encoding="utf-8", errors="replace").read()[-3000:]
        print("EXTRACT FAILED, log tail:\n" + tail, flush=True)
        sys.exit(1)
    rp = os.path.join(FRAME_DIR, "extract_report.txt")
    if os.path.exists(rp):
        print(open(rp, encoding="utf-8", errors="replace").read(), flush=True)


def ensure_data():
    if not os.path.exists(DATA_PATH):
        print("data.npz missing, launching abaqus extraction", flush=True)
        run_extract()
    else:
        print("data.npz present", flush=True)


def load_data():
    d = np.load(DATA_PATH)
    return d["X"], d["conn"], d["t"], d["U"]


def compute_limits(X, U):
    P = (X[None, :, :] + U).reshape(-1, 3)
    # data Y-up -> render Z-up: [x, -z, y]
    P = P[:, [0, 2, 1]]
    P[:, 1] *= -1.0
    x0, x1 = float(P[:, 0].min()), float(P[:, 0].max())
    y0, y1 = float(P[:, 1].min()), float(P[:, 1].max())
    z0, z1 = float(P[:, 2].min()), float(P[:, 2].max())
    x0, x1 = min(x0, -GROUND_R), max(x1, GROUND_R)
    y0, y1 = min(y0, -GROUND_R), max(y1, GROUND_R)
    z0 = min(z0, 0.0)
    m = 0.04 * max(x1 - x0, y1 - y0, z1 - z0)
    return (x0 - m, x1 + m, y0 - m, y1 + m, z0 - m, z1 + m)


def render_frame(f, X, conn, U, lim, view, out, raw=False):
    x0, x1, y0, y1, z0, z1 = lim
    P = X + U[f]
    # data Y-up -> render Z-up: tower axis (y) becomes vertical, right-hand kept: [x, -z, y]
    P = P[:, [0, 2, 1]]
    P[:, 1] *= -1.0
    mask = conn >= 0
    cd = (U[f][conn] * mask[:, :, None]).sum(axis=1) / mask.sum(axis=1)[:, None]
    cd = cd[:, [0, 2, 1]]
    cd[:, 1] *= -1.0
    cnu = np.sqrt((cd ** 2).sum(axis=1))
    faces = [P[row[row >= 0]] for row in conn]

    fig = plt.figure(figsize=(W / 100.0, H / 100.0))
    ax = fig.add_subplot(111, projection="3d")
    ax.set_proj_type("ortho")
    if view == "side":
        ax.view_init(SIDE_ELEV, SIDE_AZ)
    else:
        ax.view_init(90.0, 0.0)

    th = np.linspace(0.0, 2.0 * np.pi, 97)
    if not raw:
        gx = GROUND_R * np.cos(th)
        gz = GROUND_R * np.sin(th)
        # ground circle: data (gx, 0, gz) -> render (gx, -gz, 0), lies in render z=0 plane
        gd = np.stack([np.append(gx, gx[0]), np.append(-gz, -gz[0]), np.zeros(98)], axis=1)
        ax.add_collection3d(Poly3DCollection([gd], facecolors=(0.65, 0.68, 0.70, 0.14),
                                             edgecolors="none", zorder=0))
        ax.plot(gx, -gz, np.zeros_like(gx), color=(0.30, 0.35, 0.38, 0.9), lw=1.4, zorder=1)
        if view == "top":
            rr = 28.5 * np.cos(th)
            rz = 28.5 * np.sin(th)
            ax.plot(rr, -rz, np.zeros_like(rr), color=(0.9, 0.6, 0.2, 0.7), lw=1.2,
                    linestyle="--", zorder=1)

    if raw:
        fc = np.full((len(faces), 4), (0.72, 0.75, 0.78, 1.0))
    else:
        cmap = plt.get_cmap("viridis")
        fc = cmap(np.clip((cnu - U_MIN) / (U_MAX - U_MIN), 0.0, 1.0))
    ax.add_collection3d(Poly3DCollection(faces, facecolors=fc, edgecolors="none", zorder=2))
    ax.add_collection3d(Poly3DCollection(faces, facecolors="none",
                                         edgecolors=(0.0, 0.0, 0.0, 0.15),
                                         linewidths=0.15, zorder=3))

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_zlim(z0, z1)
    ax.set_box_aspect((x1 - x0, y1 - y0, z1 - z0))
    ax.set_axis_off()
    fig.subplots_adjust(left=0.0, right=1.0, top=1.0, bottom=0.0)
    fig.savefig(out, dpi=100)
    plt.close(fig)


def pix_diff(a, b):
    ia = np.asarray(Image.open(a)).astype(np.int32)
    ib = np.asarray(Image.open(b)).astype(np.int32)
    return float(np.abs(ia - ib).mean())


def mode_test(X, conn, U):
    print("axis mapping: data Y-up (tower axis=y, xz plane) -> render Z-up [x, -z, y]", flush=True)
    lim = compute_limits(X, U)
    print("limits x[%.1f,%.1f] y[%.1f,%.1f] z[%.1f,%.1f]" % lim, flush=True)
    os.makedirs(SIDE_DIR, exist_ok=True)
    os.makedirs(TOP_DIR, exist_ok=True)
    t0 = time.time()
    for f in (0, 24):
        render_frame(f, X, conn, U, lim, "side", os.path.join(SIDE_DIR, "f_%03d.png" % (f + 1)))
        render_frame(f, X, conn, U, lim, "top", os.path.join(TOP_DIR, "f_%03d.png" % (f + 1)))
    print("test frames rendered in %.0fs" % (time.time() - t0), flush=True)
    ok = True
    for view, d in (("side", SIDE_DIR), ("top", TOP_DIR)):
        diff = pix_diff(os.path.join(d, "f_001.png"), os.path.join(d, "f_025.png"))
        print("%s frame1-vs-frame25 mean abs diff = %.2f" % (view, diff), flush=True)
        if diff < 0.5:
            ok = False
    if not ok:
        print("TEST FAILED: frames nearly identical, stop", flush=True)
        sys.exit(1)
    print("TEST PASS", flush=True)


def mode_all(X, conn, U, raw=False):
    lim = compute_limits(X, U)
    side_dir = SIDE_RAW_DIR if raw else SIDE_DIR
    top_dir = TOP_RAW_DIR if raw else TOP_DIR
    os.makedirs(side_dir, exist_ok=True)
    os.makedirs(top_dir, exist_ok=True)
    t0 = time.time()
    for f in range(U.shape[0]):
        render_frame(f, X, conn, U, lim, "side", os.path.join(side_dir, "f_%03d.png" % (f + 1)), raw=raw)
        render_frame(f, X, conn, U, lim, "top", os.path.join(top_dir, "f_%03d.png" % (f + 1)), raw=raw)
        if (f + 1) % 10 == 0:
            print("rendered %d/%d both views (%.0fs elapsed)" % (f + 1, U.shape[0],
                                                                 time.time() - t0), flush=True)
    print("ALL FRAMES DONE in %.0fs" % (time.time() - t0), flush=True)


def mode_compose(raw=False):
    import imageio
    for view, out_name in (("side", "cooling_tower_collapse_raw.mp4" if raw else "cooling_tower_collapse.mp4"),
                           ("top", "cooling_tower_collapse_top_raw.mp4" if raw else "cooling_tower_collapse_top.mp4")):
        src = (SIDE_RAW_DIR if raw else SIDE_DIR) if view == "side" else \
            (TOP_RAW_DIR if raw else TOP_DIR)
        pngs = sorted(glob.glob(os.path.join(src, "f_*.png")))
        if len(pngs) != N_FRAMES:
            print("compose %s: expected %d frames, got %d, stop" % (view, N_FRAMES, len(pngs)),
                  flush=True)
            sys.exit(1)
        out = os.path.join(RESOURCE_DIR, out_name)
        if os.path.exists(out):
            os.remove(out)
        t0 = time.time()
        with imageio.get_writer(out, fps=FPS, codec="libx264",
                                pixelformat="yuv420p", quality=8) as w:
            for fp in pngs:
                w.append_data(imageio.v3.imread(fp))
        print("compose %s -> %s (%.0fs, %d bytes)" % (view, out, time.time() - t0,
                                                      os.path.getsize(out)), flush=True)
    if not raw:
        for view in ("side", "top"):
            src = SIDE_DIR if view == "side" else TOP_DIR
            dst = os.path.join(RESOURCE_DIR, "frames", view)
            os.makedirs(dst, exist_ok=True)
            for f in os.listdir(dst):
                p = os.path.join(dst, f)
                if os.path.isfile(p):
                    os.remove(p)
            for fp in sorted(glob.glob(os.path.join(src, "f_*.png"))):
                shutil.copy(fp, os.path.join(dst, os.path.basename(fp)))
            print("deployed %d frames to %s" % (len(os.listdir(dst)), dst), flush=True)
    print("COMPOSE DONE", flush=True)


def mode_verify():
    import imageio
    for view, out_name in (("side", "cooling_tower_collapse.mp4"),
                           ("top", "cooling_tower_collapse_top.mp4"),
                           ("side", "cooling_tower_collapse_raw.mp4"),
                           ("top", "cooling_tower_collapse_top_raw.mp4")):
        path = os.path.join(RESOURCE_DIR, out_name)
        if not os.path.exists(path):
            print("%s %s: missing, skip" % (view, out_name), flush=True)
            continue
        r = imageio.get_reader(path)
        fr = np.stack([r.get_data(i) for i in range(r.count_frames())])
        n = fr.shape[0]
        j = min(24, n - 1)
        d01 = float(np.abs(fr[0].astype(np.int32) - fr[j].astype(np.int32)).mean())
        d12 = float(np.abs(fr[j].astype(np.int32) - fr[n - 1].astype(np.int32)).mean())
        d02 = float(np.abs(fr[0].astype(np.int32) - fr[n - 1].astype(np.int32)).mean())
        print("%s %s: frames=%d bytes=%d diffs 1-mid=%.2f mid-last=%.2f 1-last=%.2f" % (
            view, out_name, n, os.path.getsize(path), d01, d12, d02), flush=True)
        Image.fromarray(fr[n - 1]).save(os.path.join(FRAME_DIR,
                                                     "_verify_final%s.png" % (
                                                         "" if view == "side" else "_top")))
        print("saved last frame -> %s" % os.path.join(FRAME_DIR,
                                                      "_verify_final%s.png" % (
                                                          "" if view == "side" else "_top")),
              flush=True)
    print("VERIFY DONE", flush=True)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    print("MODE=%s" % mode, flush=True)
    if mode == "test":
        ensure_data()
        X, conn, t, U = load_data()
        print("data: X=%s conn=%s t=%s U=%s t[0]=%.3f t[-1]=%.3f" % (
            X.shape, conn.shape, t.shape, U.shape, float(t[0]), float(t[-1])), flush=True)
        mode_test(X, conn, U)
    elif mode == "all":
        ensure_data()
        X, conn, t, U = load_data()
        mode_all(X, conn, U)
    elif mode == "all-raw":
        ensure_data()
        X, conn, t, U = load_data()
        mode_all(X, conn, U, raw=True)
    elif mode == "compose":
        mode_compose()
    elif mode == "compose-raw":
        mode_compose(raw=True)
    elif mode == "verify":
        mode_verify()
    else:
        print("unknown mode %s" % mode, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
