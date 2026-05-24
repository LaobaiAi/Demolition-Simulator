"""Tests for full_analysis_3d_server (Merge #2)."""

import json
import sys
import os

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from full_analysis_3d_server.server import (
    _run_pipeline,
    _convert_3d_to_unified,
    _select_critical_3d,
)
from frame_generator.core import FrameGenerator, FrameGeneratorConfig


def test_basic_3x3x4():
    """Default config produces correct node/element counts."""
    result = _run_pipeline({})
    assert result["status"] == "complete"
    s = result["structure"]
    # 4x4x5 = 80 nodes
    assert len(s["nodes"]) == 80, f"Expected 80 nodes, got {len(s['nodes'])}"
    # 64 columns + 96 beams = 160
    assert len(s["elements"]) == 160, f"Expected 160 elements, got {len(s['elements'])}"


def test_small_2x2x2():
    """Small frame produces correct counts."""
    result = _run_pipeline({
        "num_bays_x": 2, "num_bays_y": 2, "num_stories": 2,
    })
    assert result["status"] == "complete"
    s = result["structure"]
    # 3x3x3 = 27 nodes
    assert len(s["nodes"]) == 27
    # 18 columns + 24 beams = 42
    assert len(s["elements"]) == 42


def test_3d_coordinates():
    """Nodes have non-zero z values (real 3D, not flattened)."""
    result = _run_pipeline({"num_bays_x": 2, "num_bays_y": 2, "num_stories": 2})
    nodes = result["structure"]["nodes"]
    z_vals = {round(n["z"], 4) for n in nodes}
    assert len(z_vals) > 1, f"All nodes at same z: {z_vals}"
    assert 0 in z_vals  # some nodes at ground
    assert 6.0 in z_vals or 12.0 in z_vals  # some nodes elevated


def test_supports_at_base():
    """Base nodes (y≈0) have supports, non-base don't."""
    result = _run_pipeline({})
    s = result["structure"]
    supported_nodes = {sup["node_id"] for sup in s["supports"]}
    for n in s["nodes"]:
        if abs(n["y"]) < 0.001:
            assert n["id"] in supported_nodes, f"Base node {n['id']} missing support"
        else:
            assert n["id"] not in supported_nodes, f"Non-base node {n['id']} has support"


def test_element_types():
    """Elements are typed as column or beam."""
    result = _run_pipeline({})
    elements = result["structure"]["elements"]
    cols = [e for e in elements if e.get("type") == "column"]
    beams = [e for e in elements if e.get("type") == "beam"]
    assert len(cols) > 0, "No column elements"
    assert len(beams) > 0, "No beam elements"
    assert len(cols) + len(beams) == len(elements)


def test_analysis_results():
    """Analysis returns displacements and forces for all nodes/elements."""
    result = _run_pipeline({})
    analysis = result["analysis"]
    s = result["structure"]
    assert "error" not in analysis, f"Analysis error: {analysis.get('error')}"
    assert len(analysis.get("node_displacements", [])) == len(s["nodes"])
    assert len(analysis.get("element_forces", [])) == len(s["elements"])
    assert analysis.get("max_displacement", 0) > 0


def test_critical_element_found():
    """Critical element selector identifies a column."""
    result = _run_pipeline({})
    c = result["critical_element"]
    assert c["critical_element_id"] >= 0
    assert c["critical_axial_force_N"] > 0
    assert len(c["all_columns"]) > 0
    assert "reason" in c


def test_critical_columns_are_vertical():
    """All identified columns have same x,z at both ends (vertical)."""
    result = _run_pipeline({})
    c = result["critical_element"]
    nodes = {n["id"]: n for n in result["structure"]["nodes"]}
    for col in c["all_columns"]:
        n_i = nodes[col["bottom_node"]]
        n_j = nodes[col["top_node"]]
        assert abs(n_i["x"] - n_j["x"]) < 0.01
        assert abs(n_i["z"] - n_j["z"]) < 0.01
        assert abs(n_i["y"] - n_j["y"]) > 0.01  # different heights


def test_convert_3d_to_unified():
    """Direct test of converter."""
    cfg = FrameGeneratorConfig(num_bays_x=1, num_bays_y=1, num_stories=1)
    gen = FrameGenerator(cfg)
    geometry = gen.generate_3d()
    result = _convert_3d_to_unified(geometry, cfg)
    assert len(result["nodes"]) > 0
    assert len(result["elements"]) > 0
    assert len(result["supports"]) > 0


def test_metadata():
    """Pipeline includes metadata for frontend/tracking."""
    result = _run_pipeline({})
    meta = result.get("metadata", {})
    assert meta.get("pipeline") == "full_analysis_3d"
    assert meta.get("dimension") == "3d"
    assert "config" in meta
    assert meta["config"]["num_stories"] == 4


def test_section_properties_carried():
    """Section properties from 3d geometry are carried into UnifiedFrame."""
    result = _run_pipeline({"material_type": "steel"})
    elements = result["structure"]["elements"]
    for elem in elements:
        assert elem.get("E", 0) > 0
        assert elem.get("A", 0) > 0
        assert elem.get("Iy", 0) > 0
        assert elem.get("Iz", 0) > 0


def test_material_concrete():
    """Concrete frame uses concrete E modulus."""
    result = _run_pipeline({"material_type": "concrete", "concrete_grade": "C30"})
    elements = result["structure"]["elements"]
    assert elements[0]["E"] == 30.0e9  # C30 E


def test_lateral_load():
    """Lateral load adds horizontal forces to top nodes."""
    result = _run_pipeline({"lateral_load_kN": 100.0})
    loads = result["structure"]["loads"]
    lateral_loads = [ld for ld in loads if ld.get("Fx", 0) != 0]
    assert len(lateral_loads) > 0, "No lateral loads with Fx != 0"


def test_hinged_support():
    """Hinged support type creates different support conditions."""
    result = _run_pipeline({"base_support": "hinged"})
    supports = result["structure"]["supports"]
    for sup in supports:
        assert sup["type"] == "hinged"


if __name__ == "__main__":
    for name in sorted(globals()):
        if name.startswith("test_"):
            try:
                globals[name]()
                print(f"  ✅ {name}")
            except Exception as e:
                print(f"  ❌ {name}: {e}")
    print("Done.")
