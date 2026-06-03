"""CAIAO dependency & usage analyzer — graph analysis, merge detection, P4 suggestions.

Analyzes cross-server relationships without executing any code.
Works entirely from caiao.yaml manifests.
"""

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


def build_dependency_graph(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a directed dependency graph from server manifests.

    Dependencies come from:
    - imports: fields (merged servers importing from atomic servers)
    - pipeline steps (composite servers referencing other servers)
    - server_dependencies declarations (class-based servers)

    Returns:
        {nodes: [{name, kind, tool_count}],
         edges: [{from, to, type}],
         isolated: [str],
         cycles: [[str]]}
    """
    node_names = {m.get("name", "unknown") for m in manifests}
    nodes = []
    edges = []

    for m in manifests:
        name = m.get("name", "unknown")
        kind = m.get("kind", "atomic-mcp")
        tools = m.get("tools", [])
        nodes.append({
            "name": name,
            "kind": kind,
            "tool_count": len(tools) if isinstance(tools, list) else 0,
        })

        for imp in m.get("imports", []):
            module = imp.get("module", "")
            target = module.split(".")[0] if module else ""
            if target.endswith("_server"):
                target = target
            elif "_" in target:
                pass
            for node_name in node_names:
                if node_name in module or module.startswith(node_name):
                    edges.append({"from": name, "to": node_name, "type": "import"})
                    break

        for step in m.get("pipeline", []):
            step_server = step.get("server", "")
            if step_server in node_names:
                edges.append({"from": name, "to": step_server, "type": "pipeline_step"})

        for dep in m.get("dependencies", {}).get("server", []):
            if dep in node_names:
                edges.append({"from": name, "to": dep, "type": "declared_dependency"})

    nodes_with_deps = {e["from"] for e in edges} | {e["to"] for e in edges}
    isolated = [n["name"] for n in nodes if n["name"] not in nodes_with_deps]

    cycles = _find_cycles(build_adjacency(edges), node_names)

    return {
        "nodes": nodes,
        "edges": edges,
        "isolated": isolated,
        "cycles": cycles,
        "summary": f"{len(nodes)} servers, {len(edges)} dependencies, {len(isolated)} isolated, {len(cycles)} cycles",
    }


def build_adjacency(edges: list[dict]) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        adj[e["from"]].add(e["to"])
    return dict(adj)


def _find_cycles(adj: dict[str, set[str]], all_nodes: set[str]) -> list[list[str]]:
    """Detect cycles in the dependency graph using DFS."""
    visited: dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=done
    cycles = []

    def dfs(node: str, path: list[str]) -> None:
        if visited.get(node) == 1:
            cycle_start = path.index(node)
            cycles.append(path[cycle_start:] + [node])
            return
        if visited.get(node) == 2:
            return
        visited[node] = 1
        path.append(node)
        for neighbor in adj.get(node, set()):
            dfs(neighbor, path)
        path.pop()
        visited[node] = 2

    for node in all_nodes:
        if visited.get(node, 0) == 0:
            dfs(node, [])

    return cycles


def detect_merge_candidates(
    manifests: list[dict[str, Any]],
    usage_log: list[dict[str, Any]] | None = None,
    min_frequency: int = 3,
) -> list[dict[str, Any]]:
    """Detect potential merge candidates from server manifests.

    Looks for:
    1. Servers that are always called in sequence (from usage_log)
    2. Merged servers that could be further composed
    3. High-frequency tool pairs

    Without usage_log, analyzes the structure to suggest candidates.
    """
    candidates = []

    if usage_log:
        candidates.extend(_analyze_usage_patterns(usage_log, min_frequency))

    candidates.extend(_analyze_structural_merge_opportunities(manifests))
    candidates.extend(_analyze_pipeline_patterns(manifests))

    seen = set()
    unique = []
    for c in candidates:
        key = tuple(sorted(c.get("servers", [])))
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique


def _analyze_usage_patterns(usage_log: list[dict], min_freq: int) -> list[dict]:
    """Analyze tool call patterns to find sequences that repeat."""
    sequences = defaultdict(int)
    for entry in usage_log:
        calls = entry.get("tool_calls", [])
        for i in range(len(calls) - 1):
            pair = (calls[i], calls[i + 1])
            sequences[pair] += 1

    candidates = []
    for pair, freq in sequences.items():
        if freq >= min_freq:
            candidates.append({
                "type": "frequent_pair",
                "pattern": list(pair),
                "frequency": freq,
                "rationale": f"These two tools are called together {freq} times",
            })
    return candidates


def _analyze_structural_merge_opportunities(manifests: list[dict]) -> list[dict]:
    """Find merged servers whose imported servers might benefit from further merging."""
    candidates = []
    merged = [m for m in manifests if m.get("kind") == "merged"]
    atomic = {m.get("name"): m for m in manifests if m.get("kind", "").startswith("atomic")}

    for m in merged:
        imports = m.get("imports", [])
        imported_servers = []
        for imp in imports:
            module = imp.get("module", "")
            for aname in atomic:
                if aname in module or module.startswith(aname):
                    imported_servers.append(aname)

        if len(imported_servers) >= 3:
            candidates.append({
                "type": "deep_merge",
                "servers": imported_servers,
                "merged_server": m.get("name"),
                "rationale": f"Merged server '{m.get('name')}' already imports {len(imported_servers)} servers — consider if a further merge would reduce hops",
            })

    return candidates


def _analyze_pipeline_patterns(manifests: list[dict]) -> list[dict]:
    """Analyze composite pipelines for common step sequences."""
    candidates = []
    composites = [m for m in manifests if m.get("kind") == "composite"]
    pipe_signatures = defaultdict(list)

    for c in composites:
        steps = tuple(s.get("server", "") for s in c.get("pipeline", []))
        if steps:
            pipe_signatures[steps].append(c.get("name"))

    for steps, names in pipe_signatures.items():
        if len(names) >= 2:
            candidates.append({
                "type": "duplicate_pipeline",
                "servers": list(steps),
                "pipelines": names,
                "rationale": f"Multiple composite pipelines ({', '.join(names)}) use the same server sequence — consider a shared merged server",
            })

    return candidates


def suggest_shared_module(manifests: list[dict]) -> list[dict[str, Any]]:
    """Suggest logic that should be extracted to a shared module (P4 principle).

    Identifies patterns duplicated across 3+ servers that may benefit from extraction.
    """
    suggestions = []

    sections_by_server: dict[str, list[str]] = defaultdict(list)
    for m in manifests:
        name = m.get("name", "")
        for tool in m.get("tools", []):
            for tag in tool.get("tags", []):
                sections_by_server[(tag, name)].append(tag)
        for cap in m.get("capabilities", []):
            sections_by_server[(cap, name)].append(cap)

    tag_usage: dict[str, set[str]] = defaultdict(set)
    for m in manifests:
        name = m.get("name", "")
        for tool in m.get("tools", []):
            for tag in tool.get("tags", []):
                tag_usage[tag].add(name)
        for cap in m.get("capabilities", []):
            tag_usage[cap].add(name)

    for tag, servers in tag_usage.items():
        if len(servers) >= 3:
            suggestions.append({
                "capability": tag,
                "used_by": sorted(servers),
                "server_count": len(servers),
                "rationale": f"Capability '{tag}' is used by {len(servers)} servers — P4: evaluate shared module at 3rd consumer",
            })

    return suggestions
