"""Kernel noGUI: cooling tower quick metrics probe (one boot, no images).

Copied into each tower quick-analysis run dir by
scripts/tower_quick_analysis.py with ODB/OUT paths substituted. Reads the
solved tower_job_run.odb and writes:
  results/metrics_<run_name>.txt   -- parseable text, host parses this
  results/metrics_<run_name>.json  -- full machine report

Metric caliber == analyze_full_quick.py (r26c_full official), see
dev-notes/abaqus/2026-08-25-cooling-tower-rounds-archive.md:
  hinge        = first frame with OpeningBand concrete deletion >= 5%
  first touch  = first frame with top-ring pct_below_1m > 0 (derived from
                 the top-ring trajectory; the alive-min-y variant is
                 trivially 0 at t=0 because the base ring sits at y=0)
  fold angle   = atan2(top-slice centroid x - hinge-slice centroid x,
                       top-slice centroid y - hinge-slice centroid y);
                 slices are 1-m bands over the tower height, hinge slice = 10
  penetration  = min y over ALL tower nodes at the last frame, gate >= -0.1 m
  direction    = COM azimuth of all tower nodes at the last frame, signed
                 (+X = 0 deg, +Z = +90 deg; acceptance |az| <= 30 deg)
Element/node counts are derived from the ODB label ranges (n_theta
agnostic): conc labels 1..N, outer rebar 1000001.., inner rebar 2000001..
"""

import json
import math
import os

from odbAccess import openOdb

BANDS = [("RootBottom", 0, 5), ("RootUpper", 5, 10), ("OpeningBand", 10, 22),
         ("MidTower", 22, 68.5), ("TopRing", 68.5, 70)]
HINGE_SLICE = 10
N_SLICES = 70
TOP_Y_THRESHOLD = 69.0
NEAR_GROUND = 5.0
ON_GROUND = 1.0
MIN_Z_GATE = -0.1

ODB = r"<placeholder-odb>"
OUT = r"<placeholder-out>"
OUT_JSON = r"<placeholder-out-json>"
RUN_NAME = "<placeholder-run>"

_lines = []


def log(msg):
    _lines.append(str(msg))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_lines) + "\n")


def fmt(v):
    if v is None:
        return "None"
    if isinstance(v, float):
        return "%.2f" % v
    return str(v)


def _shell_of(label):
    return label // 1000000


def _band_of(cy):
    for name, lo, hi in BANDS:
        if lo <= cy < hi:
            return name
    return "TopRing"


def _stats(ys):
    n = len(ys)
    if n == 0:
        return {"count": 0, "max": 0.0, "mean": 0.0,
                "pct_below_5m": 0.0, "pct_below_1m": 0.0}
    return {
        "count": n,
        "max": float(round(max(ys), 3)),
        "mean": float(round(sum(ys) / n, 3)),
        "pct_below_5m": float(round(100.0 * sum(1 for y in ys if y < NEAR_GROUND) / n, 2)),
        "pct_below_1m": float(round(100.0 * sum(1 for y in ys if y < ON_GROUND) / n, 2)),
    }


def main():
    if not os.path.exists(ODB):
        print("ODB NOT FOUND: %s" % ODB, flush=True)
        return 1
    odb = openOdb(ODB, readOnly=True)
    inst = None
    for i in odb.rootAssembly.instances.values():
        if "TOWER" in i.name.upper():
            inst = i
            break
    if inst is None:
        log("ERROR: tower instance not found")
        odb.close()
        return 1

    node_map = {nd.label: nd for nd in inst.nodes}
    n_tower_nodes = len(node_map)
    n_conc_elems = 0
    n_rebar_elems = 0
    centers = {}
    for el in inst.elements:
        if _shell_of(el.label) == 0:
            n_conc_elems += 1
        else:
            n_rebar_elems += 1
        conn = list(el.connectivity)
        centers[el.label] = sum(node_map[l].coordinates[1] for l in conn) / len(conn)

    frames = []
    start = 0.0
    for sname in list(odb.steps.keys()):
        step = odb.steps[sname]
        for fr in step.frames:
            frames.append((start + fr.frameValue, fr))
        start += step.timePeriod
    if not frames:
        log("ERROR: no frames in odb")
        odb.close()
        return 1
    times = [t for t, _fr in frames]
    n_frames = len(frames)
    last_step = list(odb.steps.keys())[-1]

    log("step=%s frames=%d" % (last_step, n_frames))
    log("nodes: tower=%d conc_elems=%d rebar_elems=%d" % (
        n_tower_nodes, n_conc_elems, n_rebar_elems))

    per_frame = []
    per_frame_rebar = []
    ring_per_frame = []
    fold_hist = []
    last_min_z = 0.0
    last_underground = 0
    last_pts = []

    for fi, (t, fr) in enumerate(frames):
        uf = fr.fieldOutputs["U"].getSubset(region=inst)
        u_map = {v.nodeLabel: v.data for v in uf.values}
        sf = fr.fieldOutputs["STATUSMP"].getSubset(region=inst)
        del_el = {}
        for v in sf.values:
            if v.data is None:
                continue
            del_el.setdefault(v.elementLabel, {})[v.sectionPoint.number] = v.data
        ring_ys = []
        slice_pts = [[[], []] for _ in range(N_SLICES)]
        min_z = None
        underground = 0
        for node in inst.nodes:
            c = node.coordinates
            d = u_map.get(node.label, (0.0, 0.0, 0.0))
            x = c[0] + d[0]
            y = c[1] + d[1]
            if min_z is None or y < min_z:
                min_z = y
            if y < MIN_Z_GATE:
                underground += 1
            if c[1] > TOP_Y_THRESHOLD:
                ring_ys.append(y)
            s = int(c[1])
            if s >= N_SLICES:
                s = N_SLICES - 1
            slice_pts[s][0].append(x)
            slice_pts[s][1].append(y)

        by_band = {name: [0, 0] for name, _, _ in BANDS}
        by_band_rebar = {name: [0, 0] for name, _, _ in BANDS}
        for label, pts in del_el.items():
            bname = _band_of(centers[label])
            gone = any(d <= 0.0 for d in pts.values())
            if _shell_of(label) == 0:
                by_band[bname][1] += 1
                if gone:
                    by_band[bname][0] += 1
            else:
                by_band_rebar[bname][1] += 1
                if gone:
                    by_band_rebar[bname][0] += 1

        e = {"t": float(round(t, 3))}
        for name, (d, n) in by_band.items():
            e[name + "_pct"] = float(round(100.0 * d / n, 2)) if n else 0.0
        td = sum(v[0] for v in by_band.values())
        tn = sum(v[1] for v in by_band.values())
        e["total_pct"] = float(round(100.0 * td / tn, 2)) if tn else 0.0
        per_frame.append(e)

        re = {"t": float(round(t, 3))}
        for name, (d, n) in by_band_rebar.items():
            re[name + "_pct"] = float(round(100.0 * d / n, 2)) if n else 0.0
        rd = sum(v[0] for v in by_band_rebar.values())
        rn = sum(v[1] for v in by_band_rebar.values())
        re["total_pct"] = float(round(100.0 * rd / rn, 2)) if rn else 0.0
        per_frame_rebar.append(re)

        ring_per_frame.append({"t": float(round(t, 3)), "stats": _stats(ring_ys)})

        cxs = []
        cys = []
        for k in range(N_SLICES):
            xs, ys = slice_pts[k]
            cxs.append(sum(xs) / len(xs) if xs else None)
            cys.append(sum(ys) / len(ys) if ys else None)
        hx, hy = cxs[HINGE_SLICE], cys[HINGE_SLICE]
        tx, ty = cxs[N_SLICES - 1], cys[N_SLICES - 1]
        if hx is not None and tx is not None and abs(ty - hy) > 1e-9:
            ang = math.degrees(math.atan2(tx - hx, ty - hy))
        else:
            ang = None
        fold_hist.append(ang)

        last_min_z = min_z if min_z is not None else 0.0
        last_underground = underground
        if fi == n_frames - 1:
            for node in inst.nodes:
                c = node.coordinates
                d = u_map.get(node.label, (0.0, 0.0, 0.0))
                last_pts.append((c[0] + d[0], c[1] + d[1], c[2] + d[2]))
        if fi % 10 == 0:
            print("probe frame %d/%d t=%.1f min_z=%.3f" % (
                fi + 1, n_frames, t, last_min_z), flush=True)

    hinge = {"first_ge_5pct": None, "max_jump_t": None, "max_jump_pct": 0.0}
    prev = 0.0
    for e in per_frame:
        if hinge["first_ge_5pct"] is None and e["OpeningBand_pct"] >= 5.0:
            hinge["first_ge_5pct"] = e["t"]
        jump = e["OpeningBand_pct"] - prev
        if jump > hinge["max_jump_pct"]:
            hinge["max_jump_pct"] = jump
            hinge["max_jump_t"] = e["t"]
        prev = e["OpeningBand_pct"]

    first_touch_t = None
    for r in ring_per_frame:
        if r["stats"]["pct_below_1m"] > 0.0:
            first_touch_t = r["t"]
            break

    pre_touch = None
    if first_touch_t is not None:
        t_pre = max(first_touch_t - 1.0, times[0])
        i_pre = min(range(len(times)), key=lambda i: abs(times[i] - t_pre))
        pre_touch = {
            "t": float(times[i_pre]),
            "fold_angle_deg": fold_hist[i_pre],
            "top_ring_mean_m": ring_per_frame[i_pre]["stats"]["mean"],
            "top_ring_max_m": ring_per_frame[i_pre]["stats"]["max"],
            "conc_total_deleted_pct": per_frame[i_pre]["total_pct"],
            "rebar_total_deleted_pct": per_frame_rebar[i_pre]["total_pct"],
            "opening_band_pct": per_frame[i_pre]["OpeningBand_pct"],
            "mid_tower_pct": per_frame[i_pre]["MidTower_pct"],
        }

    r = [math.hypot(p[0], p[2]) for p in last_pts]
    r_max = max(r)
    i_max = r.index(r_max)
    p95 = sorted(r)[int(0.95 * (len(r) - 1))]
    mx = sum(p[0] for p in last_pts) / len(last_pts)
    mz = sum(p[2] for p in last_pts) / len(last_pts)
    com_az = math.degrees(math.atan2(mz, mx))
    far_az = math.degrees(math.atan2(last_pts[i_max][2], last_pts[i_max][0]))
    final_height = max(p[1] for p in last_pts)

    last_conc = per_frame[-1]
    last_rebar = per_frame_rebar[-1]
    fold_now = fold_hist[-1]
    fold_prev = None
    for i in range(len(times) - 1, -1, -1):
        if times[i] <= times[-1] - 2.0:
            fold_prev = fold_hist[i]
            break

    pen_ok = last_min_z >= MIN_Z_GATE

    log("hinge: first_ge_5pct=%s max_jump_t=%s max_jump_pct=%.2f" % (
        fmt(hinge["first_ge_5pct"]), fmt(hinge["max_jump_t"]),
        hinge["max_jump_pct"]))
    log("first_touch: top_ring_1m=%s" % fmt(first_touch_t))
    log("fold: last=%s 2s_earlier=%s" % (fmt(fold_now), fmt(fold_prev)))
    log("direction: com_azimuth=%.2f far_azimuth=%.2f" % (com_az, far_az))
    log("penetration: min_z=%.3f underground_nodes=%d gate=%s" % (
        last_min_z, last_underground, "OK" if pen_ok else "PENETRATED"))
    if pre_touch is not None:
        log("posture: t=%.1f fold_angle=%s top_ring_mean=%.3f top_ring_max=%.3f "
            "conc_total=%.2f rebar_total=%.2f" % (
                pre_touch["t"], fmt(pre_touch["fold_angle_deg"]),
                pre_touch["top_ring_mean_m"], pre_touch["top_ring_max_m"],
                pre_touch["conc_total_deleted_pct"],
                pre_touch["rebar_total_deleted_pct"]))
    else:
        log("posture: t=None fold_angle=None top_ring_mean=None "
            "top_ring_max=None conc_total=None rebar_total=None")
    names = [n for n, _, _ in BANDS]
    log("band_conc_last: %s total=%.2f" % (
        " ".join("%s=%.2f" % (n, last_conc[n + "_pct"]) for n in names),
        last_conc["total_pct"]))
    log("band_rebar_last: %s total=%.2f" % (
        " ".join("%s=%.2f" % (n, last_rebar[n + "_pct"]) for n in names),
        last_rebar["total_pct"]))
    for i in range(n_frames):
        e = per_frame[i]
        re = per_frame_rebar[i]
        rp = ring_per_frame[i]
        log("per_frame: t=%.1f %s total=%.2f" % (
            e["t"], " ".join("%s=%.2f" % (n, e[n + "_pct"]) for n in names),
            e["total_pct"]))
        log("per_frame_rebar: t=%.1f %s total=%.2f" % (
            re["t"], " ".join("%s=%.2f" % (n, re[n + "_pct"]) for n in names),
            re["total_pct"]))
        log("ring: t=%.1f mean=%.3f max=%.3f pct_below_1m=%.2f pct_below_5m=%.2f" % (
            rp["t"], rp["stats"]["mean"], rp["stats"]["max"],
            rp["stats"]["pct_below_1m"], rp["stats"]["pct_below_5m"]))
        log("fold_hist: t=%.1f angle=%s" % (times[i], fmt(fold_hist[i])))

    report = {
        "run_name": RUN_NAME,
        "odb": ODB,
        "n_frames": n_frames,
        "last_step": last_step,
        "tower": {"nodes": n_tower_nodes, "conc_elems": n_conc_elems,
                  "rebar_elems": n_rebar_elems},
        "hinge": {"first_ge_5pct": hinge["first_ge_5pct"],
                  "max_jump_t": hinge["max_jump_t"],
                  "max_jump_pct": float(round(hinge["max_jump_pct"], 2))},
        "first_touch": {"top_ring_1m": first_touch_t},
        "fold": {"last_deg": fold_now, "2s_earlier_deg": fold_prev},
        "direction": {"com_azimuth_deg": float(round(com_az, 2)),
                      "com_azimuth_abs_deg": float(round(abs(com_az), 2)),
                      "far_azimuth_deg": float(round(far_az, 2))},
        "penetration": {"min_z": float(round(last_min_z, 3)),
                        "underground_nodes": last_underground,
                        "gate_pass": pen_ok},
        "pre_touch_posture": pre_touch,
        "band_deletion_last_frame": {
            "conc": {n + "_pct": last_conc[n + "_pct"] for n in names},
            "rebar": {n + "_pct": last_rebar[n + "_pct"] for n in names},
            "conc_total_pct": last_conc["total_pct"],
            "rebar_total_pct": last_rebar["total_pct"],
        },
        "footprint": {"max_radius_m": float(round(r_max, 3)),
                      "p95_radius_m": float(round(p95, 3)),
                      "final_height_m": float(round(final_height, 3)),
                      "direction_deg_far_0_360": float(round((far_az + 360.0) % 360.0, 2))},
        "per_frame": per_frame,
        "per_frame_rebar": per_frame_rebar,
        "top_ring_trajectory": [
            {"t": rp["t"], "mean": rp["stats"]["mean"], "max": rp["stats"]["max"],
             "pct_below_1m": rp["stats"]["pct_below_1m"],
             "pct_below_5m": rp["stats"]["pct_below_5m"]}
            for rp in ring_per_frame],
        "fold_angle_hist": [float(round(a, 2)) if a is not None else None
                            for a in fold_hist],
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    log("METRICS_DONE")
    odb.close()
    print("saved=%s" % OUT, flush=True)
    print("saved=%s" % OUT_JSON, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
