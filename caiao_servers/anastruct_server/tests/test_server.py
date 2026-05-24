"""Tests for anastruct_server CAIAO server."""

import pytest
from server import _generate_frame, _analyze_structure, _select_critical_element


class TestGenerateFrame:
    def test_default_2x2_frame(self):
        frame = _generate_frame()
        assert len(frame["nodes"]) == 9  # (2+1)*(2+1)
        assert len(frame["elements"]) == 10  # 3*2 columns + 2*2 beams
        assert len(frame["supports"]) == 3  # one per column base
        assert len(frame["loads"]) == 3  # one per top node

    def test_1x1_frame(self):
        frame = _generate_frame(spans=1, stories=1)
        assert len(frame["nodes"]) == 4  # (1+1)*(1+1)
        assert len(frame["elements"]) == 3  # 2 columns + 1 beam
        assert len(frame["supports"]) == 2
        assert len(frame["loads"]) == 2

    def test_3x4_frame(self):
        frame = _generate_frame(spans=3, stories=4)
        expected_nodes = (3 + 1) * (4 + 1)  # 20
        expected_columns = 4 * (3 + 1)  # 16
        expected_beams = 4 * 3  # 12
        assert len(frame["nodes"]) == expected_nodes
        assert len(frame["elements"]) == expected_columns + expected_beams
        assert len(frame["supports"]) == 4  # spans+1

    def test_custom_dimensions(self):
        frame = _generate_frame(spans=2, stories=2, span_length=8.0, story_height=4.0)
        # Node at col=0,row=2 (top-left)
        top_left = next(n for n in frame["nodes"] if n["id"] == 6)
        assert top_left["x"] == 0.0
        assert top_left["y"] == 8.0  # 2 stories * 4.0

    def test_custom_material_properties(self):
        frame = _generate_frame(E=200e9, A=0.01, I=2e-5)
        for elem in frame["elements"]:
            assert elem["E"] == 200e9
            assert elem["A"] == 0.01
            assert elem["I"] == 2e-5

    def test_all_supports_are_fixed_on_ground(self):
        frame = _generate_frame(spans=3, stories=2)
        node_ids_at_y0 = {n["id"] for n in frame["nodes"] if n["y"] == 0.0}
        for sup in frame["supports"]:
            assert sup["node_id"] in node_ids_at_y0
            assert sup["type"] == "fixed"

    def test_loads_on_top_nodes(self):
        frame = _generate_frame(spans=2, stories=3)
        max_y = max(n["y"] for n in frame["nodes"])
        top_node_ids = {n["id"] for n in frame["nodes"] if n["y"] == max_y}
        for load in frame["loads"]:
            assert load["node_id"] in top_node_ids
            assert load["Fy"] == -50000


class TestAnalyzeStructure:
    @pytest.fixture
    def frame_2x2(self):
        return _generate_frame(spans=2, stories=2)

    def test_analysis_returns_expected_keys(self, frame_2x2):
        result = _analyze_structure(frame_2x2)
        assert "error" not in result
        assert "node_displacements" in result
        assert "element_forces" in result
        assert "max_displacement" in result
        assert "max_axial_force" in result

    def test_displacements_match_node_count(self, frame_2x2):
        result = _analyze_structure(frame_2x2)
        assert len(result["node_displacements"]) == len(frame_2x2["nodes"])

    def test_forces_match_element_count(self, frame_2x2):
        result = _analyze_structure(frame_2x2)
        assert len(result["element_forces"]) == len(frame_2x2["elements"])

    def test_max_displacement_is_positive(self, frame_2x2):
        result = _analyze_structure(frame_2x2)
        assert result["max_displacement"] > 0

    def test_max_axial_force_is_positive(self, frame_2x2):
        result = _analyze_structure(frame_2x2)
        assert result["max_axial_force"] > 0

    def test_element_forces_have_all_components(self, frame_2x2):
        result = _analyze_structure(frame_2x2)
        ef = result["element_forces"][0]
        for key in ["Nmax", "Nmin", "Mmax", "Mmin", "Qmax", "Qmin"]:
            assert key in ef

    def test_all_displacements_are_finite(self, frame_2x2):
        result = _analyze_structure(frame_2x2)
        for nd in result["node_displacements"]:
            assert abs(nd["ux"]) < 1.0  # displacement in meters, should be small
            assert abs(nd["uy"]) < 1.0


class TestSelectCriticalElement:
    def test_returns_critical_element_id(self):
        frame = _generate_frame(spans=2, stories=2)
        analysis = _analyze_structure(frame)
        result = _select_critical_element(frame, analysis)
        assert "critical_element_id" in result
        assert isinstance(result["critical_element_id"], int)

    def test_returns_positive_axial_force(self):
        frame = _generate_frame(spans=2, stories=2)
        analysis = _analyze_structure(frame)
        result = _select_critical_element(frame, analysis)
        assert result["critical_axial_force_N"] > 0

    def test_identifies_all_columns(self):
        frame = _generate_frame(spans=3, stories=2)
        analysis = _analyze_structure(frame)
        result = _select_critical_element(frame, analysis)
        # For 3-span frame: 4 columns per story * 2 stories = 8 columns
        assert result["column_count"] == 8

    def test_critical_element_matches_highest_nmax(self):
        frame = _generate_frame(spans=2, stories=2)
        analysis = _analyze_structure(frame)
        result = _select_critical_element(frame, analysis)

        # Find the max |N| manually among columns
        nodes = frame["nodes"]
        elements = frame["elements"]
        node_coords = {n["id"]: (n["x"], n["y"]) for n in nodes}
        force_by_id = {}
        for ef in analysis["element_forces"]:
            eid = ef["element_id"] - 1
            force_by_id[eid] = max(abs(ef.get("Nmax", 0)), abs(ef.get("Nmin", 0)))

        max_axial = 0
        for elem in elements:
            n1 = node_coords.get(elem["node_i"])
            n2 = node_coords.get(elem["node_j"])
            if n1 and n2 and abs(n1[0] - n2[0]) < 0.01:
                f = force_by_id.get(elem["id"], 0)
                if f > max_axial:
                    max_axial = f

        assert abs(result["critical_axial_force_N"] - max_axial) < 0.01

    def test_reason_is_not_empty(self):
        frame = _generate_frame(spans=2, stories=2)
        analysis = _analyze_structure(frame)
        result = _select_critical_element(frame, analysis)
        assert len(result["reason"]) > 0
