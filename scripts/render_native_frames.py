"""Abaqus kernel noGUI: native viewport cloud-plot frames.

Reads a config JSON (path from env NATIVE_RENDER_CFG or _native_render/config.json),
renders N uniform time targets x {side,top} views as PNGs via session.printToFile.
noGUI quirk: a viewport does not re-render after setFrame, so every frame gets a
fresh named viewport that is deleted right after the shot.
Writes _native_render/report.txt because kernel stdout is not reliably captured.
Run: abq2026.bat cae noGUI=scripts/render_native_frames.py
"""

import json
import math
import os
import time

from abaqus import *
from abaqusConstants import *
from visualization import *

BASE_DIR = os.getcwd()
CFG_PATH = os.environ.get("NATIVE_RENDER_CFG", os.path.join(BASE_DIR, "config.json"))


def p(msg):
    print(msg, flush=True)


def main():
    cfg = json.load(open(CFG_PATH, encoding="utf-8"))
    report = []
    rep = lambda msg: (report.append(str(msg)), p(msg))

    t_total0 = time.time()
    session.pngOptions.setValues(imageSize=(cfg.get("width", 1280),
                                            cfg.get("height", 720)))
    try:
        session.printOptions.setValues(reduceColors=False)
    except Exception:
        pass
    odb = session.openOdb(cfg["odb_path"], readOnly=True)
    odb_name = os.path.basename(cfg["odb_path"])

    audit = ["steps:"]
    all_frames = []
    start = 0.0
    for sname, step in odb.steps.items():
        audit.append("  %s: timePeriod=%.3f frames=%d" % (sname, step.timePeriod,
                                                          len(step.frames)))
        for fidx, fr in enumerate(step.frames):
            all_frames.append((sname, fidx, start + fr.frameValue))
        start += step.timePeriod
    last_step = list(odb.steps.values())[-1]
    last_frame = last_step.frames[-1]
    fo_names = sorted(last_frame.fieldOutputs.keys())
    audit.append("fieldOutputs (last frame of %s): %s" % (last_step.name, fo_names))
    for fn in fo_names:
        fo = last_frame.fieldOutputs[fn]
        loc = fo.locations
        vals = fo.values
        pos = vals[0].position if len(vals) else "?"
        audit.append("  %s: type=%s position=%s locations=%d values=%d" % (
            fn, fo.type, pos, len(loc), len(vals)))
    rep("\n".join(audit))

    if cfg["field"] not in fo_names:
        rep("FIELD MISSING: %s not in %s" % (cfg["field"], fo_names))
        _write_report(odb_name, cfg, report)
        return 1
    spec_for_field = {"STATUS": (WHOLE_ELEMENT, ()),
                      "STATUSMP": (INTEGRATION_POINT, ()),
                      "PEEQ": (INTEGRATION_POINT, ()),
                      "S": (INTEGRATION_POINT, (INVARIANT, "Mises")),
                      "U": (NODAL, (INVARIANT, "Magnitude"))}
    fpos, refinement = spec_for_field.get(cfg["field"], (WHOLE_ELEMENT, ()))

    insts = list(odb.rootAssembly.instances.values())
    rep("instances: %s" % [i.name for i in insts])
    geom_insts = [i for i in insts if "GROUND" not in i.name.upper()]
    if not geom_insts:
        geom_insts = insts
    x0 = y0 = z0 = 1e30
    x1 = y1 = z1 = -1e30
    u_last = last_frame.fieldOutputs["U"]
    u_by_node = {}
    u_max = 0.0
    for v in u_last.values:
        u_by_node[v.nodeLabel] = v.data
        d = v.data
        m = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
        u_max = max(u_max, m)
    dx0 = dy0 = dz0 = 1e30
    dx1 = dy1 = dz1 = -1e30
    for inst in geom_insts:
        for nd in inst.nodes:
            c = nd.coordinates
            x0, y0, z0 = min(x0, c[0]), min(y0, c[1]), min(z0, c[2])
            x1, y1, z1 = max(x1, c[0]), max(y1, c[1]), max(z1, c[2])
            u = u_by_node.get(nd.label)
            if u is not None:
                dx0 = min(dx0, c[0] + u[0])
                dy0 = min(dy0, c[1] + u[1])
                dz0 = min(dz0, c[2] + u[2])
                dx1 = max(dx1, c[0] + u[0])
                dy1 = max(dy1, c[1] + u[1])
                dz1 = max(dz1, c[2] + u[2])
    if dx0 < 1e30:
        x0, y0, z0 = min(x0, dx0), min(y0, dy0), min(z0, dz0)
        x1, y1, z1 = max(x1, dx1), max(y1, dy1), max(z1, dz1)
    rep("geom bbox x[%.1f,%.1f] y[%.1f,%.1f] z[%.1f,%.1f] maxU=%.2f" % (
        x0, x1, y0, y1, z0, z1, u_max))
    cx = 0.5 * (x0 + x1)
    cy = 0.5 * (y0 + y1)
    cz = 0.5 * (z0 + z1)
    extent = max(x1 - x0, y1 - y0, z1 - z0)

    n = cfg["n_targets"]
    targets = [cfg["t0"] + (cfg["t1"] - cfg["t0"]) * i / (n - 1) for i in range(n)]
    fmap = [(s, f) for (s, f, _t) in all_frames]
    ftimes = [t for (_s, _f, t) in all_frames]
    target_frames = []
    for t in targets:
        best = min(range(len(ftimes)), key=lambda k: abs(ftimes[k] - t))
        target_frames.append((fmap[best], ftimes[best]))

    fov = cfg.get("fov", 35.0)
    azim = math.radians(cfg.get("azim", -25.0))
    elev = math.radians(cfg.get("elev", 8.0))
    scale = cfg.get("deform_scale", 1.0)
    w = cfg.get("width", 1280)
    h = cfg.get("height", 720)
    intervals = cfg.get("num_intervals", 2)

    side_dir = (math.sin(azim) * math.cos(elev), math.sin(elev),
                math.cos(azim) * math.cos(elev))
    top_dir = (0.0, -1.0, 0.0)
    top_up = (0.0, 0.0, -1.0)
    cam_views = {"side": (side_dir, (0.0, 1.0, 0.0)),
                 "top": (top_dir, top_up)}
    dist = 0.62 * extent / math.tan(math.radians(fov) / 2.0)

    rep("targets=%d t=[%.2f,%.2f] fov=%.0f dist=%.0f scale=%.3f" % (
        n, cfg["t0"], cfg["t1"], fov, dist, scale))
    out_dir = cfg["out_dir"]
    shots = 0
    for view in cfg["views"]:
        d, up = cam_views[view]
        vdir = os.path.join(out_dir, view)
        os.makedirs(vdir, exist_ok=True)
        per_frame = []
        t_view0 = time.time()
        for i in range(n):
            (sname, fidx), t_act = target_frames[i]
            tag = "%s_%03d" % (view, i + 1)
            v = session.Viewport(name=tag)
            v.setValues(border=OFF, displayedObject=odb)
            v.odbDisplay.setFrame(step=sname, frame=fidx)
            v.odbDisplay.commonOptions.setValues(renderStyle=SHADED,
                                                 visibleEdges=NONE)
            v.odbDisplay.deformedShapeOptions.setValues(deformationScaling=UNIFORM,
                                                        uniformScaleFactor=scale)
            v.odbDisplay.setPrimaryVariable(cfg["field"], fpos, refinement)
            v.odbDisplay.contourOptions.setValues(numIntervals=intervals)
            v.viewportAnnotationOptions.setValues(legend=ON, title=OFF,
                                                  state=ON, triad=OFF,
                                                  annotations=ON)
            pos = (cx + dist * d[0], cy + dist * d[1], cz + dist * d[2])
            v.view.setValues(cameraPosition=pos, cameraTarget=(cx, cy, cz),
                             cameraUpVector=up, fieldOfViewAngle=fov)
            t0 = time.time()
            session.printToFile(fileName=os.path.join(vdir, "f_%03d.png" % (i + 1)),
                                format=PNG, canvasObjects=(v,))
            dt = time.time() - t0
            try:
                del session.viewports[tag]
            except Exception:
                pass
            per_frame.append(dt)
            shots += 1
        t_view = time.time() - t_view0
        png_sizes = []
        for f in sorted(os.listdir(vdir)):
            if f.endswith(".png"):
                png_sizes.append("%s=%d" % (f, os.path.getsize(os.path.join(vdir, f))))
        rep("%s: %d shots in %.1fs, per-frame avg=%.2fs max=%.2fs png=%s" % (
            view, n, t_view, sum(per_frame) / len(per_frame), max(per_frame),
            " ".join(png_sizes[:3]) + ("..." if len(png_sizes) > 3 else "")))
    rep("TOTAL %.1fs shots=%d" % (time.time() - t_total0, shots))
    odb.close()
    _write_report(odb_name, cfg, report)
    return 0


def _write_report(odb_name, cfg, report):
    rdir = os.path.dirname(cfg["out_dir"]) if "out_dir" in cfg else \
        os.path.join(BASE_DIR, "_native_render")
    os.makedirs(rdir, exist_ok=True)
    rp = os.path.join(rdir, "report.txt")
    with open(rp, "w", encoding="utf-8") as fh:
        fh.write("odb=%s field=%s\n%s\n" % (odb_name, cfg.get("field"), "\n".join(report)))
    print("saved=%s" % rp, flush=True)


if __name__ == "__main__":
    rc = main()
    print("RENDER_NATIVE rc=%d" % rc, flush=True)
