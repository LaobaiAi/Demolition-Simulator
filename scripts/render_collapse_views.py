"""Abaqus cae noGUI script: render cooling-tower collapse ODB to PNG frame sequences.

Two views: side panorama (elevated 3/4 view, ground included) and top-down
footprint view. Frames subsampled uniformly from t>=1.0 to the last frame of the
final step, displaced tower geometry shaded and colored by U Magnitude at scale
1.0. The GROUND plate is displayed but ignored for framing math (tower nodes
only; tower axis is Y, horizontal plane XZ).

IMPORTANT: in this 2026 noGUI kernel, a viewport renders the ODB frame captured
at its FIRST render only (setFrame afterwards does not re-render). Workaround:
create a fresh viewport per frame.

Run: abq2026.bat cae noGUI=render_collapse_views.py
"""

import math
import os

from abaqus import *
from abaqusConstants import *
from visualization import *

ODB_PATH = r"C:\Users\99005\AppData\Local\Temp\tower_collapse_96t8sjpa\tower_job_run.odb"
FRAME_ROOT = r"D:\GitHub Dev\Demolition-Simulator\frontend\public\resource\Abaqus\frames"
START_T = 1.0
N_FRAMES = 60
W, H = 1280, 720
SIDE_ELEV, SIDE_AZ = 14.0, 35.0
R_P95 = 0.95


def _configure(v):
    v.odbDisplay.commonOptions.setValues(renderStyle=SHADED, visibleEdges=NONE)
    v.odbDisplay.deformedShapeOptions.setValues(deformationScaling=UNIFORM,
                                                uniformScaleFactor=1.0)
    v.odbDisplay.setPrimaryVariable("U", NODAL, (INVARIANT, "Magnitude"))
    v.viewportAnnotationOptions.setValues(title=False, state=False, triad=OFF)
    v.setValues(width=W, height=H)


def _shoot(v, out):
    session.printToFile(fileName=out, format=PNG, canvasObjects=(v,))


def _tower_pts(odb, frame):
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


def main():
    odb = session.openOdb(ODB_PATH, readOnly=True)
    step_name = list(odb.steps.keys())[-1]
    step = odb.steps[step_name]
    frames = [f for f in step.frames if f.frameValue + 1e-6 >= START_T]
    if len(frames) > N_FRAMES:
        idxs = sorted(set(int(round(i * (len(frames) - 1) / (N_FRAMES - 1)))
                          for i in range(N_FRAMES)))
        frames = [frames[i] for i in idxs]
    n = len(frames)
    print("step=%s frames=%d t=%.2f..%.2f (source %d, target %d)" % (
        step_name, n, frames[0].frameValue, frames[-1].frameValue,
        len(step.frames), N_FRAMES), flush=True)

    first_pts = _tower_pts(odb, frames[0])
    pts = _tower_pts(odb, frames[-1])
    rs = sorted(math.hypot(x, z) for x, y, z in pts)
    r95 = rs[int(R_P95 * (len(rs) - 1))]
    box = [p for p in pts if math.hypot(p[0], p[2]) <= r95]
    all_pts = first_pts + box
    tx0 = min(p[0] for p in all_pts)
    tx1 = max(p[0] for p in all_pts)
    ty0 = min(p[1] for p in all_pts)
    ty1 = max(p[1] for p in all_pts)
    tz0 = min(p[2] for p in all_pts)
    tz1 = max(p[2] for p in all_pts)
    print("tower view bbox x[%.1f,%.1f] y[%.1f,%.1f] z[%.1f,%.1f] r95=%.1f" % (
        tx0, tx1, ty0, ty1, tz0, tz1, r95), flush=True)

    big = max(tx1 - tx0, ty1 - ty0, tz1 - tz0)
    m = 0.15 * big
    x0, x1 = tx0 - m, tx1 + m
    y0, y1 = ty0 - m, ty1 + m
    z0, z1 = tz0 - m, tz1 + m
    cx, cz = 0.5 * (x0 + x1), 0.5 * (z0 + z1)
    print("view bbox x[%.1f,%.1f] y[%.1f,%.1f] z[%.1f,%.1f] big=%.1f" % (
        x0, x1, y0, y1, z0, z1, big), flush=True)

    r_side = 2.7 * big
    el = math.radians(SIDE_ELEV)
    az = math.radians(SIDE_AZ)
    side_pos = (cx + r_side * math.cos(el) * math.cos(az),
                y0 + r_side * math.sin(el),
                cz + r_side * math.cos(el) * math.sin(az))
    side_tgt = (cx, 0.5 * (y0 + y1), cz)
    r_top = 2.7 * max(x1 - x0, z1 - z0)
    top_pos = (cx, y0 + r_top, cz)
    top_tgt = (cx, y0, cz)

    side_dir = os.path.join(FRAME_ROOT, "side")
    top_dir = os.path.join(FRAME_ROOT, "top")
    os.makedirs(side_dir, exist_ok=True)
    os.makedirs(top_dir, exist_ok=True)

    for i, fr in enumerate(frames):
        tag = "rt_%d" % i
        v = session.Viewport(name=tag)
        v.setValues(displayedObject=odb)
        v.odbDisplay.setFrame(step=step_name, frame=fr.frameId)
        _configure(v)
        v.view.setValues(cameraPosition=side_pos, cameraTarget=side_tgt,
                         cameraUpVector=(0.0, 1.0, 0.0))
        _shoot(v, os.path.join(side_dir, "f_%03d.png" % (i + 1)))
        del session.viewports[tag]
        if (i + 1) % 5 == 0:
            print("side %d/%d" % (i + 1, n), flush=True)
    open(os.path.join(side_dir, "side.done"), "w").close()
    print("DONE side frames=%d" % n, flush=True)

    for i, fr in enumerate(frames):
        tag = "rt_%d" % i
        v = session.Viewport(name=tag)
        v.setValues(displayedObject=odb)
        v.odbDisplay.setFrame(step=step_name, frame=fr.frameId)
        _configure(v)
        v.view.setValues(cameraPosition=top_pos, cameraTarget=top_tgt,
                         cameraUpVector=(0.0, 0.0, 1.0))
        _shoot(v, os.path.join(top_dir, "f_%03d.png" % (i + 1)))
        del session.viewports[tag]
        if (i + 1) % 5 == 0:
            print("top %d/%d" % (i + 1, n), flush=True)
    open(os.path.join(top_dir, "top.done"), "w").close()
    print("DONE top frames=%d" % n, flush=True)


main()
