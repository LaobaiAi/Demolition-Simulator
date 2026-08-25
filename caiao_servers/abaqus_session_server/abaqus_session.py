"""Abaqus Session Backend — runs inside `abaqus python` to provide a persistent CAE session.

Reads JSON-RPC tool calls from stdin, executes against shared mdb.models['Model-1'],
and writes JSON results to stdout. Designed to be spawned by abaqus_session_server.

Protocol (one JSON object per line):
  Request:  {"id": "...", "tool": "create_rectangular_column", "arguments": {...}}
  Response: {"id": "...", "success": true, "result": {...}}  or  {"id": "...", "error": "..."}
"""

import sys
import os
import json
import math
import subprocess
import traceback

# ── Abaqus environment setup ──────────────────────────────────────────────
# When spawned by server.py, ABAQUSLM_LICENSE_FILE is set via env.
_license_server = os.environ.get("ABAQUSLM_LICENSE_FILE")
if _license_server:
    os.environ["abaquslm_license_file"] = _license_server

# ── Abaqus imports (available only inside abaqus python) ───────────────────
from abaqus import mdb
from abaqusConstants import (
    ON, OFF, DEFAULT, UNIFORM, SINGLE, DOUBLE, DOUBLE_PLUS_PACK, PERCENTAGE,
    THREE_D, DEFORMABLE_BODY, IMPRINT, EXPLICIT, INDEPENDENT,
)

TOWER_JOB_NAME = "tower_job_run"
# set by server.py at kernel spawn; fallback to abaqus_env.json in the kernel
_SOLVER_PROC = None

# ── Tool handlers ──────────────────────────────────────────────────────────

def _handle_create_rectangular_column(args):
    name = args["name"]
    length = args["length"]
    width = args["width"]
    depth = args["depth"]
    rebar_dia = args.get("rebar_dia", 0.012)
    cover = args.get("cover", 0.05)

    if "Model-1" not in mdb.models:
        model = mdb.Model(name="Model-1")
    else:
        model = mdb.models["Model-1"]

    sketch = model.ConstrainedSketch(name="__profile__", sheetSize=2.0)
    sketch.rectangle(point1=(-width / 2, -depth / 2), point2=(width / 2, depth / 2))
    part_concrete = model.Part(name=name + "_conc", dimensionality=THREE_D, type=DEFORMABLE_BODY)
    part_concrete.BaseSolidExtrude(sketch=sketch, depth=length)
    del sketch

    part_rebar = model.Part(name=name + "_rebar", dimensionality=THREE_D, type=DEFORMABLE_BODY)
    corner_positions = [
        (-width / 2 + cover, -depth / 2 + cover),
        (width / 2 - cover, -depth / 2 + cover),
        (width / 2 - cover, depth / 2 - cover),
        (-width / 2 + cover, depth / 2 - cover),
    ]
    for x, z in corner_positions:
        part_rebar.WirePolyLine(points=((x, 0, z), (x, length, z)), mergeType=IMPRINT)

    return {
        "concrete_part": name + "_conc",
        "rebar_part": name + "_rebar",
        "message": f"Column {name} created: {length}m height, {width}x{depth}m section",
    }


def _handle_create_truss(args):
    name = args["name"]
    span = args["span"]
    height = args["height"]
    n_panels = args.get("n_panels", 4)

    if "Model-1" not in mdb.models:
        model = mdb.Model(name="Model-1")
    else:
        model = mdb.models["Model-1"]

    part = model.Part(name=name, dimensionality=THREE_D, type=DEFORMABLE_BODY)
    panel_len = span / n_panels

    part.WirePolyLine(points=((0, height, 0), (span, height, 0)), mergeType=IMPRINT)
    part.WirePolyLine(points=((0, 0, 0), (span, 0, 0)), mergeType=IMPRINT)

    for i in range(n_panels):
        p0 = i * panel_len
        p1 = (i + 1) * panel_len
        part.WirePolyLine(points=((p0, height, 0), (p0, 0, 0)), mergeType=IMPRINT)
        mid = (p0 + p1) / 2
        part.WirePolyLine(points=((p0, height, 0), (mid, 0, 0)), mergeType=IMPRINT)
        part.WirePolyLine(points=((mid, 0, 0), (p1, height, 0)), mergeType=IMPRINT)

    return {"part_name": name, "message": f"Truss {name} created: span={span}m, height={height}m"}


def _handle_create_slab(args):
    name = args["name"]
    length = args["length"]
    width = args["width"]
    thickness = args["thickness"]

    if "Model-1" not in mdb.models:
        model = mdb.Model(name="Model-1")
    else:
        model = mdb.models["Model-1"]

    sketch = model.ConstrainedSketch(name="__slab_sk__", sheetSize=max(length, width) * 2)
    sketch.rectangle(point1=(0, 0), point2=(length, width))
    part = model.Part(name=name, dimensionality=THREE_D, type=DEFORMABLE_BODY)
    part.BaseShellExtrude(sketch=sketch, depth=thickness)
    del sketch

    return {"part_name": name, "message": f"Slab {name} created: {length}x{width}m, t={thickness}m"}


def _handle_assign_concrete_cdp(args):
    part_name = args["part_name"]
    mat_name = args.get("material_name", "C30")
    density = args.get("density", 2500.0)
    E = args.get("E", 3e10)
    nu = args.get("nu", 0.2)
    fc = args.get("fc", 30.0)

    model = mdb.models["Model-1"]

    if mat_name not in model.materials:
        mat = model.Material(name=mat_name)
        mat.Density(table=((density,),))
        mat.Elastic(table=((E, nu),))
        mat.ConcreteDamagedPlasticity(table=((35.0, 0.1, 1.16, 0.667, 0.0001),))
        try:
            mat.concreteDamagedPlasticity.ConcreteCompressionHardening(table=(
                (15.0e6, 0.0), (20.0e6, 5.0e-4), (25.0e6, 1.0e-3),
                (30.0e6, 1.5e-3), (28.0e6, 2.0e-3), (20.0e6, 3.0e-3),
                (5.0e6, 5.0e-3),
            ))
        except Exception:
            pass
        ft = 2.9e6
        try:
            mat.concreteDamagedPlasticity.ConcreteTensionStiffening(table=(
                (ft, 0.0), (0.8 * ft, 1.0e-4), (0.5 * ft, 3.0e-4),
                (0.2 * ft, 1.0e-3), (0.05 * ft, 3.0e-3),
            ))
        except Exception:
            pass

    part = model.parts[part_name]
    section_name = f"Sec_{part_name}"
    if section_name not in model.sections:
        model.HomogeneousSolidSection(name=section_name, material=mat_name)
    region = part.Set(name=f"All_{part_name}", cells=part.cells)
    part.SectionAssignment(region=region, sectionName=section_name)

    return {"message": f"CDP material {mat_name} assigned to {part_name}"}


def _handle_mesh_part(args):
    part_name = args["part_name"]
    element_type = args.get("element_type", "C3D8R")
    global_size = args.get("global_size", 0.2)

    import mesh

    model = mdb.models["Model-1"]
    part = model.parts[part_name]

    part.seedPart(size=global_size)
    elem_type = mesh.ElemType(elemCode=getattr(mesh.ElemType, element_type, None) or element_type,
                              elemLibrary=EXPLICIT)
    try:
        part.setElementType(regions=(part.cells,), elemTypes=(elem_type,))
    except Exception:
        for cell_set in part.sets.values():
            try:
                part.setElementType(regions=(cell_set,), elemTypes=(elem_type,))
            except Exception:
                continue
    part.generateMesh()

    return {"message": f"Mesh generated for {part_name}: type={element_type}, size={global_size}m"}


def _handle_create_explicit_step(args):
    step_name = args["step_name"]
    time_period = args["time_period"]
    nlgeom = args.get("nlgeom", True)

    model = mdb.models["Model-1"]
    model.ExplicitDynamicsStep(name=step_name, previous="Initial",
                               timePeriod=time_period, nlgeom=nlgeom)
    # NOTE: this 2026 build has no output-request scripting API (no
    # fieldOutputRequests on steps, no FieldOutputRequest on model); field
    # output STATUS/STATUSMP is injected at INP level by _tower_inp_surgery.

    return {"step_name": step_name, "message": f"Explicit step '{step_name}' created: {time_period}s"}


def _handle_apply_gravity(args):
    magnitude = args.get("magnitude", 9.8)

    model = mdb.models["Model-1"]
    assembly = model.rootAssembly

    all_set_name = "ALL"
    if all_set_name not in assembly.sets:
        assembly.Set(name=all_set_name, referencePoint=(assembly.instances[0],))

    model.Gravity(
        name="Gravity",
        createStepName="Collapse",
        comp2=-magnitude,
        distributionType=UNIFORM,
    )

    return {"message": f"Gravity {magnitude} m/s^2 applied"}


def _handle_create_rigid_ground(args):
    max_coord = args.get("max_coord", 60.0)
    half_span = args.get("half_span", 20.0)

    model = mdb.models["Model-1"]
    assembly = model.rootAssembly

    ground_name = "Ground"
    if ground_name in model.parts:
        del model.parts[ground_name]

    ground = model.Part(name=ground_name, dimensionality=THREE_D, type=DEFORMABLE_BODY)
    sketch = model.ConstrainedSketch(name="__grd__", sheetSize=max_coord * 2)
    sketch.rectangle(point1=(-max_coord, -half_span), point2=(max_coord, half_span))
    ground.BaseSolidExtrude(sketch=sketch, depth=2.0)
    del sketch

    if "RIGID_MAT" not in model.materials:
        mat = model.Material(name="RIGID_MAT")
        mat.Density(table=((7850.0,),))
        mat.Elastic(table=((2.0e15, 0.3),))

    if "GroundSection" not in model.sections:
        model.HomogeneousSolidSection(name="GroundSection", material="RIGID_MAT")
    ground.Set(cells=ground.cells, name="AllGround")
    ground.SectionAssignment(region=ground.sets["AllGround"], sectionName="GroundSection")

    ground.seedPart(size=5.0)
    try:
        import mesh
        ground.setElementType(regions=(ground.cells,), elemTypes=(mesh.ElemType["C3D8R"],))
    except Exception:
        pass
    ground.generateMesh()

    ginst = assembly.Instance(name="Ground-1", part=ground, dependent=ON)
    assembly.rotate(instanceList=("Ground-1",),
                    axisPoint=(0.0, 0.0, 0.0),
                    axisDirection=(1.0, 0.0, 0.0),
                    angle=-90.0)
    ginst.translate(vector=(max_coord, -2.0, 0.0))

    try:
        model.EncastreBC(name="FixGround", createStepName="Initial",
                         region=ginst.sets["AllGround"])
    except Exception:
        pass

    try:
        model.ContactExp(name="GeneralContact", createStepName="Collapse")
        model.interactions["GeneralContact"].includedPairs.setValuesInStep(useAllstar=ON)
    except Exception:
        pass

    return {"message": "Rigid ground, boundary, and contact created"}


def _handle_submit_job(args):
    job_name = args["job_name"]
    cpus = args.get("cpus", 4)
    memory = args.get("memory_percent", 80)

    model = mdb.models["Model-1"]
    mdb.Job(
        name=job_name, model="Model-1",
        numCpus=cpus, numDomains=cpus,
        multiprocessingMode=DEFAULT,
        explicitPrecision=SINGLE,
        memory=memory, memoryUnits=PERCENTAGE,
    )
    mdb.jobs[job_name].submit()
    mdb.jobs[job_name].waitForCompletion()

    return {"job_name": job_name, "status": "completed"}


def _handle_get_max_displacement(args):
    odb_path = args["odb_path"]

    from odbAccess import openOdb
    odb = openOdb(odb_path)
    last_step_key = list(odb.steps.keys())[-1]
    last_frame = odb.steps[last_step_key].frames[-1]
    U = last_frame.fieldOutputs["U"]
    max_disp = 0.0
    instance_filter = args.get("instance_name")
    for v in U.values:
        if instance_filter is None or instance_filter in v.instance.name:
            mag = v.magnitude
            if mag > max_disp:
                max_disp = mag
    odb.close()

    return {"max_displacement": max_disp, "step": last_step_key}


def _handle_plot_displacement_curve(args):
    time_values = args["time_values"]
    disp_values = args["disp_values"]
    output_path = args["output_path"]

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot(time_values, disp_values)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Displacement (m)")
    ax.set_title("Collapse — Top Displacement vs Time")
    ax.grid(True)
    fig.savefig(output_path)
    plt.close(fig)

    return {"image_saved": output_path}


def _handle_create_cut_zone(args):
    cut_height = args["cut_height"]
    tol = cut_height * 0.3

    model = mdb.models["Model-1"]
    assembly = model.rootAssembly
    cut_zone_refs = []
    total_elements = 0

    for inst in assembly.instances.values():
        inst_name = inst.name
        if not (inst_name.startswith("Col_") and "-1" in inst_name and "_rebar" not in inst_name):
            continue

        part = inst.part
        cut_labels = []
        for elem in inst.elements:
            try:
                nodes = elem.getNodes()
                if not nodes:
                    continue
                ys = [n.coordinates[1] for n in nodes]
                y_mid = (min(ys) + max(ys)) / 2
                if abs(y_mid - cut_height) < tol:
                    cut_labels.append(elem.label)
            except Exception:
                continue

        if not cut_labels:
            continue

        set_name = f"CutZone_{inst_name}"
        try:
            elem_seq = part.elements.sequenceFromLabels(labels=cut_labels)
            part.Set(elements=elem_seq, name=set_name)
            cut_zone_refs.append((inst_name, set_name, len(cut_labels)))
            total_elements += len(cut_labels)
        except Exception:
            continue

    return {
        "cut_zone_refs": cut_zone_refs,
        "total_elements": total_elements,
        "cut_height": cut_height,
        "message": f"Cut zone: {total_elements} elements at {cut_height}m height",
    }


def _handle_inject_cut_zone_inp(args):
    inp_path = args["inp_path"]
    cut_zone_refs = args["cut_zone_refs"]
    step_name = args.get("step_name", "Collapse")

    with open(inp_path, "r", encoding="utf-8") as f:
        text = f.read()

    modified = False

    # a) Inject WEAK_C30 material
    if "WEAK_C30" not in text:
        weak_mat = (
            "*Material, name=WEAK_C30\n"
            "*Density\n2500.,\n"
            "*Elastic\n 1e+06, 0.2\n"
            "*Plastic\n 1000., 0.\n"
            "*Damage Initiation, criterion=DUCTILE\n 1e-06, 0., 0.\n"
            "*Damage Evolution, type=DISPLACEMENT, softening=EXPONENTIAL\n 0.0001,\n"
        )
        idx = text.find("\n*Part, name=")
        if idx > 0:
            text = text[:idx + 1] + weak_mat + text[idx + 1:]
            modified = True

    # b) Inject weak section assignment for cut zone elements
    for inst_name, set_name, n_elem in cut_zone_refs:
        part_name = inst_name.rsplit("-", 1)[0] + "_conc"
        marker = f"*Solid Section, elset=All_{part_name}, material=C30\n"
        inject = f"*Solid Section, elset={set_name}, material=WEAK_C30\n"
        if marker in text:
            text = text.replace(marker, marker + inject)
            modified = True

    # c) Inject SECTION CONTROLS with element deletion before the Collapse step
    import re
    step_pattern = re.compile(rf"^\*Step, name={re.escape(step_name)}.*$", re.MULTILINE)
    step_match = step_pattern.search(text)
    if step_match:
        inject = (
            "** ----------------------------------------------------------------\n"
            "** SECTION CONTROLS: element deletion for cut zone blast simulation\n"
            "*Section Controls, name=CutZoneDel, element deletion=YES\n"
            "** ----------------------------------------------------------------\n"
        )
        text = text[:step_match.start()] + inject + "\n" + text[step_match.start():]
        modified = True

    # d) Inject STATUS + SDEG output
    output_marker = "*Output, field, variable=PRESELECT"
    of_pos = text.find(output_marker, text.find(f"*Step, name={step_name}"))
    if of_pos < 0:
        of_pos = text.find("*Output, field", text.find(f"*Step, name={step_name}"))
    if of_pos > 0:
        nl_pos = text.find("\n", of_pos)
        inject_output = (
            "\n** STATUS + SDEG for element deletion visualization\n"
            "*Element Output, directions=YES\n"
            "STATUS,\nSDEG,\n"
        )
        if "STATUS" not in text[of_pos:of_pos + 2000]:
            text = text[:nl_pos + 1] + inject_output + text[nl_pos + 1:]
            modified = True

    if modified:
        with open(inp_path, "w", encoding="utf-8") as f:
            f.write(text)

    total_elems = sum(n for _, _, n in cut_zone_refs)
    return {
        "modified": modified,
        "total_cut_elements": total_elems,
        "message": f"INP injection complete: {len(cut_zone_refs)} sets ({total_elems} elements)",
    }


def _handle_build_factory(args):
    num_bays = args["num_bays"]
    span = args["span"]
    bay_len = args["bay_length"]
    total_h = args["total_height"]
    col_w = args.get("column_width", 0.5)
    col_d = args.get("column_depth", 0.5)
    mesh_size = args.get("mesh_size", 0.3)
    truss_h = args.get("truss_height", 2.0)
    slab_t = args.get("slab_thickness", 0.15)

    model = mdb.models["Model-1"] if "Model-1" in mdb.models else mdb.Model(name="Model-1")
    assembly = model.rootAssembly

    # Material: C30 concrete
    if "C30" not in model.materials:
        mat_c30 = model.Material(name="C30")
        mat_c30.Density(table=((2500.0,),))
        mat_c30.Elastic(table=((3e10, 0.2),))
        mat_c30.ConcreteDamagedPlasticity(table=((35.0, 0.1, 1.16, 0.667, 0.0001),))
        try:
            mat_c30.concreteDamagedPlasticity.ConcreteCompressionHardening(table=(
                (15.0e6, 0.0), (20.0e6, 5.0e-4), (25.0e6, 1.0e-3),
                (30.0e6, 1.5e-3), (28.0e6, 2.0e-3), (20.0e6, 3.0e-3),
                (5.0e6, 5.0e-3),
            ))
        except Exception:
            pass
        ft = 2.9e6
        try:
            mat_c30.concreteDamagedPlasticity.ConcreteTensionStiffening(table=(
                (ft, 0.0), (0.8 * ft, 1.0e-4), (0.5 * ft, 3.0e-4),
                (0.2 * ft, 1.0e-3), (0.05 * ft, 3.0e-3),
            ))
        except Exception:
            pass

    if "Q235" not in model.materials:
        mat_steel = model.Material(name="Q235")
        mat_steel.Density(table=((7850.0,),))
        mat_steel.Elastic(table=((2.06e11, 0.3),))

    columns = []
    all_col_inst_names = []
    trusses = []

    # Build columns
    for i in range(num_bays + 1):
        for side_idx, z in enumerate([-span / 2, span / 2]):
            side_label = "L" if side_idx == 0 else "R"
            col_name = f"Col_{i}_{side_label}"

            # Create part
            r = _handle_create_rectangular_column({
                "name": col_name, "length": total_h,
                "width": col_w, "depth": col_d,
            })
            conc_part = model.parts[r["concrete_part"]]

            # Section
            section_name = f"Sec_{r['concrete_part']}"
            if section_name not in model.sections:
                model.HomogeneousSolidSection(name=section_name, material="C30")
            region = conc_part.Set(name=f"All_{r['concrete_part']}", cells=conc_part.cells)
            conc_part.SectionAssignment(region=region, sectionName=section_name)

            # Mesh
            _handle_mesh_part({"part_name": r["concrete_part"], "global_size": mesh_size})

            # Assembly
            x_pos = i * bay_len
            inst_name = f"{col_name}-1"
            conc_inst = assembly.Instance(name=inst_name, part=conc_part, dependent=ON)
            assembly.rotate(instanceList=(inst_name,),
                            axisPoint=(0.0, 0.0, 0.0),
                            axisDirection=(1.0, 0.0, 0.0),
                            angle=-90.0)
            conc_inst.translate(vector=(x_pos, 0.0, z))

            all_col_inst_names.append(inst_name)
            columns.append({
                "name": col_name, "x": x_pos, "z": z,
                "concrete_part": r["concrete_part"],
                "rebar_part": r["rebar_part"],
                "inst_name": inst_name,
            })

    # Build trusses
    for i in range(num_bays):
        truss_name = f"Truss_{i}"
        r = _handle_create_truss({
            "name": truss_name, "span": bay_len,
            "height": truss_h, "n_panels": 4,
        })
        trusses.append(r)

    # Build roof slab
    slab_name = "RoofSlab"
    slab_len = num_bays * bay_len
    if slab_name in model.parts:
        del model.parts[slab_name]

    slab_sketch = model.ConstrainedSketch(name="_slab_sk_", sheetSize=slab_len * 2)
    slab_sketch.rectangle(point1=(0, 0), point2=(slab_len, span))
    slab_p = model.Part(name=slab_name, dimensionality=THREE_D, type=DEFORMABLE_BODY)
    slab_p.BaseSolidExtrude(sketch=slab_sketch, depth=slab_t)
    del slab_sketch

    slab_sec_name = "Sec_Slab"
    if slab_sec_name not in model.sections:
        model.HomogeneousSolidSection(name=slab_sec_name, material="C30")
    slab_region = slab_p.Set(name="AllSlab", cells=slab_p.cells)
    slab_p.SectionAssignment(region=slab_region, sectionName=slab_sec_name)

    _handle_mesh_part({"part_name": slab_name, "global_size": mesh_size})

    sl_inst = assembly.Instance(name="RoofSlab-1", part=slab_p, dependent=ON)
    assembly.rotate(instanceList=("RoofSlab-1",),
                    axisPoint=(0.0, 0.0, 0.0),
                    axisDirection=(1.0, 0.0, 0.0),
                    angle=-90.0)
    sl_inst.translate(vector=(0.0, total_h, span / 2.0))

    return {
        "num_columns": len(columns),
        "num_trusses": len(trusses),
        "slab": {"part_name": slab_name},
        "column_names": all_col_inst_names,
        "num_assembly_instances": len(assembly.instances),
    }


def _handle_setup_collapse(args):
    config = args["config"]
    project_dir = args.get("project_dir", os.getcwd())
    import shutil

    model = mdb.models["Model-1"] if "Model-1" in mdb.models else mdb.Model(name="Model-1")
    assembly = model.rootAssembly

    # 1. Build factory
    build_result = _handle_build_factory(config.get("building", config))
    if "error" in build_result:
        return {"step": "build_factory", "error": build_result["error"]}

    # 2. Create step
    time_period = config.get("collapse", {}).get("time_period", 3.0)
    _handle_create_explicit_step({"step_name": "Collapse", "time_period": time_period})

    # 3. Create ground and contact
    _handle_create_rigid_ground({})

    # 4. Apply gravity
    grav = config.get("collapse", {}).get("gravity", 9.8)
    _handle_apply_gravity({"magnitude": grav})

    # 5. Create cut zone
    cut_zone_refs = []
    cut_zone_height = config.get("collapse", {}).get("cut_zone_height")
    if cut_zone_height and cut_zone_height > 0:
        cut_result = _handle_create_cut_zone({"cut_height": cut_zone_height})
        cut_zone_refs = cut_result.get("cut_zone_refs", [])

    # 6. Write INP and inject
    cpus = config.get("job", {}).get("cpus", 4)
    mem = config.get("job", {}).get("memory", 80)
    precision_str = config.get("job", {}).get("precision", "single")
    use_double = precision_str.lower() == "double"
    prec = DOUBLE_PLUS_PACK if use_double else SINGLE

    mdb.Job(name="collapse_job", model="Model-1", numCpus=cpus, numDomains=cpus,
            multiprocessingMode=DEFAULT, explicitPrecision=prec, memory=mem,
            memoryUnits=PERCENTAGE)
    mdb.jobs["collapse_job"].writeInput()

    cwd_inp = os.path.join(os.getcwd(), "collapse_job.inp")
    target_inp = os.path.join(project_dir, "collapse_job.inp")
    inp_to_inject = cwd_inp if os.path.exists(cwd_inp) else target_inp

    if cut_zone_refs and os.path.exists(inp_to_inject):
        _handle_inject_cut_zone_inp({
            "inp_path": inp_to_inject,
            "cut_zone_refs": cut_zone_refs,
            "step_name": "Collapse",
        })

    if inp_to_inject != target_inp:
        shutil.copy2(inp_to_inject, target_inp)

    # 7. Submit
    mdb.jobs["collapse_job"].submit()
    mdb.jobs["collapse_job"].waitForCompletion()

    return {
        "job_name": "collapse_job",
        "build": build_result,
        "time_period": time_period,
        "cut_zone_elements": sum(n for _, _, n in cut_zone_refs),
        "inp_path": target_inp,
        "message": "Collapse simulation completed",
    }


def _tower_radius_at(z, height, base_radius, throat_radius, throat_elevation, top_radius):
    import math

    if z <= throat_elevation:
        r_ref, z_ref = base_radius, 0.0
    else:
        r_ref, z_ref = top_radius, height
    denom = r_ref * r_ref - throat_radius * throat_radius
    if abs(denom) < 1e-12:
        return throat_radius
    dz = z - throat_elevation
    dz_ref = z_ref - throat_elevation
    k = dz * dz * denom / (throat_radius * throat_radius * dz_ref * dz_ref)
    return throat_radius * math.sqrt(1.0 + k)


def _tower_stations(height, opening_bottom_elevation, opening_height):
    lo = max(0.0, opening_bottom_elevation - 1.0)
    hi = min(height, opening_bottom_elevation + opening_height + 1.0)
    stations = []
    z = 0.0
    while z < lo - 1e-9:
        stations.append(z)
        z += 1.0
    z = lo
    while z < hi - 1e-9:
        stations.append(z)
        z += 0.5
    z = hi
    while z < height - 1e-9:
        stations.append(z)
        z += 1.0
    if not stations or stations[-1] < height - 1e-9:
        stations.append(height)
    return stations


def _opening_element_labels(part, opening_bottom_elevation, opening_height,
                            opening_angle_deg, opening_center_angle_deg):
    import math

    z0 = opening_bottom_elevation
    z1 = opening_bottom_elevation + opening_height
    center = math.radians(opening_center_angle_deg)
    half = math.radians(opening_angle_deg / 2.0)
    labels = []
    for elem in part.elements:
        try:
            nodes = elem.getNodes()
            cx = sum(n.coordinates[0] for n in nodes) / len(nodes)
            cy = sum(n.coordinates[1] for n in nodes) / len(nodes)
            cz = sum(n.coordinates[2] for n in nodes) / len(nodes)
        except Exception:
            continue
        th = math.atan2(cz, cx)
        dth = abs(th - center)
        if dth > math.pi:
            dth = 2.0 * math.pi - dth
        if z0 - 1e-9 <= cy <= z1 + 1e-9 and dth <= half + 1e-9:
            labels.append(elem.label)
    return labels


def _handle_create_cooling_tower(args):
    name = args["name"]
    height = args.get("height", 70.0)
    base_radius = args.get("base_radius", 25.5)
    throat_radius = args.get("throat_radius", 14.5)
    throat_elevation = args.get("throat_elevation", 55.0)
    top_radius = args.get("top_radius", 15.599)
    wall_thickness = args.get("wall_thickness", 0.12)
    opening_bottom_elevation = args.get("opening_bottom_elevation", 11.0)
    opening_height = args.get("opening_height", 3.0)

    import math
    import mesh

    model = mdb.models["Model-1"] if "Model-1" in mdb.models else mdb.Model(name="Model-1")
    assembly = model.rootAssembly

    inst_name = f"{name}-1"
    if inst_name in assembly.instances:
        if "TowerBase" in assembly.sets:
            del assembly.sets["TowerBase"]
        del assembly.instances[inst_name]
    if name in model.parts:
        del model.parts[name]

    stations = _tower_stations(height, opening_bottom_elevation, opening_height)
    n_theta = 128
    part = model.Part(name=name, dimensionality=THREE_D, type=DEFORMABLE_BODY)
    node_by_label = {}
    for s, z in enumerate(stations):
        r = _tower_radius_at(z, height, base_radius, throat_radius, throat_elevation, top_radius)
        for j in range(n_theta):
            th = j * 2.0 * math.pi / n_theta
            label = s * n_theta + j + 1
            node_by_label[label] = part.Node(coordinates=(r * math.cos(th), z, r * math.sin(th)),
                                             label=label)
    for i in range(1, (len(stations) - 1) * n_theta + 1):
        row = (i - 1) // n_theta
        j = (i - 1) % n_theta
        jn = (j + 1) % n_theta
        part.Element(nodes=(node_by_label[row * n_theta + j + 1],
                            node_by_label[(row + 1) * n_theta + j + 1],
                            node_by_label[(row + 1) * n_theta + jn + 1],
                            node_by_label[row * n_theta + jn + 1]),
                     elemShape=mesh.QUAD4, label=i)
    try:
        assembly.Instance(name=inst_name, part=part, dependent=ON)
    except Exception:
        assembly.Instance(name=inst_name, part=part, dependent=INDEPENDENT)

    return {
        "part_name": name,
        "instance_name": inst_name,
        "total_elements": (len(stations) - 1) * n_theta,
        "total_nodes": len(stations) * n_theta,
        "n_meridional_stations": len(stations),
        "n_circumferential": n_theta,
        "wall_thickness": wall_thickness,
        "radius_base": round(_tower_radius_at(0.0, height, base_radius, throat_radius, throat_elevation, top_radius), 3),
        "radius_throat": round(throat_radius, 3),
        "radius_top": round(_tower_radius_at(height, height, base_radius, throat_radius, throat_elevation, top_radius), 3),
        "message": f"Cooling tower {name} created: hyperboloid S4R shell, "
                   f"{len(stations)} meridional stations x {n_theta} around, "
                   f"{(len(stations) - 1) * n_theta} elements",
    }


def _handle_assign_tower_materials(args):
    part_name = args["part_name"]
    wall_thickness = args.get("wall_thickness", 0.12)
    rebar_thickness = args.get("rebar_thickness", 0.0005)

    model = mdb.models["Model-1"]

    if "C30_Tower" not in model.materials:
        mat = model.Material(name="C30_Tower")
        mat.Density(table=((2500.0,),))
        mat.Elastic(table=((30.0e9, 0.2),))
        mat.ConcreteDamagedPlasticity(table=((30.0, 0.1, 1.16, 0.6667, 0.0),))
        mat.concreteDamagedPlasticity.ConcreteCompressionHardening(table=(
            (14.07e6, 0.0), (19.09e6, 4.0e-4), (20.10e6, 8.0e-4),
            (19.36e6, 1.2e-3), (17.92e6, 1.6e-3), (16.35e6, 2.0e-3),
            (14.84e6, 2.4e-3), (11.18e6, 3.6e-3), (8.40e6, 5.0e-3),
            (4.22e6, 1.0e-2),
        ))
        mat.concreteDamagedPlasticity.ConcreteTensionStiffening(table=(
            (2.01e6, 0.0), (1.52e6, 1.0e-4), (0.756e6, 3.0e-4),
            (0.4e6, 6.0e-4), (0.2e6, 1.0e-3),
        ))

    if "RebarSteel" not in model.materials:
        mat_s = model.Material(name="RebarSteel")
        mat_s.Density(table=((7850.0,),))
        mat_s.Elastic(table=((210.0e9, 0.3),))
        mat_s.Plastic(table=((335.0e6, 0.0), (436.0e6, 0.048)))

    t_conc = wall_thickness / 2.0
    # NOTE: 2026 kernel requires an ODD number of integration points per
    # SectionLayer; concrete layers 3, rebar layer 1.
    layers = ((t_conc, "C30_Tower", 0.0, 3),
              (rebar_thickness, "RebarSteel", 0.0, 1),
              (t_conc, "C30_Tower", 0.0, 3))
    section_name = f"Sec_{part_name}"
    if section_name not in model.sections:
        import section
        layup = tuple(section.SectionLayer(thickness=t, material=m,
                                           orientAngle=ang, numIntPts=npts)
                      for t, m, ang, npts in layers)
        model.CompositeShellSection(name=section_name, layup=layup)

    part = model.parts[part_name]
    set_name = f"All_{part_name}"
    if set_name not in part.sets:
        part.Set(name=set_name, elements=part.elements)
    part.SectionAssignment(region=part.sets[set_name], sectionName=section_name)

    return {
        "part_name": part_name,
        "section_name": section_name,
        "materials": ["C30_Tower", "RebarSteel"],
        "layers": [{"thickness": l[0], "material": l[1],
                    "orientation_deg": l[2], "integration_points": l[3]} for l in layers],
        "message": f"Composite shell section {section_name} assigned to {part_name}: "
                   f"{t_conc}m C30 + {rebar_thickness}m rebar + {t_conc}m C30",
    }


def _handle_mesh_tower(args):
    part_name = args["part_name"]
    opening_bottom_elevation = args.get("opening_bottom_elevation", 11.0)
    opening_height = args.get("opening_height", 3.0)
    opening_angle_deg = args.get("opening_angle_deg", 98.0)
    opening_center_angle_deg = args.get("opening_center_angle_deg", 0.0)

    model = mdb.models["Model-1"]
    part = model.parts[part_name]

    labels = _opening_element_labels(part, opening_bottom_elevation, opening_height,
                                     opening_angle_deg, opening_center_angle_deg)
    set_name = "OpeningHole"
    if set_name in part.sets:
        del part.sets[set_name]
    if labels:
        part.Set(elements=part.elements.sequenceFromLabels(labels=labels), name=set_name)

    return {
        "part_name": part_name,
        "total_elements": len(part.elements),
        "opening_elements": len(labels),
        "opening_set": set_name,
        "opening_elevation_range": [opening_bottom_elevation,
                                    opening_bottom_elevation + opening_height],
        "opening_angle_deg": opening_angle_deg,
        "message": f"Tower mesh {part_name}: {len(part.elements)} S4R elements, "
                   f"opening band removes {len(labels)} elements",
    }


def _tower_inp_surgery(text, part_name, opening_labels):
    import re

    opening_set = set(opening_labels)
    modified = False

    if "*Concrete Failure" not in text:
        mat_idx = text.find("*Material, name=C30_Tower")
        if mat_idx >= 0:
            search_from = mat_idx + len("*Material, name=C30_Tower")
            end_idx = len(text)
            for m_kw in re.finditer(r"\n\*(\w+)[, ]", text[search_from:]):
                kw = m_kw.group(1)
                if kw not in ("Density", "Elastic", "Concrete",
                              "ConcreteCompressionHardening", "ConcreteTensionStiffening"):
                    end_idx = search_from + m_kw.start()
                    break
            block = "\n*Concrete Failure\n0.005, 0.015, 0., 0.\n"
            text = text[:end_idx] + block + text[end_idx:]
            modified = True

    m = re.search(rf"^\*Part, name={re.escape(part_name)}\b.*$", text, re.MULTILINE)
    if m:
        p_start = m.start()
        p_end = text.find("*End Part", p_start)
        if p_end > p_start:
            block = text[p_start:p_end]
            lines = block.split("\n")
            out = []
            in_elem = False
            i = 0
            while i < len(lines):
                line = lines[i]
                stripped = line.strip()
                if stripped.startswith("*Elset"):
                    in_elem = False
                    tokens = []
                    is_gen = ", generate" in stripped.lower()
                    i += 1
                    while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("*"):
                        tokens.extend(t.strip() for t in lines[i].split(",") if t.strip())
                        i += 1
                    if is_gen and len(tokens) >= 3 and tokens[0].isdigit():
                        start, end, step = int(tokens[0]), int(tokens[1]), int(tokens[2])
                        kept = [str(l) for l in range(start, end + 1, step) if l not in opening_set]
                        out.append(line.replace(", generate", ""))
                    else:
                        kept = [t for t in tokens if t.isdigit() and int(t) not in opening_set]
                        out.append(line)
                    if len(kept) != len(tokens) or (is_gen and len(tokens) >= 3):
                        modified = True
                    for k in range(0, len(kept), 16):
                        chunk = kept[k:k + 16]
                        out.append(", ".join(chunk) + ("," if k + 16 < len(kept) else ""))
                    continue
                if in_elem:
                    if not stripped:
                        out.append(line)
                        i += 1
                        continue
                    if stripped.startswith("*"):
                        in_elem = False
                        out.append(line)
                        i += 1
                        continue
                    first = stripped.split(",")[0].strip()
                    if first.isdigit() and int(first) in opening_set:
                        modified = True
                        i += 1
                        continue
                    out.append(line)
                    i += 1
                    continue
                if stripped.startswith("*Element"):
                    in_elem = True
                out.append(line)
                i += 1
            text = text[:p_start] + "\n".join(out) + text[p_end:]

    return text, modified


class _FakeNode:
    def __init__(self, x, y, z):
        self.coordinates = (x, y, z)


class _FakeElem:
    def __init__(self, label, nodes):
        self.label = label
        self._nodes = nodes

    def getNodes(self):
        return self._nodes


class _FakePart:
    def __init__(self, elements):
        self.elements = elements


def _tower_opening_labels(n_theta, stations, height, base_radius, throat_radius,
                          throat_elevation, top_radius, opening_bottom_elevation,
                          opening_height, opening_angle_deg, opening_center_angle_deg):
    """Opening element labels from pure geometry (no CAE part needed)."""
    nodes = {}
    for s, z in enumerate(stations):
        r = _tower_radius_at(z, height, base_radius, throat_radius,
                             throat_elevation, top_radius)
        for j in range(n_theta):
            th = j * 2.0 * math.pi / n_theta
            nodes[s * n_theta + j + 1] = _FakeNode(r * math.cos(th), z, r * math.sin(th))
    elems = []
    for i in range(1, (len(stations) - 1) * n_theta + 1):
        row = (i - 1) // n_theta
        j = (i - 1) % n_theta
        jn = (j + 1) % n_theta
        conn = (row * n_theta + j + 1, (row + 1) * n_theta + j + 1,
                (row + 1) * n_theta + jn + 1, row * n_theta + jn + 1)
        elems.append(_FakeElem(i, [nodes[l] for l in conn]))
    labels = _opening_element_labels(_FakePart(elems), opening_bottom_elevation,
                                     opening_height, opening_angle_deg,
                                     opening_center_angle_deg)
    return sorted(labels)


def _tower_inp(params, stations, opening_labels):
    """Assemble the tower collapse INP directly from parameters — same cards as
    the validated host-assembled INP (run_tower_collapse.py): composite shell
    layers, CDP + rebar materials, fixed mass scaling dt=4e-4, ENCASTRE base,
    gravity ramp, general contact, full output. No CAE model involved, so prior
    create/assign/mesh calls cannot affect the result."""
    name = params["name"]
    n = params["n_theta"]
    height = params["height"]
    base_radius = params["base_radius"]
    throat_radius = params["throat_radius"]
    throat_elevation = params["throat_elevation"]
    top_radius = params["top_radius"]
    wall_thickness = params["wall_thickness"]
    settle_time = params["settle_time"]
    time_period = params["time_period"]
    L = []
    L.append("*Heading")
    L.append("** Cooling tower collapse -- kernel-assembled INP")
    L.append("*Preprint, echo=NO, model=NO, history=NO, contact=NO")
    L.append("")
    L.append("*Part, name=" + name)
    L.append("*Node")
    for s, z in enumerate(stations):
        r = _tower_radius_at(z, height, base_radius, throat_radius,
                             throat_elevation, top_radius)
        for j in range(n):
            th = j * 2.0 * math.pi / n
            L.append("{:>6d}, {:.6e}, {:.6e}, {:.6e}".format(
                s * n + j + 1, r * math.cos(th), z, r * math.sin(th)))
    total_elem = (len(stations) - 1) * n
    L.append("*Element, type=S4R")
    for i in range(1, total_elem + 1):
        row = (i - 1) // n
        j = (i - 1) % n
        jn = (j + 1) % n
        L.append("{:>6d}, {:>6d}, {:>6d}, {:>6d}, {:>6d}".format(
            i, row * n + j + 1, (row + 1) * n + j + 1,
            (row + 1) * n + jn + 1, row * n + jn + 1))
    L.append("*Elset, elset=All_Tower, generate")
    L.append("1, {}, 1".format(total_elem))
    L.append("*Elset, elset=OpeningHole")
    for k in range(0, len(opening_labels), 16):
        chunk = opening_labels[k:k + 16]
        L.append(", ".join(str(x) for x in chunk) +
                 ("," if k + 16 < len(opening_labels) else ""))
    ring_first = next(r for r in range(len(stations) - 1)
                      if 0.5 * (stations[r] + stations[r + 1]) >= height - 1.5 - 1e-9) * n + 1
    L.append("*Elset, elset=TopRing, generate")
    L.append("{}, {}, 1".format(ring_first, total_elem))
    L.append("*Shell Section, elset=All_Tower, composite")
    L.append("{:.4f}, 3, C30_Tower, 0.".format(wall_thickness / 2))
    L.append("0.0005, 1, RebarSteel, 0.")
    L.append("{:.4f}, 3, C30_Tower, 0.".format(wall_thickness / 2))
    L.append("*Shell Section, elset=TopRing, composite")
    L.append("0.1850, 3, C30_Tower, 0.")
    L.append("0.1850, 3, C30_Tower, 0.")
    L.append("*End Part")
    L.append("")
    L.append("*Part, name=Ground")
    nx, ny, nz = 37, 2, 37
    L.append("*Node")
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                idx = 1 + i + nx * (j + ny * k)
                L.append("{:>6d}, {:.6e}, {:.6e}, {:.6e}".format(
                    idx, i * 5.0, -2.0 + j * 2.0, -90.0 + k * 5.0))
    L.append("*Element, type=C3D8R")
    for i in range(nx - 1):
        for j in range(ny - 1):
            for k in range(nz - 1):
                def gl(x, y, z):
                    return 1 + x + nx * (y + ny * z)
                n1 = gl(i, j, k)
                n2 = gl(i + 1, j, k)
                n3 = gl(i + 1, j + 1, k)
                n4 = gl(i, j + 1, k)
                n5 = gl(i, j, k + 1)
                n6 = gl(i + 1, j, k + 1)
                n7 = gl(i + 1, j + 1, k + 1)
                n8 = gl(i, j + 1, k + 1)
                eidx = 1 + i + (nx - 1) * (j + (ny - 1) * k)
                L.append("{:>6d}, {:>6d}, {:>6d}, {:>6d}, {:>6d}, {:>6d}, "
                         "{:>6d}, {:>6d}, {:>6d}".format(
                             eidx, n1, n2, n3, n4, n5, n6, n7, n8))
    L.append("*Elset, elset=AllGround, generate")
    L.append("1, {}, 1".format((nx - 1) * (ny - 1) * (nz - 1)))
    L.append("*Solid Section, elset=AllGround, material=RIGID_MAT")
    L.append("*End Part")
    L.append("")
    L.append("*Assembly, name=Assembly-1")
    L.append("*Instance, name=" + name + "-1, part=" + name)
    L.append("*End Instance")
    L.append("*Instance, name=Ground-1, part=Ground")
    L.append("*End Instance")
    L.append("*Nset, nset=TowerBase, instance=" + name + "-1, generate")
    L.append("1, {}, 1".format(n))
    L.append("*Nset, nset=AllGroundNodes, instance=Ground-1, generate")
    L.append("1, {}, 1".format(nx * ny * nz))
    L.append("*End Assembly")
    L.append("")
    L.append("*Material, name=C30_Tower")
    L.append("*Density")
    L.append("2500.,")
    L.append("*Elastic")
    L.append("  3e+10, 0.2")
    L.append("*Concrete Damaged Plasticity")
    L.append("30., 0.1, 1.16, 0.6667, 0.")
    L.append("*Concrete Compression Hardening")
    for stress, strain in ((14.07e6, 0.0), (19.09e6, 4.0e-4), (20.10e6, 8.0e-4),
                           (19.36e6, 1.2e-3), (17.92e6, 1.6e-3), (16.35e6, 2.0e-3),
                           (14.84e6, 2.4e-3), (11.18e6, 3.6e-3), (8.40e6, 5.0e-3),
                           (4.22e6, 1.0e-2)):
        L.append("{:.4e}, {:.4e}".format(stress, strain))
    L.append("*Concrete Tension Stiffening")
    for stress, strain in ((2.01e6, 0.0), (1.52e6, 1.0e-4), (0.756e6, 3.0e-4),
                           (0.4e6, 6.0e-4), (0.2e6, 1.0e-3)):
        L.append("{:.4e}, {:.4e}".format(stress, strain))
    L.append("*Material, name=RebarSteel")
    L.append("*Density")
    L.append("7850.,")
    L.append("*Elastic")
    L.append("  2.1e+11, 0.3")
    L.append("*Plastic")
    L.append("3.35e+08, 0.")
    L.append("4.36e+08, 0.048")
    L.append("*Damage Initiation, criterion=DUCTILE")
    L.append("0.03, 0., 0.")
    L.append("*Damage Evolution, type=DISPLACEMENT")
    L.append("0.03")
    L.append("*Material, name=RIGID_MAT")
    L.append("*Density")
    L.append("7850.,")
    L.append("*Elastic")
    L.append("  2e+15, 0.3")
    L.append("")
    L.append("*Boundary")
    L.append("TowerBase, ENCASTRE")
    L.append("*Boundary")
    L.append("AllGroundNodes, ENCASTRE")
    L.append("")
    L.append("*Amplitude, name=GravRamp, definition=SMOOTH STEP")
    L.append("0., 0., 1., 1.")
    L.append("")
    for step_name, t in (("TowerGravity", settle_time), ("Collapse", time_period)):
        L.append("*Step, name={}, nlgeom=YES".format(step_name))
        L.append("*Dynamic, Explicit")
        L.append(", {:.1f}".format(t))
        L.append("*Fixed Mass Scaling, type=Below Min, dt=4e-4")
        if step_name == "TowerGravity":
            L.append("*Dload, amplitude=GravRamp")
            L.append(", GRAV, 9.8, 0., -1., 0.")
        if step_name == "Collapse":
            L.append("*Contact, op=NEW")
            L.append("*Contact Inclusions, ALL EXTERIOR")
        L.append("*Output, field")
        L.append("*Element Output, directions=YES")
        L.append("S, E, STATUS, STATUSMP, PEEQ,")
        L.append("*Node Output")
        L.append("U, V, A,")
        L.append("*Output, history, frequency=0")
        L.append("*End Step")
        L.append("")
    return "\n".join(L) + "\n"


def _move_concrete_failure_under_cdp(text):
    block_start = text.find("*Concrete Failure")
    if block_start < 0:
        return text
    block_end = text.find("*", block_start + len("*Concrete Failure"))
    if block_end < 0:
        return text
    block = text[block_start:block_end].strip("\n")
    text = text[:block_start] + text[block_end:]
    cdp = text.find("*Concrete Damaged Plasticity")
    if cdp < 0:
        return text[:block_start] + block + text[block_start:]
    data_end = text.find("*", cdp + len("*Concrete Damaged Plasticity"))
    if data_end < 0:
        return text[:block_start] + block + text[block_start:]
    return text[:data_end] + "\n" + block + "\n" + text[data_end:]


def _strip_empty_opening_elset(text):
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("*Elset, elset=OpeningHole"):
            j = i + 1
            while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith("*"):
                j += 1
            if j == i + 1:
                i = j
                continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _collapse_blank_lines(text):
    import re
    return re.sub(r"\n\s*\n", "\n", text)


def _resolve_launcher():
    launcher = os.environ.get("ABAQUS_LAUNCHER")
    if launcher and os.path.isfile(launcher):
        return launcher
    sdir = os.environ.get("ABAQUS_DRIVER_SERVERDIR")
    if sdir:
        env_json = os.path.join(os.path.dirname(sdir), "abaqus_environment_server",
                                "abaqus_env.json")
        try:
            with open(env_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            launcher = data.get("paths", {}).get("launcher")
            if launcher and os.path.isfile(launcher):
                return launcher
        except Exception:
            pass
    raise RuntimeError("Abaqus launcher not found (ABAQUS_LAUNCHER env unset)")


def _cleanup_job_files(job_name):
    import shutil
    import time
    archive = os.path.join(os.getcwd(), "archive_" + time.strftime("%Y%m%d_%H%M%S"))
    moved = False
    for f in os.listdir(os.getcwd()):
        if f.startswith(job_name + ".") and not f.endswith(".inp"):
            src = os.path.join(os.getcwd(), f)
            try:
                if not moved:
                    os.makedirs(archive, exist_ok=True)
                    moved = True
                shutil.move(src, os.path.join(archive, f))
            except OSError:
                try:
                    os.remove(src)
                except OSError:
                    pass


def _submit_job_from_inp(inp_path, job_name, cpus, memory):
    """Submit the INP asynchronously. PRIMARY path: direct launcher subprocess
    (host-verified async mechanism). JobFromInputFile+submit is NOT used by
    default — in this 2026 build submit() blocks until the analysis ends,
    which would defeat the async design. Kernel submit is the last-resort
    fallback when the launcher cannot be resolved."""
    global _SOLVER_PROC
    try:
        launcher = _resolve_launcher()
        cmd = '{} job={} cpus={} memory={}'.format('"' + launcher + '"', job_name, cpus, memory)
        _SOLVER_PROC = subprocess.Popen(
            cmd, cwd=os.getcwd(), shell=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "subprocess"
    except Exception:
        if job_name in mdb.jobs:
            del mdb.jobs[job_name]
        mdb.JobFromInputFile(
            name=job_name, inputFileName=inp_path, numCpus=cpus, numDomains=cpus,
            multiprocessingMode=DEFAULT, explicitPrecision=SINGLE,
            memory=memory, memoryUnits=PERCENTAGE)
        mdb.jobs[job_name].submit()
        return "kernel"


def _handle_setup_tower_collapse(args):
    """Generate the tower collapse INP directly from parameters and submit the
    job ASYNCHRONOUSLY — returns immediately with job_id + estimated duration.
    Poll progress with the get_collapse_status server tool (reads .sta)."""
    params = {
        "name": args.get("name", "Tower"),
        "n_theta": int(args.get("n_theta", 128)),
        "height": float(args.get("height", 70.0)),
        "base_radius": float(args.get("base_radius", 25.5)),
        "throat_radius": float(args.get("throat_radius", 14.5)),
        "throat_elevation": float(args.get("throat_elevation", 55.0)),
        "top_radius": float(args.get("top_radius", 15.599)),
        "wall_thickness": float(args.get("wall_thickness", 0.12)),
        "opening_bottom_elevation": float(args.get("opening_bottom_elevation", 11.0)),
        "opening_height": float(args.get("opening_height", 3.0)),
        "opening_angle_deg": float(args.get("opening_angle_deg", 98.0)),
        "opening_center_angle_deg": float(args.get("opening_center_angle_deg", 0.0)),
        "settle_time": float(args.get("settle_time", 1.0)),
        "time_period": float(args.get("time_period", 12.0)),
        "cpus": int(args.get("cpus", 4)),
        "memory": int(args.get("memory_percent", 80)),
    }
    workdir = os.getcwd()
    job_name = TOWER_JOB_NAME

    stations = _tower_stations(params["height"], params["opening_bottom_elevation"],
                               params["opening_height"])
    opening_labels = _tower_opening_labels(
        params["n_theta"], stations, params["height"], params["base_radius"],
        params["throat_radius"], params["throat_elevation"], params["top_radius"],
        params["opening_bottom_elevation"], params["opening_height"],
        params["opening_angle_deg"], params["opening_center_angle_deg"])

    _cleanup_job_files(job_name)
    text = _tower_inp(params, stations, opening_labels)
    text, modified = _tower_inp_surgery(text, params["name"], opening_labels)
    text = _move_concrete_failure_under_cdp(text)
    text = _strip_empty_opening_elset(text)
    text = _collapse_blank_lines(text)
    inp_path = os.path.join(workdir, job_name + ".inp")
    with open(inp_path, "w", encoding="utf-8") as f:
        f.write(text)

    n_elements = (len(stations) - 1) * params["n_theta"]
    submit_method = _submit_job_from_inp(inp_path, job_name, params["cpus"],
                                         params["memory"])

    # run 8 baseline: n_theta=128 solved in ~400s; floor at 300s — element-count
    # linear extrapolation understated actual wall time by ~2.3x
    est = max(300.0, 400.0 * params["n_theta"] / 128.0)
    with open(os.path.join(workdir, job_name + ".estimate.json"), "w",
              encoding="utf-8") as f:
        json.dump({
            "n_theta": params["n_theta"],
            "n_elements": n_elements,
            "estimated_duration_s": round(est, 1),
            "estimated_duration_range": [round(est * 0.5, 1), round(est * 1.5, 1)],
        }, f)
    return {
        "job_id": job_name,
        "status": "submitted",
        "submit_method": submit_method,
        "estimated_duration_s": round(est, 1),
        "estimated_duration_range": [round(est * 0.5, 1), round(est * 1.5, 1)],
        "odb_path": os.path.join(workdir, job_name + ".odb"),
        "inp_path": inp_path,
        "workdir": workdir,
        "n_theta": params["n_theta"],
        "n_elements": n_elements,
        "opening_elements": len(opening_labels),
        "inp_modified": modified,
        "tower": {
            "name": params["name"], "height": params["height"],
            "base_radius": params["base_radius"], "throat_radius": params["throat_radius"],
            "throat_elevation": params["throat_elevation"], "top_radius": params["top_radius"],
            "wall_thickness": params["wall_thickness"],
            "opening_bottom_elevation": params["opening_bottom_elevation"],
            "opening_height": params["opening_height"],
            "opening_angle_deg": params["opening_angle_deg"],
        },
        "message": ("Tower collapse job submitted asynchronously ({} elements, "
                    "n_theta={}, via {}). Estimated solve {:.0f}s (range {:.0f}-{:.0f}s). "
                    "Poll get_collapse_status(job_id={}, wait_seconds=150) until "
                    "completed, then extract_collapse_frames + render_collapse_video.").format(
                        n_elements, params["n_theta"], submit_method, est, est * 0.5,
                        est * 1.5, job_name),
    }


def _handle_extract_collapse_frames(args):
    """Extract tower nodal displacement frames from the collapse ODB into
    data.npz (X/conn/t/U) for video rendering — ported from
    scripts/extract_tower_frames.py, parameterized."""
    import numpy as np
    from odbAccess import openOdb

    workdir = os.getcwd()
    odb_path = args.get("odb_path") or os.path.join(workdir, TOWER_JOB_NAME + ".odb")
    if not os.path.isfile(odb_path):
        return {"error": "ODB not found at {} — wait for get_collapse_status=completed "
                         "before extracting".format(odb_path)}
    sdir = os.environ.get("ABAQUS_DRIVER_SERVERDIR")
    out_dir = args.get("out_dir") or (
        os.path.join(os.path.dirname(os.path.dirname(sdir)), "scripts", "_tower_frames")
        if sdir else os.path.join(workdir, "_tower_frames"))
    n_targets = int(args.get("n_targets", 50))
    t_start = float(args.get("t_start", 0.5))
    t_end = float(args.get("t_end", 13.0))
    if n_targets < 2 or n_targets > 200:
        return {"error": "n_targets must be in [2, 200]"}
    out_path = os.path.join(out_dir, "data.npz")
    report_path = os.path.join(out_dir, "extract_report.txt")

    odb = openOdb(odb_path, readOnly=True)
    report = []
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
    report.append("instance=%s" % inst.name)

    nodes = inst.nodes
    labels = [nd.label for nd in nodes]
    idx = {lab: i for i, lab in enumerate(labels)}
    X = np.array([nd.coordinates for nd in nodes], dtype=np.float64)
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

    targets = np.linspace(t_start, t_end, n_targets)
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

    U = np.zeros((n_targets, len(nodes), 3))
    for j, (tt, i) in enumerate(zip(targets, idxs)):
        a = max(0, i - 1)
        b = min(len(ft) - 1, i)
        if b == a:
            alpha = 0.0
        else:
            alpha = float(np.clip((tt - ft[a]) / (ft[b] - ft[a]), 0.0, 1.0))
        U[j] = (1.0 - alpha) * Ucache[a] + alpha * Ucache[b]

    os.makedirs(out_dir, exist_ok=True)
    np.savez_compressed(out_path, X=X, conn=conn, t=targets, U=U)
    report.append("saved=%s" % out_path)
    report.append("shapes X=%s conn=%s t=%s U=%s" % (
        X.shape, conn.shape, targets.shape, U.shape))
    report.append("t=%.3f..%.3f" % (targets[0], targets[-1]))
    report.append("EXTRACT_DONE")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(report) + "\n")
    odb.close()

    return {
        "odb_path": odb_path,
        "out_dir": out_dir,
        "npz_path": out_path,
        "report_path": report_path,
        "nodes": len(nodes),
        "elements": len(els),
        "n_targets": n_targets,
        "frames_written": int(U.shape[0]),
        "t_range": [round(float(targets[0]), 3), round(float(targets[-1]), 3)],
        "message": "Extracted {} frames x {} nodes -> {} ({} bytes)".format(
            U.shape[0], len(nodes), out_path, os.path.getsize(out_path)),
    }


def _handle_stop_collapse(args):
    """Terminate a running collapse solve: kill the kernel job (or the fallback
    solver process) and remove the .lck lock so the job cannot restart."""
    job_name = args.get("job_id", TOWER_JOB_NAME)
    actions = []
    try:
        if job_name in mdb.jobs:
            mdb.jobs[job_name].kill()
            actions.append("kernel job killed")
    except Exception as e:
        actions.append("kernel kill failed: %s" % e)
    global _SOLVER_PROC
    if _SOLVER_PROC is not None:
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(_SOLVER_PROC.pid)],
                           capture_output=True, timeout=15)
            actions.append("solver process killed")
        except Exception as e:
            actions.append("process kill failed: %s" % e)
        _SOLVER_PROC = None
    lck = os.path.join(os.getcwd(), job_name + ".lck")
    if os.path.exists(lck):
        try:
            os.remove(lck)
            actions.append("lck removed")
        except OSError:
            pass
    return {"job_id": job_name, "status": "terminated", "actions": actions}


# ── Tool registry ──────────────────────────────────────────────────────────

HANDLERS = {
    "create_rectangular_column": _handle_create_rectangular_column,
    "create_truss": _handle_create_truss,
    "create_slab": _handle_create_slab,
    "assign_concrete_cdp": _handle_assign_concrete_cdp,
    "mesh_part": _handle_mesh_part,
    "create_explicit_step": _handle_create_explicit_step,
    "apply_gravity": _handle_apply_gravity,
    "create_rigid_ground": _handle_create_rigid_ground,
    "submit_job": _handle_submit_job,
    "get_max_displacement": _handle_get_max_displacement,
    "plot_displacement_curve": _handle_plot_displacement_curve,
    "create_cut_zone": _handle_create_cut_zone,
    "inject_cut_zone_inp": _handle_inject_cut_zone_inp,
    "build_factory": _handle_build_factory,
    "setup_collapse": _handle_setup_collapse,
    "create_cooling_tower": _handle_create_cooling_tower,
    "assign_tower_materials": _handle_assign_tower_materials,
    "mesh_tower": _handle_mesh_tower,
    "setup_tower_collapse": _handle_setup_tower_collapse,
    "extract_collapse_frames": _handle_extract_collapse_frames,
    "stop_collapse": _handle_stop_collapse,
}


# ── Stdio JSON-RPC main loop ────────────────────────────────────────────────

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        req_id = request.get("id", "")
        tool_name = request.get("tool", "")
        arguments = request.get("arguments", {})

        handler = HANDLERS.get(tool_name)
        if not handler:
            resp = {"id": req_id, "error": f"Unknown tool: {tool_name}"}
        else:
            try:
                result = handler(arguments)
                resp = {"id": req_id, "success": True, "result": result}
            except Exception as e:
                resp = {"id": req_id, "error": f"{tool_name}: {str(e)}"}
                traceback.print_exc(file=sys.stderr)

        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
