"""Tests for full_analysis_3d_gb_server (steel-frame-design engine, GB50017)."""

import os
import sys

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from full_analysis_3d_gb_server.server import _run_pipeline
import servers.opensees_runner as opensees_runner


def test_default_3x3x4():
    """Default config produces complete result with 80 nodes / 160 elements."""
    result = _run_pipeline({})
    assert result["status"] == "complete", result.get("error")
    s = result["structure"]
    assert len(s["nodes"]) == 80, f"Expected 80 nodes, got {len(s['nodes'])}"
    assert len(s["elements"]) == 160, f"Expected 160 elements, got {len(s['elements'])}"
    base_ids = {n["id"] for n in s["nodes"] if abs(n["y"]) < 0.001}
    supported = {sup["node_id"] for sup in s["supports"]}
    assert base_ids == supported, "All base nodes must have supports"


def test_small_2x2x2():
    """Small frame produces 27 nodes / 42 elements."""
    result = _run_pipeline({"num_bays_x": 2, "num_bays_y": 2, "num_stories": 2})
    assert result["status"] == "complete", result.get("error")
    s = result["structure"]
    assert len(s["nodes"]) == 27, f"Expected 27 nodes, got {len(s['nodes'])}"
    assert len(s["elements"]) == 42, f"Expected 42 elements, got {len(s['elements'])}"


def test_hinged_support():
    """Hinged base maps to type string on every base node."""
    result = _run_pipeline({"base_support": "hinged"})
    supports = result["structure"]["supports"]
    assert len(supports) > 0
    for sup in supports:
        assert sup["type"] == "hinged"


def test_lateral_load():
    """Lateral load adds Fx != 0 loads to top nodes."""
    result = _run_pipeline({"lateral_load_kN": 100.0})
    loads = result["structure"]["loads"]
    lateral = [ld for ld in loads if abs(ld.get("Fx", 0)) > 0]
    assert len(lateral) > 0, "No lateral loads with Fx != 0"
    top_y = max(n["y"] for n in result["structure"]["nodes"])
    for ld in lateral:
        n = next(n for n in result["structure"]["nodes"] if n["id"] == ld["node_id"])
        assert abs(n["y"] - top_y) < 0.001, "Lateral load must be at top level"


def test_analysis_results():
    """Analysis returns displacements and forces for all nodes/elements."""
    result = _run_pipeline({})
    analysis = result["analysis"]
    s = result["structure"]
    assert "error" not in analysis, analysis.get("error")
    assert len(analysis["node_displacements"]) == len(s["nodes"])
    assert len(analysis["element_forces"]) == len(s["elements"])
    assert analysis["max_displacement"] > 0
    assert analysis["solver"] in {"Matrix Method", "OpenSeesPy"}
    assert analysis["load_case"] == "Total"
    assert analysis["max_axial_force"] > 0


def test_element_forces_have_stress_ratio():
    """Every element force entry carries the GB50017 stress ratio."""
    result = _run_pipeline({})
    for ef in result["analysis"]["element_forces"]:
        assert "stress_ratio" in ef, f"element {ef['element_id']} missing stress_ratio"
        assert ef["stress_ratio"] > 0


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


def test_code_check_gb50017():
    """GB50017 check covers all 160 elements with 0-based element ids."""
    result = _run_pipeline({})
    cc = result["code_check"]
    assert cc["summary"]["total_elements"] == 160, cc["summary"]
    assert cc["summary"]["passed"] + cc["summary"]["failed"] == 160
    ids = []
    for e in cc["elements"]:
        assert e["stress_ratio"] > 0, f"element {e['element_id']} stress_ratio not positive"
        ids.append(e["element_id"])
    assert all(0 <= i < 160 for i in ids), "code_check element ids must be 0-based in [0, 160)"
    assert len(set(ids)) == 160, "code_check element ids must be unique"
    # No calc_processes in the returned payload (volume control)
    for e in cc["elements"]:
        assert "calc_processes" not in e


def test_solver_forced_matrix_method():
    """Patching _OPENSEES_AVAILABLE=False forces the Matrix Method engine."""
    saved = opensees_runner._OPENSEES_AVAILABLE
    opensees_runner._OPENSEES_AVAILABLE = False
    try:
        result = _run_pipeline({})
        assert result["analysis"]["solver"] == "Matrix Method"
        assert result["metadata"]["engine"] == "Matrix Method"
    finally:
        opensees_runner._OPENSEES_AVAILABLE = saved


def test_material_concrete_error():
    """Concrete material returns a status error pointing to 2D/legacy tools."""
    result = _run_pipeline({"material_type": "concrete"})
    assert result["status"] == "error"
    assert "quick_analysis" in result["error"] or "full_analysis_3d" in result["error"]


def test_invalid_steel_grade_error():
    """Unknown steel grade returns an error listing valid grades."""
    result = _run_pipeline({"steel_grade": "Q500"})
    assert result["status"] == "error"
    assert "Q355" in result["error"]
    assert "Q420" in result["error"]


def test_custom_sections():
    """Custom section names are honored in the model."""
    result = _run_pipeline({"column_section": "HW300x300x10x15",
                            "beam_section": "HM300x250x9x14"})
    assert result["status"] == "complete", result.get("error")
    sects = {e["section"] for e in result["structure"]["elements"]}
    assert sects == {"HW300x300x10x15", "HM300x250x9x14"}
    assert result["metadata"]["sections_used"] == ["HW300x300x10x15", "HM300x250x9x14"]


def test_metadata():
    """Pipeline metadata carries engine, config and sections."""
    result = _run_pipeline({})
    meta = result["metadata"]
    assert meta["pipeline"] == "full_analysis_3d_gb"
    assert meta["dimension"] == "3d"
    assert meta["config"]["num_stories"] == 4
    assert meta["engine"] == result["analysis"]["solver"]
    assert meta["sections_used"] == ["HW350x350x12x19", "HM340x250x9x14"]


if __name__ == "__main__":
    passed = failed = 0
    for name in sorted(globals()):
        if name.startswith("test_"):
            try:
                globals()[name]()
                print(f"  PASS {name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL {name}: {e}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
