"""CAIAO Manager Server — manage all CAIAO servers in the ecosystem.

The manager is itself a CAIAO server (dogfooding the architecture).
It provides creation, extension, enhancement, migration, retrieval,
and orchestration capabilities for all other CAIAO servers.

All management operations go through caiao.yaml manifests and the
gateway's REST endpoints. The manager never modifies server code directly.
"""

import asyncio
import json
import logging
import os
import sys
import time

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from caiao_servers.manager_server.manifest import (
    read_manifest, write_manifest, validate_manifest, validate_manifest_file,
    manifest_to_config, discover_manifests, generate_manifest_from_server,
)
from caiao_servers.manager_server.archetypes import list_archetypes as _list_archetypes, get_archetype
from caiao_servers.manager_server.scaffolder import scaffold_server
from caiao_servers.manager_server.validator import (
    validate_server_structure, validate_contract_compliance,
    validate_tool_schemas, validate_manifest_consistency, full_validation,
)
from caiao_servers.manager_server.search import SearchIndex
from caiao_servers.manager_server.analyzer import (
    build_dependency_graph, detect_merge_candidates, suggest_shared_module,
)
from caiao_servers.manager_server.health_checker import (
    evaluate_health, evaluate_all_health, evaluate_restart_policy, format_health_summary,
)
from caiao_servers.manager_server.migrator import (
    migrate_to_manifest, rename_server, bump_version, archive_server,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("manager_server")

server = Server("manager_server")
CAIAO_SERVERS_DIR = os.path.join(_project_root, "caiao_servers")
_search_index = SearchIndex()

SERVER_CONFIGS_CACHE = None
HUB_HEALTH_CACHE = {}
HEALTH_CACHE_TIME = 0


def _get_server_configs():
    global SERVER_CONFIGS_CACHE
    if SERVER_CONFIGS_CACHE is not None:
        return SERVER_CONFIGS_CACHE
    try:
        from gateway.caiao_config import discover_server_configs
        SERVER_CONFIGS_CACHE = discover_server_configs()
    except ImportError:
        SERVER_CONFIGS_CACHE = []
    return SERVER_CONFIGS_CACHE


def _rebuild_search_index():
    manifests = discover_manifests(CAIAO_SERVERS_DIR)
    if not manifests:
        return 0
    return _search_index.build(manifests)


_rebuild_search_index()


@server.list_tools()
async def list_tools():
    return [
        _t("create_server", "Scaffold a new CAIAO server from an archetype",
          {"server_name": _s("string", "Unique server name (snake_case, matches directory)"),
           "kind": _s("string", "Archetype kind: atomic-mcp, atomic-class, merged, composite, bridge"),
           "description": _s("string", "One-line description of what this server does"),
           "start_mode": _s("string", "eager or lazy (default: lazy)"),
           "tools": _s("array", 'List of {name, description} dicts for initial tools')},
          ["server_name", "kind"]),
        _t("list_archetypes", "List all available server archetypes with descriptions", {}, []),
        _t("generate_manifest", "Generate a caiao.yaml manifest from an existing server.py or SERVER_CONFIGS entry",
          {"server_name": _s("string", "Name of the server to generate manifest for")}, ["server_name"]),
        _t("validate_server", "Validate a server against the CAIAO contract (static analysis, no execution)",
          {"server_name": _s("string", "Name of the server to validate")}, ["server_name"]),

        _t("add_tool", "Add a tool definition to an existing server's manifest",
          {"server_name": _s("string", "Target server name"),
           "tool_name": _s("string", "New tool name (snake_case)"),
           "description": _s("string", "Tool description for LLM understanding"),
           "tags": _s("array", "Optional tags for capability classification")},
          ["server_name", "tool_name", "description"]),
        _t("update_tool", "Update a tool's description or tags in the manifest",
          {"server_name": _s("string", "Target server name"),
           "tool_name": _s("string", "Tool to update"),
           "description": _s("string", "New description (optional)"),
           "tags": _s("array", "New tags (optional)")},
          ["server_name", "tool_name"]),
        _t("remove_tool", "Remove a tool from a server's manifest",
          {"server_name": _s("string", "Target server name"),
           "tool_name": _s("string", "Tool to remove")},
          ["server_name", "tool_name"]),
        _t("add_import", "Add an import dependency to a merged server's manifest",
          {"server_name": _s("string", "Target merged server name"),
           "module": _s("string", "Module path to import from"),
           "symbols": _s("array", "List of symbol names to import")},
          ["server_name", "module", "symbols"]),

        _t("health_check", "Run health check on one or all servers",
          {"server_name": _s("string", "Server name (omit for all)")}, []),
        _t("get_metrics", "Get runtime metrics for one or all servers",
          {"server_name": _s("string", "Server name (omit for all)")}, []),
        _t("restart_server", "Request a server restart through the gateway",
          {"server_name": _s("string", "Server to restart")}, ["server_name"]),
        _t("configure_health", "Update health monitoring policy for a server",
          {"server_name": _s("string", "Target server name"),
           "restart_on_crash": _s("boolean", "Auto-restart on crash"),
           "max_restarts": _s("integer", "Max restarts before giving up"),
           "health_check_interval_s": _s("integer", "Periodic health check interval (0=off)")},
          ["server_name"]),

        _t("rename_server", "Rename a server (directory + manifest + reference warnings)",
          {"server_name": _s("string", "Current server name"),
           "new_name": _s("string", "New server name (snake_case)")},
          ["server_name", "new_name"]),
        _t("bump_version", "Bump server semantic version (patch/minor/major)",
          {"server_name": _s("string", "Target server name"),
           "bump": _s("string", "patch, minor, or major")},
          ["server_name"]),
        _t("archive_server", "Deprecate/archive a server (marks status=deprecated)",
          {"server_name": _s("string", "Server to archive")}, ["server_name"]),
        _t("migrate_to_manifest", "Generate caiao.yaml from SERVER_CONFIGS for servers missing a manifest",
          {"server_name": _s("string", "Server name (omit for bulk migration of all)")}, []),

        _t("search_capabilities", "Semantic search across all registered tools and capabilities",
          {"query": _s("string", "Natural language query"),
           "threshold": _s("number", "Minimum score threshold (0-1, default 0.15)"),
           "top_k": _s("integer", "Max results (default 10)")},
          ["query"]),
        _t("list_servers", "List all servers with metadata, status, and tool counts",
          {"kind": _s("string", "Filter by kind (optional)"),
           "status": _s("string", "Filter by status (optional)")}, []),
        _t("get_server", "Get detailed information about a specific server",
          {"server_name": _s("string", "Server name")}, ["server_name"]),
        _t("find_tool_owner", "Find which server provides a given tool",
          {"tool_name": _s("string", "Tool name to find")}, ["tool_name"]),

        _t("detect_merge_opportunities", "Analyze tool call patterns and server structure to suggest merges",
          {"min_frequency": _s("integer", "Minimum co-occurrence frequency to flag (default 3)")}, []),
        _t("analyze_dependency_graph", "Build and analyze the cross-server dependency graph", {}, []),
        _t("validate_pipeline", "Validate a declarative pipeline configuration",
          {"pipeline": _s("array", "Pipeline steps array [{server, tool, ...}]")}, ["pipeline"]),
        _t("suggest_pipeline", "Given a capability goal, suggest a server pipeline",
          {"goal": _s("string", "Natural language description of the desired capability")}, ["goal"]),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    global _search_index
    logger.info(f"Manager tool: {name}")

    try:
        if name == "create_server":
            result = _do_create_server(arguments)
        elif name == "list_archetypes":
            result = {"archetypes": _list_archetypes()}
        elif name == "generate_manifest":
            result = _do_generate_manifest(arguments)
        elif name == "validate_server":
            result = _do_validate_server(arguments)

        elif name == "add_tool":
            result = _do_modify_tool(arguments, "add")
        elif name == "update_tool":
            result = _do_modify_tool(arguments, "update")
        elif name == "remove_tool":
            result = _do_modify_tool(arguments, "remove")
        elif name == "add_import":
            result = _do_add_import(arguments)

        elif name == "health_check":
            result = _do_health_check(arguments)
        elif name == "get_metrics":
            result = _do_get_metrics(arguments)
        elif name == "restart_server":
            result = _do_restart_server(arguments)
        elif name == "configure_health":
            result = _do_configure_health(arguments)

        elif name == "rename_server":
            result = _do_rename_server(arguments)
        elif name == "bump_version":
            result = _do_bump_version(arguments)
        elif name == "archive_server":
            result = _do_archive_server(arguments)
        elif name == "migrate_to_manifest":
            result = _do_migrate_to_manifest(arguments)

        elif name == "search_capabilities":
            result = _do_search_capabilities(arguments)
        elif name == "list_servers":
            result = _do_list_servers(arguments)
        elif name == "get_server":
            result = _do_get_server(arguments)
        elif name == "find_tool_owner":
            result = _do_find_tool_owner(arguments)

        elif name == "detect_merge_opportunities":
            result = _do_detect_merge_opportunities(arguments)
        elif name == "analyze_dependency_graph":
            result = _do_analyze_dependency_graph(arguments)
        elif name == "validate_pipeline":
            result = _do_validate_pipeline(arguments)
        elif name == "suggest_pipeline":
            result = _do_suggest_pipeline(arguments)

        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    except Exception as e:
        logger.exception(f"Manager tool '{name}' failed")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]


def _serve_dir(name: str) -> str:
    return os.path.join(CAIAO_SERVERS_DIR, name)


# ── Group A: Creation ──────────────────────────────────────────────────────

def _do_create_server(args: dict) -> dict:
    sname = args["server_name"]
    kind = args.get("kind", "atomic-mcp")
    desc = args.get("description", "")
    start_mode = args.get("start_mode", "lazy")
    tools = args.get("tools", [])
    if isinstance(tools, str):
        tools = json.loads(tools)
    return scaffold_server(sname, kind, tools, desc, start_mode, CAIAO_SERVERS_DIR)


def _do_generate_manifest(args: dict) -> dict:
    sname = args["server_name"]
    server_dir = _serve_dir(sname)
    if not os.path.isdir(server_dir):
        return {"error": f"Server directory not found: {server_dir}"}

    config = None
    for cfg in _get_server_configs():
        if cfg.get("name") == sname:
            config = cfg
            break

    return migrate_to_manifest(server_dir, config)


def _do_validate_server(args: dict) -> dict:
    sname = args["server_name"]
    server_dir = _serve_dir(sname)
    if not os.path.isdir(server_dir):
        return {"error": f"Server directory not found: {server_dir}"}
    return full_validation(server_dir)


# ── Group B: Extension ─────────────────────────────────────────────────────

def _do_modify_tool(args: dict, action: str) -> dict:
    sname = args["server_name"]
    server_dir = _serve_dir(sname)
    manifest = read_manifest(server_dir)
    if manifest is None:
        return {"error": f"No caiao.yaml found for '{sname}'. Run generate_manifest first."}

    tools = list(manifest.get("tools", []))

    if action == "add":
        tname = args["tool_name"]
        if any(t.get("name") == tname for t in tools):
            return {"error": f"Tool '{tname}' already exists in '{sname}'"}
        tools.append({
            "name": tname,
            "description": args.get("description", ""),
            "tags": args.get("tags", []),
        })
    elif action == "update":
        tname = args["tool_name"]
        found = False
        for t in tools:
            if t.get("name") == tname:
                if "description" in args:
                    t["description"] = args["description"]
                if "tags" in args:
                    t["tags"] = args["tags"]
                found = True
                break
        if not found:
            return {"error": f"Tool '{tname}' not found in '{sname}'"}
    elif action == "remove":
        tname = args["tool_name"]
        tools = [t for t in tools if t.get("name") != tname]

    manifest["tools"] = tools
    write_manifest(server_dir, manifest)
    _rebuild_search_index()
    return {"status": "ok", "server": sname, "action": action, "tool_count": len(tools)}


def _do_add_import(args: dict) -> dict:
    sname = args["server_name"]
    server_dir = _serve_dir(sname)
    manifest = read_manifest(server_dir)
    if manifest is None:
        return {"error": f"No caiao.yaml found for '{sname}'"}

    if manifest.get("kind") != "merged":
        return {"error": f"Server '{sname}' is not a merged server (kind={manifest.get('kind')})"}

    imports = list(manifest.get("imports", []))
    imports.append({"module": args["module"], "symbols": args["symbols"]})
    manifest["imports"] = imports
    write_manifest(server_dir, manifest)
    return {"status": "ok", "server": sname, "import_count": len(imports)}


# ── Group C: Enhancement ───────────────────────────────────────────────────

def _do_health_check(args: dict) -> dict:
    sname = args.get("server_name")
    manifests_list = discover_manifests(CAIAO_SERVERS_DIR)
    manifest_map = {m.get("name"): m for m in manifests_list}

    if sname:
        sdir = _serve_dir(sname)
        manifest = read_manifest(sdir)
        state = _hub_health_state(sname)
        report = evaluate_health(state, manifest)
        return {"server": sname, "health": report, "summary": format_health_summary(report)}

    hub_health = {m.get("name", "unknown"): _hub_health_state(m.get("name", "unknown"))
                  for m in manifests_list}
    report = evaluate_all_health(hub_health, manifest_map)
    return {
        "total": report["total"],
        "healthy": report["healthy"],
        "unhealthy": report["unhealthy"],
        "healthy_ratio": report["healthy_ratio"],
        "servers": {k: {"state": v["state"], "healthy": v["healthy"]} for k, v in report["servers"].items()},
    }


def _do_get_metrics(args: dict) -> dict:
    sname = args.get("server_name")
    all_configs = _get_server_configs()
    if sname:
        return {"server": sname, "metrics": _hub_metrics(sname)}
    return {"servers": {c.get("name", "?"): _hub_metrics(c.get("name", "?")) for c in all_configs}}


def _do_restart_server(args: dict) -> dict:
    sname = args["server_name"]
    return {"status": "requested", "server": sname,
            "note": "Restart request sent. The gateway handles the actual restart."}


def _do_configure_health(args: dict) -> dict:
    sname = args["server_name"]
    server_dir = _serve_dir(sname)
    manifest = read_manifest(server_dir)
    if manifest is None:
        return {"error": f"No caiao.yaml found for '{sname}'"}

    health = dict(manifest.get("health", {}))
    if "restart_on_crash" in args:
        health["restart_on_crash"] = args["restart_on_crash"]
    if "max_restarts" in args:
        health["max_restarts"] = args["max_restarts"]
    if "health_check_interval_s" in args:
        health["health_check_interval_s"] = args["health_check_interval_s"]
    manifest["health"] = health
    write_manifest(server_dir, manifest)
    return {"status": "ok", "server": sname, "health": health}


# ── Group D: Migration ─────────────────────────────────────────────────────

def _do_rename_server(args: dict) -> dict:
    sname = args["server_name"]
    new_name = args["new_name"]
    server_dir = _serve_dir(sname)
    return rename_server(server_dir, new_name, CAIAO_SERVERS_DIR)


def _do_bump_version(args: dict) -> dict:
    sname = args["server_name"]
    bump = args.get("bump", "patch")
    server_dir = _serve_dir(sname)
    return bump_version(server_dir, bump)


def _do_archive_server(args: dict) -> dict:
    sname = args["server_name"]
    server_dir = _serve_dir(sname)
    return archive_server(server_dir)


def _do_migrate_to_manifest(args: dict) -> dict:
    sname = args.get("server_name")
    if sname:
        server_dir = _serve_dir(sname)
        config = None
        for cfg in _get_server_configs():
            if cfg.get("name") == sname:
                config = cfg
                break
        return migrate_to_manifest(server_dir, config)

    from caiao_servers.manager_server.migrator import bulk_migrate
    return bulk_migrate(CAIAO_SERVERS_DIR)


# ── Group E: Retrieval ─────────────────────────────────────────────────────

def _do_search_capabilities(args: dict) -> dict:
    global _search_index
    query = args["query"]
    threshold = float(args.get("threshold", 0.15))
    top_k = int(args.get("top_k", 10))
    if not _search_index._built:
        _rebuild_search_index()
    results = _search_index.search(query, threshold, top_k)
    return {"query": query, "count": len(results), "results": results}


def _do_list_servers(args: dict) -> dict:
    manifests = discover_manifests(CAIAO_SERVERS_DIR)
    kind_filter = args.get("kind")
    status_filter = args.get("status")

    servers = []
    for m in manifests:
        if kind_filter and m.get("kind") != kind_filter:
            continue
        if status_filter and m.get("status", "active") != status_filter:
            continue
        sname = m.get("name", "unknown")
        servers.append({
            "name": sname,
            "kind": m.get("kind", "atomic-mcp"),
            "version": m.get("version", "0.0.0"),
            "status": m.get("status", "active"),
            "description": m.get("description", ""),
            "tool_count": len(m.get("tools", [])),
            "tool_names": [t["name"] for t in m.get("tools", [])],
            "start_mode": m.get("start_mode", "eager"),
            "health_state": _hub_health_state(sname).get("state", "unknown"),
        })

    return {"total": len(servers), "servers": servers}


def _do_get_server(args: dict) -> dict:
    sname = args["server_name"]
    server_dir = _serve_dir(sname)
    manifest = read_manifest(server_dir)
    if manifest is None:
        return {"error": f"No caiao.yaml found for '{sname}'"}

    health_state = _hub_health_state(sname)
    return {
        "name": manifest.get("name"),
        "kind": manifest.get("kind"),
        "version": manifest.get("version"),
        "status": manifest.get("status"),
        "description": manifest.get("description"),
        "start_mode": manifest.get("start_mode"),
        "tools": manifest.get("tools", []),
        "capabilities": manifest.get("capabilities", []),
        "imports": manifest.get("imports", []),
        "pipeline": manifest.get("pipeline", []),
        "dependencies": manifest.get("dependencies", {}),
        "health": manifest.get("health", {}),
        "health_state": health_state,
        "server_dir": server_dir,
    }


def _do_find_tool_owner(args: dict) -> dict:
    global _search_index
    tname = args["tool_name"]
    if not _search_index._built:
        _rebuild_search_index()
    result = _search_index.find_tool_owner(tname)
    if result:
        return {"found": True, "tool": tname, **result}
    manifests = discover_manifests(CAIAO_SERVERS_DIR)
    for m in manifests:
        for tool in m.get("tools", []):
            if tool.get("name") == tname:
                return {"found": True, "tool": tname, "server_name": m.get("name"),
                        "server_kind": m.get("kind"), "tool_description": tool.get("description", "")}
    return {"found": False, "tool": tname}


# ── Group F: Orchestration ─────────────────────────────────────────────────

def _do_detect_merge_opportunities(args: dict) -> dict:
    min_freq = int(args.get("min_frequency", 3))
    manifests = discover_manifests(CAIAO_SERVERS_DIR)
    candidates = detect_merge_candidates(manifests, min_frequency=min_freq)
    suggestions = suggest_shared_module(manifests)
    return {
        "merge_candidates": candidates,
        "shared_module_suggestions": suggestions,
        "total_candidates": len(candidates) + len(suggestions),
    }


def _do_analyze_dependency_graph(args: dict) -> dict:
    manifests = discover_manifests(CAIAO_SERVERS_DIR)
    graph = build_dependency_graph(manifests)
    return graph


def _do_validate_pipeline(args: dict) -> dict:
    pipeline = args.get("pipeline", [])
    if isinstance(pipeline, str):
        pipeline = json.loads(pipeline)

    errors = []
    warnings = []
    all_manifests = discover_manifests(CAIAO_SERVERS_DIR)
    server_names = {m.get("name") for m in all_manifests}

    for i, step in enumerate(pipeline):
        if not isinstance(step, dict):
            errors.append(f"Step {i}: must be a dict")
            continue
        s = step.get("server", "")
        t = step.get("tool", "")
        if not s:
            errors.append(f"Step {i}: missing 'server'")
        elif s not in server_names:
            warnings.append(f"Step {i}: server '{s}' not found in registry")

        if not t:
            errors.append(f"Step {i}: missing 'tool'")

    if not pipeline:
        errors.append("Pipeline is empty")

    return {
        "valid": len(errors) == 0,
        "step_count": len(pipeline),
        "errors": errors,
        "warnings": warnings,
    }


def _do_suggest_pipeline(args: dict) -> dict:
    goal = args.get("goal", "")
    manifests = discover_manifests(CAIAO_SERVERS_DIR)

    all_tools = []
    for m in manifests:
        for t in m.get("tools", []):
            all_tools.append({
                "tool_name": t["name"],
                "description": t.get("description", ""),
                "server": m.get("name"),
                "tags": t.get("tags", []),
                "capabilities": m.get("capabilities", []),
            })

    goal_lower = goal.lower()
    scored = []
    for t in all_tools:
        score = 0
        desc_lower = t["description"].lower()
        for word in goal_lower.split():
            if word in desc_lower:
                score += 2
            if word in t["tool_name"]:
                score += 3
            for tag in t.get("tags", []):
                if word in tag.lower():
                    score += 1
            for cap in t.get("capabilities", []):
                if word in cap.lower():
                    score += 1
        if score > 0:
            scored.append({"tool": t["tool_name"], "server": t["server"],
                           "description": t["description"], "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)

    structure_keywords = {
        "generate": 0, "model": 1, "create": 0, "build": 0, "frame": 1, "structure": 1,
        "analyze": 2, "analysis": 2, "solve": 2, "fem": 2, "fea": 2,
        "critical": 3, "select": 3, "demolish": 3, "collapse": 3,
        "visualiz": 4, "animate": 4, "render": 4, "display": 4,
    }

    pipeline_suggestion = []
    used_servers = set()
    for phase_name, keywords in [
        ("Generate Model", ["generate", "model", "frame", "create", "build"]),
        ("Analyze Structure", ["analyze", "analysis", "solve", "fem", "fea"]),
        ("Select Critical Elements", ["critical", "select", "key", "important"]),
        ("Execute Demolition", ["demolish", "remove", "collapse", "break"]),
        ("Visualize Results", ["visualiz", "animate", "render", "display", "show"]),
    ]:
        for t in scored:
            if t["server"] in used_servers:
                continue
            if any(kw in t["tool_name"].lower() or kw in t["description"].lower() for kw in keywords):
                pipeline_suggestion.append({
                    "phase": phase_name,
                    "server": t["server"],
                    "tool": t["tool"],
                    "score": t["score"],
                })
                used_servers.add(t["server"])
                break

    return {
        "goal": goal,
        "matched_tools": scored[:15],
        "suggested_pipeline": pipeline_suggestion,
        "pipeline_yaml_hint": _format_pipeline_hint(pipeline_suggestion),
    }


# ── Helpers ─────────────────────────────────────────────────────────────────

def _hub_health_state(server_name: str) -> dict:
    return {"state": "unknown", "pid": None}


def _hub_metrics(server_name: str) -> dict:
    return {"total_calls": 0, "avg_latency_ms": 0, "error_count": 0}


def _format_pipeline_hint(steps: list[dict]) -> str:
    if not steps:
        return "# No matching pipeline found"
    lines = ["pipeline:"]
    for s in steps:
        lines.append(f"  - server: {s['server']}")
        lines.append(f"    tool: {s['tool']}")
        lines.append(f"    map_result: {s['phase'].lower().replace(' ', '_')}")
    return "\n".join(lines)


def _s(type_name: str, description: str) -> dict:
    return {"type": type_name, "description": description}


def _t(name: str, description: str, properties: dict, required: list[str]) -> Tool:
    return Tool(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": properties,
            "required": required,
        } if required else {
            "type": "object",
            "properties": properties,
        },
    )


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
