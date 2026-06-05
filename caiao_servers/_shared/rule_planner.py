"""Rule-based demolition sequence planner — topology analysis and strategy execution."""

from collections import defaultdict

from .demolition_schemas import (
    DEFAULT_DURATIONS,
    EFFECT_MAP,
    DemolitionStep,
    DemolitionPlan,
    StructuralTopology,
    VisualEffects,
)


def _detect_vertical_axis(nodes: list[dict]) -> str:
    """Detect which axis is vertical.

    If all z values are identical but y varies, the structure is 2D with y as vertical.
    Otherwise, z is treated as vertical (3D convention).
    """
    if not nodes:
        return "z"
    z_vals = {n.get("z", 0) for n in nodes}
    y_vals = {n.get("y", 0) for n in nodes}
    if len(z_vals) == 1 and len(y_vals) > 1:
        return "y"
    return "z"


def _infer_element_type(el: dict, node_map: dict) -> str:
    """Infer element type from geometry when 'type' field is missing.

    Vertical element (both nodes share x,y in 2D, or x,y in 3D projection) → column.
    Horizontal element → beam.
    """
    if el.get("type"):
        return el["type"]
    ni = node_map.get(el.get("node_i"))
    nj = node_map.get(el.get("node_j"))
    if ni and nj:
        dx = abs(ni.get("x", 0) - nj.get("x", 0))
        dy = abs(ni.get("y", 0) - nj.get("y", 0))
        dz = abs(ni.get("z", 0) - nj.get("z", 0))
        max_d = max(dx, dy, dz)
        if max_d == 0:
            return "beam"
        if dy >= max_d * 0.8 or dz >= max_d * 0.8:
            return "column"
    return "beam"


def _get_floor_map(nodes: list[dict], elements: list[dict]) -> tuple[dict[int, list[int]], int, float]:
    """Map elements to floors based on node vertical coordinates.

    Auto-detects vertical axis: uses y for 2D frames (all z identical), z for 3D.

    Returns (floor_map, floor_count, floor_height) where floor_map maps
    floor index (0=ground) to list of element IDs.
    """
    if not nodes or not elements:
        return {}, 0, 0.0

    v_axis = _detect_vertical_axis(nodes)

    v_values = sorted({n[v_axis] for n in nodes})
    floor_count = len(v_values)
    floor_height = v_values[1] - v_values[0] if len(v_values) > 1 else 3.0

    node_map = {n["id"]: n for n in nodes}
    node_to_floor = {}
    for n in nodes:
        node_to_floor[n["id"]] = v_values.index(n[v_axis])

    floor_map: dict[int, list[int]] = defaultdict(list)
    for el in elements:
        ni = node_map.get(el["node_i"]) if isinstance(el["node_i"], int) else None
        nj = node_map.get(el["node_j"]) if isinstance(el["node_j"], int) else None
        if not ni or not nj:
            continue
        avg_v = (ni[v_axis] + nj[v_axis]) / 2
        floor_idx = min(range(len(v_values)), key=lambda i: abs(v_values[i] - avg_v))
        floor_map[floor_idx].append(el["id"])

    return dict(floor_map), floor_count, floor_height


def _normalize_structure(structure: dict) -> dict:
    """Ensure all elements have a 'type' field, inferring from geometry if missing."""
    nodes = structure.get("nodes", [])
    elements = structure.get("elements", [])
    if not nodes or not elements:
        return structure
    node_map = {n["id"]: n for n in nodes}
    normalized = []
    for el in elements:
        el_copy = dict(el)
        if not el_copy.get("type"):
            el_copy["type"] = _infer_element_type(el, node_map)
        normalized.append(el_copy)
    return {**structure, "elements": normalized}


def _element_type_label(el_type: str) -> str:
    """Human-readable Chinese label for element type."""
    labels = {"column": "柱", "beam": "梁", "wall": "墙", "slab": "板"}
    return labels.get(el_type, el_type)


def _make_step(step_num: int, element: dict, effects: list[str] | None = None,
               duration: int | None = None, extra_desc: str = "") -> DemolitionStep:
    """Create a standardized demolition step dict."""
    el_type = element.get("type", "beam")
    el_id = element.get("original_id", element.get("id", 0))
    base_desc = f"拆除第{el_id}号{_element_type_label(el_type)}"

    return DemolitionStep(
        step=step_num,
        action="remove",
        element_id=el_id,
        element_type=el_type,
        description=f"{base_desc}{extra_desc}",
        duration_ms=duration or DEFAULT_DURATIONS.get(el_type, 2000),
        effects=effects or EFFECT_MAP.get(el_type, [VisualEffects.FLASH_RED]),
    )


def plan_top_down(structure: dict) -> DemolitionPlan:
    """Remove from top: slabs first, then beams, then columns on top floor, repeat downward."""
    nodes = structure.get("nodes", [])
    elements = structure.get("elements", [])

    floor_map, floor_count, floor_height = _get_floor_map(nodes, elements)

    steps: list[DemolitionStep] = []
    step_num = 0

    sorted_floors = sorted(floor_map.keys(), reverse=True)

    for floor_idx in sorted_floors:
        floor_elements = [el for el in elements if el["id"] in floor_map[floor_idx]]
        floor_label = f"（第{floor_idx + 1}层）" if floor_idx > 0 else "（地面层）"

        # 1. Remove slabs on this floor
        slabs = [el for el in floor_elements if el.get("type") == "slab"]
        for el in slabs:
            step_num += 1
            steps.append(_make_step(step_num, el, extra_desc=floor_label))

        # 2. Remove beams on this floor
        beams = [el for el in floor_elements if el.get("type") == "beam"]
        for el in beams:
            step_num += 1
            steps.append(_make_step(step_num, el, extra_desc=floor_label,
                                    effects=[VisualEffects.FLASH_RED, VisualEffects.SHAKE, VisualEffects.DEBRIS]))

        # 3. Remove walls on this floor
        walls = [el for el in floor_elements if el.get("type") == "wall"]
        for el in walls:
            step_num += 1
            steps.append(_make_step(step_num, el, extra_desc=floor_label,
                                    effects=[VisualEffects.FLASH_RED, VisualEffects.CRACK,
                                             VisualEffects.DEBRIS, VisualEffects.DUST]))

        # 4. Remove columns on this floor (connecting this floor to the one below)
        columns = [el for el in elements if el.get("type") == "column"]
        floor_columns = []
        node_map_v = {n["id"]: n for n in nodes}
        v_axis = _detect_vertical_axis(nodes)
        for col in columns:
            ni = node_map_v.get(col["node_i"]) if isinstance(col["node_i"], int) else None
            nj = node_map_v.get(col["node_j"]) if isinstance(col["node_j"], int) else None
            if not ni or not nj:
                continue
            col_max_v = max(ni[v_axis], nj[v_axis])
            if abs(col_max_v - (floor_idx * floor_height)) < (floor_height * 0.5):
                floor_columns.append(col)

        for el in floor_columns:
            step_num += 1
            steps.append(_make_step(step_num, el, extra_desc=floor_label + "（失去支撑）",
                                    effects=[VisualEffects.FLASH_RED, VisualEffects.SHAKE,
                                             VisualEffects.FALL_DOWN, VisualEffects.DEBRIS,
                                             VisualEffects.DUST, VisualEffects.COLLAPSE_CHAIN]))

        # Add chain collapse effect between floor transitions
        if floor_idx > 0 and (slabs or beams or floor_columns):
            step_num += 1
            steps.append(DemolitionStep(
                step=step_num,
                action="collapse_propagate",
                element_id=-1,
                element_type="system",
                description=f"第{floor_idx + 1}层失去支撑，荷载向下传递至第{floor_idx}层",
                duration_ms=1000,
                effects=[VisualEffects.SHAKE, VisualEffects.DUST, VisualEffects.SWAY],
            ))

    return DemolitionPlan(
        steps=steps,
        total_steps=len(steps),
        strategy="top_down",
        estimated_duration_ms=sum(s["duration_ms"] for s in steps),
        structure_summary=f"{floor_count}层结构，共{len(elements)}个构件",
    )


def plan_bottom_up(structure: dict) -> DemolitionPlan:
    """Remove from bottom: columns first, then beams, then slabs, going upward. Riskier strategy."""
    nodes = structure.get("nodes", [])
    elements = structure.get("elements", [])

    floor_map, floor_count, _ = _get_floor_map(nodes, elements)

    steps: list[DemolitionStep] = []
    step_num = 0

    sorted_floors = sorted(floor_map.keys())

    for floor_idx in sorted_floors:
        floor_label = f"（第{floor_idx + 1}层）"

        # 1. Remove columns on this floor first (most aggressive)
        columns = [el for el in elements if el.get("type") == "column"]
        for el in columns:
            step_num += 1
            steps.append(_make_step(step_num, el, extra_desc=floor_label + "（底部拆除）",
                                    effects=[VisualEffects.FLASH_RED, VisualEffects.SHAKE,
                                             VisualEffects.FALL_DOWN, VisualEffects.COLLAPSE_CHAIN]))

        # 2. Remove walls
        floor_elements = [el for el in elements if el["id"] in floor_map.get(floor_idx, set())]
        walls = [el for el in floor_elements if el.get("type") == "wall"]
        for el in walls:
            step_num += 1
            steps.append(_make_step(step_num, el, extra_desc=floor_label))

        # 3. Remove beams
        beams = [el for el in floor_elements if el.get("type") == "beam"]
        for el in beams:
            step_num += 1
            steps.append(_make_step(step_num, el, extra_desc=floor_label))

        # 4. Remove slabs last
        slabs = [el for el in floor_elements if el.get("type") == "slab"]
        for el in slabs:
            step_num += 1
            steps.append(_make_step(step_num, el, extra_desc=floor_label))

        # Collapse warning
        step_num += 1
        steps.append(DemolitionStep(
            step=step_num,
            action="warning",
            element_id=-1,
            element_type="system",
            description=f"警告：第{floor_idx + 1}层底部支撑已拆除，上方结构可能倒塌",
            duration_ms=500,
            effects=[VisualEffects.SHAKE, VisualEffects.DUST],
        ))

    return DemolitionPlan(
        steps=steps,
        total_steps=len(steps),
        strategy="bottom_up",
        estimated_duration_ms=sum(s["duration_ms"] for s in steps),
        structure_summary=f"{floor_count}层结构，{len(elements)}个构件 — 底部拆除高风险策略",
    )


def plan_sequential(structure: dict) -> DemolitionPlan:
    """Remove element by element in ascending ID order."""
    elements = structure.get("elements", [])
    nodes = structure.get("nodes", [])
    sorted_elements = sorted(elements, key=lambda el: el.get("original_id", el.get("id", 0)))

    floor_map, floor_count, _ = _get_floor_map(nodes, elements)

    steps: list[DemolitionStep] = []
    for i, el in enumerate(sorted_elements, start=1):
        effects = EFFECT_MAP.get(el.get("type", "beam"), [VisualEffects.FLASH_RED])
        if i > 1 and i % 3 == 0:
            effects = effects + [VisualEffects.SHAKE]

        steps.append(_make_step(
            step_num=i,
            element=el,
            effects=effects,
            extra_desc=f"（顺序拆除第{i}步）",
        ))

    return DemolitionPlan(
        steps=steps,
        total_steps=len(steps),
        strategy="sequential",
        estimated_duration_ms=sum(s["duration_ms"] for s in steps),
        structure_summary=f"按编号顺序拆除{len(elements)}个构件",
    )


def plan_center_out(structure: dict) -> DemolitionPlan:
    """Remove columns from the center outward, then beams and slabs follow."""
    nodes = structure.get("nodes", [])
    elements = structure.get("elements", [])

    floor_map, floor_count, floor_height = _get_floor_map(nodes, elements)

    center_x = sum(n["x"] for n in nodes) / max(len(nodes), 1)
    center_y = sum(n.get("y", 0) for n in nodes) / max(len(nodes), 1)

    columns = [el for el in elements if el.get("type") == "column"]
    node_map = {n["id"]: n for n in nodes}

    def _dist_from_center(el: dict) -> float:
        ni = node_map.get(el["node_i"], {})
        nj = node_map.get(el["node_j"], {})
        xi = ni.get("x", center_x) if isinstance(ni, dict) else center_x
        yi = ni.get("y", center_y) if isinstance(ni, dict) else center_y
        xj = nj.get("x", center_x) if isinstance(nj, dict) else center_x
        yj = nj.get("y", center_y) if isinstance(nj, dict) else center_y
        mx = (xi + xj) / 2
        my = (yi + yj) / 2
        return (mx - center_x) ** 2 + (my - center_y) ** 2

    sorted_columns = sorted(columns, key=_dist_from_center, reverse=True)

    steps: list[DemolitionStep] = []
    step_num = 0

    for el in sorted_columns:
        step_num += 1
        steps.append(_make_step(step_num, el, extra_desc="（中心向外拆除）",
                                effects=[VisualEffects.FLASH_RED, VisualEffects.SHAKE,
                                         VisualEffects.FALL_DOWN, VisualEffects.DEBRIS,
                                         VisualEffects.DUST]))

    beams = [el for el in elements if el.get("type") == "beam"]
    for el in beams:
        step_num += 1
        steps.append(_make_step(step_num, el, extra_desc="（随柱拆除）",
                                effects=[VisualEffects.FLASH_RED, VisualEffects.DEBRIS]))

    slabs = [el for el in elements if el.get("type") == "slab"]
    for el in slabs:
        step_num += 1
        steps.append(_make_step(step_num, el, effects=[VisualEffects.FLASH_RED, VisualEffects.DEBRIS, VisualEffects.DUST]))

    return DemolitionPlan(
        steps=steps,
        total_steps=len(steps),
        strategy="center_out",
        estimated_duration_ms=sum(s["duration_ms"] for s in steps),
        structure_summary=f"{floor_count}层结构，从中心向外拆除{len(sorted_columns)}根柱",
    )


def plan_alternating_floors(structure: dict) -> DemolitionPlan:
    """Remove alternating floors: top floor first, skip one, remove next, etc.
    Creates a cascading pancake collapse effect."""
    nodes = structure.get("nodes", [])
    elements = structure.get("elements", [])

    floor_map, floor_count, floor_height = _get_floor_map(nodes, elements)

    sorted_floors = sorted(floor_map.keys(), reverse=True)
    even_floors = [f for f in sorted_floors if f % 2 == 0]
    odd_floors = [f for f in sorted_floors if f % 2 == 1]
    interleaved = even_floors + odd_floors

    steps: list[DemolitionStep] = []
    step_num = 0

    for floor_idx in interleaved:
        floor_label = f"（第{floor_idx + 1}层，隔层拆除）"
        floor_elements = [el for el in elements if el["id"] in floor_map.get(floor_idx, set())]

        columns_on_floor = []
        for el in elements:
            if el.get("type") != "column":
                continue
            ni = {n["id"]: n for n in nodes}.get(el["node_i"]) if isinstance(el["node_i"], int) else None
            nj = {n["id"]: n for n in nodes}.get(el["node_j"]) if isinstance(el["node_j"], int) else None
            if not ni or not nj:
                continue
            v_ax = _detect_vertical_axis(nodes)
            if abs(max(ni[v_ax], nj[v_ax]) - (floor_idx * floor_height)) < floor_height * 0.5:
                columns_on_floor.append(el)

        for el in columns_on_floor:
            step_num += 1
            steps.append(_make_step(step_num, el, extra_desc=floor_label,
                                    effects=[VisualEffects.FLASH_RED, VisualEffects.SHAKE,
                                             VisualEffects.FALL_DOWN, VisualEffects.COLLAPSE_CHAIN]))

        for el in floor_elements:
            if el.get("type") == "beam":
                step_num += 1
                steps.append(_make_step(step_num, el, extra_desc=floor_label,
                                        effects=[VisualEffects.FLASH_RED, VisualEffects.DEBRIS]))

        step_num += 1
        steps.append(DemolitionStep(
            step=step_num, action="collapse_propagate", element_id=-1,
            element_type="system",
            description=f"第{floor_idx + 1}层隔层倒塌，荷载重分布",
            duration_ms=800,
            effects=[VisualEffects.SHAKE, VisualEffects.DUST],
        ))

    return DemolitionPlan(
        steps=steps,
        total_steps=len(steps),
        strategy="alternating_floors",
        estimated_duration_ms=sum(s["duration_ms"] for s in steps),
        structure_summary=f"{floor_count}层结构，隔层交替拆除（先偶层后奇层）",
    )


def analyze_topology(structure: dict) -> StructuralTopology:
    """Build load path graph, detect primary vs secondary elements."""
    nodes = structure.get("nodes", [])
    elements = structure.get("elements", [])

    if not nodes or not elements:
        return StructuralTopology(
            load_paths=[],
            primary_elements=[],
            secondary_elements=[],
            floor_count=0,
            floor_map={},
            dependencies=[],
            critical_load_paths=[],
        )

    floor_map, floor_count, floor_height = _get_floor_map(nodes, elements)

    # Build element adjacency (by shared nodes)
    node_to_elements: dict[int, list[int]] = defaultdict(list)
    for el in elements:
        node_to_elements[el["node_i"]].append(el["id"])
        node_to_elements[el["node_j"]].append(el["id"])

    # Build element-to-element connections
    el_deps: dict[int, set[int]] = defaultdict(set)
    for el in elements:
        connected = set(node_to_elements[el["node_i"]]) | set(node_to_elements[el["node_j"]])
        el_deps[el["id"]] = connected - {el["id"]}

    # For each element, check if it has elements above it (supports them)
    # Columns are primary, slabs are secondary
    primary: list[int] = []
    secondary: list[int] = []

    for el in elements:
        el_type = el.get("type", "beam")
        el_id = el.get("original_id", el.get("id", 0))

        if el_type in ("column", "wall"):
            primary.append(el_id)
        else:
            secondary.append(el_id)

    # Build load paths: for each top-floor element, trace down through columns
    load_paths: list[dict] = []
    sorted_floors = sorted(floor_map.keys(), reverse=True)

    for floor_idx in sorted_floors:
        if floor_idx == 0:
            continue
        floor_els = floor_map.get(floor_idx, [])
        below_floor_els = floor_map.get(floor_idx - 1, [])

        for el_id in floor_els:
            el = next((e for e in elements if e.get("original_id", e.get("id", 0)) == el_id), None)
            if el is None:
                continue
            supported_by = [eid for eid in below_floor_els if eid in el_deps.get(el_id, set())]
            if supported_by:
                load_paths.append({
                    "from_element": el_id,
                    "from_floor": floor_idx,
                    "to_elements": supported_by,
                    "to_floor": floor_idx - 1,
                    "load_type": "重力传递",
                })

    # Critical load paths: chains from top to ground
    critical_paths: list[list[int]] = []
    top_floor_els = floor_map.get(max(floor_map.keys()), [])
    for el_id in top_floor_els:
        path = [el_id]
        current = el_id
        visited = {current}
        for _ in range(floor_count):
            deps = el_deps.get(current, set())
            below = [d for d in deps if d not in visited]
            if not below:
                break
            next_el = below[0]
            path.append(next_el)
            visited.add(next_el)
            current = next_el
        if len(path) > 1:
            critical_paths.append(path)

    dependencies = [
        {
            "element_id": eid,
            "depends_on": sorted(el_deps.get(eid, [])),
            "dependency_count": len(el_deps.get(eid, [])),
        }
        for eid in sorted(el_deps.keys())
    ]

    return StructuralTopology(
        load_paths=load_paths,
        primary_elements=sorted(primary),
        secondary_elements=sorted(secondary),
        floor_count=floor_count,
        floor_map=floor_map,
        dependencies=dependencies,
        critical_load_paths=critical_paths,
    )
