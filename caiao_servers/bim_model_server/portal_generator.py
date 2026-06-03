"""Portal frame generator — single-bay and multi-bay portal frames.

Output format matches FrameStructure: {nodes, elements, loads, supports, metadata}.
Supports steel portal frames with tapered or uniform sections.
"""

from __future__ import annotations
import math
from typing import Any

STEEL_GRADES: dict[str, dict[str, float]] = {
    "Q235": {"fy": 235e6, "E": 206e9, "nu": 0.3, "rho": 7850},
    "Q355": {"fy": 355e6, "E": 206e9, "nu": 0.3, "rho": 7850},
    "Q420": {"fy": 420e6, "E": 206e9, "nu": 0.3, "rho": 7850},
}

# Standard UK/US portal frame sections (hot-rolled)
PORTAL_SECTIONS: dict[str, dict[str, float]] = {
    "UB203x133x25":  {"h": 0.203, "b": 0.133, "A": 3.18e-3, "Iy": 2.34e-5, "Iz": 5.89e-6},
    "UB254x146x37":  {"h": 0.254, "b": 0.146, "A": 4.75e-3, "Iy": 5.54e-5, "Iz": 1.24e-5},
    "UB305x165x46":  {"h": 0.305, "b": 0.165, "A": 5.86e-3, "Iy": 9.90e-5, "Iz": 2.14e-5},
    "UB356x171x57":  {"h": 0.356, "b": 0.171, "A": 7.23e-3, "Iy": 1.60e-4, "Iz": 3.34e-5},
    "UB406x178x67":  {"h": 0.406, "b": 0.178, "A": 8.53e-3, "Iy": 2.43e-4, "Iz": 4.69e-5},
    "UB457x191x89":  {"h": 0.457, "b": 0.191, "A": 1.14e-2, "Iy": 4.10e-4, "Iz": 7.82e-5},
    "UB533x210x109": {"h": 0.533, "b": 0.210, "A": 1.39e-2, "Iy": 6.68e-4, "Iz": 1.24e-4},
    "UB610x229x125": {"h": 0.610, "b": 0.229, "A": 1.59e-2, "Iy": 9.95e-4, "Iz": 1.77e-4},
    "UB686x254x152": {"h": 0.686, "b": 0.254, "A": 1.94e-2, "Iy": 1.64e-3, "Iz": 2.85e-4},
}

# Rafter sections (typically shallower than columns)
RAFTER_SECTIONS: dict[str, dict[str, float]] = {
    "UB254x146x37":  {"h": 0.254, "b": 0.146, "A": 4.75e-3, "Iy": 5.54e-5, "Iz": 1.24e-5},
    "UB305x165x46":  {"h": 0.305, "b": 0.165, "A": 5.86e-3, "Iy": 9.90e-5, "Iz": 2.14e-5},
    "UB356x171x57":  {"h": 0.356, "b": 0.171, "A": 7.23e-3, "Iy": 1.60e-4, "Iz": 3.34e-5},
    "UB406x178x67":  {"h": 0.406, "b": 0.178, "A": 8.53e-3, "Iy": 2.43e-4, "Iz": 4.69e-5},
    "UB457x191x89":  {"h": 0.457, "b": 0.191, "A": 1.14e-2, "Iy": 4.10e-4, "Iz": 7.82e-5},
}

# Purlin sections (cold-formed Z/C sections)
PURLIN_SECTIONS: dict[str, dict[str, float]] = {
    "Z150x1.5": {"A": 5.25e-4, "Iy": 1.98e-6, "Iz": 3.60e-7},
    "Z200x2.0": {"A": 8.80e-4, "Iy": 5.52e-6, "Iz": 8.60e-7},
    "Z250x2.5": {"A": 1.33e-3, "Iy": 1.32e-5, "Iz": 1.78e-6},
    "Z300x3.0": {"A": 1.88e-3, "Iy": 2.67e-5, "Iz": 3.25e-6},
}


def _recommend_column_section(span: float, eave_height: float) -> str:
    if eave_height <= 6:
        return "UB254x146x37" if span <= 15 else "UB305x165x46"
    elif eave_height <= 9:
        return "UB356x171x57" if span <= 20 else "UB406x178x67"
    elif eave_height <= 12:
        return "UB457x191x89" if span <= 25 else "UB533x210x109"
    return "UB686x254x152"


def _recommend_rafter_section(span: float) -> str:
    if span <= 12: return "UB254x146x37"
    elif span <= 18: return "UB305x165x46"
    elif span <= 24: return "UB356x171x57"
    elif span <= 30: return "UB406x178x67"
    elif span <= 36: return "UB457x191x89"
    return "UB457x191x89"


def generate_portal_frame(
    num_bays: int = 1,
    span_m: float = 18.0,
    eave_height_m: float = 6.0,
    roof_pitch_deg: float = 5.0,
    bay_spacing_m: float = 6.0,
    steel_grade: str = "Q355",
    load_kN_per_m2: float = 0.5,
    crane_capacity_tons: float = 0.0,
) -> dict[str, Any]:
    steel = STEEL_GRADES.get(steel_grade, STEEL_GRADES["Q355"])
    col_sec_name = _recommend_column_section(span_m, eave_height_m)
    raft_sec_name = _recommend_rafter_section(span_m)
    col_sec = PORTAL_SECTIONS[col_sec_name]
    raft_sec = RAFTER_SECTIONS[raft_sec_name]

    pitch_rad = math.radians(roof_pitch_deg)
    half_span = span_m / 2
    ridge_rise = half_span * math.tan(pitch_rad)

    nodes: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    loads: list[dict[str, Any]] = []
    supports: list[dict[str, Any]] = []

    nid = 1
    eid = 1

    # For each frame (each bay line in 3D)
    # In 2D mode just one frame; in 3D we create multiple frames spaced by bay_spacing
    n_frames = max(1, num_bays)
    for frame_idx in range(n_frames):
        z = frame_idx * bay_spacing_m

        # Nodes per frame: 2 columns + 2 eaves + 1 ridge
        # Left column base, left eave, ridge, right eave, right column base
        base_offset = nid

        # Left column base
        nodes.append({"id": nid, "x": -half_span, "y": 0.0, "z": z})
        nid += 1
        # Left eave
        nodes.append({"id": nid, "x": -half_span, "y": eave_height_m, "z": z})
        nid += 1
        # Ridge
        nodes.append({"id": nid, "x": 0.0, "y": eave_height_m + ridge_rise, "z": z})
        nid += 1
        # Right eave
        nodes.append({"id": nid, "x": half_span, "y": eave_height_m, "z": z})
        nid += 1
        # Right column base
        nodes.append({"id": nid, "x": half_span, "y": 0.0, "z": z})
        nid += 1

        col_adjust = base_offset

        # Columns
        elements.append({
            "id": eid, "node_i": col_adjust, "node_j": col_adjust + 1,
            "E": steel["E"], "A": col_sec["A"],
            "Iy": col_sec["Iy"], "Iz": col_sec["Iz"], "J": col_sec["Iy"] * 0.3,
            "type": "column",
            "section": col_sec_name,
        })
        eid += 1
        elements.append({
            "id": eid, "node_i": col_adjust + 3, "node_j": col_adjust + 4,
            "E": steel["E"], "A": col_sec["A"],
            "Iy": col_sec["Iy"], "Iz": col_sec["Iz"], "J": col_sec["Iy"] * 0.3,
            "type": "column",
            "section": col_sec_name,
        })
        eid += 1

        # Left rafter (eave to ridge)
        elements.append({
            "id": eid, "node_i": col_adjust + 1, "node_j": col_adjust + 2,
            "E": steel["E"], "A": raft_sec["A"],
            "Iy": raft_sec["Iy"], "Iz": raft_sec["Iz"], "J": raft_sec["Iy"] * 0.3,
            "type": "rafter",
            "section": raft_sec_name,
        })
        eid += 1

        # Right rafter (ridge to eave)
        elements.append({
            "id": eid, "node_i": col_adjust + 2, "node_j": col_adjust + 3,
            "E": steel["E"], "A": raft_sec["A"],
            "Iy": raft_sec["Iy"], "Iz": raft_sec["Iz"], "J": raft_sec["Iy"] * 0.3,
            "type": "rafter",
            "section": raft_sec_name,
        })
        eid += 1

        # Supports: pinned bases
        supports.append({"node_id": col_adjust, "type": "pin"})
        supports.append({"node_id": col_adjust + 4, "type": "pin"})

        # Gravity loads on rafters
        rafter_len = math.sqrt(half_span ** 2 + ridge_rise ** 2)
        load_per_node = load_kN_per_m2 * bay_spacing_m * half_span * 1000 / 2  # N
        loads.append({"node_id": col_adjust + 1, "Fx": 0.0, "Fy": -load_per_node})
        loads.append({"node_id": col_adjust + 3, "Fx": 0.0, "Fy": -load_per_node})
        loads.append({"node_id": col_adjust + 2, "Fx": 0.0, "Fy": -load_per_node * 2})

    total_mass = 0
    for el in elements:
        l = _element_length(el, nodes)
        total_mass += steel["rho"] * el["A"] * l

    if num_bays <= 1:
        dim = "2d"
    else:
        dim = "3d"

    return {
        "nodes": nodes,
        "elements": elements,
        "loads": loads,
        "supports": supports,
        "metadata": {
            "type": "portal_frame",
            "dimension": dim,
            "num_bays": num_bays,
            "span_m": span_m,
            "eave_height_m": eave_height_m,
            "roof_pitch_deg": roof_pitch_deg,
            "bay_spacing_m": bay_spacing_m,
            "steel_grade": steel_grade,
            "nodes_total": len(nodes),
            "elements_total": len(elements),
            "column_section": col_sec_name,
            "rafter_section": raft_sec_name,
            "estimated_weight_kg": round(total_mass, 1),
        },
        "materials": {
            "steel": {
                "grade": steel_grade,
                "fy_MPa": steel["fy"] / 1e6,
                "E_GPa": steel["E"] / 1e9,
                "sections": {
                    "column": {"name": col_sec_name, **col_sec},
                    "rafter": {"name": raft_sec_name, **raft_sec},
                },
            },
        },
    }


def _element_length(el: dict, nodes: list[dict]) -> float:
    n1 = next((n for n in nodes if n["id"] == el["node_i"]), None)
    n2 = next((n for n in nodes if n["id"] == el["node_j"]), None)
    if not n1 or not n2:
        return 0.0
    dx = n2["x"] - n1["x"]
    dy = n2["y"] - n1["y"]
    dz = (n2.get("z", 0) or 0) - (n1.get("z", 0) or 0)
    return math.sqrt(dx * dx + dy * dy + dz * dz)
