"""Abaqus kernel noGUI: how much run 18 debris sits OUTSIDE the ground slab?

The slab covers x,z in [-260,260], top y=0. Fragments beyond the footprint at
low altitude sit in the VOID where no ground exists - from a typical CAE camera
angle they appear at/through "ground level". Count per late frame: nodes
outside footprint by height band, plus the lowest outside node xyz.
"""

from odbAccess import openOdb

ODB_PATH = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\concrete_stack_run18\results\stack_job_run.odb"
OUT_PATH = r"D:\GitHub Dev\Demolition-Simulator\abaqus_projects\concrete_stack_run18\results\void_debris_run18.txt"

G = 260.0


def outside(x, z):
    return x < -G or x > G or z < -G or z > G


def main():
    lines = []

    def log(msg):
        lines.append(str(msg))
        print(msg, flush=True)

    odb = openOdb(ODB_PATH, readOnly=True)
    stack = [i for i in odb.rootAssembly.instances.values() if "STACK" in i.name.upper()][0]
    nmap = {nd.label: nd for nd in stack.nodes}

    abs_t = {}
    start = 0.0
    for sname, step in odb.steps.items():
        for fidx, fr in enumerate(step.frames):
            abs_t[(sname, fidx)] = start + fr.frameValue
        start += step.timePeriod

    for (sname, fidx), t in sorted(abs_t.items(), key=lambda kv: kv[1]):
        if t < 10.6:
            continue
        fr = odb.steps[sname].frames[fidx]
        U = {v.nodeLabel: v.data for v in fr.fieldOutputs["U"].getSubset(region=stack).values}
        n_out = 0
        bands = {"<0": 0, "0-0.5": 0, "0.5-2": 0, "2-10": 0, ">10": 0}
        lowest = None
        for lab, nd in nmap.items():
            d = U.get(lab, (0.0, 0.0, 0.0))
            x = nd.coordinates[0] + d[0]
            y = nd.coordinates[1] + d[1]
            z = nd.coordinates[2] + d[2]
            if not outside(x, z):
                continue
            n_out += 1
            if y < 0:
                bands["<0"] += 1
            elif y <= 0.5:
                bands["0-0.5"] += 1
            elif y <= 2:
                bands["0.5-2"] += 1
            elif y <= 10:
                bands["2-10"] += 1
            else:
                bands[">10"] += 1
            if lowest is None or y < lowest[0]:
                lowest = (y, lab, x, z)
        if lowest is None:
            log("t=%7.3f outside_footprint=%5d bands=%s lowest=none" % (
                t, n_out, bands))
        else:
            log("t=%7.3f outside_footprint=%5d bands=%s lowest=(y=%.3f node=%d x=%.1f z=%.1f)" % (
                t, n_out, bands, lowest[0], lowest[1], lowest[2], lowest[3]))

    odb.close()
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("saved=%s" % OUT_PATH, flush=True)
    print("VOID_DONE", flush=True)


main()
