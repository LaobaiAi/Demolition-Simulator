"""Steel frame generator — parametric steel structure generation with standard sections.

Produces structural geometry using standard European I-beam sections (IPE, HE-A, HE-B).
Output format is compatible with the project's FrameNode/FrameElement conventions and
can be consumed by anaStruct, OpenSees, PyNite analyzers and the frontend visualizer.
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Standard steel section database (European profiles)
# ---------------------------------------------------------------------------

IPE_SECTIONS: dict[str, dict[str, float]] = {
    "IPE100":  {"h": 0.100, "b": 0.055, "tw": 0.0041, "tf": 0.0057, "A": 1.03e-3, "Iy": 1.71e-6,  "Iz": 1.59e-7,  "Wely": 3.42e-5,  "Welz": 5.79e-6},
    "IPE120":  {"h": 0.120, "b": 0.064, "tw": 0.0044, "tf": 0.0063, "A": 1.32e-3, "Iy": 3.18e-6,  "Iz": 2.77e-7,  "Wely": 5.30e-5,  "Welz": 8.65e-6},
    "IPE140":  {"h": 0.140, "b": 0.073, "tw": 0.0047, "tf": 0.0069, "A": 1.64e-3, "Iy": 5.41e-6,  "Iz": 4.49e-7,  "Wely": 7.73e-5,  "Welz": 1.23e-5},
    "IPE160":  {"h": 0.160, "b": 0.082, "tw": 0.0050, "tf": 0.0074, "A": 2.01e-3, "Iy": 8.69e-6,  "Iz": 6.83e-7,  "Wely": 1.09e-4,  "Welz": 1.66e-5},
    "IPE180":  {"h": 0.180, "b": 0.091, "tw": 0.0053, "tf": 0.0080, "A": 2.39e-3, "Iy": 1.32e-5,  "Iz": 1.01e-6,  "Wely": 1.46e-4,  "Welz": 2.21e-5},
    "IPE200":  {"h": 0.200, "b": 0.100, "tw": 0.0056, "tf": 0.0085, "A": 2.85e-3, "Iy": 1.94e-5,  "Iz": 1.42e-6,  "Wely": 1.94e-4,  "Welz": 2.85e-5},
    "IPE220":  {"h": 0.220, "b": 0.110, "tw": 0.0059, "tf": 0.0092, "A": 3.34e-3, "Iy": 2.77e-5,  "Iz": 2.05e-6,  "Wely": 2.52e-4,  "Welz": 3.72e-5},
    "IPE240":  {"h": 0.240, "b": 0.120, "tw": 0.0062, "tf": 0.0098, "A": 3.91e-3, "Iy": 3.89e-5,  "Iz": 2.84e-6,  "Wely": 3.24e-4,  "Welz": 4.73e-5},
    "IPE270":  {"h": 0.270, "b": 0.135, "tw": 0.0066, "tf": 0.0102, "A": 4.59e-3, "Iy": 5.79e-5,  "Iz": 4.20e-6,  "Wely": 4.29e-4,  "Welz": 6.22e-5},
    "IPE300":  {"h": 0.300, "b": 0.150, "tw": 0.0071, "tf": 0.0107, "A": 5.38e-3, "Iy": 8.36e-5,  "Iz": 6.04e-6,  "Wely": 5.57e-4,  "Welz": 8.05e-5},
    "IPE330":  {"h": 0.330, "b": 0.160, "tw": 0.0075, "tf": 0.0115, "A": 6.26e-3, "Iy": 1.18e-4,  "Iz": 7.88e-6,  "Wely": 7.13e-4,  "Welz": 9.85e-5},
    "IPE360":  {"h": 0.360, "b": 0.170, "tw": 0.0080, "tf": 0.0127, "A": 7.27e-3, "Iy": 1.63e-4,  "Iz": 1.04e-5,  "Wely": 9.04e-4,  "Welz": 1.23e-4},
    "IPE400":  {"h": 0.400, "b": 0.180, "tw": 0.0086, "tf": 0.0135, "A": 8.45e-3, "Iy": 2.31e-4,  "Iz": 1.32e-5,  "Wely": 1.16e-3,  "Welz": 1.46e-4},
    "IPE450":  {"h": 0.450, "b": 0.190, "tw": 0.0094, "tf": 0.0146, "A": 9.88e-3, "Iy": 3.37e-4,  "Iz": 1.68e-5,  "Wely": 1.50e-3,  "Welz": 1.77e-4},
    "IPE500":  {"h": 0.500, "b": 0.200, "tw": 0.0102, "tf": 0.0160, "A": 1.16e-2, "Iy": 4.82e-4,  "Iz": 2.14e-5,  "Wely": 1.93e-3,  "Welz": 2.14e-4},
    "IPE550":  {"h": 0.550, "b": 0.210, "tw": 0.0111, "tf": 0.0172, "A": 1.34e-2, "Iy": 6.71e-4,  "Iz": 2.67e-5,  "Wely": 2.44e-3,  "Welz": 2.54e-4},
    "IPE600":  {"h": 0.600, "b": 0.220, "tw": 0.0120, "tf": 0.0190, "A": 1.56e-2, "Iy": 9.21e-4,  "Iz": 3.39e-5,  "Wely": 3.07e-3,  "Welz": 3.08e-4},
}

HE_A_SECTIONS: dict[str, dict[str, float]] = {
    "HEA100":  {"h": 0.096, "b": 0.100, "tw": 0.0050, "tf": 0.0080, "A": 2.12e-3, "Iy": 3.49e-6,  "Iz": 1.33e-6,  "Wely": 7.27e-5,  "Welz": 2.67e-5},
    "HEA120":  {"h": 0.114, "b": 0.120, "tw": 0.0050, "tf": 0.0080, "A": 2.53e-3, "Iy": 6.06e-6,  "Iz": 2.31e-6,  "Wely": 1.06e-4,  "Welz": 3.85e-5},
    "HEA140":  {"h": 0.133, "b": 0.140, "tw": 0.0055, "tf": 0.0085, "A": 3.14e-3, "Iy": 1.03e-5,  "Iz": 3.89e-6,  "Wely": 1.55e-4,  "Welz": 5.56e-5},
    "HEA160":  {"h": 0.152, "b": 0.160, "tw": 0.0060, "tf": 0.0090, "A": 3.88e-3, "Iy": 1.67e-5,  "Iz": 6.16e-6,  "Wely": 2.20e-4,  "Welz": 7.70e-5},
    "HEA180":  {"h": 0.171, "b": 0.180, "tw": 0.0060, "tf": 0.0095, "A": 4.53e-3, "Iy": 2.51e-5,  "Iz": 9.24e-6,  "Wely": 2.94e-4,  "Welz": 1.03e-4},
    "HEA200":  {"h": 0.190, "b": 0.200, "tw": 0.0065, "tf": 0.0100, "A": 5.38e-3, "Iy": 3.69e-5,  "Iz": 1.34e-5,  "Wely": 3.89e-4,  "Welz": 1.34e-4},
    "HEA220":  {"h": 0.210, "b": 0.220, "tw": 0.0070, "tf": 0.0110, "A": 6.43e-3, "Iy": 5.41e-5,  "Iz": 1.96e-5,  "Wely": 5.15e-4,  "Welz": 1.78e-4},
    "HEA240":  {"h": 0.230, "b": 0.240, "tw": 0.0075, "tf": 0.0120, "A": 7.68e-3, "Iy": 7.76e-5,  "Iz": 2.77e-5,  "Wely": 6.75e-4,  "Welz": 2.31e-4},
    "HEA260":  {"h": 0.250, "b": 0.260, "tw": 0.0075, "tf": 0.0125, "A": 8.68e-3, "Iy": 1.05e-4,  "Iz": 3.67e-5,  "Wely": 8.37e-4,  "Welz": 2.82e-4},
    "HEA280":  {"h": 0.270, "b": 0.280, "tw": 0.0080, "tf": 0.0130, "A": 9.73e-3, "Iy": 1.37e-4,  "Iz": 4.76e-5,  "Wely": 1.01e-3,  "Welz": 3.40e-4},
    "HEA300":  {"h": 0.290, "b": 0.300, "tw": 0.0085, "tf": 0.0140, "A": 1.13e-2, "Iy": 1.83e-4,  "Iz": 6.31e-5,  "Wely": 1.26e-3,  "Welz": 4.21e-4},
    "HEA320":  {"h": 0.310, "b": 0.300, "tw": 0.0090, "tf": 0.0155, "A": 1.24e-2, "Iy": 2.29e-4,  "Iz": 6.99e-5,  "Wely": 1.48e-3,  "Welz": 4.66e-4},
    "HEA340":  {"h": 0.330, "b": 0.300, "tw": 0.0095, "tf": 0.0165, "A": 1.34e-2, "Iy": 2.77e-4,  "Iz": 7.44e-5,  "Wely": 1.68e-3,  "Welz": 4.96e-4},
    "HEA360":  {"h": 0.350, "b": 0.300, "tw": 0.0100, "tf": 0.0175, "A": 1.43e-2, "Iy": 3.31e-4,  "Iz": 7.89e-5,  "Wely": 1.89e-3,  "Welz": 5.26e-4},
    "HEA400":  {"h": 0.390, "b": 0.300, "tw": 0.0110, "tf": 0.0190, "A": 1.59e-2, "Iy": 4.52e-4,  "Iz": 8.66e-5,  "Wely": 2.32e-3,  "Welz": 5.77e-4},
    "HEA450":  {"h": 0.440, "b": 0.300, "tw": 0.0120, "tf": 0.0210, "A": 1.78e-2, "Iy": 6.37e-4,  "Iz": 9.47e-5,  "Wely": 2.90e-3,  "Welz": 6.31e-4},
    "HEA500":  {"h": 0.490, "b": 0.300, "tw": 0.0120, "tf": 0.0230, "A": 1.98e-2, "Iy": 8.69e-4,  "Iz": 1.04e-4,  "Wely": 3.55e-3,  "Welz": 6.91e-4},
    "HEA550":  {"h": 0.540, "b": 0.300, "tw": 0.0125, "tf": 0.0240, "A": 2.12e-2, "Iy": 1.12e-3,  "Iz": 1.08e-4,  "Wely": 4.14e-3,  "Welz": 7.22e-4},
    "HEA600":  {"h": 0.590, "b": 0.300, "tw": 0.0130, "tf": 0.0250, "A": 2.27e-2, "Iy": 1.41e-3,  "Iz": 1.13e-4,  "Wely": 4.78e-3,  "Welz": 7.52e-4},
}

HE_B_SECTIONS: dict[str, dict[str, float]] = {
    "HEB100":  {"h": 0.100, "b": 0.100, "tw": 0.0060, "tf": 0.0100, "A": 2.60e-3, "Iy": 4.49e-6,  "Iz": 1.67e-6,  "Wely": 8.99e-5,  "Welz": 3.33e-5},
    "HEB120":  {"h": 0.120, "b": 0.120, "tw": 0.0065, "tf": 0.0110, "A": 3.40e-3, "Iy": 8.64e-6,  "Iz": 3.18e-6,  "Wely": 1.44e-4,  "Welz": 5.30e-5},
    "HEB140":  {"h": 0.140, "b": 0.140, "tw": 0.0070, "tf": 0.0120, "A": 4.30e-3, "Iy": 1.51e-5,  "Iz": 5.50e-6,  "Wely": 2.16e-4,  "Welz": 7.85e-5},
    "HEB160":  {"h": 0.160, "b": 0.160, "tw": 0.0080, "tf": 0.0130, "A": 5.43e-3, "Iy": 2.49e-5,  "Iz": 8.89e-6,  "Wely": 3.11e-4,  "Welz": 1.11e-4},
    "HEB180":  {"h": 0.180, "b": 0.180, "tw": 0.0085, "tf": 0.0140, "A": 6.53e-3, "Iy": 3.83e-5,  "Iz": 1.36e-5,  "Wely": 4.26e-4,  "Welz": 1.51e-4},
    "HEB200":  {"h": 0.200, "b": 0.200, "tw": 0.0090, "tf": 0.0150, "A": 7.81e-3, "Iy": 5.70e-5,  "Iz": 2.00e-5,  "Wely": 5.70e-4,  "Welz": 2.00e-4},
    "HEB220":  {"h": 0.220, "b": 0.220, "tw": 0.0095, "tf": 0.0160, "A": 9.10e-3, "Iy": 8.09e-5,  "Iz": 2.84e-5,  "Wely": 7.35e-4,  "Welz": 2.58e-4},
    "HEB240":  {"h": 0.240, "b": 0.240, "tw": 0.0100, "tf": 0.0170, "A": 1.06e-2, "Iy": 1.12e-4,  "Iz": 3.92e-5,  "Wely": 9.36e-4,  "Welz": 3.27e-4},
    "HEB260":  {"h": 0.260, "b": 0.260, "tw": 0.0100, "tf": 0.0175, "A": 1.18e-2, "Iy": 1.49e-4,  "Iz": 5.13e-5,  "Wely": 1.15e-3,  "Welz": 3.95e-4},
    "HEB280":  {"h": 0.280, "b": 0.280, "tw": 0.0105, "tf": 0.0180, "A": 1.31e-2, "Iy": 1.92e-4,  "Iz": 6.60e-5,  "Wely": 1.37e-3,  "Welz": 4.71e-4},
    "HEB300":  {"h": 0.300, "b": 0.300, "tw": 0.0110, "tf": 0.0190, "A": 1.49e-2, "Iy": 2.52e-4,  "Iz": 8.56e-5,  "Wely": 1.68e-3,  "Welz": 5.71e-4},
    "HEB320":  {"h": 0.320, "b": 0.300, "tw": 0.0115, "tf": 0.0205, "A": 1.61e-2, "Iy": 3.08e-4,  "Iz": 9.24e-5,  "Wely": 1.93e-3,  "Welz": 6.16e-4},
    "HEB340":  {"h": 0.340, "b": 0.300, "tw": 0.0120, "tf": 0.0215, "A": 1.71e-2, "Iy": 3.67e-4,  "Iz": 9.70e-5,  "Wely": 2.16e-3,  "Welz": 6.47e-4},
    "HEB360":  {"h": 0.360, "b": 0.300, "tw": 0.0125, "tf": 0.0225, "A": 1.81e-2, "Iy": 4.32e-4,  "Iz": 1.01e-4,  "Wely": 2.40e-3,  "Welz": 6.76e-4},
    "HEB400":  {"h": 0.400, "b": 0.300, "tw": 0.0135, "tf": 0.0240, "A": 1.98e-2, "Iy": 5.77e-4,  "Iz": 1.08e-4,  "Wely": 2.88e-3,  "Welz": 7.21e-4},
    "HEB450":  {"h": 0.450, "b": 0.300, "tw": 0.0140, "tf": 0.0260, "A": 2.18e-2, "Iy": 7.99e-4,  "Iz": 1.17e-4,  "Wely": 3.55e-3,  "Welz": 7.81e-4},
    "HEB500":  {"h": 0.500, "b": 0.300, "tw": 0.0145, "tf": 0.0280, "A": 2.39e-2, "Iy": 1.07e-3,  "Iz": 1.26e-4,  "Wely": 4.29e-3,  "Welz": 8.42e-4},
    "HEB550":  {"h": 0.550, "b": 0.300, "tw": 0.0150, "tf": 0.0290, "A": 2.54e-2, "Iy": 1.37e-3,  "Iz": 1.31e-4,  "Wely": 4.97e-3,  "Welz": 8.71e-4},
    "HEB600":  {"h": 0.600, "b": 0.300, "tw": 0.0155, "tf": 0.0300, "A": 2.70e-2, "Iy": 1.71e-3,  "Iz": 1.36e-4,  "Wely": 5.70e-3,  "Welz": 9.04e-4},
}

# Maps from section family names
SECTION_FAMILIES: dict[str, dict[str, dict[str, float]]] = {
    "IPE": IPE_SECTIONS,
    "HE-A": HE_A_SECTIONS,
    "HE-B": HE_B_SECTIONS,
}


def get_steel_material(grade: str) -> dict[str, float]:
    """Get material properties for a steel grade.

    Supports Chinese (Q235-Q420) and European (S235-S355) standards.
    """
    grades: dict[str, dict[str, float]] = {
        "Q235": {"E": 206e9, "G": 79e9, "nu": 0.3, "rho": 7850, "fy": 235e6, "fu": 370e6},
        "Q345": {"E": 206e9, "G": 79e9, "nu": 0.3, "rho": 7850, "fy": 345e6, "fu": 470e6},
        "Q355": {"E": 206e9, "G": 79e9, "nu": 0.3, "rho": 7850, "fy": 355e6, "fu": 490e6},
        "Q390": {"E": 206e9, "G": 79e9, "nu": 0.3, "rho": 7850, "fy": 390e6, "fu": 530e6},
        "Q420": {"E": 206e9, "G": 79e9, "nu": 0.3, "rho": 7850, "fy": 420e6, "fu": 540e6},
        "S235": {"E": 210e9, "G": 81e9, "nu": 0.3, "rho": 7850, "fy": 235e6, "fu": 360e6},
        "S275": {"E": 210e9, "G": 81e9, "nu": 0.3, "rho": 7850, "fy": 275e6, "fu": 430e6},
        "S355": {"E": 210e9, "G": 81e9, "nu": 0.3, "rho": 7850, "fy": 355e6, "fu": 510e6},
    }
    if grade in grades:
        return grades[grade]
    # Default fallback
    return {"E": 206e9, "G": 79e9, "nu": 0.3, "rho": 7850, "fy": 355e6, "fu": 490e6}


def recommend_column_section(stories: int, span_m: float, section_family: str = "HE-B") -> str:
    """Recommend a standard steel column section based on structural demand.

    Taller buildings and longer spans need heavier sections.
    """
    demand = stories * span_m

    sections = list(SECTION_FAMILIES[section_family].keys())
    # Sort by section depth (ascending)
    sections.sort(key=lambda s: float(s.replace(section_family.replace("-", ""), "")))

    if stories <= 3 or demand <= 20:
        idx = 0
    elif stories <= 5 or demand <= 30:
        idx = min(2, len(sections) - 1)
    elif stories <= 8 or demand <= 50:
        idx = min(5, len(sections) - 1)
    elif stories <= 12 or demand <= 80:
        idx = min(8, len(sections) - 1)
    else:
        idx = min(12, len(sections) - 1)

    return sections[idx]


def recommend_beam_section(span_m: float, section_family: str = "IPE") -> str:
    """Recommend a standard steel beam section based on span length."""
    sections = list(SECTION_FAMILIES[section_family].keys())
    sections.sort(key=lambda s: float(s.replace(section_family, "")))

    # IPE sections: span-to-depth ratio ~20-25
    required_depth_m = span_m / 20.0

    for sec in sections:
        h = SECTION_FAMILIES[section_family][sec]["h"]
        if h >= required_depth_m:
            return sec

    return sections[-1]


def compute_torsion_constant(sec: dict[str, float]) -> float:
    """Approximate torsional constant J for an I-section.

    J ≈ (2 * b * tf^3 + (h - 2*tf) * tw^3) / 3
    """
    b = sec["b"]
    h = sec["h"]
    tf = sec["tf"]
    tw = sec["tw"]
    return (2 * b * tf**3 + (h - 2 * tf) * tw**3) / 3


def generate_steel_frame(
    num_bays_x: int = 3,
    num_bays_y: int = 3,
    num_stories: int = 4,
    span_x_m: float = 6.0,
    span_y_m: float = 6.0,
    story_height_m: float = 3.0,
    steel_grade: str = "Q355",
    section_family_beams: str = "IPE",
    section_family_columns: str = "HE-B",
    dead_load_kpa: float = 5.0,
    live_load_kpa: float = 2.0,
    base_support: str = "fixed",
) -> dict[str, Any]:
    """Generate a 3D steel frame structure with standard I-beam sections.

    Returns a JSON-compatible dict with nodes, elements, loads, supports,
    and metadata, following the project's analysis-ready format.
    """
    mat = get_steel_material(steel_grade)
    E = mat["E"]
    fy = mat["fy"]

    # Select sections
    col_sec_name = recommend_column_section(num_stories, max(span_x_m, span_y_m), section_family_columns)
    beam_x_sec_name = recommend_beam_section(span_x_m, section_family_beams)
    beam_y_sec_name = recommend_beam_section(span_y_m, section_family_beams)

    col_sec = SECTION_FAMILIES[section_family_columns][col_sec_name]
    beam_x_sec = SECTION_FAMILIES[section_family_beams][beam_x_sec_name]
    beam_y_sec = SECTION_FAMILIES[section_family_beams][beam_y_sec_name]

    # Section properties
    A_col = col_sec["A"]
    Iy_col = col_sec["Iy"]
    Iz_col = col_sec["Iz"]
    J_col = compute_torsion_constant(col_sec)

    A_beam_x = beam_x_sec["A"]
    Iy_beam_x = beam_x_sec["Iy"]
    Iz_beam_x = beam_x_sec["Iz"]
    J_beam_x = compute_torsion_constant(beam_x_sec)

    A_beam_y = beam_y_sec["A"]
    Iy_beam_y = beam_y_sec["Iy"]
    Iz_beam_y = beam_y_sec["Iz"]
    J_beam_y = compute_torsion_constant(beam_y_sec)

    # Build coordinate grid
    x_coords = [i * span_x_m for i in range(num_bays_x + 1)]
    y_coords = [i * span_y_m for i in range(num_bays_y + 1)]
    z_coords = [i * story_height_m for i in range(num_stories + 1)]

    nodes: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    loads: list[dict[str, Any]] = []
    supports: list[dict[str, Any]] = []

    grid_index: dict[tuple[int, int, int], int] = {}

    nid = 0
    for iz, z in enumerate(z_coords):
        for iy, y in enumerate(y_coords):
            for ix, x in enumerate(x_coords):
                nodes.append({"id": nid, "x": x, "y": z, "z": y})
                grid_index[(ix, iy, iz)] = nid
                nid += 1

    eid = 0

    # Columns (vertical) — between each story level
    for story in range(num_stories):
        for iy in range(num_bays_y + 1):
            for ix in range(num_bays_x + 1):
                n_bot = grid_index[(ix, iy, story)]
                n_top = grid_index[(ix, iy, story + 1)]
                is_corner = (ix in (0, num_bays_x)) and (iy in (0, num_bays_y))
                elements.append({
                    "id": eid,
                    "node_i": n_bot,
                    "node_j": n_top,
                    "E": E,
                    "A": A_col,
                    "Iy": Iy_col,
                    "Iz": Iz_col,
                    "J": J_col,
                    "type": "column",
                    "section": col_sec_name,
                    "material": "steel",
                    "steel_grade": steel_grade,
                    "fy": fy,
                    "story": story + 1,
                    "is_corner": is_corner,
                })
                eid += 1

    # X-direction beams (along span_x_m)
    for story in range(1, num_stories + 1):
        for iy in range(num_bays_y + 1):
            for ix in range(num_bays_x):
                n_left = grid_index[(ix, iy, story)]
                n_right = grid_index[(ix + 1, iy, story)]
                elements.append({
                    "id": eid,
                    "node_i": n_left,
                    "node_j": n_right,
                    "E": E,
                    "A": A_beam_x,
                    "Iy": Iy_beam_x,
                    "Iz": Iz_beam_x,
                    "J": J_beam_x,
                    "type": "beam",
                    "direction": "x",
                    "section": beam_x_sec_name,
                    "material": "steel",
                    "steel_grade": steel_grade,
                    "fy": fy,
                    "story": story,
                })
                eid += 1

    # Y-direction beams (along span_y_m)
    for story in range(1, num_stories + 1):
        for ix in range(num_bays_x + 1):
            for iy in range(num_bays_y):
                n_front = grid_index[(ix, iy, story)]
                n_back = grid_index[(ix, iy + 1, story)]
                elements.append({
                    "id": eid,
                    "node_i": n_front,
                    "node_j": n_back,
                    "E": E,
                    "A": A_beam_y,
                    "Iy": Iy_beam_y,
                    "Iz": Iz_beam_y,
                    "J": J_beam_y,
                    "type": "beam",
                    "direction": "y",
                    "section": beam_y_sec_name,
                    "material": "steel",
                    "steel_grade": steel_grade,
                    "fy": fy,
                    "story": story,
                })
                eid += 1

    # Supports — base nodes (z=0)
    for ix in range(num_bays_x + 1):
        for iy in range(num_bays_y + 1):
            supports.append({
                "node_id": grid_index[(ix, iy, 0)],
                "type": base_support,
            })

    # Loads — vertical loads at each floor level
    floor_area = span_x_m * span_y_m
    factor_dead = dead_load_kpa * 1000 * floor_area  # kPa → N per bay
    factor_live = live_load_kpa * 1000 * floor_area

    # Distribute to nodes on perimeter
    for story in range(1, num_stories + 1):
        for ix in range(num_bays_x + 1):
            for iy in range(num_bays_y + 1):
                # Determine tributary area fraction
                bays_nx = 1 if ix in (0, num_bays_x) else 2
                bays_ny = 1 if iy in (0, num_bays_y) else 2
                share = bays_nx * bays_ny
                Fz = -(factor_dead + factor_live) / 4.0 * (4.0 / share)
                loads.append({
                    "node_id": grid_index[(ix, iy, story)],
                    "Fx": 0.0,
                    "Fy": 0.0,
                    "Fz": Fz,
                })

    # Lateral wind loads (simplified: 1 kN/m^2 facade pressure)
    wind_pressure = 1000.0  # N/m^2
    for story in range(1, num_stories + 1):
        facade_height = story_height_m
        for iy in range(num_bays_y + 1):
            for ix in [0, num_bays_x]:
                trib_width = span_y_m / (num_bays_y + 1 if iy in (0, num_bays_y) else num_bays_y)
                force_x = wind_pressure * facade_height * trib_width / 2.0
                loads.append({
                    "node_id": grid_index[(ix, iy, story)],
                    "Fx": force_x if ix == 0 else -force_x,
                    "Fy": 0.0,
                    "Fz": 0.0,
                })

    metadata = {
        "type": "steel_frame",
        "dimension": "3d",
        "material": steel_grade,
        "material_type": "steel",
        "num_bays_x": num_bays_x,
        "num_bays_y": num_bays_y,
        "num_stories": num_stories,
        "span_x_m": span_x_m,
        "span_y_m": span_y_m,
        "story_height_m": story_height_m,
        "E": E,
        "fy": fy,
        "elements_total": len(elements),
        "columns": num_stories * (num_bays_x + 1) * (num_bays_y + 1),
        "beams_x": num_stories * (num_bays_y + 1) * num_bays_x,
        "beams_y": num_stories * (num_bays_x + 1) * num_bays_y,
        "base_support": base_support,
        "column_section": col_sec_name,
        "beam_section_x": beam_x_sec_name,
        "beam_section_y": beam_y_sec_name,
        "section_family_columns": section_family_columns,
        "section_family_beams": section_family_beams,
        "dead_load_kpa": dead_load_kpa,
        "live_load_kpa": live_load_kpa,
        "available_sections": {
            "columns": list(SECTION_FAMILIES[section_family_columns].keys()),
            "beams": list(SECTION_FAMILIES[section_family_beams].keys()),
        },
    }

    return {
        "nodes": nodes,
        "elements": elements,
        "loads": loads,
        "supports": supports,
        "metadata": metadata,
        "materials": {
            "steel": {
                "grade": steel_grade,
                "fy": fy,
                "fu": mat["fu"],
                "E": E,
                "G": mat["G"],
                "nu": mat["nu"],
                "rho": mat["rho"],
            },
        },
    }


def list_steel_sections() -> dict[str, Any]:
    """List all available steel sections with their properties."""
    result = {}
    for family, sections in SECTION_FAMILIES.items():
        result[family] = {}
        for name, sec in sections.items():
            result[family][name] = {
                "h_m": sec["h"],
                "b_m": sec["b"],
                "tw_m": sec["tw"],
                "tf_m": sec["tf"],
                "A_m2": sec["A"],
                "Iy_m4": sec["Iy"],
                "Iz_m4": sec["Iz"],
                "Wely_m3": sec["Wely"],
                "Welz_m3": sec["Welz"],
                "J_m4": compute_torsion_constant(sec),
            }
    return result
