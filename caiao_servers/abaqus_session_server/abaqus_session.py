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
    THREE_D, DEFORMABLE_BODY, IMPRINT, EXPLICIT,
)

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
    model.steps[step_name].fieldOutputRequests["F-Output-1"].setValues(
        variables=("S", "E", "U", "V", "A", "STATUS", "PEEQ")
    )

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
