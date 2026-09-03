"""Local (no-deploy) render variant for the 90m cooling tower runs.

Patches render_tower_frames constants for the 90m tower and redirects all
outputs to abaqus_projects/cooling_tower_90m/<run>/frames + <run>/videos.
The frontend resource dir is never touched.

Usage:
  gateway/venv/Scripts/python.exe scripts/render_tower_frames_local.py <run> all|compose|verify
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_tower_frames as R

RUN = sys.argv[1] if len(sys.argv) > 1 else "run28"
mode = sys.argv[2] if len(sys.argv) > 2 else "all"

BASE = os.path.join(R.PROJECT_DIR, "abaqus_projects", "cooling_tower_90m", RUN)
FRAME_DIR = os.path.join(BASE, "frames")
RESOURCE_DIR = os.path.join(BASE, "videos")

R.GROUND_R = 58.0
R.TOP_RING_R = 35.876
R.U_MIN, R.U_MAX = 0.0, 100.0
R.FRAME_DIR = FRAME_DIR
R.DATA_PATH = os.path.join(FRAME_DIR, "data.npz")
R.SIDE_DIR = os.path.join(FRAME_DIR, "side")
R.TOP_DIR = os.path.join(FRAME_DIR, "top")
R.SIDE_RAW_DIR = os.path.join(FRAME_DIR, "side_raw")
R.TOP_RAW_DIR = os.path.join(FRAME_DIR, "top_raw")
R.RESOURCE_DIR = RESOURCE_DIR
os.makedirs(FRAME_DIR, exist_ok=True)
os.makedirs(RESOURCE_DIR, exist_ok=True)

print("run=%s mode=%s frame_dir=%s videos=%s" % (RUN, mode, FRAME_DIR, RESOURCE_DIR),
      flush=True)

X, conn, t, U = R.load_data()
print("data: X=%s conn=%s t=%s U=%s t[0]=%.3f t[-1]=%.3f" % (
    X.shape, conn.shape, t.shape, U.shape, float(t[0]), float(t[-1])), flush=True)
if mode == "all":
    R.mode_all(X, conn, U)
elif mode == "compose":
    R.mode_compose()
elif mode == "verify":
    R.mode_verify()
else:
    print("unknown mode %s" % mode, flush=True)
    sys.exit(1)
