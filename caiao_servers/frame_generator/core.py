"""FrameGenerator core — parametric 2D/3D frame structure generation.

Pure logic, no MCP dependency. Can be imported and tested independently.
Outputs structures in the project's native format (FrameNode, FrameElement, etc.)
compatible with anaStruct and OpenSees analyzers.

Inspired by StructureClaw's material/section reference database.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Material databases (from StructureClaw reference)
# ---------------------------------------------------------------------------

STEEL_GRADES: dict[str, dict[str, float]] = {
    "Q235": {"E": 206e9, "G": 79e9, "nu": 0.3, "rho": 7850, "fy": 235e6},
    "Q345": {"E": 206e9, "G": 79e9, "nu": 0.3, "rho": 7850, "fy": 345e6},
    "Q355": {"E": 206e9, "G": 79e9, "nu": 0.3, "rho": 7850, "fy": 355e6},
    "Q390": {"E": 206e9, "G": 79e9, "nu": 0.3, "rho": 7850, "fy": 390e6},
    "Q420": {"E": 206e9, "G": 79e9, "nu": 0.3, "rho": 7850, "fy": 420e6},
    "S235": {"E": 210e9, "G": 81e9, "nu": 0.3, "rho": 7850, "fy": 235e6},
    "S275": {"E": 210e9, "G": 81e9, "nu": 0.3, "rho": 7850, "fy": 275e6},
    "S355": {"E": 210e9, "G": 81e9, "nu": 0.3, "rho": 7850, "fy": 355e6},
}

CONCRETE_GRADES: dict[str, dict[str, float]] = {
    "C20": {"E": 25.5e9, "G": 10.625e9, "nu": 0.2, "rho": 2500, "fc": 9.6e6},
    "C25": {"E": 28.0e9, "G": 11.667e9, "nu": 0.2, "rho": 2500, "fc": 11.9e6},
    "C30": {"E": 30.0e9, "G": 12.5e9, "nu": 0.2, "rho": 2500, "fc": 14.3e6},
    "C35": {"E": 31.5e9, "G": 13.125e9, "nu": 0.2, "rho": 2500, "fc": 16.7e6},
    "C40": {"E": 32.5e9, "G": 13.542e9, "nu": 0.2, "rho": 2500, "fc": 19.1e6},
    "C45": {"E": 33.5e9, "G": 13.958e9, "nu": 0.2, "rho": 2500, "fc": 21.1e6},
    "C50": {"E": 34.5e9, "G": 14.375e9, "nu": 0.2, "rho": 2500, "fc": 23.1e6},
}

# ---------------------------------------------------------------------------
# Section sizing rules
# ---------------------------------------------------------------------------

def _recommend_column_section(stories: int) -> tuple[float, float]:
    """Recommend column section (width_m, depth_m) based on story count."""
    if stories <= 3:
        return (0.4, 0.4)
    if stories <= 5:
        return (0.5, 0.5)
    if stories <= 8:
        return (0.6, 0.6)
    return (0.7, 0.7)


def _recommend_beam_section(span_m: float) -> tuple[float, float]:
    """Recommend beam section (width_m, depth_m) based on span."""
    if span_m <= 6:
        return (0.2, 0.4)
    if span_m <= 7:
        return (0.25, 0.5)
    if span_m <= 8:
        return (0.3, 0.6)
    return (0.35, 0.7)


def _recommend_steel_column(stories: int) -> str:
    """Recommend standard steel column section name."""
    if stories > 10:
        return "HW400X400"
    if stories > 5:
        return "HW350X350"
    return "HW300X300"


def _recommend_steel_beam(stories: int) -> str:
    """Recommend standard steel beam section name."""
    if stories > 10:
        return "HN600X200"
    if stories > 5:
        return "HN450X200"
    return "HN350X175"


# ---------------------------------------------------------------------------
# Section property calculators
# ---------------------------------------------------------------------------

def compute_rectangular_section(width: float, depth: float) -> dict[str, float]:
    """Compute section properties for a rectangular section (concrete)."""
    A = width * depth
    Iy = width * depth ** 3 / 12  # strong axis
    Iz = depth * width ** 3 / 12  # weak axis
    J = max(width, depth) * min(width, depth) ** 3 * (
        (1 / 3) - 0.21 * min(width, depth) / max(width, depth) * (1 - min(width, depth) ** 4 / (12 * max(width, depth) ** 4))
    )
    return {"A": A, "Iy": Iy, "Iz": Iz, "J": J}


# ---------------------------------------------------------------------------
# Structure generation
# ---------------------------------------------------------------------------

@dataclass
class FrameGeneratorConfig:
    """Configuration for frame generation."""
    # Grid geometry
    num_bays_x: int = 3          # Number of bays in X direction
    num_bays_y: int = 3          # Number of bays in Y direction (1 = 2D)
    num_stories: int = 4         # Number of stories
    span_x_m: float = 6.0        # Span length in X direction (m)
    span_y_m: float = 6.0        # Span length in Y direction (m)
    story_height_m: float = 3.0  # Story height (m)

    # Material
    material_type: str = "steel"  # "steel" or "concrete"
    steel_grade: str = "Q355"
    concrete_grade: str = "C30"

    # Loads (kN)
    dead_load_kpa: float = 5.0   # Dead load per floor area (kPa)
    live_load_kpa: float = 2.0   # Live load per floor area (kPa)
    lateral_load_kN: float = 0.0 # Lateral load per floor at each node (kN)

    # Support
    base_support: str = "fixed"  # "fixed" or "hinged"

    def __post_init__(self):
        # Validate
        assert self.num_bays_x >= 1, "num_bays_x must be >= 1"
        assert self.num_bays_y >= 1, "num_bays_y must be >= 1"
        assert self.num_stories >= 1, "num_stories must be >= 1"
        assert self.material_type in ("steel", "concrete")
        if self.material_type == "steel":
            assert self.steel_grade in STEEL_GRADES, f"Unknown steel grade: {self.steel_grade}"
        else:
            assert self.concrete_grade in CONCRETE_GRADES, f"Unknown concrete grade: {self.concrete_grade}"


class FrameGenerator:
    """Parametric frame structure generator.

    Produces structures in the project's native format, compatible with
    anaStruct / OpenSees analyzers and the frontend FrameVisualization.
    """

    def __init__(self, config: FrameGeneratorConfig):
        self.config = config
        self._init_materials()

    def _init_materials(self):
        if self.config.material_type == "steel":
            mat = STEEL_GRADES[self.config.steel_grade]
            self._E = mat["E"]
            self._rho = mat["rho"]
            self._fy = mat.get("fy", 0)
            self._grade_name = self.config.steel_grade
        else:
            mat = CONCRETE_GRADES[self.config.concrete_grade]
            self._E = mat["E"]
            self._rho = mat["rho"]
            self._fc = mat.get("fc", 0)
            self._grade_name = self.config.concrete_grade

    # --- 2D frame generation (X-Z plane, Y-up) ---

    def generate_2d(self) -> dict[str, Any]:
        """Generate a 2D frame structure in the native format.

        Returns:
            dict with keys: nodes, elements, loads, supports
            Each element/node/load/support matches the FrameVisualization types.
        """
        cfg = self.config

        # Compute section sizes
        if cfg.material_type == "steel":
            col_name = _recommend_steel_column(cfg.num_stories)
            beam_name = _recommend_steel_beam(cfg.num_stories)
            col_w, col_d = 0.4, 0.4  # placeholder — real sections differ
            beam_w, beam_d = 0.2, 0.4
            A_col = col_w * col_d
            I_col = col_w * col_d ** 3 / 12
            A_beam = beam_w * beam_d
            I_beam = beam_w * beam_d ** 3 / 12
        else:
            col_w, col_d = _recommend_column_section(cfg.num_stories)
            beam_w, beam_d = _recommend_beam_section(cfg.span_x_m)
            col_props = compute_rectangular_section(col_w, col_d)
            beam_props = compute_rectangular_section(beam_w, beam_d)
            A_col, I_col = col_props["A"], col_props["Iy"]
            A_beam, I_beam = beam_props["A"], beam_props["Iy"]

        nodes: list[dict[str, Any]] = []
        elements: list[dict[str, Any]] = []
        loads: list[dict[str, Any]] = []
        supports: list[dict[str, Any]] = []

        # 2D frame = single bay line in X, stories in Y
        nid = 0
        grid: dict[tuple[int, int], int] = {}

        for row in range(cfg.num_stories + 1):
            for col in range(cfg.num_bays_x + 1):
                x = col * cfg.span_x_m
                y = row * cfg.story_height_m
                nodes.append({"id": nid, "x": x, "y": y})
                grid[(col, row)] = nid
                nid += 1

        # Columns (vertical elements)
        eid = 0
        for row in range(cfg.num_stories):
            for col in range(cfg.num_bays_x + 1):
                elements.append({
                    "id": eid, "node_i": grid[(col, row)], "node_j": grid[(col, row + 1)],
                    "E": self._E, "A": A_col, "I": I_col,
                    "Iy": I_col, "Iz": A_col * col_w ** 2 / 12, "J": A_col * col_w ** 2 / 12,
                })
                eid += 1

        # Beams (horizontal elements)
        for row in range(1, cfg.num_stories + 1):
            for col in range(cfg.num_bays_x):
                elements.append({
                    "id": eid, "node_i": grid[(col, row)], "node_j": grid[(col + 1, row)],
                    "E": self._E, "A": A_beam, "I": I_beam,
                    "Iy": I_beam, "Iz": A_beam * beam_w ** 2 / 12, "J": A_beam * beam_w ** 2 / 12,
                })
                eid += 1

        # Supports — base nodes are fixed/hinged
        support_type = cfg.base_support
        for col in range(cfg.num_bays_x + 1):
            supports.append({"node_id": grid[(col, 0)], "type": support_type})

        # Loads — distribute floor loads to nodes at each story level
        # Convert kPa to point loads: kPa * (span_x * span_y) / nodes_per_floor
        nodes_per_floor = cfg.num_bays_x + 1
        floor_area = cfg.span_x_m * cfg.span_y_m
        total_dead_N = cfg.dead_load_kpa * 1000 * floor_area  # kPa → N
        total_live_N = cfg.live_load_kpa * 1000 * floor_area
        per_node_dead = total_dead_N / nodes_per_floor
        per_node_live = total_live_N / nodes_per_floor

        for row in range(1, cfg.num_stories + 1):
            for col in range(cfg.num_bays_x + 1):
                Fy = -(per_node_dead + per_node_live)  # downward
                loads.append({"node_id": grid[(col, row)], "Fx": 0, "Fy": Fy})

        # Metadata
        metadata = {
            "type": "frame",
            "dimension": "2d",
            "material": self._grade_name,
            "material_type": cfg.material_type,
            "stories": cfg.num_stories,
            "bays": cfg.num_bays_x,
            "span_m": cfg.span_x_m,
            "story_height_m": cfg.story_height_m,
            "elements_total": len(elements),
            "columns": cfg.num_stories * (cfg.num_bays_x + 1),
            "beams": cfg.num_stories * cfg.num_bays_x,
            "base_support": cfg.base_support,
            "dead_load_kpa": cfg.dead_load_kpa,
            "live_load_kpa": cfg.live_load_kpa,
            "column_section": f"{col_w}x{col_d}",
            "beam_section": f"{beam_w}x{beam_d}",
        }

        return {
            "nodes": nodes,
            "elements": elements,
            "loads": loads,
            "supports": supports,
            "metadata": metadata,
        }

    # --- 3D frame generation (for reference / Unity export) ---

    def generate_3d(self) -> dict[str, Any]:
        """Generate a 3D frame description with columns, beams, slabs.

        Returns geometry-oriented format suitable for:
        - Unity 3D scene construction
        - SVG 3D projection visualization
        - Future Three.js/WebGL rendering
        """
        cfg = self.config
        x_coords = [i * cfg.span_x_m for i in range(cfg.num_bays_x + 1)]
        y_coords = [i * cfg.span_y_m for i in range(cfg.num_bays_y + 1)]
        z_coords = [i * cfg.story_height_m for i in range(cfg.num_stories + 1)]

        if cfg.material_type == "steel":
            col_w, col_d = 0.4, 0.4
            beam_w, beam_d = 0.2, 0.4
            col_color = "#A9A9A9"
            beam_color = "#808080"
        else:
            col_w, col_d = _recommend_column_section(cfg.num_stories)
            beam_w, beam_d = _recommend_beam_section(cfg.span_x_m)
            col_color = "#8B8B8B"
            beam_color = "#A0A0A0"

        columns: list[dict[str, Any]] = []
        beams: list[dict[str, Any]] = []
        slabs: list[dict[str, Any]] = []
        threejs_objects: list[dict[str, Any]] = []

        # Columns
        col_id = 0
        for story_idx in range(1, cfg.num_stories + 1):
            for xi, x in enumerate(x_coords):
                for yi, y in enumerate(y_coords):
                    bot_z = z_coords[story_idx - 1]
                    top_z = z_coords[story_idx]
                    is_corner = (xi in (0, cfg.num_bays_x)) and (yi in (0, cfg.num_bays_y))
                    is_edge = (xi in (0, cfg.num_bays_x)) or (yi in (0, cfg.num_bays_y))

                    columns.append({
                        "id": f"C{col_id}",
                        "type": "column",
                        "start": [x, bot_z, y],
                        "end": [x, top_z, y],
                        "width": col_w,
                        "depth": col_d,
                        "height": cfg.story_height_m,
                        "material": {"concrete": cfg.concrete_grade if cfg.material_type == "concrete" else "", "color": col_color},
                        "isCorner": is_corner,
                        "isEdge": is_edge,
                        "story": story_idx,
                        "gridIndex": [xi, yi, story_idx],
                        "fixedBase": story_idx == 1,
                        "userData": {
                            "demolition": {
                                "fragile": not (story_idx == 1 and not is_corner),
                                "blastResistance": 1.0 if story_idx == 1 else 0.6,
                            }
                        },
                    })

                    # Three.js box for column
                    center_x = x
                    center_y = bot_z + cfg.story_height_m / 2
                    center_z = y
                    threejs_objects.append({
                        "uuid": f"col_{col_id}",
                        "type": "box",
                        "position": [center_x, center_y, center_z],
                        "size": [col_w, cfg.story_height_m, col_d],
                        "rotation": [0, 0, 0],
                        "color": col_color,
                        "userData": {
                            "structuralId": f"C{col_id}",
                            "structuralRole": "column",
                            "isLoadBearing": True,
                            "demolition": {
                                "fragile": not (story_idx == 1 and not is_corner),
                                "blastResistance": 1.0 if story_idx == 1 else 0.6,
                            },
                        },
                    })
                    col_id += 1

        # Beams
        beam_id = 0
        for story_idx in range(1, cfg.num_stories + 1):
            z = z_coords[story_idx]

            # X-direction beams
            for xi in range(cfg.num_bays_x):
                for yi, y in enumerate(y_coords):
                    x1 = x_coords[xi]
                    x2 = x_coords[xi + 1]
                    beams.append({
                        "id": f"BX{beam_id}",
                        "type": "beam",
                        "direction": "x",
                        "start": [x1, z, y],
                        "end": [x2, z, y],
                        "width": beam_w,
                        "height": beam_d,
                        "material": {"concrete": cfg.concrete_grade if cfg.material_type == "concrete" else "", "color": beam_color},
                        "story": story_idx,
                        "gridIndex": [xi, yi, story_idx],
                    })

                    cx = (x1 + x2) / 2
                    threejs_objects.append({
                        "uuid": f"beam_x_{beam_id}",
                        "type": "box",
                        "position": [cx, z, y],
                        "size": [cfg.span_x_m, beam_d, beam_w],
                        "rotation": [0, 0, 0],
                        "color": beam_color,
                        "userData": {
                            "structuralId": f"BX{beam_id}",
                            "structuralRole": "beam",
                            "isLoadBearing": True,
                            "demolition": {"fragile": True, "blastResistance": 0.5},
                        },
                    })
                    beam_id += 1

            # Y-direction beams
            for yi in range(cfg.num_bays_y):
                for xi, x in enumerate(x_coords):
                    y1 = y_coords[yi]
                    y2 = y_coords[yi + 1]
                    beams.append({
                        "id": f"BY{beam_id}",
                        "type": "beam",
                        "direction": "y",
                        "start": [x, z, y1],
                        "end": [x, z, y2],
                        "width": beam_w,
                        "height": beam_d,
                        "material": {"concrete": cfg.concrete_grade if cfg.material_type == "concrete" else "", "color": beam_color},
                        "story": story_idx,
                        "gridIndex": [xi, yi, story_idx],
                    })

                    cz = (y1 + y2) / 2
                    threejs_objects.append({
                        "uuid": f"beam_y_{beam_id}",
                        "type": "box",
                        "position": [x, z, cz],
                        "size": [beam_w, beam_d, cfg.span_y_m],
                        "rotation": [0, 0, 0],
                        "color": beam_color,
                        "userData": {
                            "structuralId": f"BY{beam_id}",
                            "structuralRole": "beam",
                            "isLoadBearing": True,
                            "demolition": {"fragile": True, "blastResistance": 0.5},
                        },
                    })
                    beam_id += 1

        # Slabs
        slab_id = 0
        for story_idx in range(1, cfg.num_stories + 1):
            z = z_coords[story_idx]
            for xi in range(cfg.num_bays_x):
                for yi in range(cfg.num_bays_y):
                    x1, x2 = x_coords[xi], x_coords[xi + 1]
                    y1, y2 = y_coords[yi], y_coords[yi + 1]
                    slabs.append({
                        "id": f"S{slab_id}",
                        "type": "slab",
                        "corners": [[x1, z, y1], [x2, z, y1], [x2, z, y2], [x1, z, y2]],
                        "thickness": 0.15,
                        "material": {"concrete": cfg.concrete_grade if cfg.material_type == "concrete" else "", "color": "#D3D3D3"},
                        "story": story_idx,
                    })

                    cx = (x1 + x2) / 2
                    cz = (y1 + y2) / 2
                    threejs_objects.append({
                        "uuid": f"slab_{slab_id}",
                        "type": "box",
                        "position": [cx, z - 0.075, cz],
                        "size": [cfg.span_x_m, 0.15, cfg.span_y_m],
                        "rotation": [0, 0, 0],
                        "color": "#D3D3D3",
                        "userData": {
                            "structuralId": f"S{slab_id}",
                            "structuralRole": "slab",
                            "isLoadBearing": True,
                            "demolition": {"fragile": True, "blastResistance": 0.3},
                        },
                    })
                    slab_id += 1

        return {
            "metadata": {
                "type": "frame",
                "dimension": "3d",
                "grid": {
                    "xFrames": cfg.num_bays_x,
                    "ySpans": cfg.num_bays_y,
                    "stories": cfg.num_stories,
                    "storyHeight": cfg.story_height_m,
                    "spanLength": cfg.span_x_m,
                    "spanWidth": cfg.span_y_m,
                },
                "material": self._grade_name,
                "material_type": cfg.material_type,
                "origin": [0, 0, 0],
            },
            "columns": columns,
            "beams": beams,
            "slabs": slabs,
            "threejsObjects": threejs_objects,
        }

    def generate_2d_analysis_ready(self) -> dict[str, Any]:
        """Generate a 2D frame and pre-compute analysis inputs.

        Returns structure + recommended element sizing for analysis.
        """
        result = self.generate_2d()
        cfg = self.config

        # Add analysis hints
        result["analysis_hints"] = {
            "recommended_solver": "anastruct",
            "verify_with": "opensees",
            "critical_load_case": "dead + live",
            "max_axial_column_expected": (
                (cfg.dead_load_kpa + cfg.live_load_kpa)
                * cfg.span_x_m * cfg.span_y_m
                * cfg.num_stories * 1000  # N
            ),
        }
        return result


def generate_from_natural(text: str) -> dict[str, Any]:
    """Quick parser for natural-language descriptions.

    Supports patterns like:
    - "3x4 frame, 4 stories, 3m height, 6m span"
    - "2x2 bay 3-story steel frame Q345"
    - "concrete frame C30 5 floor"
    """
    import re

    cfg = FrameGeneratorConfig()

    # bays
    m = re.search(r"(\d+)\s*[xX×]\s*(\d+)", text)
    if m:
        cfg.num_bays_x = int(m.group(1))
        cfg.num_bays_y = int(m.group(2))

    # stories
    m = re.search(r"(\d+)\s*(?:stor(?:y|ies)|floor|层)", text)
    if m:
        cfg.num_stories = int(m.group(1))

    # story height (supports "3m height", "height 3m", "层高3m", "3m层高")
    # Try "3m height" pattern FIRST to avoid cross-word matching like "height 6m"
    for pat in [
        r"(\d+(?:\.\d+)?)\s*m\s*(?:height|层高)\b",
        r"(?:height|层高)\s*(\d+(?:\.\d+)?)\s*m(?!\w)",
    ]:
        m = re.search(pat, text)
        if m:
            cfg.story_height_m = float(m.group(1))
            break

    # span (supports "6m span", "span 6m", "跨度6m", "6m跨度")
    for pat in [
        r"(\d+(?:\.\d+)?)\s*m\s*(?:span|跨度)\b",
        r"(?:span|跨度)\s*(\d+(?:\.\d+)?)\s*m(?!\w)",
    ]:
        m = re.search(pat, text)
        if m:
            cfg.span_x_m = float(m.group(1))
            cfg.span_y_m = float(m.group(1))
            break

    # material
    m = re.search(r"(?:steel|钢)", text)
    if m:
        cfg.material_type = "steel"
    m = re.search(r"(?:concrete|混凝土)", text)
    if m:
        cfg.material_type = "concrete"

    for grade in list(STEEL_GRADES.keys()) + list(CONCRETE_GRADES.keys()):
        if grade.lower() in text.lower():
            if grade in STEEL_GRADES:
                cfg.material_type = "steel"
                cfg.steel_grade = grade
            else:
                cfg.material_type = "concrete"
                cfg.concrete_grade = grade
            break

    # support
    if "hinged" in text or "铰接" in text:
        cfg.base_support = "hinged"

    return FrameGenerator(cfg).generate_2d_analysis_ready()
