"""Tests for FrameGenerator core logic."""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from core import FrameGenerator, FrameGeneratorConfig, generate_from_natural


def test_default_config():
    cfg = FrameGeneratorConfig()
    assert cfg.num_bays_x == 3
    assert cfg.num_stories == 4
    assert cfg.span_x_m == 6.0
    assert cfg.story_height_m == 3.0


def test_2d_frame_structure():
    cfg = FrameGeneratorConfig(num_bays_x=2, num_stories=2, span_x_m=6.0, story_height_m=3.0)
    gen = FrameGenerator(cfg)
    result = gen.generate_2d()

    # Check basic structure
    assert "nodes" in result
    assert "elements" in result
    assert "loads" in result
    assert "supports" in result

    # 2 bays x 2 stories: (2+1)*(2+1) = 9 nodes
    expected_nodes = (cfg.num_bays_x + 1) * (cfg.num_stories + 1)
    assert len(result["nodes"]) == expected_nodes

    # Columns: stories * (bays+1) = 2*3 = 6
    expected_columns = cfg.num_stories * (cfg.num_bays_x + 1)
    # Beams: stories * bays = 2*2 = 4
    expected_beams = cfg.num_stories * cfg.num_bays_x
    assert len(result["elements"]) == expected_columns + expected_beams


def test_2d_supports():
    cfg = FrameGeneratorConfig(num_bays_x=3, num_stories=4, base_support="fixed")
    result = FrameGenerator(cfg).generate_2d()

    assert len(result["supports"]) == cfg.num_bays_x + 1
    for s in result["supports"]:
        assert s["type"] == "fixed"


def test_2d_hinged_supports():
    cfg = FrameGeneratorConfig(num_bays_x=2, num_stories=3, base_support="hinged")
    result = FrameGenerator(cfg).generate_2d()

    for s in result["supports"]:
        assert s["type"] == "hinged"


def test_3d_frame_structure():
    cfg = FrameGeneratorConfig(num_bays_x=2, num_bays_y=2, num_stories=2)
    result = FrameGenerator(cfg).generate_3d()

    assert "columns" in result
    assert "beams" in result
    assert "slabs" in result
    assert "threejsObjects" in result

    # Columns: stories * (bays_x+1) * (bays_y+1) = 2*3*3 = 18
    assert len(result["columns"]) == cfg.num_stories * (cfg.num_bays_x + 1) * (cfg.num_bays_y + 1)


def test_material_steel():
    cfg = FrameGeneratorConfig(material_type="steel", steel_grade="Q345")
    gen = FrameGenerator(cfg)
    assert gen._E == 206e9
    assert gen._grade_name == "Q345"

    result = gen.generate_2d()
    assert result["metadata"]["material"] == "Q345"
    assert result["metadata"]["material_type"] == "steel"


def test_material_concrete():
    cfg = FrameGeneratorConfig(material_type="concrete", concrete_grade="C30")
    gen = FrameGenerator(cfg)
    assert gen._E == 30.0e9

    result = gen.generate_2d()
    assert result["metadata"]["material_type"] == "concrete"


def test_steel_grades():
    from core import STEEL_GRADES
    assert "Q235" in STEEL_GRADES
    assert "Q355" in STEEL_GRADES
    assert "S355" in STEEL_GRADES
    assert STEEL_GRADES["Q355"]["fy"] == 355e6


def test_concrete_grades():
    from core import CONCRETE_GRADES
    assert "C20" in CONCRETE_GRADES
    assert "C50" in CONCRETE_GRADES
    assert CONCRETE_GRADES["C30"]["fc"] == 14.3e6


def test_natural_language_parser():
    result = generate_from_natural("3x4 frame 5 stories 3m height 6m span Q355 steel")
    assert result["metadata"]["bays"] == 3
    assert result["metadata"]["stories"] == 5
    assert result["metadata"]["span_m"] == 6.0
    assert result["metadata"]["story_height_m"] == 3.0
    assert "Q355" in result["metadata"]["material"]


def test_natural_language_concrete():
    result = generate_from_natural("concrete C30 4 floor frame")
    assert result["metadata"]["material_type"] == "concrete"


def test_analysis_ready_has_hints():
    cfg = FrameGeneratorConfig(num_bays_x=2, num_stories=3)
    result = FrameGenerator(cfg).generate_2d_analysis_ready()
    assert "analysis_hints" in result
    assert "recommended_solver" in result["analysis_hints"]


def test_single_bay():
    """1 bay 1 story should generate minimal valid structure."""
    cfg = FrameGeneratorConfig(num_bays_x=1, num_stories=1, span_x_m=6.0, story_height_m=3.0)
    result = FrameGenerator(cfg).generate_2d()
    # Nodes: 2x2 = 4
    assert len(result["nodes"]) == 4
    # Columns: 1*2 = 2, Beams: 1*1 = 1, Total = 3
    assert len(result["elements"]) == 3


def test_elements_have_structure_properties():
    cfg = FrameGeneratorConfig(material_type="steel", steel_grade="Q355")
    result = FrameGenerator(cfg).generate_2d()
    for elem in result["elements"]:
        assert "E" in elem
        assert "A" in elem
        assert "I" in elem
        assert "node_i" in elem
        assert "node_j" in elem
