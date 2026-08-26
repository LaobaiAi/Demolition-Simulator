"""Tests for full_analysis_3d_gb_server member removal re-analysis (_run_removal)."""

import os
import sys

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from full_analysis_3d_gb_server.server import _run_pipeline, _run_removal


def test_1_baseline():
    """Baseline pipeline returns the 160-element structure to remove members from."""
    result = _run_pipeline({})
    assert result["status"] == "complete", result.get("error")
    assert len(result["structure"]["elements"]) == 160
    assert result["metadata"]["config"]["dead_load_kpa"] == 5.0
    assert result["metadata"]["config"]["column_section"] == "HW350x350x12x19"


def test_2_remove_one_beam():
    """Removing one interior beam re-analyzes cleanly on the remaining structure."""
    base = _run_pipeline({})
    s = base["structure"]
    n = len(s["elements"])
    beam = next(e for e in s["elements"] if e["type"] == "beam")
    result = _run_removal({"structure": s, "removed_member_ids": [beam["id"]]})
    assert result["status"] == "complete", result.get("error")
    assert len(result["structure"]["elements"]) == n - 1
    ids = {e["id"] for e in result["structure"]["elements"]}
    assert beam["id"] not in ids
    assert beam["id"] in result["removed_member_ids"]
    assert result["remaining_member_ids"] == sorted(ids)
    assert len(result["analysis"]["element_forces"]) == n - 1
    for ef in result["analysis"]["element_forces"]:
        assert "stress_ratio" in ef, f"element {ef['element_id']} missing stress_ratio"
    assert result["analysis"]["max_displacement"] <= 5.0 * base["analysis"]["max_displacement"]
    assert result["critical_element"]["critical_element_id"] in ids


def test_3_remove_all_ground_columns():
    """Removing every ground-story column leaves a singular (unstable) structure."""
    base = _run_pipeline({})
    s = base["structure"]
    nodes = {n["id"]: n for n in s["nodes"]}
    ground_cols = [e["id"] for e in s["elements"]
                   if e["type"] == "column"
                   and (nodes[e["node_i"]]["y"] < 0.001 or nodes[e["node_j"]]["y"] < 0.001)]
    assert len(ground_cols) == 16, f"Expected 16 ground columns, got {len(ground_cols)}"
    result = _run_removal({"structure": s, "removed_member_ids": ground_cols})
    assert result["status"] == "unstable", result.get("error")
    assert result["unstable"]["failed_case"] in {"Dead", "Live", "Wind", "Total"}
    assert result["unstable"]["reason"]
    assert len(result["structure"]["elements"]) == len(s["elements"]) - len(ground_cols)
    assert result["structure"]["metadata"]["num_base_nodes"] == 0


def test_4_remove_all_around_interior_joint():
    """Removing every member at one interior joint purges that node."""
    base = _run_pipeline({})
    s = base["structure"]
    target = next(n for n in s["nodes"]
                  if abs(n["x"] - 6.0) < 1e-3 and abs(n["z"] - 6.0) < 1e-3 and abs(n["y"] - 3.0) < 1e-3)
    touching = [e["id"] for e in s["elements"]
                if e["node_i"] == target["id"] or e["node_j"] == target["id"]]
    assert len(touching) > 0
    result = _run_removal({"structure": s, "removed_member_ids": touching})
    assert result["status"] == "complete", result.get("error")
    assert target["id"] in result["purged_node_ids"]


def test_5_invalid_member_id():
    """Unknown member ids produce a clear error."""
    base = _run_pipeline({})
    result = _run_removal({"structure": base["structure"], "removed_member_ids": [999999]})
    assert result["status"] == "error"
    assert "999999" in result["error"]
    result2 = _run_removal({"structure": base["structure"], "removed_member_ids": []})
    assert result2["status"] == "error"
    result3 = _run_removal({"structure": {"nodes": [], "elements": []}, "removed_member_ids": [1]})
    assert result3["status"] == "error"


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
