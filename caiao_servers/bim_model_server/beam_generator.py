"""Beam generator — simply supported, cantilever, and continuous beams.

Output format matches FrameStructure: {nodes, elements, loads, supports, metadata}.
"""

from __future__ import annotations
import math
from typing import Any

BEAM_TYPES = ["simply_supported", "cantilever", "continuous", "fixed"]

STEEL_GRADES: dict[str, dict[str, float]] = {
    "Q235": {"fy": 235e6, "E": 206e9, "nu": 0.3, "rho": 7850},
    "Q355": {"fy": 355e6, "E": 206e9, "nu": 0.3, "rho": 7850},
    "Q420": {"fy": 420e6, "E": 206e9, "nu": 0.3, "rho": 7850},
}

BEAM_SECTIONS: dict[str, dict[str, float]] = {
    "IPE200": {"h": 0.200, "A": 2.85e-3, "Iy": 1.94e-5, "Iz": 1.42e-6, "Wely": 1.94e-4},
    "IPE240": {"h": 0.240, "A": 3.91e-3, "Iy": 3.89e-5, "Iz": 2.84e-6, "Wely": 3.24e-4},
    "IPE300": {"h": 0.300, "A": 5.38e-3, "Iy": 8.36e-5, "Iz": 6.04e-6, "Wely": 5.57e-4},
    "IPE360": {"h": 0.360, "A": 7.27e-3, "Iy": 1.63e-4, "Iz": 1.04e-5, "Wely": 9.04e-4},
    "IPE400": {"h": 0.400, "A": 8.45e-3, "Iy": 2.31e-4, "Iz": 1.32e-5, "Wely": 1.16e-3},
    "IPE500": {"h": 0.500, "A": 1.16e-2, "Iy": 4.82e-4, "Iz": 2.14e-5, "Wely": 1.93e-3},
    "IPE600": {"h": 0.600, "A": 1.56e-2, "Iy": 9.21e-4, "Iz": 3.39e-5, "Wely": 3.07e-3},
}

# Concrete rectangular beam sections
CONCRETE_BEAM_SECTIONS: dict[str, dict[str, float]] = {
    "B200x300":  {"b": 0.20, "h": 0.30, "A": 6.00e-2, "I": 4.50e-4},
    "B250x400":  {"b": 0.25, "h": 0.40, "A": 1.00e-1, "I": 1.33e-3},
    "B300x500":  {"b": 0.30, "h": 0.50, "A": 1.50e-1, "I": 3.13e-3},
    "B300x600":  {"b": 0.30, "h": 0.60, "A": 1.80e-1, "I": 5.40e-3},
    "B350x700":  {"b": 0.35, "h": 0.70, "A": 2.45e-1, "I": 1.00e-2},
    "B400x800":  {"b": 0.40, "h": 0.80, "A": 3.20e-1, "I": 1.71e-2},
}

CONCRETE_GRADES: dict[str, dict[str, float]] = {
    "C25": {"fck": 25e6, "E": 31e9, "nu": 0.2, "rho": 2500},
    "C30": {"fck": 30e6, "E": 32e9, "nu": 0.2, "rho": 2500},
    "C35": {"fck": 35e6, "E": 34e9, "nu": 0.2, "rho": 2500},
    "C40": {"fck": 40e6, "E": 35e9, "nu": 0.2, "rho": 2500},
}


def _recommend_steel_section(span: float, udl_N: float) -> str:
    moment = udl_N * span / 8
    if moment < 30000: return "IPE200"
    elif moment < 60000: return "IPE240"
    elif moment < 120000: return "IPE300"
    elif moment < 200000: return "IPE360"
    elif moment < 350000: return "IPE400"
    elif moment < 600000: return "IPE500"
    return "IPE600"


def generate_beam(
    beam_type: str = "simply_supported",
    span_m: float = 6.0,
    material: str = "steel",
    steel_grade: str = "Q355",
    concrete_grade: str = "C30",
    udl_kN_per_m: float = 10.0,
    num_spans: int = 3,
    load_type: str = "udl",
) -> dict[str, Any]:
    if beam_type not in BEAM_TYPES:
        beam_type = "simply_supported"

    if material == "concrete":
        mat = CONCRETE_GRADES.get(concrete_grade, CONCRETE_GRADES["C30"])
        sec_name = f"B300x500"
        if span_m <= 4: sec_name = "B200x300"
        elif span_m <= 6: sec_name = "B250x400"
        elif span_m <= 8: sec_name = "B300x500"
        elif span_m <= 10: sec_name = "B300x600"
        elif span_m <= 14: sec_name = "B350x700"
        else: sec_name = "B400x800"
        sec = CONCRETE_BEAM_SECTIONS[sec_name]
    else:
        mat = STEEL_GRADES.get(steel_grade, STEEL_GRADES["Q355"])
        total_load_N = udl_kN_per_m * span_m * 1000
        sec_name = _recommend_steel_section(span_m, total_load_N)
        sec = BEAM_SECTIONS[sec_name]

    nodes: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    loads: list[dict[str, Any]] = []
    supports: list[dict[str, Any]] = []

    if beam_type == "simply_supported":
        n_elements = max(4, int(span_m * 2))
        dx = span_m / n_elements

        for i in range(n_elements + 1):
            nodes.append({"id": i + 1, "x": i * dx, "y": 0.0, "z": 0.0})

        for i in range(n_elements):
            elements.append({
                "id": i + 1, "node_i": i + 1, "node_j": i + 2,
                "E": mat["E"], "A": sec["A"],
                "Iy": sec.get("Iy", sec.get("I", 0)),
                "Iz": sec.get("Iz", sec.get("I", 0)),
                "J": 0, "type": "beam", "section": sec_name,
            })

        supports.append({"node_id": 1, "type": "pin"})
        supports.append({"node_id": n_elements + 1, "type": "roller_y"})

        if load_type == "udl":
            udl_N_per_m = udl_kN_per_m * 1000
            load_per_node = udl_N_per_m * dx
            for i in range(n_elements + 1):
                loads.append({"node_id": i + 1, "Fx": 0.0, "Fy": -load_per_node})
        else:
            point_load = udl_kN_per_m * span_m * 1000
            mid_node = n_elements // 2 + 1
            loads.append({"node_id": mid_node, "Fx": 0.0, "Fy": -point_load})

    elif beam_type == "cantilever":
        n_elements = max(4, int(span_m * 2))
        dx = span_m / n_elements

        for i in range(n_elements + 1):
            nodes.append({"id": i + 1, "x": i * dx, "y": 0.0, "z": 0.0})

        for i in range(n_elements):
            elements.append({
                "id": i + 1, "node_i": i + 1, "node_j": i + 2,
                "E": mat["E"], "A": sec["A"],
                "Iy": sec.get("Iy", sec.get("I", 0)),
                "Iz": sec.get("Iz", sec.get("I", 0)),
                "J": 0, "type": "beam", "section": sec_name,
            })

        supports.append({"node_id": 1, "type": "fixed"})

        if load_type == "udl":
            udl_N = udl_kN_per_m * 1000
            load_per_node = udl_N * dx
            for i in range(n_elements + 1):
                loads.append({"node_id": i + 1, "Fx": 0.0, "Fy": -load_per_node})
        else:
            point_load = udl_kN_per_m * span_m * 1000
            loads.append({"node_id": n_elements + 1, "Fx": 0.0, "Fy": -point_load})

    elif beam_type == "continuous":
        spans = max(2, num_spans)
        n_elements_per_span = max(4, int(span_m))
        dx = span_m / n_elements_per_span
        total_elements = spans * n_elements_per_span
        total_nodes = total_elements + 1

        for i in range(total_nodes):
            nodes.append({"id": i + 1, "x": i * dx, "y": 0.0, "z": 0.0})

        for i in range(total_elements):
            elements.append({
                "id": i + 1, "node_i": i + 1, "node_j": i + 2,
                "E": mat["E"], "A": sec["A"],
                "Iy": sec.get("Iy", sec.get("I", 0)),
                "Iz": sec.get("Iz", sec.get("I", 0)),
                "J": 0, "type": "beam", "section": sec_name,
            })

        # Supports at each span junction
        for i in range(spans + 1):
            nid = 1 + i * n_elements_per_span
            if i == 0:
                supports.append({"node_id": nid, "type": "pin"})
            else:
                supports.append({"node_id": nid, "type": "roller_y"})

        udl_N = udl_kN_per_m * 1000
        load_per_node = udl_N * dx
        for i in range(total_nodes):
            loads.append({"node_id": i + 1, "Fx": 0.0, "Fy": -load_per_node})

    elif beam_type == "fixed":
        n_elements = max(4, int(span_m * 2))
        dx = span_m / n_elements

        for i in range(n_elements + 1):
            nodes.append({"id": i + 1, "x": i * dx, "y": 0.0, "z": 0.0})

        for i in range(n_elements):
            elements.append({
                "id": i + 1, "node_i": i + 1, "node_j": i + 2,
                "E": mat["E"], "A": sec["A"],
                "Iy": sec.get("Iy", sec.get("I", 0)),
                "Iz": sec.get("Iz", sec.get("I", 0)),
                "J": 0, "type": "beam", "section": sec_name,
            })

        supports.append({"node_id": 1, "type": "fixed"})
        supports.append({"node_id": n_elements + 1, "type": "fixed"})

        udl_N = udl_kN_per_m * 1000
        load_per_node = udl_N * dx
        for i in range(n_elements + 1):
            loads.append({"node_id": i + 1, "Fx": 0.0, "Fy": -load_per_node})

    total_mass = sum(mat["rho"] * el["A"] * _element_length(el, nodes) for el in elements)

    return {
        "nodes": nodes,
        "elements": elements,
        "loads": loads,
        "supports": supports,
        "metadata": {
            "type": f"{beam_type}_beam",
            "dimension": "2d",
            "beam_type": beam_type,
            "span_m": span_m,
            "material": material,
            "section": sec_name,
            "load_type": load_type,
            "udl_kN_per_m": udl_kN_per_m,
            "num_spans": num_spans if beam_type == "continuous" else 1,
            "nodes_total": len(nodes),
            "elements_total": len(elements),
            "estimated_weight_kg": round(total_mass, 1),
        },
        "materials": {
            material: {
                "grade": steel_grade if material == "steel" else concrete_grade,
                "E_GPa": mat["E"] / 1e9,
                "section": {"name": sec_name, **sec},
            },
        },
    }


def _element_length(el: dict, nodes: list[dict]) -> float:
    n1 = next((n for n in nodes if n["id"] == el["node_i"]), None)
    n2 = next((n for n in nodes if n["id"] == el["node_j"]), None)
    if not n1 or not n2:
        return 0.0
    return math.sqrt((n2["x"] - n1["x"]) ** 2 + (n2["y"] - n1["y"]) ** 2 + (n2.get("z", 0) - n1.get("z", 0)) ** 2)
