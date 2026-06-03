"""Tests for the CAIAO Manager Server and its supporting modules."""

import json
import os
import sys
import tempfile
import pytest

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from caiao_servers.manager_server.manifest import (
    read_manifest, write_manifest, validate_manifest, validate_manifest_file,
    manifest_to_config, discover_manifests, generate_manifest_from_server,
)
from caiao_servers.manager_server.archetypes import list_archetypes, get_archetype, ARCHETYPES
from caiao_servers.manager_server.scaffolder import scaffold_server
from caiao_servers.manager_server.validator import (
    validate_server_structure, validate_contract_compliance, full_validation,
)
from caiao_servers.manager_server.search import SearchIndex
from caiao_servers.manager_server.analyzer import (
    build_dependency_graph, detect_merge_candidates, suggest_shared_module,
)
from caiao_servers.manager_server.health_checker import (
    evaluate_health, evaluate_all_health, evaluate_restart_policy,
)
from caiao_servers.manager_server.migrator import (
    migrate_to_manifest, rename_server, bump_version, archive_server,
)


class TestManifest:
    def test_validate_valid_manifest(self):
        data = {
            "name": "test_server",
            "version": "0.1.0",
            "kind": "atomic-mcp",
            "description": "Test server",
            "status": "active",
            "since": "2026-05-31",
            "start_mode": "lazy",
            "tools": [{"name": "my_tool", "description": "A tool", "tags": []}],
            "capabilities": [],
            "dependencies": {"python": [], "system": []},
        }
        errors = validate_manifest(data)
        assert errors == []

    def test_validate_invalid_kind(self):
        data = {"name": "test", "kind": "invalid_kind", "start_mode": "lazy"}
        errors = validate_manifest(data)
        assert any("kind" in e for e in errors)

    def test_validate_missing_name(self):
        data = {"kind": "atomic-mcp", "start_mode": "lazy"}
        errors = validate_manifest(data)
        assert any("name" in e for e in errors)

    def test_validate_merged_must_have_imports(self):
        data = {"name": "merged_svr", "kind": "merged", "start_mode": "eager"}
        errors = validate_manifest(data)
        assert any("imports" in e for e in errors)

    def test_validate_composite_must_have_pipeline(self):
        data = {"name": "comp_svr", "kind": "composite"}
        errors = validate_manifest(data)
        assert any("pipeline" in e for e in errors)

    def test_manifest_to_config_atomic(self):
        data = {
            "name": "my_server",
            "kind": "atomic-mcp",
            "start_mode": "lazy",
            "command": {"python": "auto", "args": ["server.py"], "cwd": ".", "env": {}},
            "tools": [{"name": "my_tool", "description": "Test"}],
        }
        config = manifest_to_config(data, "/tmp/my_server")
        assert config["name"] == "my_server"
        assert config["lazy"] is True
        assert config["tools"] == ["my_tool"]
        assert "command" in config

    def test_manifest_to_config_composite(self):
        data = {
            "name": "my_pipeline",
            "kind": "composite",
            "description": "A pipeline",
            "pipeline": [{"server": "s1", "tool": "t1"}],
            "tools": [{"name": "t1", "description": "T1"}],
        }
        config = manifest_to_config(data, "/tmp/my_pipeline")
        assert config["composite"] is True
        assert config["pipeline"] == [{"server": "s1", "tool": "t1"}]

    def test_discover_manifests(self):
        manifests = discover_manifests(
            os.path.join(_project_root, "caiao_servers")
        )
        names = {m.get("name") for m in manifests}
        assert "manager_server" in names

    def test_generate_manifest_from_config(self):
        config = {
            "name": "test_svr",
            "command": "python",
            "args": ["server.py"],
            "tools": ["tool_a", "tool_b"],
            "lazy": True,
        }
        data = generate_manifest_from_server("/tmp/test_svr", config)
        assert data["name"] == "test_svr"
        assert data["start_mode"] == "lazy"
        assert len(data["tools"]) == 2
        assert data["tools"][0]["name"] == "tool_a"


class TestArchetypes:
    def test_all_archetypes_have_required_fields(self):
        for key, val in ARCHETYPES.items():
            assert "label" in val
            assert "description" in val
            assert "template_files" in val
            assert val.get("has_subprocess") is not None

    def test_list_archetypes(self):
        archs = list_archetypes()
        assert len(archs) == 5
        names = {a["name"] for a in archs}
        assert names == {"atomic-mcp", "atomic-class", "merged", "composite", "bridge"}

    def test_get_archetype(self):
        a = get_archetype("atomic-mcp")
        assert a is not None
        assert a["label"] == "Atomic MCP Server"

    def test_get_invalid_archetype(self):
        assert get_archetype("nonexistent") is None


class TestScaffolder:
    def test_scaffold_atomic_mcp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scaffold_server("demo_server", "atomic-mcp",
                                     [{"name": "demo_tool", "description": "A demo tool"}],
                                     "Demo server", "lazy", tmpdir)
            assert result["status"] == "ok"
            assert result["server_name"] == "demo_server"
            assert "server.py" in result["files_created"]
            assert "caiao.yaml" in result["files_created"]

            server_py = os.path.join(tmpdir, "demo_server", "server.py")
            assert os.path.exists(server_py)
            with open(server_py, encoding="utf-8") as f:
                code = f.read()
            assert "Server(" in code
            assert "demo_tool" in code

            manifest = read_manifest(os.path.join(tmpdir, "demo_server"))
            assert manifest is not None
            assert manifest["name"] == "demo_server"
            assert manifest["kind"] == "atomic-mcp"

    def test_scaffold_composite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scaffold_server("demo_pipeline", "composite",
                                     [{"name": "run", "description": "Run pipeline"}],
                                     "Demo pipeline", "lazy", tmpdir)
            assert result["status"] == "ok"
            assert "caiao.yaml" in result["files_created"]
            assert "server.py" not in result["files_created"]

    def test_scaffold_duplicate_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scaffold_server("dup", "atomic-mcp", [], "", "lazy", tmpdir)
            result = scaffold_server("dup", "atomic-mcp", [], "", "lazy", tmpdir)
            assert "error" in result


class TestValidator:
    def test_validate_structure_on_real_server(self):
        server_dir = os.path.join(_project_root, "caiao_servers", "manager_server")
        result = validate_server_structure(server_dir)
        assert result["valid"]

    def test_validate_contract_on_manager(self):
        server_dir = os.path.join(_project_root, "caiao_servers", "manager_server")
        result = validate_contract_compliance(server_dir)
        assert result["valid"]

    def test_full_validation_on_manager(self):
        server_dir = os.path.join(_project_root, "caiao_servers", "manager_server")
        result = full_validation(server_dir)
        assert result["valid"]


class TestSearch:
    def test_build_and_search(self):
        manifests = discover_manifests(
            os.path.join(_project_root, "caiao_servers")
        )
        index = SearchIndex()
        count = index.build(manifests)
        assert count > 0

        results = index.search("structural analysis frame", threshold=0.0)
        assert len(results) > 0

    def test_find_tool_owner(self):
        manifests = discover_manifests(
            os.path.join(_project_root, "caiao_servers")
        )
        index = SearchIndex()
        index.build(manifests)

        result = index.find_tool_owner("create_server")
        assert result is not None
        assert result["server_name"] == "manager_server"

    def test_find_nonexistent_tool(self):
        index = SearchIndex()
        index.build([])
        assert index.find_tool_owner("nonexistent") is None


class TestAnalyzer:
    def test_build_dependency_graph(self):
        manifests = discover_manifests(
            os.path.join(_project_root, "caiao_servers")
        )
        graph = build_dependency_graph(manifests)
        assert "nodes" in graph
        assert "edges" in graph
        assert "summary" in graph
        assert len(graph["nodes"]) > 0

    def test_detect_merge_candidates(self):
        manifests = discover_manifests(
            os.path.join(_project_root, "caiao_servers")
        )
        candidates = detect_merge_candidates(manifests, min_frequency=1)
        assert isinstance(candidates, list)

    def test_suggest_shared_module(self):
        manifests = discover_manifests(
            os.path.join(_project_root, "caiao_servers")
        )
        suggestions = suggest_shared_module(manifests)
        assert isinstance(suggestions, list)


class TestHealthChecker:
    def test_evaluate_healthy_server(self):
        state = {"state": "running", "pid": 1234, "started_at": 1717000000.0, "crash_count": 0}
        report = evaluate_health(state)
        assert report["healthy"]
        assert report["state"] == "running"

    def test_evaluate_crashed_server(self):
        state = {"state": "crashed", "pid": None, "crash_count": 5, "last_error": "segfault"}
        manifest = {"health": {"max_restarts": 3, "timeout_ms": 5000}}
        report = evaluate_health(state, manifest)
        assert not report["healthy"]
        assert report["restart_policy"] == "exhausted"

    def test_evaluate_degraded_server(self):
        state = {"state": "degraded", "pid": 1234, "crash_count": 0}
        report = evaluate_health(state)
        assert not report["healthy"]

    def test_evaluate_all_health(self):
        hub_health = {
            "server_a": {"state": "running", "pid": 1, "started_at": 1717000000.0, "crash_count": 0},
            "server_b": {"state": "crashed", "pid": None, "crash_count": 1, "last_error": "timeout"},
        }
        report = evaluate_all_health(hub_health, {})
        assert report["total"] == 2
        assert report["healthy"] == 1
        assert report["unhealthy"] == 1

    def test_restart_policy(self):
        assert evaluate_restart_policy({"state": "running"}) == "noop"
        assert evaluate_restart_policy({"state": "crashed", "crash_count": 0}) == "restart"
        assert evaluate_restart_policy({"state": "crashed", "crash_count": 5},
                                       {"health": {"max_restarts": 3}}) == "alert"


class TestMigrator:
    def test_migrate_to_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = migrate_to_manifest(tmpdir, None)
            assert result.get("status") in ("ok", "skipped")

    def test_bump_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = {"name": "test", "version": "0.1.0", "kind": "atomic-mcp",
                    "start_mode": "lazy", "tools": [], "capabilities": [],
                    "dependencies": {"python": [], "system": []}}
            write_manifest(tmpdir, data)
            result = bump_version(tmpdir, "minor")
            assert result["status"] == "ok"
            assert result["new_version"] == "0.2.0"

            manifest = read_manifest(tmpdir)
            assert manifest["version"] == "0.2.0"

    def test_archive_server(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = {"name": "test", "version": "0.1.0", "kind": "atomic-mcp",
                    "start_mode": "lazy", "tools": [], "status": "active",
                    "capabilities": [], "dependencies": {"python": [], "system": []}}
            write_manifest(tmpdir, data)
            result = archive_server(tmpdir)
            assert result["status"] == "ok"

            manifest = read_manifest(tmpdir)
            assert manifest["status"] == "deprecated"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
