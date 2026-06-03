"""Truss structure generator — Pratt, Howe, and Warren truss configurations.

Output format matches FrameStructure: {nodes, elements, loads, supports, metadata}.
"""

from __future__ import annotations
import math
from typing import Any

TRUSS_TYPES = ["pratt", "howe", "warren"]

STEEL_GRADES: dict[str, dict[str, float]] = {
    "Q235": {"fy": 235e6, "E": 206e9, "nu": 0.3, "rho": 7850},
    "Q355": {"fy": 355e6, "E": 206e9, "nu": 0.3, "rho": 7850},
    "Q420": {"fy": 420e6, "E": 206e9, "nu": 0.3, "rho": 7850},
}

# Simplified tubular section database for truss members
TUBE_SECTIONS: dict[str, dict[str, float]] = {
    "TUB60x4":  {"d": 0.060, "t": 0.004, "A": 7.04e-4, "I": 2.86e-7},
    "TUB76x4":  {"d": 0.076, "t": 0.004, "A": 9.05e-4, "I": 5.94e-7},
    "TUB89x4":  {"d": 0.089, "t": 0.004, "A": 1.07e-3, "I": 9.73e-7},
    "TUB89x5":  {"d": 0.089, "t": 0.005, "A": 1.32e-3, "I": 1.17e-6},
    "TUB102x5": {"d": 0.102, "t": 0.005, "A": 1.52e-3, "I": 1.79e-6},
    "TUB102x6": {"d": 0.102, "t": 0.006, "A": 1.81e-3, "I": 2.08e-6},
    "TUB114x5": {"d": 0.114, "t": 0.005, "A": 1.71e-3, "I": 2.55e-6},
    "TUB114x6": {"d": 0.114, "t": 0.006, "A": 2.04e-3, "I": 2.98e-6},
    "TUB127x6": {"d": 0.127, "t": 0.006, "A": 2.28e-3, "I": 4.18e-6},
    "TUB140x6": {"d": 0.140, "t": 0.006, "A": 2.53e-3, "I": 5.65e-6},
    "TUB140x8": {"d": 0.140, "t": 0.008, "A": 3.32e-3, "I": 7.13e-6},
}


def _recommend_section(span: float, force_kN: float) -> str:
    if span <= 12:
        if force_kN < 100: return "TUB89x4"
        elif force_kN < 200: return "TUB102x5"
        else: return "TUB114x6"
    elif span <= 24:
        if force_kN < 200: return "TUB114x5"
        elif force_kN < 400: return "TUB127x6"
        else: return "TUB140x8"
    else:
        if force_kN < 400: return "TUB140x6"
        else: return "TUB140x8"


def generate_truss(
    truss_type: str = "pratt",
    span_m: float = 18.0,
    height_m: float = 2.5,
    panels: int = 8,
    steel_grade: str = "Q355",
    load_kN_per_node: float = 20.0,
    is_3d: bool = False,
) -> dict[str, Any]:
    if truss_type not in TRUSS_TYPES:
        truss_type = "pratt"

    steel = STEEL_GRADES.get(steel_grade, STEEL_GRADES["Q355"])
    chord_sec = _recommend_section(span_m, load_kN_per_node * panels * 0.5)
    web_sec = _recommend_section(span_m, load_kN_per_node * 0.3)

    cs = TUBE_SECTIONS[chord_sec]
    ws = TUBE_SECTIONS[web_sec]

    nodes: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    loads: list[dict[str, Any]] = []
    supports: list[dict[str, Any]] = []

    nid = 1
    eid = 1
    dx = span_m / panels

    # Top and bottom chord nodes
    for i in range(panels + 1):
        x = i * dx
        y_top = height_m
        y_bot = 0.0

        # Top chord node
        if truss_type == "howe":
            # Howe: top chord peaks at center (gable shape)
            peak = height_m * 1.5
            mid = panels / 2
            y_top = height_m + (peak - height_m) * (1 - abs(i - mid) / mid) if panels > 0 else height_m

        nodes.append({"id": nid, "x": x, "y": y_top, "z": 0.0})
        nid += 1
        nodes.append({"id": nid, "x": x, "y": y_bot, "z": 0.0})
        nid += 1

    total_nodes = nid - 1

    # Top chord elements
    for i in range(panels):
        n1 = 1 + i * 2
        n2 = 3 + i * 2
        elements.append({
            "id": eid, "node_i": n1, "node_j": n2,
            "E": steel["E"], "A": cs["A"], "I": cs["I"],
            "Iy": cs["I"], "Iz": cs["I"], "J": cs["I"] * 0.5,
            "type": "top_chord",
        })
        eid += 1

    # Bottom chord elements
    for i in range(panels):
        n1 = 2 + i * 2
        n2 = 4 + i * 2
        elements.append({
            "id": eid, "node_i": n1, "node_j": n2,
            "E": steel["E"], "A": cs["A"], "I": cs["I"],
            "Iy": cs["I"], "Iz": cs["I"], "J": cs["I"] * 0.5,
            "type": "bottom_chord",
        })
        eid += 1

    # Web members (vertical + diagonal)
    for i in range(panels):
        top_left = 1 + i * 2
        top_right = 3 + i * 2
        bot_left = 2 + i * 2
        bot_right = 4 + i * 2

        if truss_type == "pratt":
            # Pratt: diagonals slope down toward center (compression in diagonals toward center)
            if i < panels - 1:
                elements.append({
                    "id": eid, "node_i": top_left, "node_j": bot_right,
                    "E": steel["E"], "A": ws["A"], "I": ws["I"],
                    "Iy": ws["I"], "Iz": ws["I"], "J": ws["I"] * 0.5,
                    "type": "diagonal",
                })
                eid += 1
            if i > 0:
                elements.append({
                    "id": eid, "node_i": top_right, "node_j": bot_left,
                    "E": steel["E"], "A": ws["A"], "I": ws["I"],
                    "Iy": ws["I"], "Iz": ws["I"], "J": ws["I"] * 0.5,
                    "type": "diagonal",
                })
                eid += 1
            # Vertical members
            elements.append({
                "id": eid, "node_i": top_left, "node_j": bot_left,
                "E": steel["E"], "A": ws["A"], "I": ws["I"],
                "Iy": ws["I"], "Iz": ws["I"], "J": ws["I"] * 0.5,
                "type": "vertical",
            })
            eid += 1

        elif truss_type == "howe":
            # Howe: diagonals slope up toward center (reverse of Pratt)
            if i < panels - 1:
                elements.append({
                    "id": eid, "node_i": bot_left, "node_j": top_right,
                    "E": steel["E"], "A": ws["A"], "I": ws["I"],
                    "Iy": ws["I"], "Iz": ws["I"], "J": ws["I"] * 0.5,
                    "type": "diagonal",
                })
                eid += 1
            if i > 0:
                elements.append({
                    "id": eid, "node_i": bot_right, "node_j": top_left,
                    "E": steel["E"], "A": ws["A"], "I": ws["I"],
                    "Iy": ws["I"], "Iz": ws["I"], "J": ws["I"] * 0.5,
                    "type": "diagonal",
                })
                eid += 1
            # Vertical members
            elements.append({
                "id": eid, "node_i": top_left, "node_j": bot_left,
                "E": steel["E"], "A": ws["A"], "I": ws["I"],
                "Iy": ws["I"], "Iz": ws["I"], "J": ws["I"] * 0.5,
                "type": "vertical",
            })
            eid += 1

        elif truss_type == "warren":
            # Warren: no verticals, only zigzag diagonals
            elements.append({
                "id": eid, "node_i": top_left, "node_j": bot_right,
                "E": steel["E"], "A": ws["A"], "I": ws["I"],
                "Iy": ws["I"], "Iz": ws["I"], "J": ws["I"] * 0.5,
                "type": "diagonal",
            })
            eid += 1
            elements.append({
                "id": eid, "node_i": bot_left, "node_j": top_right,
                "E": steel["E"], "A": ws["A"], "I": ws["I"],
                "Iy": ws["I"], "Iz": ws["I"], "J": ws["I"] * 0.5,
                "type": "diagonal",
            })
            eid += 1

    # Supports: pin at left bottom, roller at right bottom
    supports.append({"node_id": 2, "type": "pin"})
    supports.append({"node_id": total_nodes, "type": "roller_x"})

    # Loads: vertical at top chord nodes
    f_load = load_kN_per_node * 1000  # kN → N
    for i in range(panels + 1):
        nid_top = 1 + i * 2
        loads.append({"node_id": nid_top, "Fx": 0.0, "Fy": -f_load})

    # Self-weight estimate
    total_mass = sum(
        (steel["rho"] * el["A"] * _element_length(el, nodes))
        for el in elements
    )
    self_weight_N = total_mass * 9.82

    return {
        "nodes": nodes,
        "elements": elements,
        "loads": loads,
        "supports": supports,
        "metadata": {
            "type": f"{truss_type}_truss",
            "dimension": "2d",
            "truss_type": truss_type,
            "span_m": span_m,
            "height_m": height_m,
            "panels": panels,
            "steel_grade": steel_grade,
            "nodes_total": len(nodes),
            "elements_total": len(elements),
            "chord_section": chord_sec,
            "web_section": web_sec,
            "estimated_weight_kg": round(total_mass, 1),
            "estimated_self_weight_N": round(self_weight_N, 1),
        },
        "materials": {
            "steel": {
                "grade": steel_grade,
                "fy_MPa": steel["fy"] / 1e6,
                "E_GPa": steel["E"] / 1e9,
                "sections": {
                    "chord": {"name": chord_sec, **cs},
                    "web": {"name": web_sec, **ws},
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
