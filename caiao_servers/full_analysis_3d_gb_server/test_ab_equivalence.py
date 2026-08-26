"""Solver A/B equivalence test (implementation plan §4.2).

Same model (generation + loading logic of full_analysis_3d_gb_server) solved
by two engines:
  A) steel-frame-design Matrix Method  (opensees_runner, _OPENSEES_AVAILABLE=False)
  B) PyNiteFEA                          (pynite_server._run_pynite, plus a direct
                                         model build for the uniform member-load case,
                                         since _run_pynite only supports node loads)

Compares per-node translational displacements (ext[ux,uy,uz] ↔ uni[ux,uz,uy])
and per-element axial forces (uni element_id = ext element_id - 1), tolerance 1e-3.

Known conversion-layer difference: _run_pynite hardcodes material E = 210 GPa
while the GB material library uses E = 206 GPa (Q355). Displacements scale
exactly as 1/E, so an E-normalized comparison is reported alongside the raw one.
Axial force distributions are E-independent (uniform E in both models).
"""

import os
import sys

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

import numpy as np

from full_analysis_3d_gb_server.server import _run_pipeline  # noqa: F401  (validates ext import path)
import servers.opensees_runner as opensees_runner
from servers.opensees_runner import OpenSeesRunner
from servers.steel_frame_generator import SteelFrameGenerator
from servers.defaults import BUILTIN_SECTIONS, BUILTIN_MATERIALS

from pynite_server.server import _run_pynite
from Pynite.FEModel3D import FEModel3D

TOL = 1e-3
E_MATRIX = BUILTIN_MATERIALS["Q355"]["E"] * 1000.0   # 206 GPa (Pa)
E_PYNITE = 210e9                                      # hardcoded in _run_pynite


def build_ext_model(args: dict) -> tuple[dict, dict, dict]:
    """Replicates the new server's generation + load-case construction (external format)."""
    n_bays_x = int(args.get("num_bays_x", 3))
    n_bays_y = int(args.get("num_bays_y", 3))
    n_stories = int(args.get("num_stories", 4))
    span_x = float(args.get("span_x_m", 6.0))
    span_y = float(args.get("span_y_m", 6.0))
    story_h = float(args.get("story_height_m", 3.0))
    dead_load_kpa = float(args.get("dead_load_kpa", 5.0))
    live_load_kpa = float(args.get("live_load_kpa", 2.0))
    lateral_load_kN = float(args.get("lateral_load_kN", 0.0))
    base_support = args.get("base_support", "fixed")
    column_section = args.get("column_section", "HW350x350x12x19")
    beam_section = args.get("beam_section", "HM340x250x9x14")
    steel_grade = args.get("steel_grade", "Q355")

    model = SteelFrameGenerator().generate_frame({
        "grid_x": [span_x] * n_bays_x,
        "grid_y": [span_y] * n_bays_y,
        "num_stories": n_stories,
        "story_heights": [story_h] * n_stories,
        "column_section": column_section,
        "beam_section": beam_section,
        "material": steel_grade,
        "name": "A/B test frame",
    })
    assert "error" not in model, model

    base_nodes = [n for n in model["nodes"] if n["z"] < 0.001]
    top_z = max(n["z"] for n in model["nodes"])
    top_nodes = [n for n in model["nodes"] if abs(n["z"] - top_z) < 0.001]

    def beam_uniform_loads(kpa: float) -> list[dict]:
        loads = []
        for el in model["elements"]:
            if el["type"] != "beam":
                continue
            n_i = next(n for n in model["nodes"] if n["id"] == el["node_i"])
            n_j = next(n for n in model["nodes"] if n["id"] == el["node_j"])
            if min(n_i["z"], n_j["z"]) < 0.001:
                continue
            dx = abs(n_j["x"] - n_i["x"])
            dy = abs(n_j["y"] - n_i["y"])
            trib = (span_y / 2) if dx > dy else (span_x / 2)
            loads.append({"element_id": el["id"], "type": "uniform",
                          "direction": "global_z", "values": {"q": -kpa * trib}})
        return loads

    def shear_only_nodal(kpa: float) -> list[dict]:
        """Equivalent end-shear-only nodal loads (as the server's display loads use)."""
        loads = []
        for el in model["elements"]:
            if el["type"] != "beam":
                continue
            n_i = next(n for n in model["nodes"] if n["id"] == el["node_i"])
            n_j = next(n for n in model["nodes"] if n["id"] == el["node_j"])
            if min(n_i["z"], n_j["z"]) < 0.001:
                continue
            dx = abs(n_j["x"] - n_i["x"])
            dy = abs(n_j["y"] - n_i["y"])
            trib = (span_y / 2) if dx > dy else (span_x / 2)
            length = ((n_j["x"] - n_i["x"]) ** 2 + (n_j["y"] - n_i["y"]) ** 2) ** 0.5
            f_end = -kpa * trib * length / 2
            loads.append({"node_id": n_i["id"], "values": {"P": f_end}, "direction": "global_z"})
            loads.append({"node_id": n_j["id"], "values": {"P": f_end}, "direction": "global_z"})
        return loads

    wind_loads = []
    if lateral_load_kN > 0:
        wind_loads = [{"node_id": n["id"], "values": {"P": lateral_load_kN / len(top_nodes)},
                       "direction": "global_x"} for n in top_nodes]

    load_cases = [
        {"name": "Total", "loads": beam_uniform_loads(dead_load_kpa + live_load_kpa)},
        {"name": "NodalGravity", "loads": shear_only_nodal(dead_load_kpa + live_load_kpa)},
        {"name": "Wind", "loads": wind_loads},
    ]
    restraints = [1, 1, 1, 1, 1, 1] if base_support == "fixed" else [1, 1, 1, 0, 0, 0]
    bc = [{"node_id": n["id"], "restraints": restraints} for n in base_nodes]
    return model, {"model": model, "boundary_conditions": bc, "load_cases": load_cases}, bc


def matrix_solve(loaded_model: dict, case_name: str) -> dict:
    saved = opensees_runner._OPENSEES_AVAILABLE
    opensees_runner._OPENSEES_AVAILABLE = False
    try:
        return OpenSeesRunner().run_analysis({"loaded_model": loaded_model, "load_case_name": case_name})
    finally:
        opensees_runner._OPENSEES_AVAILABLE = saved


def unified_structure(model: dict, base_support: str) -> dict:
    """ext → UnifiedFrame (same mapping as the new server, no loads)."""
    base_nodes = [n for n in model["nodes"] if n["z"] < 0.001]
    sec_e = BUILTIN_MATERIALS["Q355"]["E"]
    elements = []
    for el in model["elements"]:
        sec = BUILTIN_SECTIONS[el["section_id"]]
        elements.append({
            "id": el["id"] - 1,
            "node_i": el["node_i"] - 1,
            "node_j": el["node_j"] - 1,
            "type": el["type"],
            "E": sec_e * 1000,
            "A": sec["A"],
            "Iy": sec["Iy"],
            "Iz": sec["Ix"],
            "J": (sec["Ix"] + sec["Iy"]) / 2,
        })
    return {
        "nodes": [{"id": n["id"] - 1, "x": n["x"], "y": n["z"], "z": n["y"]}
                  for n in model["nodes"]],
        "elements": elements,
        "loads": [],
        "supports": [{"node_id": n["id"] - 1, "type": base_support} for n in base_nodes],
    }


def ext_nodal_loads_unified(loads: list[dict], model: dict) -> list[dict]:
    """Convert ext node loads (kN, direction-based) to uni node loads (N, component-based)."""
    uni = []
    for ld in loads:
        nid = ld["node_id"] - 1
        P = ld["values"]["P"]
        d = ld["direction"]
        if d == "global_x":
            uni.append({"node_id": nid, "Fx": P * 1000, "Fy": 0, "Fz": 0})
        elif d == "global_y":
            uni.append({"node_id": nid, "Fx": 0, "Fy": 0, "Fz": P * 1000})
        elif d == "global_z":
            uni.append({"node_id": nid, "Fx": 0, "Fy": P * 1000, "Fz": 0})
    return uni


def pynite_direct_solve(model: dict, structure: dict, member_q_n_m: dict, node_loads: list[dict]) -> dict:
    """Direct PyNite build: exact same E as the matrix engine, plus uniform member loads.

    Mirrors _run_pynite's model construction; E/G are taken from the GB material
    library so the model is physically identical to the matrix-method model.
    """
    mat = BUILTIN_MATERIALS["Q355"]
    E = mat["E"] * 1000.0
    G = E / (2 * (1 + mat["nu"]))
    m = FEModel3D()
    m.add_material("Steel", E, G, mat["nu"], 7850)
    for n in structure["nodes"]:
        m.add_node(str(n["id"]), n["x"], n["y"], n["z"])
    for el in structure["elements"]:
        sec_name = f"Section_{el['id']}"
        m.add_section(sec_name, el["A"], el["Iy"], el["Iz"], el["J"])
        m.add_member(str(el["id"]), str(el["node_i"]), str(el["node_j"]), "Steel", sec_name)
    for sup in structure["supports"]:
        if sup["type"] == "fixed":
            m.def_support(str(sup["node_id"]), True, True, True, True, True, True)
        else:
            m.def_support(str(sup["node_id"]), True, True, True, False, False, False)
    for ld in node_loads:
        for d in ("Fx", "Fy", "Fz"):
            if ld.get(d):
                m.add_node_load(str(ld["node_id"]), d, ld[d])
    for eid, w in member_q_n_m.items():
        m.add_member_dist_load(str(eid), "FY", w, w, case="Case 1")
    m.analyze_linear(log=False, check_stability=True, sparse=True)

    disps = {}
    for n in structure["nodes"]:
        node = m.nodes[str(n["id"])]
        disps[n["id"]] = [float(node.DX["Combo 1"]), float(node.DY["Combo 1"]), float(node.DZ["Combo 1"])]
    axial = {}
    for el in structure["elements"]:
        axial[el["id"]] = float(m.members[str(el["id"])].max_axial())
    return {"displacements": disps, "axial": axial}


def rel_err(a: float, b: float, floor: float = 1e-6) -> float:
    denom = max(abs(a), abs(b))
    if denom < floor:
        return 0.0 if abs(a - b) < floor else abs(a - b) / floor
    return abs(a - b) / denom


ZERO_FLOOR = 1e-5  # m: components below this are treated as exactly zero (solver noise)


def compare_displacements(matrix: dict, pynite: dict, model: dict, label: str,
                          normalize_e: bool = False) -> tuple[float, int, int]:
    """matrix: {ext node id: [ux,uy,uz,...]}; pynite: {uni node id: [ux,uy,uz]}."""
    max_rel = 0.0
    checked = 0
    violations = 0
    for n in model["nodes"]:
        uni_id = n["id"] - 1
        a = matrix[str(n["id"])]           # ext [ux, uy, uz]
        b = pynite[uni_id]                 # uni [ux, uy, uz]
        # ext[ux,uy,uz] ↔ uni[ux, uz, uy]
        pairs = ((a[0], b[0]), (a[2], b[1]), (a[1], b[2]))
        for ax, bx in pairs:
            if normalize_e:
                bx = bx * E_PYNITE / E_MATRIX
            if max(abs(ax), abs(bx)) < ZERO_FLOOR:
                if abs(ax - bx) > ZERO_FLOOR:
                    violations += 1
                continue
            r = rel_err(ax, bx)
            checked += 1
            max_rel = max(max_rel, r)
            if r > TOL:
                violations += 1
    print(f"    [{label}] displacements: max_rel={max_rel:.3e}  checked={checked}  violations={violations}")
    return max_rel, checked, violations


def compare_axial(matrix: dict, pynite_axial: dict, model: dict, label: str) -> tuple[float, int, int]:
    """matrix N: tension + (kN); PyNite N: compression + (N) → flip before comparing."""
    max_rel = 0.0
    checked = 0
    violations = 0
    pairs = []
    for el in model["elements"]:
        a = float(matrix[str(el["id"])]["N"]) * 1000.0   # kN → N, tension +
        b = -float(pynite_axial[el["id"] - 1])           # flip PyNite compression + convention
        pairs.append((a, b))
    scale = max(max(abs(a), abs(b)) for a, b in pairs)
    floor = 0.01 * scale   # elements at <1% of the max axial are physically zero (e.g. beams under transverse load)
    for a, b in pairs:
        if max(abs(a), abs(b)) < floor:
            continue
        checked += 1
        r = rel_err(a, b)
        max_rel = max(max_rel, r)
        if r > TOL:
            violations += 1
    print(f"    [{label}] axial forces: max_rel={max_rel:.3e}  checked={checked}  violations={violations}")
    return max_rel, checked, violations


def run_case(model: dict, loaded_model: dict, base_support: str, case_name: str) -> bool:
    """Solve one load case with both engines and compare."""
    print(f"  case: {case_name}")
    matrix = matrix_solve(loaded_model, case_name)
    assert "error" not in matrix, matrix.get("error")
    assert matrix["engine"] == "Matrix Method", matrix.get("engine")
    ok = True

    structure = unified_structure(model, base_support)
    loads = [lc for lc in loaded_model["load_cases"] if lc["name"] == case_name][0]["loads"]

    if case_name == "Total":
        # Uniform member loads: PyNite direct build with identical E (no normalization needed)
        node_loads = []
        member_q = {}
        for ld in loads:
            if "node_id" in ld:
                node_loads.extend(ext_nodal_loads_unified([ld], model))
            else:
                el = next(e for e in model["elements"] if e["id"] == ld["element_id"])
                n_i = next(n for n in model["nodes"] if n["id"] == el["node_i"])
                n_j = next(n for n in model["nodes"] if n["id"] == el["node_j"])
                L = ((n_j["x"] - n_i["x"]) ** 2 + (n_j["y"] - n_i["y"]) ** 2) ** 0.5
                member_q[el["id"] - 1] = ld["values"]["q"] * 1000.0  # kN/m → N/m
        pynite = pynite_direct_solve(model, structure, member_q, node_loads)
        _, _, v = compare_displacements(matrix["displacements"], pynite["displacements"],
                                        model, "Total (exact E, uniform loads)", normalize_e=False)
        _, _, va = compare_axial(matrix["element_forces"], pynite["axial"], model, "Total")
        ok = ok and v == 0 and va == 0
    else:
        uni_loads = ext_nodal_loads_unified(loads, model)
        struct = dict(structure)
        struct["loads"] = uni_loads
        pr = _run_pynite(struct)
        assert "error" not in pr, pr.get("error")
        pynite_disps = {d["node_id"]: [d["ux"], d["uy"], d["uz"]] for d in pr["node_displacements"]}
        pynite_axial = {e["element_id"]: e["N"] for e in pr["element_forces"]}
        # Raw comparison documents the E=210 vs E=206 conversion-layer difference
        _, _, v_raw = compare_displacements(matrix["displacements"], pynite_disps, model, f"{case_name} (raw, E=210GPa)")
        _, _, v_norm = compare_displacements(matrix["displacements"], pynite_disps, model, f"{case_name} (E-normalized)", normalize_e=True)
        _, _, va = compare_axial(matrix["element_forces"], pynite_axial, model, case_name)
        ok = ok and v_norm == 0 and va == 0
        # Report the observed E ratio to confirm the displacement deviation is purely E-scaled
        ratios = []
        for n in model["nodes"]:
            a = matrix["displacements"][str(n["id"])]
            b = pynite_disps[n["id"] - 1]
            for ax, bx in ((a[0], b[0]), (a[2], b[1]), (a[1], b[2])):
                if abs(ax) > 1e-4:
                    ratios.append(ax / bx)
        if ratios:
            print(f"    [{case_name}] observed displacement ratio matrix/pynite: "
                  f"min={min(ratios):.5f} max={max(ratios):.5f} (expect ~{E_PYNITE / E_MATRIX:.5f})")
    return ok


def main() -> None:
    configs = [
        ("default 3x3x4 (symmetric, vertical only)", {}),
        ("asymmetric 2x1x2 + lateral 50kN", {"num_bays_x": 2, "num_bays_y": 1, "num_stories": 2,
                                             "lateral_load_kN": 50.0}),
    ]
    failed_cases = 0
    total_ok = True
    for label, args in configs:
        print(f"\n== {label} ==")
        model, loaded_model, _ = build_ext_model(args)
        base_support = args.get("base_support", "fixed")
        for case_name in ("Total", "NodalGravity", "Wind"):
            try:
                ok = run_case(model, loaded_model, base_support, case_name)
            except AssertionError as e:
                ok = False
                print(f"    [{case_name}] ERROR: {e}")
            if not ok:
                failed_cases += 1
                total_ok = False
    print(f"\nA/B equivalence: {'ALL PASS' if total_ok else f'{failed_cases} CASE(S) FAILED'} "
          f"(tolerance {TOL})")
    sys.exit(0 if total_ok else 1)


if __name__ == "__main__":
    main()
