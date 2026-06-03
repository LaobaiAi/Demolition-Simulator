"""CAIAO config discovery — read caiao.yaml manifests and build SERVER_CONFIGS.

Replaces the hardcoded SERVER_CONFIGS list in main.py.
Auto-discovers servers from caiao_servers/*/caiao.yaml manifests.
Falls back to legacy hardcoded configs when no manifests are found.
"""

import os
import sys
import logging

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
CAIAO_SERVERS_DIR = os.path.join(PROJECT_DIR, "caiao_servers")

_VENV_CANDIDATES = [
    os.path.join(BASE_DIR, "venv", "Scripts", "python.exe"),
    os.path.join(PROJECT_DIR, ".venv", "Scripts", "python.exe"),
    os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe"),
]
VENV_PYTHON = next((p for p in _VENV_CANDIDATES if os.path.exists(p)), sys.executable)


def discover_server_configs() -> list[dict]:
    """Walk caiao_servers/*/caiao.yaml and return SERVER_CONFIGS entries.

    Skips directories starting with '_' or '.'.
    Falls back to legacy configs if no manifests are found.
    """
    configs = []

    if not os.path.isdir(CAIAO_SERVERS_DIR):
        logger.warning(f"CAIAO servers dir not found: {CAIAO_SERVERS_DIR}")
        return _legacy_server_configs()

    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not available, using legacy configs")
        return _legacy_server_configs()

    for entry in os.scandir(CAIAO_SERVERS_DIR):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue

        manifest_path = os.path.join(entry.path, "caiao.yaml")
        if not os.path.exists(manifest_path):
            continue

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"Failed to read manifest {manifest_path}: {e}")
            continue

        if not isinstance(data, dict):
            logger.warning(f"Invalid manifest (not a dict): {manifest_path}")
            continue

        try:
            config = _manifest_to_config(data, entry.path)
            configs.append(config)
            logger.info(f"Discovered server from manifest: {data.get('name')} ({data.get('kind')})")
        except Exception as e:
            logger.warning(f"Failed to convert manifest {manifest_path}: {e}")

    if not configs:
        logger.info("No manifests found, using legacy hardcoded configs")
        return _legacy_server_configs()

    manifest_names = {c["name"] for c in configs}
    for legacy in _legacy_server_configs():
        if legacy["name"] not in manifest_names:
            configs.append(legacy)
            logger.info(f"Added legacy config for '{legacy['name']}' (no manifest yet)")

    return configs


def _manifest_to_config(data: dict, server_dir: str) -> dict:
    """Convert a caiao.yaml manifest dict to a SERVER_CONFIGS entry."""
    name = data["name"]
    kind = data.get("kind", "atomic-mcp")

    if kind == "composite":
        return {
            "name": name,
            "composite": True,
            "description": data.get("description", ""),
            "input_schema": data.get("input_schema", {}),
            "pipeline": data.get("pipeline", []),
            "tools": [t["name"] for t in data.get("tools", [])],
        }

    cmd = data.get("command", {})
    python_spec = cmd.get("python", "auto")
    if python_spec == "auto" or python_spec == "python":
        python_path = VENV_PYTHON
    else:
        python_path = python_spec

    args = cmd.get("args", ["server.py"])
    cwd = os.path.join(server_dir, cmd.get("cwd", "."))

    config = {
        "name": name,
        "command": python_path,
        "args": args,
        "cwd": os.path.normpath(cwd),
        "tools": [t["name"] for t in data.get("tools", [])],
    }

    if data.get("start_mode") == "lazy":
        config["lazy"] = True

    env = cmd.get("env")
    if env and isinstance(env, dict) and env:
        config["env"] = env

    return config


def _legacy_server_configs() -> list[dict]:
    """Return the hardcoded SERVER_CONFIGS as fallback.

    This is the original list from main.py, kept for backward compatibility.
    When all servers have caiao.yaml manifests, this function can be removed.
    """
    return [
        {
            "name": "anastruct_server",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": [os.path.join(CAIAO_SERVERS_DIR, "anastruct_server", "server.py")],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "anastruct_server"),
            "tools": ["generate_simple_frame", "analyze_frame", "select_critical_element"],
        },
        {
            "name": "opensees_server",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": ["server.py"],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "opensees_server"),
            "lazy": True,
            "tools": ["high_fidelity_analysis"],
        },
        {
            "name": "pynite_server",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": ["server.py"],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "pynite_server"),
            "lazy": True,
            "tools": ["pynite_analysis"],
        },
        {
            "name": "fapp_server",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": ["server.py"],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "fapp_server"),
            "lazy": True,
            "tools": ["fapp_analysis"],
        },
        {
            "name": "unity_simulator",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": ["server.py"],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "unity_simulator"),
            "lazy": True,
            "tools": [
                "apply_demolition_action",
                "modify_structure",
                "get_structure_status",
                "get_removed_elements",
            ],
        },
        {
            "name": "frame_generator",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": ["server.py"],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "frame_generator"),
            "tools": ["generate_frame", "generate_frame_3d", "generate_from_text", "list_materials"],
        },
        {
            "name": "quick_analysis_server",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": ["server.py"],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "quick_analysis_server"),
            "tools": ["quick_analysis"],
        },
        {
            "name": "full_analysis_3d_server",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": ["server.py"],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "full_analysis_3d_server"),
            "lazy": True,
            "tools": ["full_analysis_3d"],
        },
        {
            "name": "run_full_analysis",
            "composite": True,
            "description": "Pipeline: generate frame → analyze → find critical element",
            "input_schema": {
                "type": "object",
                "properties": {
                    "num_bays_x": {"type": "integer", "description": "Number of bays in X"},
                    "num_stories": {"type": "integer", "description": "Number of stories"},
                    "span_x_m": {"type": "number", "description": "Span length in X in meters"},
                    "story_height_m": {"type": "number", "description": "Story height in meters"},
                },
            },
            "pipeline": [
                {"server": "frame_generator", "tool": "generate_frame", "map_result": "structure"},
                {"server": "anastruct_server", "tool": "analyze_frame",
                 "input_map": {"structure": "structure"}, "map_result": "analysis"},
                {"server": "anastruct_server", "tool": "select_critical_element",
                 "input_map": {"structure": "structure", "analysis_result": "analysis"},
                 "map_result": "critical_element"},
            ],
        },
        {
            "name": "bim_model_server",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": ["server.py"],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "bim_model_server"),
            "lazy": True,
            "tools": ["generate_steel_frame", "generate_concrete_structure",
                      "generate_hybrid_structure", "export_ifc"],
        },
        {
            "name": "planning_server",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": ["server.py"],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "planning_server"),
            "lazy": True,
            "tools": ["plan_demolition_sequence", "analyze_structure_topology",
                      "get_demolition_plan_summary"],
        },
        {
            "name": "animation_control_server",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": ["server.py"],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "animation_control_server"),
            "lazy": True,
            "tools": ["create_timeline", "get_timeline_state",
                      "sequence_to_animation_data", "generate_effects_config"],
        },
        {
            "name": "physics_server",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": ["server.py"],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "physics_server"),
            "lazy": True,
            "tools": ["init_physics_scene", "apply_demolition_action",
                      "step_physics", "get_physics_state", "reset_physics"],
        },
        {
            "name": "scenario_server",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": ["server.py"],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "scenario_server"),
            "lazy": True,
            "tools": ["list_scenarios", "get_scenario", "recommend_scenario"],
        },
        {
            "name": "full_bim_demolition",
            "composite": True,
            "description": "Pipeline: BIM model → plan demolition → create animation timeline",
            "input_schema": {
                "type": "object",
                "properties": {
                    "structure_type": {"type": "string", "description": "steel / concrete / hybrid"},
                    "strategy": {"type": "string", "description": "top_down / bottom_up / sequential"},
                },
            },
            "pipeline": [
                {"server": "bim_model_server", "tool": "generate_steel_frame", "map_result": "bim_model"},
                {"server": "planning_server", "tool": "plan_demolition_sequence",
                 "input_map": {"structure": "bim_model"}, "map_result": "demolition_plan"},
                {"server": "animation_control_server", "tool": "create_timeline",
                 "input_map": {"demolition_plan": "demolition_plan"},
                 "map_result": "animation_timeline"},
            ],
        },
        {
            "name": "manager_server",
            "command": VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python",
            "args": ["server.py"],
            "cwd": os.path.join(CAIAO_SERVERS_DIR, "manager_server"),
            "tools": [
                "create_server", "list_archetypes", "generate_manifest", "validate_server",
                "add_tool", "update_tool", "remove_tool", "add_import",
                "health_check", "get_metrics", "restart_server", "configure_health",
                "rename_server", "bump_version", "archive_server", "migrate_to_manifest",
                "search_capabilities", "list_servers", "get_server", "find_tool_owner",
                "detect_merge_opportunities", "analyze_dependency_graph",
                "validate_pipeline", "suggest_pipeline",
            ],
        },
    ]
