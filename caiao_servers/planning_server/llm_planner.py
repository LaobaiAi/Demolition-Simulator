"""LLM-guided demolition planning — template-based strategic planner.

This module provides a template-based demolition planner that generates
structurally-sound demolition sequences. The actual LLM call is handled
by the Gateway agent loop; this module focuses on structural common sense
to produce reasonable sequences from a high-level strategy description.
"""

from demolition_schemas import (
    DEFAULT_DURATIONS,
    EFFECT_MAP,
    DemolitionPlan,
    DemolitionStep,
    VisualEffects,
)
from rule_planner import _get_floor_map, _element_type_label


def plan_with_llm(structure: dict, user_prompt: str = "") -> DemolitionPlan:
    """Generate a demolition plan using template-based structural common sense.

    This interprets a high-level strategy (from user_prompt or default) and
    produces a demolition sequence. The gateway agent enriches the LLM
    response with this planner's output for structured data.

    Args:
        structure: Building structure dict with nodes/elements.
        user_prompt: Optional strategy description from the user/LLM.

    Returns:
        A DemolitionPlan with structured steps.
    """
    elements = structure.get("elements", [])
    nodes = structure.get("nodes", [])
    floor_map, floor_count, _ = _get_floor_map(nodes, elements)

    strategy = _interpret_strategy(user_prompt, floor_count, elements)
    steps: list[DemolitionStep] = []
    step_num = 0

    if strategy == "perimeter_first":
        # Remove perimeter elements first, then core
        perimeter, core = _split_perimeter_core(elements, nodes)
        steps, step_num = _add_element_group(steps, step_num, perimeter, "（外围拆除）",
                                              [VisualEffects.FLASH_RED, VisualEffects.DEBRIS])
        steps, step_num = _add_transition(steps, step_num, "外围结构已清除，开始拆除核心区域")
        steps, step_num = _add_element_group(steps, step_num, core, "（核心区域）",
                                              [VisualEffects.FLASH_RED, VisualEffects.SHAKE,
                                               VisualEffects.FALL_DOWN])

    elif strategy == "core_first":
        # Remove core elements first, then perimeter
        perimeter, core = _split_perimeter_core(elements, nodes)
        steps, step_num = _add_element_group(steps, step_num, core, "（核心区域拆除）",
                                              [VisualEffects.FLASH_RED, VisualEffects.SHAKE])
        steps, step_num = _add_transition(steps, step_num, "核心结构已拆除，外围失去支撑")
        steps, step_num = _add_element_group(steps, step_num, perimeter, "（外围倒塌）",
                                              [VisualEffects.SHAKE, VisualEffects.FALL_DOWN,
                                               VisualEffects.DEBRIS, VisualEffects.DUST,
                                               VisualEffects.COLLAPSE_CHAIN])

    elif strategy == "alternating_floors":
        # Remove every other floor, creating a "pancake" collapse
        sorted_floors = sorted(floor_map.keys(), reverse=True)
        for i, floor_idx in enumerate(sorted_floors):
            if i % 2 == 0:
                floor_els = [el for el in elements if el["id"] in floor_map.get(floor_idx, [])]
                steps, step_num = _add_element_group(
                    steps, step_num, floor_els,
                    f"（第{floor_idx + 1}层隔层拆除）",
                    [VisualEffects.FLASH_RED, VisualEffects.SHAKE,
                     VisualEffects.FALL_DOWN, VisualEffects.DEBRIS],
                )
                if i < len(sorted_floors) - 1:
                    steps, step_num = _add_transition(
                        steps, step_num,
                        f"第{floor_idx + 1}层倒塌，冲击第{floor_idx}层",
                    )

        # Then remove remaining floors
        for i, floor_idx in enumerate(sorted_floors):
            if i % 2 != 0:
                floor_els = [el for el in elements if el["id"] in floor_map.get(floor_idx, [])]
                steps, step_num = _add_element_group(
                    steps, step_num, floor_els,
                    f"（第{floor_idx + 1}层剩余拆除）",
                    [VisualEffects.FLASH_RED, VisualEffects.DEBRIS, VisualEffects.DUST],
                )

    else:
        # Default: smart top-down with perimeter priority
        perimeter, core = _split_perimeter_core(elements, nodes)
        sorted_floors = sorted(floor_map.keys(), reverse=True)

        for floor_idx in sorted_floors:
            floor_label = f"（第{floor_idx + 1}层）"
            floor_els = [el for el in elements if el["id"] in floor_map.get(floor_idx, [])]

            # Slabs first
            slabs = [el for el in floor_els if el.get("type") == "slab"]
            steps, step_num = _add_element_group(steps, step_num, slabs, floor_label)

            # Beams
            beams = [el for el in floor_els if el.get("type") == "beam"]
            steps, step_num = _add_element_group(steps, step_num, beams, floor_label,
                                                  [VisualEffects.FLASH_RED, VisualEffects.SHAKE])

            # Walls
            walls = [el for el in floor_els if el.get("type") == "wall"]
            steps, step_num = _add_element_group(steps, step_num, walls, floor_label,
                                                  [VisualEffects.FLASH_RED, VisualEffects.CRACK,
                                                   VisualEffects.DEBRIS])

            # Columns on this floor (connecting to floor below)
            columns = [el for el in elements if el.get("type") == "column"
                       and el.get("original_id", el.get("id", 0)) in
                       [e.get("original_id", e.get("id", 0)) for e in floor_els
                        if e.get("type") == "column"]]
            steps, step_num = _add_element_group(steps, step_num, columns, floor_label + "（失去支撑）",
                                                  [VisualEffects.FLASH_RED, VisualEffects.SHAKE,
                                                   VisualEffects.FALL_DOWN, VisualEffects.DEBRIS,
                                                   VisualEffects.COLLAPSE_CHAIN])

            if floor_idx > 0 and floor_els:
                steps, step_num = _add_transition(
                    steps, step_num,
                    f"第{floor_idx + 1}层荷载向下传递",
                )

    return DemolitionPlan(
        steps=steps,
        total_steps=len(steps),
        strategy=f"llm_{strategy}",
        estimated_duration_ms=sum(s["duration_ms"] for s in steps),
        structure_summary=f"{floor_count}层结构，{len(elements)}个构件 — AI规划策略: {strategy}",
    )


def _interpret_strategy(prompt: str, floor_count: int, elements: list) -> str:
    """Map user prompt to a known demolition strategy."""
    prompt_lower = prompt.lower()

    if "perimeter" in prompt_lower or "外围" in prompt_lower:
        return "perimeter_first"
    if "core" in prompt_lower or "核心" in prompt_lower or "center" in prompt_lower:
        return "core_first"
    if "alternate" in prompt_lower or "隔层" in prompt_lower or "pancake" in prompt_lower:
        return "alternating_floors"
    if "top" in prompt_lower or "自上而下" in prompt_lower or "down" in prompt_lower:
        return "smart_top_down"
    if "bottom" in prompt_lower or "自下而上" in prompt_lower or "up" in prompt_lower:
        return "core_first"

    # Default based on structure height
    if floor_count > 5:
        return "perimeter_first"
    return "smart_top_down"


def _split_perimeter_core(elements: list, nodes: list) -> tuple[list, list]:
    """Split elements into perimeter (outer boundary) and core (interior) groups."""
    if not nodes or not elements:
        return [], []

    xs = [n["x"] for n in nodes]
    ys = [n["y"] for n in nodes]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    x_range = max_x - min_x or 1
    y_range = max_y - min_y or 1

    # Build node lookup
    node_map = {n["id"]: n for n in nodes}

    perimeter: list = []
    core: list = []

    for el in elements:
        n_i = node_map.get(el["node_i"])
        n_j = node_map.get(el["node_j"])
        if not n_i or not n_j:
            core.append(el)
            continue

        avg_x = (n_i["x"] + n_j["x"]) / 2
        avg_y = (n_i["y"] + n_j["y"]) / 2

        # If near the boundary (>80% of range from center), it's perimeter
        cx = (avg_x - min_x) / x_range
        cy = (avg_y - min_y) / y_range

        if cx < 0.15 or cx > 0.85 or cy < 0.15 or cy > 0.85:
            perimeter.append(el)
        else:
            core.append(el)

    return perimeter, core


def _add_element_group(steps: list[DemolitionStep], start_step: int,
                       elements: list, extra_desc: str = "",
                       override_effects: list[str] | None = None) -> tuple[list[DemolitionStep], int]:
    """Add a group of element removal steps. Returns (updated_steps, next_step_num)."""
    step_num = start_step
    for el in elements:
        step_num += 1
        el_type = el.get("type", "beam")
        el_id = el.get("original_id", el.get("id", 0))
        effects = override_effects or EFFECT_MAP.get(el_type, [VisualEffects.FLASH_RED])

        steps.append(DemolitionStep(
            step=step_num,
            action="remove",
            element_id=el_id,
            element_type=el_type,
            description=f"拆除第{el_id}号{_element_type_label(el_type)}{extra_desc}",
            duration_ms=DEFAULT_DURATIONS.get(el_type, 2000),
            effects=effects,
        ))
    return steps, step_num


def _add_transition(steps: list[DemolitionStep], step_num: int,
                    description: str) -> tuple[list[DemolitionStep], int]:
    """Add a structural transition / cascade step."""
    step_num += 1
    steps.append(DemolitionStep(
        step=step_num,
        action="collapse_propagate",
        element_id=-1,
        element_type="system",
        description=description,
        duration_ms=800,
        effects=[VisualEffects.SHAKE, VisualEffects.DUST, VisualEffects.SWAY],
    ))
    return steps, step_num
