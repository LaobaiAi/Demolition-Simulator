"""Host-side fit comparison: a 90m run vs the instance-library 70m baseline (run 10 v3).

Top-ring trajectory computed for BOTH models from their data.npz (instance npz in
scripts/_tower_frames, run npz in abaqus_projects/cooling_tower_90m/<run>/frames)
with identical thresholds relative to each tower height. Deletion/footprint taken
from the run's analyze_report.json + cooling_tower_footprint.json, final metrics
vs frontend/public/resource/Abaqus/cooling_tower_footprint.json.

Usage:
  gateway/venv/Scripts/python.exe scripts/compare_90m_to_instance.py <run>
"""

import json
import os
import sys

import numpy as np

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = sys.argv[1] if len(sys.argv) > 1 else "run28"
BASE = os.path.join(PROJECT_DIR, "abaqus_projects", "cooling_tower_90m")
INST_NPZ = os.path.join(PROJECT_DIR, "scripts", "_tower_frames", "data.npz")
RUN_NPZ = os.path.join(BASE, RUN, "frames", "data.npz")
INST_FOOT = os.path.join(PROJECT_DIR, "frontend", "public", "resource", "Abaqus",
                         "cooling_tower_footprint.json")


def top_trajectory(npz_path):
    d = np.load(npz_path)
    X, t, U = d["X"], d["t"], d["U"]
    H = X[:, 1].max()
    top = X[:, 1] > 0.98 * H
    rows = []
    for f in range(U.shape[0]):
        y = X[top, 1] + U[f][top, 1]
        rows.append((float(t[f]), float(y.mean())))
    return H, rows


def interp(rows, t):
    prev = None
    for ft, vy in rows:
        if ft >= t:
            if prev is None:
                return vy
            f0, v0 = prev
            return v0 + (vy - v0) * (t - f0) / (ft - f0)
        prev = (ft, vy)
    return rows[-1][1]


iH, irows = top_trajectory(INST_NPZ)
aH, arows = top_trajectory(RUN_NPZ)
ana = json.load(open(os.path.join(BASE, RUN, "analyze_report.json"), encoding="utf-8"))
fp = json.load(open(os.path.join(BASE, RUN, "cooling_tower_footprint.json"), encoding="utf-8"))
ifp = json.load(open(INST_FOOT, encoding="utf-8"))
aframes = ana["per_frame"]

print("=== %s vs instance (70m run10 v3) ===" % RUN)
print("instance: H=%.1f | %s: H=%.1f  (%d frames)" % (iH, RUN, aH, len(arows)))

print("\n-- top-ring mean, relative %% of height --")
print("%5s  %8s  %8s" % ("t", "inst", RUN))
for t in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 7.5, 8.0):
    print("%5.1f  %7.0f%%  %7.0f%%" % (
        t, 100.0 * interp(irows, t) / iH, 100.0 * interp(arows, t) / aH))

print("\n-- deletion total %% --")
print("%5s  %10s" % ("t", RUN))
for t in (3.0, 4.0, 5.0, 6.0, 7.0, 8.0):
    ta = next((f for f in aframes if abs(f["t"] - t) < 0.4), None)
    print("%5.1f  %9.1f%%" % (t, ta["total_pct"] if ta else -1.0))

print("\n-- final footprint --")
print("  %-16s %-22s %s" % ("metric", "instance(json)", RUN))
for k in ("max_radius_m", "p95_radius_m", "ratio_max", "ratio_p95",
          "direction_deg", "final_height_m"):
    iv = ifp.get(k, 0.0)
    rv = fp.get(k, 0.0)
    print("  %-16s %-22s %s" % (k, "%.3f" % iv if isinstance(iv, (int, float)) else iv,
                                "%.3f" % rv if isinstance(rv, (int, float)) else rv))
print("  tower_base_radius_m  %-22s %s" % ("28.5", fp["tower_base_radius_m"]))

print("\n-- dynamics (run) --")
print("  hinge first_ge_5pct:   %s" % ana["hinge"]["first_ge_5pct"])
print("  slow_tilt drop_1m_at:  %s (init ring mean %.1fm)" % (
    ana["slow_tilt"]["drop_1m_at_t"], ana["slow_tilt"]["init_mean_m"]))
print("  first_touch_top_1m:    %s" % ana["first_touch_top_ring_1m"])
print("  fold_angle_last_deg:   %s" % ana["fold_angle_last_deg"])
print("  top_ring_last_frame:   mean %.1fm max %.1fm (%.0f%% of H)" % (
    ana["top_ring_last_frame"]["mean"], ana["top_ring_last_frame"]["max"],
    100.0 * ana["top_ring_last_frame"]["mean"] / aH))
print("  survivors_by_band:     %s" % ana["survivors_by_band"])

print("\n-- fit verdict (6.6 criteria) --")
d = fp["com_direction_deg"]
print("  COM direction %.1f deg in +X±15 (inst %.2f; max-disp-node %.1f may be fragment artifact): %s" % (
    d, ifp["direction_deg"], fp["direction_deg"], "PASS" if d <= 15.0 or d >= 345.0 else "FAIL"))
ratio = fp["ratio_max"]
print("  ratio_max %.3f <= 1.2 (inst %.3f): %s" % (
    ratio, ifp["ratio_max"], "PASS" if ratio <= 1.2 else "FAIL"))
tot = aframes[-1]["total_pct"]
print("  total deletion %.1f%% in 35-55%%: %s" % (tot, "PASS" if 35.0 <= tot <= 55.0 else "WATCH"))
b = aframes[-1]
loc = b["Opening_pct"] >= b["Mid_pct"] >= b["TopRing_pct"]
print("  localization Opening>=Mid>=TopRing (%.0f/%.0f/%.0f): %s" % (
    b["Opening_pct"], b["Mid_pct"], b["TopRing_pct"], "PASS" if loc else "FAIL"))
top_rel = 100.0 * ana["top_ring_last_frame"]["mean"] / aH
print("  top ring last mean %.0f%% of H in 45-60%%: %s" % (
    top_rel, "PASS" if 45.0 <= top_rel <= 60.0 else "CHECK"))
