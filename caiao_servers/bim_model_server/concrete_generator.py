"""Concrete structure generator — parametric RC structure generation.

Produces structural geometry for concrete buildings with columns, beams,
shear walls (as closely-spaced vertical elements), and slabs (as grid of
horizontal elements). Output matches the analysis-ready format.
"""

from __future__ import annotations

import math
from typing import Any

CONCRETE_GRADES: dict[str, dict[str, float]] = {
    "C25": {"fck": 25e6, "E": 31.5e9, "nu": 0.2, "rho": 2400},
    "C30": {"fck": 30e6, "E": 33.0e9, "nu": 0.2, "rho": 2400},
    "C35": {"fck": 35e6, "E": 34.0e9, "nu": 0.2, "rho": 2400},
    "C40": {"fck": 40e6, "E": 35.0e9, "nu": 0.2, "rho": 2400},
}

CONCRETE_COLUMN_SECTIONS: dict[str, dict[str, float]] = {
    "C300x300": {"b": 0.30, "h": 0.30},
    "C350x350": {"b": 0.35, "h": 0.35},
    "C400x400": {"b": 0.40, "h": 0.40},
    "C450x450": {"b": 0.45, "h": 0.45},
    "C500x500": {"b": 0.50, "h": 0.50},
    "C550x550": {"b": 0.55, "h": 0.55},
    "C600x600": {"b": 0.60, "h": 0.60},
}

CONCRETE_BEAM_SECTIONS: dict[str, dict[str, float]] = {
    "B200x300": {"b": 0.20, "h": 0.30},
    "B250x400": {"b": 0.25, "h": 0.40},
    "B300x450": {"b": 0.30, "h": 0.45},
    "B300x500": {"b": 0.30, "h": 0.50},
    "B300x600": {"b": 0.30, "h": 0.60},
    "B350x600": {"b": 0.35, "h": 0.60},
    "B350x700": {"b": 0.35, "h": 0.70},
    "B400x700": {"b": 0.40, "h": 0.70},
    "B400x800": {"b": 0.40, "h": 0.80},
}


def rectangular_props(b: float, h: float) -> dict[str, float]:
    A = b * h
    Iy = b * h ** 3 / 12.0
    Iz = h * b ** 3 / 12.0
    J = (b * h ** 3 + h * b ** 3) / 12.0
    return {"A": A, "Iy": Iy, "Iz": Iz, "J": J}


def get_concrete(grade: str) -> dict[str, float]:
    if grade in CONCRETE_GRADES:
        return CONCRETE_GRADES[grade].copy()
    return CONCRETE_GRADES["C30"].copy()


def recommend_column(num_stories: int, max_span: float) -> str:
    sections = list(CONCRETE_COLUMN_SECTIONS.keys())
    demand = num_stories * max_span
    if demand <= 15:
        idx = 0
    elif demand <= 30:
        idx = 1
    elif demand <= 50:
        idx = 2
    elif demand <= 80:
        idx = 4
    elif demand <= 120:
        idx = 5
    else:
        idx = len(sections) - 1
    return sections[idx]


def recommend_beam(span_m: float) -> str:
    sections = list(CONCRETE_BEAM_SECTIONS.keys())
    required_depth = span_m / 15.0
    for sec in sections:
        h = CONCRETE_BEAM_SECTIONS[sec]["h"]
        if h >= required_depth:
            return sec
    return sections[-1]


def _trib(count: int, idx: int, span: float) -> float:
    if count == 0:
        return max(span, 0.5)
    if idx == 0 or idx == count:
        return span / 2.0
    return span


def generate_concrete_structure(
    num_bays_x: int = 3,
    num_bays_y: int = 3,
    num_stories: int = 4,
    span_x_m: float = 6.0,
    span_y_m: float = 6.0,
    story_height_m: float = 3.5,
    wall_thickness: float = 0.2,
    slab_thickness: float = 0.15,
    concrete_grade: str = "C30",
    concrete_density: float = 2400.0,
    base_support: str = "fixed",
    dead_load_kpa: float = 5.0,
    live_load_kpa: float = 2.0,
) -> dict[str, Any]:
    mat = get_concrete(concrete_grade)
    E = mat["E"]
    fck = mat["fck"]

    col_name = recommend_column(num_stories, max(span_x_m, span_y_m))
    beam_x_name = recommend_beam(span_x_m)
    beam_y_name = recommend_beam(span_y_m)

    col_sec = CONCRETE_COLUMN_SECTIONS[col_name]
    beam_x_sec = CONCRETE_BEAM_SECTIONS[beam_x_name]
    beam_y_sec = CONCRETE_BEAM_SECTIONS[beam_y_name]

    col_p = rectangular_props(col_sec["b"], col_sec["h"])
    bx_p = rectangular_props(beam_x_sec["b"], beam_x_sec["h"])
    by_p = rectangular_props(beam_y_sec["b"], beam_y_sec["h"])

    x_coords = [i * span_x_m for i in range(num_bays_x + 1)]
    y_coords = [i * span_y_m for i in range(num_bays_y + 1)]
    z_coords = [i * story_height_m for i in range(num_stories + 1)]

    nodes: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    loads: list[dict[str, Any]] = []
    supports: list[dict[str, Any]] = []

    grid: dict[tuple[int, int, int], int] = {}
    nid = 0
    for iz, z in enumerate(z_coords):
        for iy, y in enumerate(y_coords):
            for ix, x in enumerate(x_coords):
                nodes.append({"id": nid, "x": x, "y": z, "z": y})
                grid[(ix, iy, iz)] = nid
                nid += 1

    eid = 0

    # Columns
    for story in range(num_stories):
        for iy in range(num_bays_y + 1):
            for ix in range(num_bays_x + 1):
                bot = grid[(ix, iy, story)]
                top = grid[(ix, iy, story + 1)]
                elements.append({
                    "id": eid, "node_i": bot, "node_j": top,
                    "E": E, "A": col_p["A"], "Iy": col_p["Iy"],
                    "Iz": col_p["Iz"], "J": col_p["J"],
                    "type": "column", "section": col_name,
                    "material": "concrete", "concrete_grade": concrete_grade,
                    "fck": fck, "story": story + 1,
                    "is_corner": (ix in (0, num_bays_x)) and (iy in (0, num_bays_y)),
                })
                eid += 1

    # Beams X-direction
    for story in range(1, num_stories + 1):
        for iy in range(num_bays_y + 1):
            for ix in range(num_bays_x):
                left = grid[(ix, iy, story)]
                right = grid[(ix + 1, iy, story)]
                elements.append({
                    "id": eid, "node_i": left, "node_j": right,
                    "E": E, "A": bx_p["A"], "Iy": bx_p["Iy"],
                    "Iz": bx_p["Iz"], "J": bx_p["J"],
                    "type": "beam", "direction": "x", "section": beam_x_name,
                    "material": "concrete", "concrete_grade": concrete_grade,
                    "fck": fck, "story": story,
                })
                eid += 1

    # Beams Z-direction
    for story in range(1, num_stories + 1):
        for ix in range(num_bays_x + 1):
            for iy in range(num_bays_y):
                f = grid[(ix, iy, story)]
                b = grid[(ix, iy + 1, story)]
                elements.append({
                    "id": eid, "node_i": f, "node_j": b,
                    "E": E, "A": by_p["A"], "Iy": by_p["Iy"],
                    "Iz": by_p["Iz"], "J": by_p["J"],
                    "type": "beam", "direction": "z", "section": beam_y_name,
                    "material": "concrete", "concrete_grade": concrete_grade,
                    "fck": fck, "story": story,
                })
                eid += 1

    # Walls — closely-spaced vertical elements at perimeter grid positions
    def wall_trib(count, idx, span):
        return _trib(count, idx, span)

    # Wall along X-edges (vertical elements running in Z/span_y direction)
    for x_edge in (0, num_bays_x):
        for iy in range(num_bays_y + 1):
            trib = wall_trib(num_bays_y, iy, span_y_m)
            A_w = trib * wall_thickness
            Iy_w = wall_thickness * trib ** 3 / 12.0
            Iz_w = trib * wall_thickness ** 3 / 12.0
            J_w = (trib * wall_thickness ** 3 + wall_thickness * trib ** 3) / 12.0
            for story in range(num_stories):
                bot = grid[(x_edge, iy, story)]
                top = grid[(x_edge, iy, story + 1)]
                elements.append({
                    "id": eid, "node_i": bot, "node_j": top,
                    "E": E, "A": A_w, "Iy": Iy_w, "Iz": Iz_w, "J": J_w,
                    "type": "wall", "direction": "z",
                    "section": f"W{int(wall_thickness*1000)}",
                    "material": "concrete", "concrete_grade": concrete_grade,
                    "fck": fck, "story": story + 1,
                })
                eid += 1

    # Wall along Y-edges (vertical elements running in X direction)
    for y_edge in (0, num_bays_y):
        for ix in range(num_bays_x + 1):
            trib = wall_trib(num_bays_x, ix, span_x_m)
            A_w = trib * wall_thickness
            Iy_w = wall_thickness * trib ** 3 / 12.0
            Iz_w = trib * wall_thickness ** 3 / 12.0
            J_w = (trib * wall_thickness ** 3 + wall_thickness * trib ** 3) / 12.0
            for story in range(num_stories):
                bot = grid[(ix, y_edge, story)]
                top = grid[(ix, y_edge, story + 1)]
                elements.append({
                    "id": eid, "node_i": bot, "node_j": top,
                    "E": E, "A": A_w, "Iy": Iy_w, "Iz": Iz_w, "J": J_w,
                    "type": "wall", "direction": "x",
                    "section": f"W{int(wall_thickness*1000)}",
                    "material": "concrete", "concrete_grade": concrete_grade,
                    "fck": fck, "story": story + 1,
                })
                eid += 1

    # Slabs — grid of horizontal elements at each floor
    for story in range(1, num_stories + 1):
        # X-direction slab elements
        for iy in range(num_bays_y + 1):
            trib_z = _trib(num_bays_y, iy, span_y_m)
            A_s = trib_z * slab_thickness
            Iy_s = trib_z * slab_thickness ** 3 / 12.0
            Iz_s = slab_thickness * trib_z ** 3 / 12.0
            J_s = (trib_z * slab_thickness ** 3 + slab_thickness * trib_z ** 3) / 12.0
            for ix in range(num_bays_x):
                left = grid[(ix, iy, story)]
                right = grid[(ix + 1, iy, story)]
                elements.append({
                    "id": eid, "node_i": left, "node_j": right,
                    "E": E, "A": A_s, "Iy": Iy_s, "Iz": Iz_s, "J": J_s,
                    "type": "slab", "direction": "x",
                    "section": f"S{int(slab_thickness*1000)}",
                    "material": "concrete", "concrete_grade": concrete_grade,
                    "fck": fck, "story": story,
                })
                eid += 1

        # Z-direction slab elements
        for ix in range(num_bays_x + 1):
            trib_x = _trib(num_bays_x, ix, span_x_m)
            A_s = trib_x * slab_thickness
            Iy_s = trib_x * slab_thickness ** 3 / 12.0
            Iz_s = slab_thickness * trib_x ** 3 / 12.0
            J_s = (trib_x * slab_thickness ** 3 + slab_thickness * trib_x ** 3) / 12.0
            for iy in range(num_bays_y):
                f = grid[(ix, iy, story)]
                b = grid[(ix, iy + 1, story)]
                elements.append({
                    "id": eid, "node_i": f, "node_j": b,
                    "E": E, "A": A_s, "Iy": Iy_s, "Iz": Iz_s, "J": J_s,
                    "type": "slab", "direction": "z",
                    "section": f"S{int(slab_thickness*1000)}",
                    "material": "concrete", "concrete_grade": concrete_grade,
                    "fck": fck, "story": story,
                })
                eid += 1

    # Supports at base
    for ix in range(num_bays_x + 1):
        for iy in range(num_bays_y + 1):
            supports.append({"node_id": grid[(ix, iy, 0)], "type": base_support})

    # Gravity loads at each floor
    floor_area = span_x_m * span_y_m
    factor_dead = dead_load_kpa * 1000 * floor_area
    factor_live = live_load_kpa * 1000 * floor_area
    for story in range(1, num_stories + 1):
        for ix in range(num_bays_x + 1):
            for iy in range(num_bays_y + 1):
                nx = 1 if ix in (0, num_bays_x) else 2
                ny = 1 if iy in (0, num_bays_y) else 2
                share = nx * ny
                Fz = -(factor_dead + factor_live) / 4.0 * (4.0 / share)
                loads.append({"node_id": grid[(ix, iy, story)], "Fx": 0.0, "Fy": 0.0, "Fz": Fz})

    # Lateral wind loads
    wind_pressure = 1000.0
    for story in range(1, num_stories + 1):
        for iy in range(num_bays_y + 1):
            for ix in (0, num_bays_x):
                tw = span_y_m / (num_bays_y + 1 if iy in (0, num_bays_y) else num_bays_y)
                fx = wind_pressure * story_height_m * tw / 2.0
                loads.append({
                    "node_id": grid[(ix, iy, story)],
                    "Fx": fx if ix == 0 else -fx, "Fy": 0.0, "Fz": 0.0,
                })

    num_walls = sum(1 for e in elements if e["type"] == "wall")
    num_slabs = sum(1 for e in elements if e["type"] == "slab")

    metadata = {
        "type": "concrete_structure", "dimension": "3d",
        "material": concrete_grade, "material_type": "concrete",
        "num_bays_x": num_bays_x, "num_bays_y": num_bays_y,
        "num_stories": num_stories, "span_x_m": span_x_m,
        "span_y_m": span_y_m, "story_height_m": story_height_m,
        "E": E, "fck": fck,
        "elements_total": len(elements),
        "columns": num_stories * (num_bays_x + 1) * (num_bays_y + 1),
        "walls": num_walls, "slabs": num_slabs,
        "wall_thickness": wall_thickness, "slab_thickness": slab_thickness,
        "base_support": base_support,
        "column_section": col_name,
        "beam_section_x": beam_x_name, "beam_section_y": beam_y_name,
    }

    return {
        "nodes": nodes,
        "elements": elements,
        "loads": loads,
        "supports": supports,
        "metadata": metadata,
        "materials": {
            "concrete": {
                "grade": concrete_grade, "fck": fck,
                "E": E, "nu": mat["nu"], "rho": mat["rho"],
            },
        },
    }
