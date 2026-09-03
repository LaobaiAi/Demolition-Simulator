"""Abaqus 2026 kernel noGUI batch: extract tower geometry + per-frame nodal U to npz.

Tower instance only (shell mesh, tower axis is Y, base center at origin).
Outputs scripts/_tower_frames/data.npz: X (Nx3), conn (Ex4, -1 padded), t (F),
U (FxNx3). F=50 uniform target times 0.5..7.0 s; U linearly interpolated from
nearest bracketing ODB frames. A text report is written next to the npz because
kernel stdout is not reliably captured.
Run: abq2026.bat cae noGUI=extract_tower_frames.py
"""

import os

import numpy as np
from odbAccess import openOdb

ODB_PATH = r"C:\Users\99005\AppData\Local\Temp\tower_collapse_ijlll326\tower_job_run.odb"
OUT_DIR = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\cooling_tower_90m\run31\frames"
OUT_PATH = os.path.join(OUT_DIR, "data.npz")
REPORT_PATH = os.path.join(OUT_DIR, "extract_report.txt")
N_TARGETS = 50
T0, T1 = 0.5, 8.0


def p(msg):
    print(msg, flush=True)


def main():
    report = []
    odb = openOdb(ODB_PATH, readOnly=True)
    insts = list(odb.rootAssembly.instances.values())
    inst = None
    for i in insts:
        if "TOWER" in i.name.upper():
            inst = i
            break
    if inst is None:
        for i in insts:
            if all(len(e.connectivity) == 4 for e in i.elements):
                inst = i
                break
    if inst is None:
        inst = insts[0]
    p("instance=%s" % inst.name)

    nodes = inst.nodes
    labels = [nd.label for nd in nodes]
    idx = {lab: i for i, lab in enumerate(labels)}
    X = np.array([nd.coordinates for nd in nodes], dtype=np.float64)
    report.append("instance=%s" % inst.name)
    report.append("nodes=%d" % len(nodes))
    report.append("x[%.2f,%.2f] y[%.2f,%.2f] z[%.2f,%.2f]" % (
        X[:, 0].min(), X[:, 0].max(), X[:, 1].min(), X[:, 1].max(),
        X[:, 2].min(), X[:, 2].max()))

    els = [el for el in inst.elements if len(el.connectivity) in (3, 4)]
    conn = np.full((len(els), 4), -1, dtype=np.int64)
    n3 = 0
    for i, el in enumerate(els):
        if len(el.connectivity) == 3:
            n3 += 1
        for j, c in enumerate(el.connectivity):
            conn[i, j] = idx[c]
    report.append("elements=%d (3node=%d 4node=%d)" % (len(els), n3, len(els) - n3))
    p(report[-1])

    abs_t = {}
    start = 0.0
    for sname, step in odb.steps.items():
        for fidx, fr in enumerate(step.frames):
            abs_t[(sname, fidx)] = start + fr.frameValue
        start += step.timePeriod
    pairs = sorted((t_, k) for k, t_ in abs_t.items())
    ft = np.array([t_ for t_, _ in pairs])
    report.append("odb_frames=%d steps=%s t_range=%.3f..%.3f" % (
        len(abs_t), list(odb.steps.keys()), ft[0], ft[-1]))
    p(report[-1])

    targets = np.linspace(T0, T1, N_TARGETS)
    idxs = np.searchsorted(ft, targets)
    need = set()
    for i in idxs:
        need.add(max(0, i - 1))
        need.add(min(len(ft) - 1, i))
    Ucache = {}
    for k in sorted(need):
        sname, fidx = pairs[k][1]
        fr = odb.steps[sname].frames[fidx]
        Uf = np.zeros((len(nodes), 3))
        if "U" in fr.fieldOutputs:
            for v in fr.fieldOutputs["U"].getSubset(region=inst).values:
                Uf[idx[v.nodeLabel], :] = v.data[:3]
        Ucache[k] = Uf
    report.append("interp_source_frames=%d" % len(need))

    U = np.zeros((N_TARGETS, len(nodes), 3))
    for j, (tt, i) in enumerate(zip(targets, idxs)):
        a = max(0, i - 1)
        b = min(len(ft) - 1, i)
        if b == a:
            alpha = 0.0
        else:
            alpha = float(np.clip((tt - ft[a]) / (ft[b] - ft[a]), 0.0, 1.0))
        U[j] = (1.0 - alpha) * Ucache[a] + alpha * Ucache[b]

    os.makedirs(OUT_DIR, exist_ok=True)
    np.savez_compressed(OUT_PATH, X=X, conn=conn, t=targets, U=U)
    report.append("saved=%s" % OUT_PATH)
    report.append("shapes X=%s conn=%s t=%s U=%s" % (
        X.shape, conn.shape, targets.shape, U.shape))
    report.append("t=%.3f..%.3f" % (targets[0], targets[-1]))
    report.append("EXTRACT_DONE")
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(report) + "\n")
    odb.close()
    for line in report:
        p(line)


main()
