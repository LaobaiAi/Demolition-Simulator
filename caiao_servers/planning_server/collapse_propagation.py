"""Progressive collapse propagation algorithm.

Implements topology-based chain reaction detection for progressive collapse.
When a column is removed, adjacent beams lose support, potentially triggering
cascading failure of neighboring elements.
"""

from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger("collapse_propagation")

# ── Types ───────────────────────────────────────────────────────────────────────
PropagationStep = dict[str, Any]


def build_adjacency(
    structure: dict[str, Any]
) -> tuple[dict[int, list[int]], dict[int, set[str]], dict[int, int]]:
    """Build element adjacency from structure data.

    Returns:
        node_to_elements: mapping from node_id to list of element_ids connected
        element_types: mapping from element_id to set of type labels
        node_floor: mapping from node_id to floor index
    """
    nodes = structure.get("nodes", [])
    elements = structure.get("elements", [])

    # Build node → element adjacency
    node_to_elements: dict[int, list[int]] = {}
    element_types: dict[int, set[str]] = {}
    node_coords: dict[int, dict[str, float]] = {}

    for n in nodes:
        nid = n["id"]
        node_to_elements.setdefault(nid, [])
        node_coords[nid] = {"x": n.get("x", 0), "y": n.get("y", 0), "z": n.get("z", 0)}

    for el in elements:
        eid = el["id"]
        ni, nj = el["node_i"], el["node_j"]
        node_to_elements.setdefault(ni, []).append(eid)
        node_to_elements.setdefault(nj, []).append(eid)

        # Determine element type
        types: set[str] = set()
        if el.get("type"):
            types.add(el["type"])

        # Auto-detect: column if vertical
        if ni in node_coords and nj in node_coords:
            yi = node_coords[ni]["y"]
            yj = node_coords[nj]["y"]
            xi = node_coords[ni]["x"]
            xj = node_coords[nj]["x"]
            zi = node_coords[ni]["z"]
            zj = node_coords[nj]["z"]
            dx = abs(xi - xj)
            dz = abs(zi - zj)
            dy = abs(yi - yj)

            if dx < 0.01 and dz < 0.01 and dy > 0.5:
                types.add("column")
            elif dy < 0.5 and (dx > 0.1 or dz > 0.1):
                types.add("beam")
            elif dy < 0.5 and dx < 0.1 and dz < 0.1:
                types.add("node")
            else:
                types.add("brace")

        element_types[eid] = types

    # Detect floors from node y-coordinates
    node_floor: dict[int, int] = {}
    floor_ys = sorted(set(
        nc["y"] for nid, nc in node_coords.items()
    ))
    floor_map = {y: i for i, y in enumerate(floor_ys)}
    for nid, nc in node_coords.items():
        node_floor[nid] = floor_map.get(nc["y"], 0)

    return node_to_elements, element_types, node_floor


def detect_columns_on_floor(
    node_to_elements: dict[int, list[int]],
    element_types: dict[int, set[str]],
    node_floor: dict[int, int],
    floor: int,
) -> set[int]:
    """Find all column element IDs on a given floor."""
    columns: set[int] = set()
    for nid, f in node_floor.items():
        if f != floor:
            continue
        for eid in node_to_elements.get(nid, []):
            if "column" in element_types.get(eid, set()):
                columns.add(eid)
    return columns


def detect_beams_on_floor(
    node_to_elements: dict[int, list[int]],
    element_types: dict[int, set[str]],
    node_floor: dict[int, int],
    floor: int,
) -> set[int]:
    """Find all beam element IDs on a given floor."""
    beams: set[int] = set()
    for nid, f in node_floor.items():
        if f != floor:
            continue
        for eid in node_to_elements.get(nid, []):
            if "beam" in element_types.get(eid, set()):
                beams.add(eid)
    return beams


def find_supported_elements(
    removed_element_ids: list[int],
    structure: dict[str, Any],
    threshold: float = 0.3,
) -> list[PropagationStep]:
    """Find elements that lose support when given columns are removed.

    Args:
        removed_element_ids: IDs of columns that were removed/demolished
        structure: Structure dict with nodes and elements
        threshold: Propagation threshold ratio (default 0.3)

    Returns:
        List of propagation steps, each containing newly affected elements
    """
    node_to_elements, element_types, node_floor = build_adjacency(structure)
    removed_set = set(removed_element_ids)

    # Find nodes attached to removed elements
    affected_nodes: set[int] = set()
    for eid in removed_element_ids:
        for nid, elist in node_to_elements.items():
            if eid in elist:
                affected_nodes.add(nid)

    # Beams connected to affected nodes
    affected_beams: set[int] = set()
    for nid in affected_nodes:
        for eid in node_to_elements.get(nid, []):
            if "beam" in element_types.get(eid, set()):
                if eid not in removed_set:
                    affected_beams.add(eid)

    # Group affected beams by floor
    floor_beams: dict[int, set[int]] = {}
    for bid in affected_beams:
        for nid, f in node_floor.items():
            if f not in floor_beams:
                floor_beams[f] = set()
            if bid in node_to_elements.get(nid, []):
                floor_beams[f].add(bid)

    # Determine which floors exceed threshold for propagation
    propagation_steps: list[PropagationStep] = []
    all_collapsed: set[int] = set()

    max_floor = max(node_floor.values()) if node_floor else 0

    for floor in sorted(floor_beams.keys(), reverse=True):
        floor_total = detect_beams_on_floor(node_to_elements, element_types, node_floor, floor)
        floor_affected = floor_beams[floor]

        if len(floor_total) == 0:
            continue

        ratio = len(floor_affected) / len(floor_total)
        if ratio >= threshold:
            # Also find columns on this floor that might be overloaded
            floor_cols = detect_columns_on_floor(node_to_elements, element_types, node_floor, floor)
            overloaded_cols: set[int] = set()

            for cid in floor_cols:
                if cid in removed_set:
                    continue
                # Check if this column's beams are all affected
                col_nodes: set[int] = set()
                for nid, elist in node_to_elements.items():
                    if cid in elist:
                        col_nodes.add(nid)
                col_beams: set[int] = set()
                for nid in col_nodes:
                    for eid in node_to_elements.get(nid, []):
                        if "beam" in element_types.get(eid, set()) and "column" not in element_types.get(eid, set()):
                            col_beams.add(eid)
                if len(col_beams) > 0 and col_beams.issubset(affected_beams):
                    overloaded_cols.add(cid)

            step: PropagationStep = {
                "floor": floor,
                "affected_beams": list(floor_affected),
                "overloaded_columns": list(overloaded_cols),
                "ratio": round(ratio, 3),
                "propagation_delay_ms": 200 * (max_floor - floor + 1),
                "description": f"Floor {floor}: {len(floor_affected)}/{len(floor_total)} beams affected ({ratio:.0%})",
            }
            propagation_steps.append(step)
            all_collapsed.update(floor_affected)
            all_collapsed.update(overloaded_cols)

    return propagation_steps


def compute_collapse_chain(
    structure: dict[str, Any],
    initial_removals: list[int],
    max_rounds: int = 10,
    threshold: float = 0.3,
) -> list[dict[str, Any]]:
    """Compute the full chain reaction collapse sequence.

    Iteratively removes elements and checks for new propagation until
    no more elements are affected or max_rounds is reached.

    Args:
        structure: Structure dict
        initial_removals: First set of elements removed
        max_rounds: Maximum propagation rounds
        threshold: Propagation threshold

    Returns:
        List of collapse rounds, each with removed elements and propagation steps
    """
    removed_so_far = set(initial_removals)
    rounds: list[dict[str, Any]] = []

    # Round 0: initial removal
    rounds.append({
        "round": 0,
        "new_removals": initial_removals,
        "type": "initial",
        "description": f"Initial removal of {len(initial_removals)} element(s)",
    })

    for round_num in range(1, max_rounds + 1):
        propagation = find_supported_elements(
            list(removed_so_far), structure, threshold
        )

        # Collect all new element IDs from propagation
        new_removals: set[int] = set()
        for step in propagation:
            new_removals.update(step.get("affected_beams", []))
            new_removals.update(step.get("overloaded_columns", []))

        # Remove already-counted
        new_removals -= removed_so_far

        if not new_removals:
            break

        removed_so_far.update(new_removals)

        rounds.append({
            "round": round_num,
            "new_removals": list(new_removals),
            "type": "propagation",
            "description": f"Chain reaction round {round_num}: {len(new_removals)} new element(s) collapsed",
            "propagation_steps": propagation,
        })

    return rounds


def create_propagation_timeline(
    chain_rounds: list[dict[str, Any]],
    base_delay_ms: int = 600,
) -> list[dict[str, Any]]:
    """Convert collapse chain into animation timeline events.

    Each event has timing information for the animation system.

    Args:
        chain_rounds: Output from compute_collapse_chain
        base_delay_ms: Base delay between rounds

    Returns:
        Timeline events with element IDs and timing
    """
    timeline: list[dict[str, Any]] = []
    current_time = 0

    for round_data in chain_rounds:
        round_num = round_data["round"]
        new_removals = round_data["new_removals"]

        if round_num == 0:
            delay = 0
        else:
            delay = base_delay_ms

        current_time += delay

        timeline.append({
            "time_ms": current_time,
            "round": round_num,
            "type": round_data.get("type", "propagation"),
            "element_ids": new_removals,
            "description": round_data.get("description", ""),
            "effect": "collapse" if round_num == 0 else "chain_collapse",
        })

    return timeline
