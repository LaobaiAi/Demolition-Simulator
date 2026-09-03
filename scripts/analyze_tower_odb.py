"""Abaqus kernel noGUI: per-frame collapse metrics for the base 90m tower ODB.

Model layout (base run_tower_collapse.py host INP): single tower node block
1..12288 (96 stations x 128), S4R composite shell 7 section points per element
(0.07 C30 x3pt / 0.0005 rebar x1pt / 0.07 C30 x3pt), tower elements 1..12160,
Ground C3D8R 1..1296. Opening surgery removes 204 elements; Abaqus cleans 165
isolated nodes.

Metrics per frame: top-ring trajectory (station y>88.5), per-band concrete
deletion % (any section point STATUSMP<=0), total deletion %, max displacement,
footprint max/p95 radius of displaced nodes, COM. Plus: slow-tilt (top-ring
drop 1m), hinge (OpeningBand first >=5%), first touch (top ring pct<1m >0),
rebound, final footprint, fold angle (slice 10 vs top).

Run: abq2026.bat cae noGUI=analyze_tower_odb.py
"""

import json
import math
import os
import sys

from odbAccess import openOdb

ODB_PATH = r"C:\Users\99005\AppData\Local\Temp\tower_collapse_ijlll326\tower_job_run.odb"
OUT_PATH = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\cooling_tower_90m\run31\analyze_report.json"

HEIGHT = 90.0
BASE_RADIUS = 35.876
TOP_RING_Y0 = 88.5
NEAR_GROUND = 5.0
ON_GROUND = 1.0
FIRST_TOUCH_Y = 0.05
BANDS = [("RootBottom", 0.0, 5.0),
         ("RootUpper", 5.0, 10.0),
         ("Opening", 10.0, 22.0),
         ("Mid", 22.0, TOP_RING_Y0),
         ("TopRing", TOP_RING_Y0, HEIGHT)]
HINGE_SLICE = 10
N_SLICES = 90
N_STATIONS = 96
N_THETA = 128
N_NODES = N_STATIONS * N_THETA

_ARGS = {}
for _a in sys.argv[1:]:
    _k, _, _v = _a.partition("=")
    _ARGS[_k.strip("-")] = _v
if "odb" in _ARGS:
    ODB_PATH = _ARGS["odb"]
if "out" in _ARGS:
    OUT_PATH = _ARGS["out"]
if "height" in _ARGS:
    HEIGHT = float(_ARGS["height"])
if "base" in _ARGS:
    BASE_RADIUS = float(_ARGS["base"])
if "top" in _ARGS:
    TOP_RING_Y0 = float(_ARGS["top"])
if "n_theta" in _ARGS:
    N_THETA = int(_ARGS["n_theta"])
N_NODES = N_STATIONS * N_THETA
BANDS = [("RootBottom", 0.0, 5.0),
         ("RootUpper", 5.0, 10.0),
         ("Opening", 10.0, 22.0),
         ("Mid", 22.0, TOP_RING_Y0),
         ("TopRing", TOP_RING_Y0, HEIGHT)]


def _tower(odb):
    for inst in odb.rootAssembly.instances.values():
        if "TOWER" in inst.name.upper():
            return inst
    raise RuntimeError("tower instance not found")


def _stats(ys):
    n = len(ys)
    if n == 0:
        return {"count": 0, "max": 0.0, "mean": 0.0, "p50": 0.0, "p95": 0.0,
                "pct_below_5m": 0.0, "pct_below_1m": 0.0}
    s = sorted(ys)
    return {
        "count": n,
        "max": float(round(s[-1], 3)),
        "mean": float(round(sum(ys) / n, 3)),
        "p50": float(round(s[n // 2], 3)),
        "p95": float(round(s[int(0.95 * (n - 1))], 3)),
        "pct_below_5m": float(round(100.0 * sum([1 for y in ys if y < NEAR_GROUND]) / n, 2)),
        "pct_below_1m": float(round(100.0 * sum([1 for y in ys if y < ON_GROUND]) / n, 2)),
    }


def _slice_of(y):
    s = int(y)
    return N_SLICES - 1 if s >= N_SLICES else s


def _band_of(cy):
    for name, lo, hi in BANDS:
        if lo <= cy < hi:
            return name
    return "TopRing"


def main():
    if not os.path.exists(ODB_PATH):
        print("ODB NOT FOUND: %s" % ODB_PATH, flush=True)
        return 1
    odb = openOdb(ODB_PATH, readOnly=True)
    inst = _tower(odb)
    node_map = {nd.label: nd for nd in inst.nodes}
    centers = {}
    for el in inst.elements:
        ys = [node_map[l].coordinates[1] for l in el.connectivity]
        centers[el.label] = sum(ys) / len(ys)
    band_totals = {name: 0 for name, _, _ in BANDS}
    for el in inst.elements:
        band_totals[_band_of(centers[el.label])] += 1

    all_frames = []
    raw_times = []
    start = 0.0
    for sname in odb.steps.keys():
        step = odb.steps[sname]
        for fr in step.frames:
            all_frames.append(fr)
            raw_times.append(start + fr.frameValue)
        start += step.timePeriod
    keep = {}
    for i, t in enumerate(raw_times):
        keep[t] = i
    times = sorted(keep.keys())
    frame_index = [keep[t] for t in times]
    abs_times = [raw_times[k] for k in frame_index]

    per_frame = []
    ring_per_frame = []
    fold_hist = []
    last_all_ys = None
    last_u_map = None
    last_status = None
    init_coords = {int(nd.label): [float(v) for v in nd.coordinates] for nd in inst.nodes}

    for fi, i in enumerate(frame_index):
        fr = all_frames[i]
        abs_t = abs_times[fi]
        uf = fr.fieldOutputs["U"].getSubset(region=inst)
        u_map = {v.nodeLabel: v.data for v in uf.values}
        ring_ys = []
        all_ys = []
        slice_pts = [[[], []] for _ in range(N_SLICES)]
        max_disp = 0.0
        pts_last = []
        for node in inst.nodes:
            if node.label > N_NODES:
                continue
            c = node.coordinates
            d = u_map.get(node.label, (0.0, 0.0, 0.0))
            x = c[0] + d[0]
            y = c[1] + d[1]
            z = c[2] + d[2]
            all_ys.append(y)
            pts_last.append((x, y, z))
            if c[1] > TOP_RING_Y0:
                ring_ys.append(y)
            sl = _slice_of(c[1])
            slice_pts[sl][0].append(x)
            slice_pts[sl][1].append(y)
            dd = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)
            if dd > max_disp:
                max_disp = dd
        ring_per_frame.append({
            "t": float(round(abs_t, 3)),
            "stats": _stats(ring_ys),
        })
        last_all_ys = all_ys
        last_u_map = u_map

        r = [math.hypot(p[0], p[2]) for p in pts_last]
        r_max = max(r)
        p95 = sorted(r)[int(0.95 * (len(r) - 1))]
        mx = sum([p[0] for p in pts_last]) / len(pts_last)
        mz = sum([p[2] for p in pts_last]) / len(pts_last)

        sf = fr.fieldOutputs["STATUSMP"].getSubset(region=inst)
        del_el = {}
        for v in sf.values:
            del_el.setdefault(v.elementLabel, {})[v.sectionPoint.number] = v.data
        by_band = {name: [0, 0] for name in band_totals}
        for label, pts in del_el.items():
            bname = _band_of(centers[label])
            by_band[bname][1] += 1
            if any(d is not None and d <= 0.0 for d in pts.values()):
                by_band[bname][0] += 1
        tot_del = sum([v[0] for v in by_band.values()])
        tot_n = sum([v[1] for v in by_band.values()])
        entry = {"t": float(round(abs_t, 3)), "max_disp_m": float(round(max_disp, 3)),
                 "footprint_max_m": float(round(r_max, 3)),
                 "footprint_p95_m": float(round(p95, 3)),
                 "com_radius_m": float(round(math.hypot(mx, mz), 3))}
        for name, (d, n) in by_band.items():
            entry[name + "_pct"] = float(round(100.0 * d / n, 2)) if n else 0.0
        entry["total_pct"] = float(round(100.0 * tot_del / tot_n, 2)) if tot_n else 0.0
        per_frame.append(entry)

        cxs, cys = [], []
        for k in range(N_SLICES):
            xs, ys = slice_pts[k]
            if xs:
                cxs.append(sum(xs) / len(xs))
                cys.append(sum(ys) / len(ys))
            else:
                cxs.append(None)
                cys.append(None)
        hx, hy = cxs[HINGE_SLICE], cys[HINGE_SLICE]
        tx, ty = cxs[N_SLICES - 1], cys[N_SLICES - 1]
        if hx is not None and tx is not None and (ty - hy) != 0.0:
            ang = math.degrees(math.atan2(tx - hx, ty - hy))
        else:
            ang = None
        fold_hist.append(ang)

        if fi == len(frame_index) - 1:
            last_status = sf

    all_stats = _stats(last_all_ys)

    hinge = {"first_ge_5pct": None, "max_jump_t": None, "max_jump_pct": 0.0}
    prev = 0.0
    for e in per_frame:
        if hinge["first_ge_5pct"] is None and e["Opening_pct"] >= 5.0:
            hinge["first_ge_5pct"] = e["t"]
        jump = e["Opening_pct"] - prev
        if jump > hinge["max_jump_pct"]:
            hinge["max_jump_pct"] = float(round(jump, 2))
            hinge["max_jump_t"] = e["t"]
        prev = e["Opening_pct"]
    hinge["first_ge_5pct"] = (float(hinge["first_ge_5pct"])
                              if hinge["first_ge_5pct"] is not None else None)

    first_touch = None
    for entry in ring_per_frame:
        if entry["stats"]["pct_below_1m"] > 0.0:
            first_touch = entry["t"]
            break
    if first_touch is not None:
        first_touch = float(first_touch)

    init_mean = ring_per_frame[0]["stats"]["mean"]
    slow_tilt = {"init_mean_m": float(round(init_mean, 3)), "drop_1m_at_t": None}
    for entry in ring_per_frame:
        if slow_tilt["drop_1m_at_t"] is None and \
                entry["stats"]["mean"] <= init_mean - 1.0:
            slow_tilt["drop_1m_at_t"] = entry["t"]
    if slow_tilt["drop_1m_at_t"] is not None:
        slow_tilt["drop_1m_at_t"] = float(slow_tilt["drop_1m_at_t"])

    min_mean = min([e["stats"]["mean"] for e in ring_per_frame])
    t_min = next(e["t"] for e in ring_per_frame if e["stats"]["mean"] == min_mean)
    last_mean = ring_per_frame[-1]["stats"]["mean"]
    rebound = {"min_mean_m": float(round(min_mean, 3)),
               "t_at_min_mean": float(round(t_min, 3)),
               "last_mean_m": float(round(last_mean, 3)),
               "rise_after_min_m": float(round(last_mean - min_mean, 3))}

    by_el = {}
    for v in last_status.values:
        by_el.setdefault(v.elementLabel, {})[v.sectionPoint.number] = v.data
    alive_labels = set()
    for el, pts in by_el.items():
        if all(d is not None and d > 0.0 for d in pts.values()):
            alive_labels.add(el)
    survivors_by_band = {}
    for name, lo, hi in BANDS:
        survivors_by_band[name] = sum(
            [1 for el in alive_labels if lo <= centers[el] < hi])
    alive_node_labels = set()
    for elem in inst.elements:
        if elem.label in alive_labels:
            alive_node_labels.update(elem.connectivity)
    surv_ys = []
    for node in inst.nodes:
        if node.label <= N_NODES and node.label in alive_node_labels:
            d = last_u_map.get(node.label, (0.0, 0.0, 0.0))
            surv_ys.append(node.coordinates[1] + d[1])

    first_frame = odb.steps[list(odb.steps.keys())[0]].frames[0]
    u0 = {v.nodeLabel: v.data for v in
          first_frame.fieldOutputs["U"].getSubset(region=inst).values}
    init_pts = []
    last_pts = []
    for node in inst.nodes:
        if node.label > N_NODES:
            continue
        c = node.coordinates
        d0 = u0.get(node.label, (0.0, 0.0, 0.0))
        d1 = last_u_map.get(node.label, (0.0, 0.0, 0.0))
        init_pts.append((c[0] + d0[0], c[1] + d0[1], c[2] + d0[2]))
        last_pts.append((c[0] + d1[0], c[1] + d1[1], c[2] + d1[2]))
    r0 = [math.hypot(x, z) for x, y, z in init_pts]
    r = [math.hypot(x, z) for x, y, z in last_pts]
    r_max = max(r)
    i_max = r.index(r_max)
    p95 = sorted(r)[int(0.95 * (len(r) - 1))]
    mx = sum([p[0] for p in last_pts]) / len(last_pts)
    mz = sum([p[2] for p in last_pts]) / len(last_pts)
    az_max = (math.degrees(math.atan2(last_pts[i_max][2], last_pts[i_max][0])) + 360.0) % 360.0
    footprint = {
        "tower_nodes": len(r),
        "max_radius_m": float(round(r_max, 3)),
        "p95_radius_m": float(round(p95, 3)),
        "direction_deg": float(round(az_max, 2)),
        "com_radius_m": float(round(math.hypot(mx, mz), 3)),
        "com_direction_deg": float(round((math.degrees(math.atan2(mz, mx)) + 360.0) % 360.0, 2)),
        "tower_base_radius_m": float(round(max(r0), 3)),
        "init_height_m": float(round(max([p[1] for p in init_pts]), 3)),
        "final_height_m": float(round(max([p[1] for p in last_pts]), 3)),
        "ratio_max": float(round(r_max / max(r0), 3)),
        "ratio_p95": float(round(p95 / max(r0), 3)),
    }

    report = {
        "odb": ODB_PATH,
        "last_step": list(odb.steps.keys())[-1],
        "last_frame_time_s": per_frame[-1]["t"],
        "deletion_method": "any_of_section_points",
        "bands_total_elems": band_totals,
        "per_frame": per_frame,
        "hinge": hinge,
        "first_touch_top_ring_1m": first_touch,
        "slow_tilt": slow_tilt,
        "rebound": rebound,
        "top_ring_last_frame": ring_per_frame[-1]["stats"],
        "all_tower_nodes_last_frame": all_stats,
        "survivors_by_band": survivors_by_band,
        "surviving_nodes": len(surv_ys),
        "survivor_y_stats": _stats(surv_ys),
        "footprint": footprint,
        "fold_angle_last_deg": (float(round(fold_hist[-1], 2))
                                if fold_hist[-1] is not None else None),
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("saved=%s" % OUT_PATH, flush=True)
    print("frames=%d last_t=%.2f" % (len(per_frame), per_frame[-1]["t"]), flush=True)
    for e in per_frame:
        print("t=%.2f maxd=%.1f fp_max=%.1f fp_p95=%.1f del=%.1f%% "
              "Rbot=%.1f%% Rup=%.1f%% Open=%.1f%% Mid=%.1f%% Top=%.1f%%" % (
                  e["t"], e["max_disp_m"], e["footprint_max_m"], e["footprint_p95_m"],
                  e["total_pct"], e["RootBottom_pct"], e["RootUpper_pct"],
                  e["Opening_pct"], e["Mid_pct"], e["TopRing_pct"]), flush=True)
    print("hinge=%s first_touch=%s slow_tilt=%s rebound=%s" % (
        hinge, first_touch, slow_tilt, rebound), flush=True)
    print("footprint: %s" % footprint, flush=True)
    print("fold_angle_last=%s survivors_by_band=%s" % (
        report["fold_angle_last_deg"], survivors_by_band), flush=True)
    odb.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
