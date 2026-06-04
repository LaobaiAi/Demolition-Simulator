"""CAIAO config discovery — project-specific wrapper around the caiao package.

Delegates manifest discovery to caiao.discovery.discover_server_configs.
Keeps only project-specific parts: venv path, Abaqus sentinel, legacy fallback configs.
"""

import os
import sys
import logging

from caiao.discovery import discover_server_configs as _caiao_discover

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


def _resolve_abaqus_python() -> str:
    env_json_path = os.path.join(
        PROJECT_DIR, "caiao_servers", "abaqus_environment_server", "abaqus_env.json"
    )
    try:
        import json
        with open(env_json_path, "r", encoding="utf-8") as f:
            env_data = json.load(f)
        python_dir = env_data.get("paths", {}).get("python")
        if python_dir:
            python_exe = os.path.join(python_dir, "python.exe")
            if os.path.exists(python_exe):
                return python_exe
            return python_exe
        logger.warning(f"@abaqus_python@ sentinel used but paths.python not found in {env_json_path}")
    except Exception as e:
        logger.warning(f"Failed to resolve @abaqus_python@ from {env_json_path}: {e}")
    return sys.executable


def discover_server_configs() -> list[dict]:
    return _caiao_discover(
        servers_dir=CAIAO_SERVERS_DIR,
        sentinel_resolvers={"@abaqus_python@": _resolve_abaqus_python},
        legacy_configs=_legacy_server_configs(),
        venv_python=VENV_PYTHON,
    )


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
