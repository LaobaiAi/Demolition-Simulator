"""Abaqus kernel noGUI: which stretched elements are actually RENDERED (alive)?

For run 18 stack ODB late frames (t >= 8.8), per element compute deformed max
edge; report how many of the stretched (edge > EDGE_ALERT) elements have
STATUS=1 (alive -> CAE renders them as giant quads) vs STATUS=0 (deleted ->
not drawn). Also locate worst element (undeformed position) to know which
stack region the slivers belong to.
"""

from odbAccess import openOdb

ODB_PATH = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\concrete_stack_run18\results\stack_job_run.odb"
OUT_PATH = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\concrete_stack_run18\results\sliver_analysis_run18.txt"

EDGE_ALERT = 30.0


def main():
    lines = []

    def log(msg):
        lines.append(str(msg))
        print(msg, flush=True)

    odb = openOdb(ODB_PATH, readOnly=True)
    stack = [i for i in odb.rootAssembly.instances.values() if "STACK" in i.name.upper()][0]
    nmap = {nd.label: nd for nd in stack.nodes}
    els = list(stack.elements)
    conn = []
    for el in els:
        c = list(el.connectivity)
        while len(c) < 4:
            c.append(-1)
        conn.append(c)
    # undeformed element centroid + z-extent, to classify regions
    centroids = []
    for el in els:
        cs = [nmap[l].coordinates for l in el.connectivity if l in nmap]
        sx = sy = sz = 0.0
        for c in cs:
            sx += float(c[0])
            sy += float(c[1])
            sz += float(c[2])
        n = len(cs)
        centroids.append((sx / n, sy / n, sz / n))

    abs_t = {}
    start = 0.0
    for sname, step in odb.steps.items():
        for fidx, fr in enumerate(step.frames):
            abs_t[(sname, fidx)] = start + fr.frameValue
        start += step.timePeriod

    for (sname, fidx), t in sorted(abs_t.items(), key=lambda kv: kv[1]):
        if t < 8.8:
            continue
        fr = odb.steps[sname].frames[fidx]
        U = {v.nodeLabel: v.data for v in fr.fieldOutputs["U"].getSubset(region=stack).values}
        st = {}
        if "STATUS" in fr.fieldOutputs:
            for v in fr.fieldOutputs["STATUS"].getSubset(region=stack).values:
                try:
                    dd = list(v.data)
                except Exception:
                    dd = [float(v.data)]
                st[v.elementLabel] = dd
        n_alive_stretch = 0
        n_dead_stretch = 0
        worst = (0.0, None)
        worst_st = None
        worst_cy = None
        for i, el in enumerate(els):
            pts = []
            for lab in conn[i]:
                if lab < 0 or lab not in U:
                    continue
                c = nmap[lab].coordinates
                d = U[lab]
                pts.append((c[0] + d[0], c[1] + d[1], c[2] + d[2]))
            if len(pts) < 2:
                continue
            e = 0.0
            for a in range(len(pts)):
                for b in range(a + 1, len(pts)):
                    l2 = (pts[a][0] - pts[b][0]) ** 2 + (pts[a][1] - pts[b][1]) ** 2 + \
                         (pts[a][2] - pts[b][2]) ** 2
                    if l2 > e:
                        e = l2
            e = e ** 0.5
            if e > worst[0]:
                worst = (e, el.label)
                dd = st.get(el.label)
                if dd is None:
                    worst_st = "missing"
                elif all(float(x) < 0.5 for x in dd):
                    worst_st = "dead"
                else:
                    worst_st = "alive"
                worst_cy = centroids[i][1]
            if e <= EDGE_ALERT:
                continue
            dd = st.get(el.label)
            if dd is None:
                continue
            if all(float(x) < 0.5 for x in dd):
                n_dead_stretch += 1
            else:
                n_alive_stretch += 1
        log("t=%7.3f stretched(alive=%5d dead=%5d) worst_edge=%9.2f el=%d status=%s undeformed_cy=%7.2f" % (
            t, n_alive_stretch, n_dead_stretch, worst[0], worst[1], worst_st, worst_cy))

    odb.close()
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("saved=%s" % OUT_PATH, flush=True)
    print("SLIVER_DONE", flush=True)


main()
