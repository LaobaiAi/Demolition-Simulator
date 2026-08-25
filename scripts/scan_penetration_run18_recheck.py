"""Abaqus kernel noGUI: exhaustive penetration recheck of run 18 stack ODB.

Previous scan (scan_penetration_run18.py) only covered the STACK instance and
its per-frame min y was dominated by the ENCASTRE base ring (28 nodes pinned at
y=0), so "ymin=0.000" at every frame was near-meaningless. This script:

1. Enumerates all steps, frames, instances and per-instance node counts.
2. For EVERY instance and EVERY frame, scans ALL nodes (no subset filtering):
   min y (all nodes), min y (moving nodes only, |U|>1e-9 -> excludes the pinned
   ring), counts of nodes below 0 / below -0.05, deepest node identity + xyz.
3. Records any node with y < -0.05: absolute time, instance, node label, xyz.
4. Reports undeformed coordinate ranges of every instance: ground top y
   (GROUND-1 max y) and tower base elevation (STACK-1 min y).
5. Cross-checks U field value count vs node count per frame per instance
   (catches missing nodes / wrong field output).

Run from repo root:
  python scripts/run_with_wake.py "D:\\Program Files\\SIMULIA\\Commands\\abq2026.bat" \
      cae noGUI=D:\\GitHub Dev\\Demolition-Simulator\\scripts\\scan_penetration_run18_recheck.py
"""

import os

from odbAccess import openOdb

ODB_PATH = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\concrete_stack_run18\results\stack_job_run.odb"
OUT_PATH = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\concrete_stack_run18\results\penetration_scan_run18_recheck.txt"

GROUND_HALF = 260.0          # run 18 ground slab x,z in [-260, 260]
THRESH = -0.05               # y below this counts as penetration evidence
MOVING_EPS = 1e-9            # |U| <= this => pinned (ENCASTRE) node
DETAIL_CAP = 20              # max below-threshold nodes recorded per frame


def in_footprint(x, z):
    return -GROUND_HALF <= x <= GROUND_HALF and -GROUND_HALF <= z <= GROUND_HALF


def main():
    lines = []

    def log(msg):
        lines.append(str(msg))
        print(msg, flush=True)

    odb = openOdb(ODB_PATH, readOnly=True)

    log("odb=%s" % ODB_PATH)
    log("steps=%s" % list(odb.steps.keys()))
    for sname, step in odb.steps.items():
        log("  step %s: frames=%d timePeriod=%s" % (sname, len(step.frames), step.timePeriod))

    log("instances=%s" % list(odb.rootAssembly.instances.keys()))
    insts = {}
    for i in odb.rootAssembly.instances.values():
        xs = [c for c in (nd.coordinates for nd in i.nodes)]
        xmin = min(c[0] for c in xs)
        xmax = max(c[0] for c in xs)
        ymin = min(c[1] for c in xs)
        ymax = max(c[1] for c in xs)
        zmin = min(c[2] for c in xs)
        zmax = max(c[2] for c in xs)
        insts[i.name] = i
        log("  inst %s: nodes=%d elems=%d undeformed x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f]" % (
            i.name, len(i.nodes), len(i.elements), xmin, xmax, ymin, ymax, zmin, zmax))
        if "GROUND" in i.name.upper():
            log("  -> GROUND top y = %.3f, bottom y = %.3f (slab thickness %.3f)" % (
                ymax, ymin, ymax - ymin))
        if "STACK" in i.name.upper():
            log("  -> STACK base elevation (undeformed min y) = %.3f" % ymin)

    # absolute time per (step, frame)
    abs_t = {}
    start = 0.0
    for sname, step in odb.steps.items():
        for fidx, fr in enumerate(step.frames):
            abs_t[(sname, fidx)] = start + fr.frameValue
        start += step.timePeriod
    n_pairs = len(abs_t)
    n_unique_t = len(set(abs_t.values()))
    log("frame pairs=%d unique times=%d (t=1.0 duplicated: TowerGravity f20 == Collapse f0)" % (
        n_pairs, n_unique_t))

    # per-instance node maps
    node_maps = {}
    for iname, i in insts.items():
        node_maps[iname] = {nd.label: nd for nd in i.nodes}

    worst = {"t": None, "y": 1e30, "info": None}   # non-ground instances only
    below_records = []                              # (t, iname, label, xyz) for y < THRESH

    log("")
    log("--- per-frame per-instance min y (ALL nodes, no subset filter) ---")
    for (sname, fidx), t in sorted(abs_t.items(), key=lambda kv: kv[1]):
        fr = odb.steps[sname].frames[fidx]
        row_min = 1e30
        row_min_info = None
        for iname, i in insts.items():
            is_ground = "GROUND" in iname.upper()
            is_candidate = not is_ground
            Uf = fr.fieldOutputs["U"].getSubset(region=i)
            u = {v.nodeLabel: v.data for v in Uf.values}
            n_missing = len(node_maps[iname]) - len(u)
            ymin_all = 1e30
            lbl_all = None
            xyz_all = None
            u_all = None
            ymin_mov = 1e30
            lbl_mov = None
            n_below0 = 0
            n_belowT = 0
            n_y0 = 0
            details = []
            for lab, nd in node_maps[iname].items():
                c = nd.coordinates
                d = u.get(lab)
                if d is None:
                    d = (0.0, 0.0, 0.0)
                y = c[1] + d[1]
                mag = (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]) ** 0.5
                x = c[0] + d[0]
                z = c[2] + d[2]
                if y < ymin_all:
                    ymin_all = y
                    lbl_all = lab
                    xyz_all = (x, y, z)
                    u_all = mag
                if mag > MOVING_EPS and y < ymin_mov:
                    ymin_mov = y
                    lbl_mov = lab
                if y < 0.0:
                    n_below0 += 1
                if is_candidate and y < THRESH:
                    n_belowT += 1
                    if len(details) < DETAIL_CAP:
                        details.append((lab, x, y, z, mag))
                if abs(y) < 1e-9:
                    n_y0 += 1
            tag = ""
            if lbl_all is not None:
                tag = "inside" if in_footprint(xyz_all[0], xyz_all[2]) else "OUTSIDE-gnd"
            log("step=%-11s f=%2d t=%7.3f inst=%-10s nodes=%5d nU=%5d miss=%d "
                "minY_all=%9.4f lbl=%d xyz=(%.2f,%.4f,%.2f) |U|=%.3f [%s] | "
                "minY_mov=%9.4f lbl=%d | n_y0=%d n_y<0=%d n_y<-0.05=%d" % (
                    sname, fidx, t, iname, len(node_maps[iname]), len(u), n_missing,
                    ymin_all, lbl_all if lbl_all is not None else -1,
                    xyz_all[0] if xyz_all else 0.0, xyz_all[1] if xyz_all else 0.0,
                    xyz_all[2] if xyz_all else 0.0, u_all if u_all is not None else 0.0,
                    tag, ymin_mov if ymin_mov < 1e29 else -1.0,
                    lbl_mov if lbl_mov is not None else -1,
                    n_y0, n_below0, n_belowT))
            if details:
                for lab, x, y, z, mag in details:
                    below_records.append((t, iname, lab, x, y, z, mag))
            if ymin_all < row_min:
                row_min = ymin_all
                row_min_info = (iname, lbl_all)
            if is_candidate and ymin_all < worst["y"]:
                worst = {"t": t, "y": ymin_all, "info": (iname, lbl_all)}

    log("")
    if below_records:
        log("PENETRATION EVIDENCE (y < %.3f): %d records" % (THRESH, len(below_records)))
        for t, iname, lab, x, y, z, mag in below_records:
            log("  t=%7.3f inst=%s node=%d xyz=(%.2f, %.4f, %.2f) |U|=%.3f" % (
                t, iname, lab, x, y, z, mag))
    else:
        log("PENETRATION EVIDENCE: none (no node below y=%.3f at any recorded frame)" % THRESH)

    log("")
    log("WORST (any instance, all frames): y=%.4f at t=%s inst=%s node=%s" % (
        worst["y"], worst["t"], worst["info"][0] if worst["info"] else None,
        worst["info"][1] if worst["info"] else None))
    log("CONCLUSION: run 18 ODB %s penetration at recorded frames" % (
        "HAS" if below_records else "HAS NO"))
    log("RECHECK_DONE")

    odb.close()

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("saved=%s" % OUT_PATH, flush=True)


main()
