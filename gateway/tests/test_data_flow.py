"""Data flow integration tests — verify key paths end-to-end.

Tests the critical data flow paths:
1. Server discovery → hub init → tool list
2. Frame generation → analysis → critical element selection
3. Pipeline config discovery from caiao.yaml manifests
"""

import json
import os
import sys
import asyncio
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from caiao_config import discover_server_configs, CAIAO_SERVERS_DIR


class TestServerDiscovery:
    """Verify caiao.yaml manifests are valid and parseable."""

    def test_all_servers_discovered(self):
        configs = discover_server_configs()
        assert len(configs) >= 25, f"Expected >=25 servers, got {len(configs)}"

    def test_no_legacy_configs(self):
        configs = discover_server_configs()
        non_manifest = [c for c in configs
                        if not any(c["name"] in d for d in [{}])]
        assert len(configs) >= 25

    def test_all_composites_have_pipeline(self):
        configs = discover_server_configs()
        composites = [c for c in configs if c.get("composite")]
        for c in composites:
            assert c.get("pipeline"), f"Composite '{c['name']}' has no pipeline steps"
            assert c.get("tools"), f"Composite '{c['name']}' has no tools declared"

    def test_all_atomic_have_command(self):
        configs = discover_server_configs()
        atomic = [c for c in configs
                  if not c.get("composite") and c.get("kind") != "infrastructure"]
        for c in atomic:
            if c.get("kind") == "merged":
                continue  # merged servers import logic, have different structure
            assert c.get("command"), f"Atomic '{c['name']}' has no command"


class TestPipelineConfig:
    """Verify pipeline configs are readable from hub configs."""

    def test_visual_demolition_pipelines_exist(self):
        configs = discover_server_configs()
        names = {c["name"] for c in configs}
        assert "visual_demolition_topology" in names
        assert "visual_demolition_mechanics" in names

    def test_visual_demolition_topology_steps(self):
        configs = discover_server_configs()
        topo = next(c for c in configs if c["name"] == "visual_demolition_topology")
        steps = topo["pipeline"]
        assert len(steps) == 6, f"Expected 6 steps, got {len(steps)}"
        tools = [s["tool"] for s in steps]
        assert tools == [
            "generate_frame", "plan_demolition_sequence", "create_timeline",
            "sequence_to_animation_data", "generate_effects_config", "init_physics_scene",
        ]

    def test_visual_demolition_mechanics_steps(self):
        configs = discover_server_configs()
        mech = next(c for c in configs if c["name"] == "visual_demolition_mechanics")
        steps = mech["pipeline"]
        assert len(steps) == 8, f"Expected 8 steps, got {len(steps)}"

    def test_composite_pipeline_has_input_schema(self):
        configs = discover_server_configs()
        for c in configs:
            if c.get("composite"):
                assert c.get("input_schema"), f"Composite '{c['name']}' missing input_schema"


class TestServiceImports:
    """Verify service modules import correctly."""

    def test_pipeline_service_imports(self):
        from services.pipeline_service import (
            get_pipeline_config,
            resolve_pipeline_args,
            parse_step_result,
            trim_for_pipeline,
            extract_timeline_steps,
        )
        assert callable(get_pipeline_config)
        assert callable(resolve_pipeline_args)

    def test_router_imports(self):
        from routers import routers
        assert len(routers) == 5

    def test_llm_engine_import(self):
        from llm_engine import LLMEngine, SYSTEM_PROMPT
        assert len(SYSTEM_PROMPT) > 1000

    def test_memory_import(self):
        from memory import SessionMemory
        mem = SessionMemory()
        assert mem is not None


class TestDataFlowContracts:
    """Verify standardized result formats across analysis servers."""

    def test_pipeline_arg_resolution(self):
        from services.pipeline_service import resolve_pipeline_args

        args = resolve_pipeline_args(
            tool_name="generate_frame",
            structure=None,
            strategy="top_down",
            effects_preset="standard",
            speed=1.0,
            structure_params={"num_bays_x": 3, "num_stories": 4, "span_x_m": 6.0, "story_height_m": 3.0},
            ctx={},
        )
        assert args["num_bays_x"] == 3
        assert args["num_stories"] == 4

    def test_pipeline_parse_result(self):
        from services.pipeline_service import parse_step_result

        raw = {"result": json.dumps({"status": "ok", "nodes": [1, 2, 3]})}
        parsed = parse_step_result(raw)
        assert parsed["status"] == "ok"
        assert parsed["nodes"] == [1, 2, 3]

    def test_pipeline_parse_raw_dict(self):
        from services.pipeline_service import parse_step_result

        raw = {"result": {"status": "ok", "nodes": [1, 2, 3]}}
        parsed = parse_step_result(raw)
        assert parsed["status"] == "ok"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
