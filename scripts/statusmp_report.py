"""Abaqus kernel noGUI: per-frame STATUSMP element-deletion report for the tower.

STATUSMP is written at one section point per concrete layer per element
(9396 elements x 2 layers = 18792 entries; layer 1 at section point 1,
layer 2 at point 7, or point 6 on the 2-layer TopRing section). A layer
counts as deleted when its STATUSMP <= 0. Mirrors the run-9 methodology.

Run: abq2026.bat cae noGUI=statusmp_report.py
"""

from odbAccess import openOdb

ODB_PATH = r"C:\Users\99005\AppData\Local\Temp\tower_collapse_4shdyzvy\tower_job_run.odb"
OUT_PATH = r"D:\GitHub Dev\Demolition-Simulator\scripts\_tower_frames\statusmp_report.txt"


def main():
    odb = openOdb(ODB_PATH, readOnly=True)
    inst = None
    for i in odb.rootAssembly.instances.values():
        if "TOWER" in i.name.upper():
            inst = i
            break
    n_elems = len(inst.elements)
    lines = ["elements=%d concrete_layer_entries=%d" % (n_elems, n_elems * 2)]

    start = 0.0
    for sname, step in odb.steps.items():
        for fr in step.frames:
            abs_t = start + fr.frameValue
            uf = fr.fieldOutputs["STATUSMP"].getSubset(region=inst)
            by_el = {}
            for v in uf.values:
                by_el.setdefault(v.elementLabel, {})[v.sectionPoint.number] = v.data
            deleted = 0
            for el, pts in by_el.items():
                l1 = pts.get(1)
                l2 = pts.get(7, pts.get(6))
                for layer in (l1, l2):
                    if layer is not None and layer <= 0.0:
                        deleted += 1
            lines.append("t=%.3f concrete_deleted=%.1f%%" % (
                abs_t, 100.0 * deleted / (n_elems * 2)))
        start += step.timePeriod
    odb.close()
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    for l in lines:
        print(l, flush=True)
    print("saved=%s" % OUT_PATH, flush=True)


main()
