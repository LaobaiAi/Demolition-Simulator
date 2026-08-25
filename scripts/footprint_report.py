"""Abaqus kernel noGUI script: collapse-footprint report from the final ODB frame.

Tower instance only (skip the GROUND plate). Tower axis is Y: horizontal plane
is XZ, vertical is Y. Reports max radius, P95 radius, direction of the farthest
node, debris COM direction/distance, and final height vs initial geometry.

Run: abq2026.bat cae noGUI=footprint_report.py
"""

import json
import math

from odbAccess import openOdb

ODB_PATH = r"C:\Users\99005\AppData\Local\Temp\tower_collapse_4shdyzvy\tower_job_run.odb"
OUT_PATH = r"D:\GitHub Dev\Demolition-Simulator\frontend\public\resource\Abaqus\cooling_tower_footprint.json"


def _collect(odb, frame):
    uf = frame.fieldOutputs["U"]
    pts = []
    for inst in odb.rootAssembly.instances.values():
        if "TOWER" not in inst.name.upper():
            continue
        u = {v.nodeLabel: v.data for v in uf.getSubset(region=inst).values}
        for node in inst.nodes:
            c = node.coordinates
            d = u.get(node.label, (0.0, 0.0, 0.0))
            pts.append((c[0] + d[0], c[1] + d[1], c[2] + d[2]))
    return pts


def _radii(pts):
    return [math.hypot(x, z) for x, y, z in pts]


def _azimuth(pts, i):
    x, z = pts[i][0], pts[i][2]
    return (math.degrees(math.atan2(z, x)) + 360.0) % 360.0


def main():
    odb = openOdb(ODB_PATH, readOnly=True)
    steps = list(odb.steps.values())
    step_names = [s.name for s in steps]
    init = _collect(odb, steps[0].frames[0])
    last = _collect(odb, steps[-1].frames[-1])
    frame_time = steps[-1].frames[-1].frameValue
    odb.close()

    r0 = _radii(init)
    r = _radii(last)
    n = len(r)
    r_max = max(r)
    i_max = r.index(r_max)
    p95 = sorted(r)[int(0.95 * (n - 1))]
    sx = sz = 0.0
    for p in last:
        sx += p[0]
        sz += p[2]
    mx, mz = sx / n, sz / n
    com_r = math.hypot(mx, mz)
    com_az = (math.degrees(math.atan2(mz, mx)) + 360.0) % 360.0
    base_r = max(r0)
    h0 = max(p[1] for p in init)
    h1 = max(p[1] for p in last)

    report = {
        "odb": ODB_PATH,
        "steps": step_names,
        "frame_time_s": float(frame_time),
        "tower_nodes": n,
        "max_radius_m": float(round(r_max, 3)),
        "p95_radius_m": float(round(p95, 3)),
        "direction_deg": float(round(_azimuth(last, i_max), 2)),
        "com_radius_m": float(round(com_r, 3)),
        "com_direction_deg": float(round(com_az, 2)),
        "tower_base_radius_m": float(round(base_r, 3)),
        "init_height_m": float(round(h0, 3)),
        "final_height_m": float(round(h1, 3)),
        "ratio_max": float(round(r_max / base_r, 3)),
        "ratio_p95": float(round(p95 / base_r, 3)),
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print("report written to " + OUT_PATH, flush=True)


main()
