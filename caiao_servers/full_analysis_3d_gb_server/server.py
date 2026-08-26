"""
╔══════════════════════════════════════════════════════════════════════╗
║  CAIAO Server: Pipeline B2 — 3D Full Structural Analysis (GB50017)  ║
║                                                                     ║
║  Merges: SteelFrameGenerator.generate_frame →                      ║
║          OpenSeesRunner.run_analysis (matrix method / OpenSeesPy)   ║
║          → SteelCodeCheck.check_code (GB50017-2017)                 ║
║          → select_critical_3d                                       ║
║                                                                     ║
║  External engine: sibling repo "steel-frame-design" (pure NumPy)    ║
║  (STEEL_FRAME_DESIGN_ROOT env var overrides the default location)   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import json
import os
import sys
from typing import Any

import numpy as np

_server_dir = os.path.dirname(os.path.abspath(__file__))
_caiao_servers = os.path.dirname(_server_dir)
_repo_root = os.path.dirname(_caiao_servers)
if _caiao_servers not in sys.path:
    sys.path.insert(0, _caiao_servers)

_ext_root = os.environ.get("STEEL_FRAME_DESIGN_ROOT") or os.path.join(
    os.path.dirname(_repo_root), "steel-frame-design"
)
if not os.path.isdir(_ext_root):
    raise ImportError(
        f"steel-frame-design not found at '{_ext_root}'. "
        "Clone it as a sibling of this repo (D:\\GitHub Dev\\steel-frame-design) "
        "or set STEEL_FRAME_DESIGN_ROOT to its root directory."
    )
if _ext_root not in sys.path:
    sys.path.insert(0, _ext_root)

from servers.defaults import BUILTIN_MATERIALS, BUILTIN_SECTIONS
from servers.opensees_runner import OpenSeesRunner
from servers.steel_code_check import SteelCodeCheck
from servers.steel_frame_generator import SteelFrameGenerator

from full_analysis_3d_server.server import _select_critical_3d

from mcp.server import Server
import mcp.types as types

server = Server("full_analysis_3d_gb_server")


def _run_pipeline(arguments: dict) -> dict[str, Any]:
    """3D full analysis: generate 3D steel frame → solve → GB50017 check → critical column."""
    n_bays_x = int(arguments.get("num_bays_x", 3))
    n_bays_y = int(arguments.get("num_bays_y", 3))
    n_stories = int(arguments.get("num_stories", 4))
    span_x = float(arguments.get("span_x_m", 6.0))
    span_y = float(arguments.get("span_y_m", 6.0))
    story_h = float(arguments.get("story_height_m", 3.0))
    material_type = arguments.get("material_type", "steel")
    steel_grade = arguments.get("steel_grade", "Q355")
    dead_load_kpa = float(arguments.get("dead_load_kpa", 5.0))
    live_load_kpa = float(arguments.get("live_load_kpa", 2.0))
    lateral_load_kN = float(arguments.get("lateral_load_kN", 0.0))
    base_support = arguments.get("base_support", "fixed")
    column_section = arguments.get("column_section", "HW350x350x12x19")
    beam_section = arguments.get("beam_section", "HM340x250x9x14")

    if material_type != "steel":
        return {"status": "error", "error": (
            f"material_type '{material_type}' is not supported by full_analysis_3d_gb "
            "(steel + GB50017 only). Use quick_analysis (2D) or full_analysis_3d (legacy 3D) "
            "for non-steel materials."
        )}
    if steel_grade not in BUILTIN_MATERIALS:
        return {"status": "error", "error": (
            f"steel_grade '{steel_grade}' is not in the built-in material library. "
            f"Valid grades: {sorted(BUILTIN_MATERIALS)}"
        )}

    model = SteelFrameGenerator().generate_frame({
        "grid_x": [span_x] * n_bays_x,
        "grid_y": [span_y] * n_bays_y,
        "num_stories": n_stories,
        "story_heights": [story_h] * n_stories,
        "column_section": column_section,
        "beam_section": beam_section,
        "material": steel_grade,
        "name": f"{n_bays_x}x{n_bays_y} {n_stories}-story steel frame",
    })
    if "error" in model:
        return {"status": "error", "error": model["error"]}

    # ── 四工况（外部单位 kN·m，z 向上）────────────────────────
    # Dead/Live/Total 按引擎惯例施加为梁上均布荷载（tributary = 半跨），
    # Wind 为顶层节点水平集中力；Total = 1.0D + 1.0L。
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

    wind_loads = []
    if lateral_load_kN > 0:
        wind_loads = [{"node_id": n["id"], "values": {"P": lateral_load_kN / len(top_nodes)},
                       "direction": "global_x"} for n in top_nodes]
    load_cases = [
        {"name": "Dead", "loads": beam_uniform_loads(dead_load_kpa)},
        {"name": "Live", "loads": beam_uniform_loads(live_load_kpa)},
        {"name": "Wind", "loads": wind_loads},
        {"name": "Total", "loads": beam_uniform_loads(dead_load_kpa + live_load_kpa)},
    ]
    restraints = [1, 1, 1, 1, 1, 1] if base_support == "fixed" else [1, 1, 1, 0, 0, 0]
    bc = [{"node_id": n["id"], "restraints": restraints} for n in base_nodes]
    loaded_model = {"model": model, "boundary_conditions": bc, "load_cases": load_cases}

    runner = OpenSeesRunner()
    analysis_by_case: dict[str, dict] = {}
    for lc in load_cases:
        ar = runner.run_analysis({"loaded_model": loaded_model, "load_case_name": lc["name"]})
        if "error" in ar:
            return {"status": "error", "error": f"{lc['name']}: {ar['error']}"}
        analysis_by_case[lc["name"]] = ar

    checker = SteelCodeCheck()
    check = checker.check_code({
        "model": model,
        "analysis_results": [analysis_by_case[c] for c in ("Dead", "Live", "Wind")],
        "load_case_name": "Total",
    })
    if "error" in check:
        return {"status": "error", "error": check["error"]}
    stress_by_elem = {int(e["id"]): e.get("stress_ratio", 0.0) for e in check["elements"]}

    # ── 回填映射：ext(x,y,z↑) → uni(x, y=z↑, z=y)；id 减 1；kN→N ──
    sec_e = BUILTIN_MATERIALS[steel_grade]["E"]
    elements = []
    for el in model["elements"]:
        sec = BUILTIN_SECTIONS[el["section_id"]]
        elements.append({
            "id": el["id"] - 1,
            "node_i": el["node_i"] - 1,
            "node_j": el["node_j"] - 1,
            "type": el["type"],
            "section": el["section_id"],
            "E": sec_e * 1000,
            "A": sec["A"],
            "Iy": sec["Iy"],
            "Iz": sec["Ix"],
            "J": (sec["Ix"] + sec["Iy"]) / 2,
        })

    supports = [{"node_id": n["id"] - 1, "type": base_support} for n in base_nodes]

    loads = []
    nodal_fy: dict[int, float] = {}
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
        f_end = -(dead_load_kpa + live_load_kpa) * trib * length / 2
        nodal_fy[n_i["id"]] = nodal_fy.get(n_i["id"], 0.0) + f_end
        nodal_fy[n_j["id"]] = nodal_fy.get(n_j["id"], 0.0) + f_end
    for n in model["nodes"]:
        fx = lateral_load_kN / len(top_nodes) if (lateral_load_kN > 0 and abs(n["z"] - top_z) < 0.001) else 0.0
        fy = nodal_fy.get(n["id"], 0.0)
        if fx or fy:
            loads.append({"node_id": n["id"] - 1, "Fx": round(fx * 1000, 4),
                          "Fy": round(fy * 1000, 4), "Fz": 0.0})

    def uni_displacements(ar: dict) -> list[dict]:
        return [{"node_id": n["id"] - 1, "ux": ar["displacements"][str(n["id"])][0],
                 "uy": ar["displacements"][str(n["id"])][2],
                 "uz": ar["displacements"][str(n["id"])][1]} for n in model["nodes"]]

    force_by_elem = {}
    for el in model["elements"]:
        eid = el["id"]
        ns = [analysis_by_case[c]["element_forces"].get(str(eid), {}).get("N", 0.0)
              for c in ("Dead", "Live", "Wind", "Total")]
        force_by_elem[eid] = {"N": ns[3], "Nmax": max(ns), "Nmin": min(ns)}

    total_ar = analysis_by_case["Total"]
    solver = total_ar.get("engine", "Matrix Method")
    elem_forces = [{"element_id": eid - 1,
                    "N": round(f["N"] * 1000, 4),
                    "Nmax": round(f["Nmax"] * 1000, 4),
                    "Nmin": round(f["Nmin"] * 1000, 4),
                    "stress_ratio": round(stress_by_elem.get(eid, 0.0), 6)}
                   for eid, f in sorted(force_by_elem.items())]
    analysis = {
        "node_displacements": uni_displacements(total_ar),
        "element_forces": elem_forces,
        "max_displacement": float(total_ar["summary"]["max_displacement"]),
        "max_axial_force": max(max(abs(f["N"]), abs(f["Nmax"]), abs(f["Nmin"])) * 1000
                               for f in force_by_elem.values()),
        "solver": solver,
        "load_case": "Total",
    }

    structure = {
        "nodes": [{"id": n["id"] - 1, "x": n["x"], "y": n["z"], "z": n["y"]}
                  for n in model["nodes"]],
        "elements": elements,
        "loads": loads,
        "supports": supports,
        "metadata": {
            "dimension": "3d",
            "num_nodes": len(model["nodes"]),
            "num_elements": len(model["elements"]),
            "num_columns": len([e for e in model["elements"] if e["type"] == "column"]),
            "num_beams": len([e for e in model["elements"] if e["type"] == "beam"]),
            "num_base_nodes": len(base_nodes),
        },
    }

    critical = _select_critical_3d(structure, analysis)

    code_elements = [{
        "element_id": e["id"] - 1,
        "type": e["type"],
        "section": e["section"],
        "story": e["story"],
        "node_i": e["node_i"] - 1,
        "node_j": e["node_j"] - 1,
        "slenderness_ratio": e["slenderness_ratio"],
        "stress_ratio": e["stress_ratio"],
        "stability_ratio": e["stability_ratio"],
        "deflection_ratio": e["deflection_ratio"],
        "pass": e["pass"],
        "messages": e["messages"],
    } for e in check["elements"]]

    return {
        "status": "complete",
        "pipeline": "full_analysis_3d_gb",
        "dimension": "3d",
        "structure": structure,
        "analysis": analysis,
        "critical_element": critical,
        "code_check": {
            "elements": code_elements,
            "summary": {
                "total_elements": check["summary"]["total_elements"],
                "passed": check["summary"]["passed"],
                "failed": check["summary"]["failed"],
                "max_stress_ratio": check["summary"]["max_stress_ratio"],
                "max_deflection_ratio": check["summary"]["max_deflection_ratio"],
            },
        },
        "metadata": {
            "pipeline": "full_analysis_3d_gb",
            "dimension": "3d",
            "engine": solver,
            "description": "Merge: SteelFrameGenerator → OpenSeesRunner (matrix method / OpenSeesPy) → SteelCodeCheck (GB50017-2017) → select_critical_3d",
            "config": {
                "num_bays_x": n_bays_x,
                "num_bays_y": n_bays_y,
                "num_stories": n_stories,
                "span_x_m": span_x,
                "span_y_m": span_y,
                "story_height_m": story_h,
                "material_type": material_type,
                "steel_grade": steel_grade,
                "base_support": base_support,
                "dead_load_kpa": dead_load_kpa,
                "live_load_kpa": live_load_kpa,
                "lateral_load_kN": lateral_load_kN,
                "column_section": column_section,
                "beam_section": beam_section,
            },
            "sections_used": [column_section, beam_section],
        },
    }


def _run_removal(arguments: dict) -> dict[str, Any]:
    """Member removal re-analysis: re-solve an existing baseline structure minus removed members.

    Input `structure` is the uni-format block returned by full_analysis_3d_gb (y-up, 0-based,
    kN→N). Removed members are excluded, orphan nodes purged, and the remaining structure is
    re-solved for Dead/Live/Wind/Total. A singular solve (mechanism) → status "unstable"
    (collapse risk); otherwise GB50017 check + critical element on the remaining members.
    """
    structure = arguments.get("structure")
    removed = [int(i) for i in arguments.get("removed_member_ids", [])]
    steel_grade = arguments.get("steel_grade", "Q355")
    dead_load_kpa = float(arguments.get("dead_load_kpa", 5.0))
    live_load_kpa = float(arguments.get("live_load_kpa", 2.0))

    try:
        if not isinstance(structure, dict) or not structure.get("nodes") or not structure.get("elements"):
            return {"status": "error", "error": (
                "structure must be a non-empty uni-format structure (output of full_analysis_3d_gb)")}
        if not removed:
            return {"status": "error", "error": "removed_member_ids must be a non-empty list of element ids"}
        if steel_grade not in BUILTIN_MATERIALS:
            return {"status": "error", "error": (
                f"steel_grade '{steel_grade}' is not in the built-in material library. "
                f"Valid grades: {sorted(BUILTIN_MATERIALS)}")}

        elem_ids = {e["id"] for e in structure["elements"]}
        invalid = [i for i in removed if i not in elem_ids]
        if invalid:
            return {"status": "error", "error": (
                f"removed_member_ids not found in structure.elements: {invalid}")}
        removed_set = set(removed)

        # ── keep survivors, purge degree-0 nodes ─────────────────────
        remaining_elements = [e for e in structure["elements"] if e["id"] not in removed_set]
        referenced = set()
        for e in remaining_elements:
            referenced.add(e["node_i"])
            referenced.add(e["node_j"])
        remaining_nodes = [n for n in structure["nodes"] if n["id"] in referenced]
        purged = sorted(n["id"] for n in structure["nodes"] if n["id"] not in referenced)
        remaining_loads = [ld for ld in structure.get("loads", []) if ld["node_id"] in referenced]
        remaining_supports = [s for s in structure.get("supports", []) if s["node_id"] in referenced]
        remaining_ids = sorted(e["id"] for e in remaining_elements)

        # ── uni(y-up, 0-based, N) → ext(z-up, 1-based, kN) ──────────
        ext_nodes = [{"id": n["id"] + 1, "x": n["x"], "y": n["z"], "z": n["y"]}
                     for n in remaining_nodes]
        ext_elements = [{"id": e["id"] + 1, "node_i": e["node_i"] + 1, "node_j": e["node_j"] + 1,
                         "type": e.get("type", "beam"), "section_id": e["section"]}
                        for e in remaining_elements]
        ext_sections = []
        for name in sorted({e["section"] for e in remaining_elements}):
            if name in BUILTIN_SECTIONS:
                ext_sections.append({"id": name, "material_id": steel_grade, **BUILTIN_SECTIONS[name]})
            else:
                src = next(e for e in remaining_elements if e["section"] == name)
                ext_sections.append({"id": name, "material_id": steel_grade,
                                     "A": src["A"], "Ix": src["Iz"], "Iy": src["Iy"], "J": src["J"]})
        ext_materials = [{"id": steel_grade, **BUILTIN_MATERIALS[steel_grade]}]
        ext_bc = [{"node_id": s["node_id"] + 1,
                   "restraints": [1, 1, 1, 0, 0, 0] if s.get("type") == "hinged" else [1, 1, 1, 1, 1, 1]}
                  for s in remaining_supports]

        def _ext_load(ld: dict) -> dict:
            return {"node_id": ld["node_id"] + 1,
                    "values": {"Px": ld.get("Fx", 0.0) / 1000.0,
                               "Py": ld.get("Fz", 0.0) / 1000.0,
                               "Pz": ld.get("Fy", 0.0) / 1000.0}}

        denom = dead_load_kpa + live_load_kpa
        dead_ratio = dead_load_kpa / denom if denom > 0 else 1.0

        def _vertical_case(scale: float) -> list[dict]:
            out = []
            for ld in remaining_loads:
                pz = ld.get("Fy", 0.0) / 1000.0 * scale
                if abs(pz) > 1e-9:
                    out.append({"node_id": ld["node_id"] + 1,
                                "values": {"Px": 0.0, "Py": 0.0, "Pz": pz}})
            return out

        wind_loads = [{"node_id": ld["node_id"] + 1, "values": {"Px": ld.get("Fx", 0.0) / 1000.0}}
                      for ld in remaining_loads if abs(ld.get("Fx", 0.0)) > 1e-6]
        load_cases = [
            {"name": "Dead", "loads": _vertical_case(dead_ratio)},
            {"name": "Live", "loads": _vertical_case(1.0 - dead_ratio)},
            {"name": "Wind", "loads": wind_loads},
            {"name": "Total", "loads": [_ext_load(ld) for ld in remaining_loads]},
        ]

        ext_model = {"nodes": ext_nodes, "elements": ext_elements,
                     "sections": ext_sections, "materials": ext_materials}
        loaded_model = {"model": ext_model, "boundary_conditions": ext_bc, "load_cases": load_cases}

        runner = OpenSeesRunner()
        analysis_by_case: dict[str, dict] = {}
        failed = None
        if not remaining_elements:
            failed = {"failed_case": "Total", "reason": "no members remain after removal"}
        else:
            # ── mechanism probe ────────────────────────────────────
            # The matrix-method fallback returns garbage instead of raising on a
            # singular system, so stability is verified on the constrained K first.
            K, dof_map, _, _ = runner._assemble_system(ext_model)
            constrained = set()
            for bc_item in ext_bc:
                start = dof_map.get(bc_item["node_id"])
                if start is None:
                    continue
                for i, r in enumerate(bc_item["restraints"]):
                    if r:
                        constrained.add(start + i)
            free = [d for d in range(K.shape[0]) if d not in constrained]
            if free:
                evals = np.linalg.eigvalsh(K[np.ix_(free, free)])
                if np.min(np.abs(evals)) <= 1e-8 * np.max(np.abs(evals)):
                    failed = {"failed_case": "Total",
                              "reason": "structure is a mechanism: singular stiffness matrix after member removal (collapse risk)"}
        if failed is None:
            for lc in load_cases:
                ar = runner.run_analysis({"loaded_model": loaded_model, "load_case_name": lc["name"]})
                if "error" in ar:
                    failed = {"failed_case": lc["name"], "reason": ar["error"]}
                    break
                analysis_by_case[lc["name"]] = ar

        def _remaining_structure() -> dict:
            return {
                "nodes": [dict(n) for n in remaining_nodes],
                "elements": [dict(e) for e in remaining_elements],
                "loads": [dict(ld) for ld in remaining_loads],
                "supports": [dict(s) for s in remaining_supports],
                "metadata": {
                    "dimension": "3d",
                    "num_nodes": len(remaining_nodes),
                    "num_elements": len(remaining_elements),
                    "num_columns": len([e for e in remaining_elements if e.get("type") == "column"]),
                    "num_beams": len([e for e in remaining_elements if e.get("type") == "beam"]),
                    "num_base_nodes": len([n for n in remaining_nodes if n["y"] < 0.001]),
                },
            }

        base_payload = {
            "removed_member_ids": removed,
            "remaining_member_ids": remaining_ids,
            "purged_node_ids": purged,
        }
        if failed is not None:
            return {"status": "unstable", **base_payload,
                    "structure": _remaining_structure(), "unstable": failed}

        # ── all cases solved: GB50017 check + result mapping (ext→uni) ──
        checker = SteelCodeCheck()
        check = checker.check_code({
            "model": ext_model,
            "analysis_results": [analysis_by_case[c] for c in ("Dead", "Live", "Wind")],
            "load_case_name": "Total",
        })
        if "error" in check:
            return {"status": "error", "error": check["error"]}
        stress_by_elem = {int(e["id"]): e.get("stress_ratio", 0.0) for e in check["elements"]}

        def uni_displacements(ar: dict) -> list[dict]:
            return [{"node_id": n["id"] - 1, "ux": ar["displacements"][str(n["id"])][0],
                     "uy": ar["displacements"][str(n["id"])][2],
                     "uz": ar["displacements"][str(n["id"])][1]} for n in ext_nodes]

        force_by_elem = {}
        for el in ext_elements:
            eid = el["id"]
            ns = [analysis_by_case[c]["element_forces"].get(str(eid), {}).get("N", 0.0)
                  for c in ("Dead", "Live", "Wind", "Total")]
            force_by_elem[eid] = {"N": ns[3], "Nmax": max(ns), "Nmin": min(ns)}

        total_ar = analysis_by_case["Total"]
        solver = total_ar.get("engine", "Matrix Method")
        elem_forces = [{"element_id": eid - 1,
                        "N": round(f["N"] * 1000, 4),
                        "Nmax": round(f["Nmax"] * 1000, 4),
                        "Nmin": round(f["Nmin"] * 1000, 4),
                        "stress_ratio": round(stress_by_elem.get(eid, 0.0), 6)}
                       for eid, f in sorted(force_by_elem.items())]
        analysis = {
            "node_displacements": uni_displacements(total_ar),
            "element_forces": elem_forces,
            "max_displacement": float(total_ar["summary"]["max_displacement"]),
            "max_axial_force": max((max(abs(f["N"]), abs(f["Nmax"]), abs(f["Nmin"])) * 1000
                                    for f in force_by_elem.values()), default=0.0),
            "solver": solver,
            "load_case": "Total",
        }

        structure = _remaining_structure()
        critical = _select_critical_3d(structure, analysis)

        code_elements = [{
            "element_id": e["id"] - 1,
            "type": e["type"],
            "section": e["section"],
            "story": e["story"],
            "node_i": e["node_i"] - 1,
            "node_j": e["node_j"] - 1,
            "slenderness_ratio": e["slenderness_ratio"],
            "stress_ratio": e["stress_ratio"],
            "stability_ratio": e["stability_ratio"],
            "deflection_ratio": e["deflection_ratio"],
            "pass": e["pass"],
            "messages": e["messages"],
        } for e in check["elements"]]

        return {
            "status": "complete",
            **base_payload,
            "structure": structure,
            "analysis": analysis,
            "critical_element": critical,
            "code_check": {
                "elements": code_elements,
                "summary": {
                    "total_elements": check["summary"]["total_elements"],
                    "passed": check["summary"]["passed"],
                    "failed": check["summary"]["failed"],
                    "max_stress_ratio": check["summary"]["max_stress_ratio"],
                    "max_deflection_ratio": check["summary"]["max_deflection_ratio"],
                },
            },
        }
    except Exception as e:
        return {"status": "error", "error": f"full_analysis_3d_gb_remove failed: {e}"}


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="full_analysis_3d_gb",
            description="3D full structural analysis (GB50017): generate a 3D steel frame → solve each load case with the matrix displacement method or OpenSeesPy → run per-member GB50017-2017 code check → identify the critical column. One atomic call. Returns structure (UnifiedFrame topology), analysis results (Total case), GB50017 code check, and critical element.",
            inputSchema={
                "type": "object",
                "properties": {
                    "num_bays_x": {"type": "integer", "default": 3},
                    "num_bays_y": {"type": "integer", "default": 3},
                    "num_stories": {"type": "integer", "default": 4},
                    "span_x_m": {"type": "number", "default": 6.0},
                    "span_y_m": {"type": "number", "default": 6.0},
                    "story_height_m": {"type": "number", "default": 3.0},
                    "material_type": {"type": "string", "default": "steel", "enum": ["steel", "concrete"]},
                    "steel_grade": {"type": "string", "default": "Q355", "enum": ["Q235", "Q355", "Q390", "Q420"]},
                    "dead_load_kpa": {"type": "number", "default": 5.0},
                    "live_load_kpa": {"type": "number", "default": 2.0},
                    "lateral_load_kN": {"type": "number", "default": 0.0},
                    "base_support": {"type": "string", "default": "fixed", "enum": ["fixed", "hinged"]},
                    "column_section": {"type": "string", "default": "HW350x350x12x19"},
                    "beam_section": {"type": "string", "default": "HM340x250x9x14"},
                },
                "required": [],
            },
        ),
        types.Tool(
            name="full_analysis_3d_gb_remove",
            description="Member removal re-analysis (progressive demolition): take an EXISTING baseline structure (uni format returned by full_analysis_3d_gb) plus a list of member ids to remove, purge now-orphaned nodes, re-solve Dead/Live/Wind/Total on the remaining members (matrix displacement method / OpenSeesPy), and report whether the structure is still stable or loses stability (singular solve = collapse risk), with redistributed forces + GB50017-2017 per-member code check + critical element for the remaining members.",
            inputSchema={
                "type": "object",
                "properties": {
                    "structure": {"type": "object"},
                    "removed_member_ids": {"type": "array", "items": {"type": "integer"}},
                    "steel_grade": {"type": "string", "default": "Q355", "enum": ["Q235", "Q355", "Q390", "Q420"]},
                    "dead_load_kpa": {"type": "number", "default": 5.0},
                    "live_load_kpa": {"type": "number", "default": 2.0},
                },
                "required": ["structure", "removed_member_ids"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "full_analysis_3d_gb":
        result = _run_pipeline(arguments)
    elif name == "full_analysis_3d_gb_remove":
        result = _run_removal(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [types.TextContent(type="text", text=json.dumps(result, default=str))]


if __name__ == "__main__":
    from mcp.server.stdio import stdio_server
    import asyncio

    async def main():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(main())
