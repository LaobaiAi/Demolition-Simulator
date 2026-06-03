"""Timeline management logic for demolition animation.

Converts a multi-round demolition plan into a keyframe-based animation
timeline, and provides interpolation to query state at any time point.
"""

import copy
import math
from typing import Any


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ease_linear(t: float) -> float:
    return t


def _ease_out(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def _ease_bounce(t: float) -> float:
    if t < 1 / 2.75:
        return 7.5625 * t * t
    if t < 2 / 2.75:
        t -= 1.5 / 2.75
        return 7.5625 * t * t + 0.75
    if t < 2.5 / 2.75:
        t -= 2.25 / 2.75
        return 7.5625 * t * t + 0.9375
    t -= 2.625 / 2.75
    return 7.5625 * t * t + 0.984375


_EASING_FUNCS = {
    "linear": _ease_linear,
    "ease_out": _ease_out,
    "bounce": _ease_bounce,
}


def _apply_easing(t: float, easing: str) -> float:
    return _EASING_FUNCS.get(easing, _ease_linear)(max(0.0, min(1.0, t)))


# ── Keyframe creation ────────────────────────────────────────────────────────

def _build_element_keyframes(
    element_id: int,
    round_index: int,
    round_count: int,
    is_critical: bool,
    total_duration_ms: int,
    config: dict | None = None,
) -> list[dict]:
    """Build a sequence of keyframes for a single element being demolished.

    Parameters
    ----------
    element_id : int
        The element identifier.
    round_index : int
        Which demolition round this element belongs to (0-based).
    round_count : int
        Total number of rounds in the demolition plan.
    is_critical : bool
        Whether this element is the critical column in its round.
    total_duration_ms : int
        Total animation duration across all rounds.
    config : dict or None
        Optional config overrides (fall_duration_ms, flash_duration_ms, etc.)

    Returns
    -------
    list[dict]
        Keyframes for this element.
    """
    cfg = config or {}
    stagger_ms = cfg.get("stagger_duration_ms", 1200)
    fall_ms = cfg.get("fall_duration_ms", 800)
    flash_ms = cfg.get("flash_duration_ms", 300)
    settle_ms = cfg.get("settle_duration_ms", 500)
    base_delay = int(total_duration_ms * round_index / max(round_count, 1))
    stagger_offset = int(stagger_ms * (element_id % 5) / 5)

    kfs = [
        {
            "time_ms": base_delay,
            "element_id": element_id,
            "action": "flash",
            "duration_ms": flash_ms,
            "easing": "linear",
            "params": {
                "flash_color": cfg.get("flash_color", "#ef4444"),
                "intensity": 0.7,
            },
        },
        {
            "time_ms": base_delay + flash_ms,
            "element_id": element_id,
            "action": "remove",
            "duration_ms": 0,
            "easing": "linear",
            "params": {},
        },
    ]

    fall_start = base_delay + flash_ms + stagger_offset
    kfs.append({
        "time_ms": fall_start,
        "element_id": element_id,
        "action": "fall",
        "duration_ms": fall_ms,
        "easing": cfg.get("easing", "ease_out"),
        "params": {
            "is_critical": is_critical,
            "fall_height_ratio": 0.6,
            "rotation_degrees": 80 if is_critical else 30,
        },
    })

    kfs.append({
        "time_ms": fall_start + fall_ms,
        "element_id": element_id,
        "action": "explode",
        "duration_ms": 400,
        "easing": "ease_out",
        "params": {
            "debris_count": cfg.get("debris_count", 6),
            "particle_speed_min": 2,
            "particle_speed_max": 7,
        },
    })

    if cfg.get("dust_clouds_per_element", 0) > 0:
        kfs.append({
            "time_ms": fall_start + fall_ms + 200,
            "element_id": element_id,
            "action": "dust",
            "duration_ms": 1200,
            "easing": "ease_out",
            "params": {
                "cloud_count": cfg.get("dust_clouds_per_element", 2),
                "max_radius": 32,
            },
        })

    kfs.append({
        "time_ms": fall_start + fall_ms + settle_ms,
        "element_id": element_id,
        "action": "settle",
        "duration_ms": settle_ms,
        "easing": "ease_out",
        "params": {
            "final_opacity": 0.3,
        },
    })

    return kfs


# ── Plan → Timeline ──────────────────────────────────────────────────────────

def create_timeline_from_plan(
    plan: list[dict],
    structure: dict,
    total_duration_ms: int = 8000,
    config: dict | None = None,
) -> dict:
    """Convert a demolition plan into a keyframe-based animation timeline.

    Parameters
    ----------
    plan : list[dict]
        Demolition steps. Each step has:
          - "round" (int)
          - "element_ids" (list[int])
          - "critical_element_id" (int | None)
    structure : dict
        Frame structure with "nodes", "elements", "loads", "supports".
    total_duration_ms : int
        Total desired animation duration in milliseconds.
    config : dict or None
        Optional effect config overrides.

    Returns
    -------
    dict
        Timeline object with keyframes and metadata.
    """
    elements_map = {e["id"]: e for e in structure.get("elements", [])}
    nodes_map = {n["id"]: n for n in structure.get("nodes", [])}

    all_keyframes: list[dict] = []
    planned_elements: set[int] = set()

    for step in plan:
        round_idx = step.get("round", 0)
        element_ids = step.get("element_ids", [])
        critical_id = step.get("critical_element_id")
        round_count = len(plan)

        for eid in element_ids:
            if eid in planned_elements:
                continue
            planned_elements.add(eid)
            is_critical = eid == critical_id
            kfs = _build_element_keyframes(
                eid, round_idx, round_count, is_critical,
                total_duration_ms, config,
            )
            all_keyframes.extend(kfs)

    all_keyframes.sort(key=lambda kf: kf["time_ms"])

    element_positions = {}
    for elem in structure.get("elements", []):
        ni = nodes_map.get(elem.get("node_i"))
        nj = nodes_map.get(elem.get("node_j"))
        if ni and nj:
            x1, y1 = ni["x"], ni.get("y", 0)
            x2, y2 = nj["x"], nj.get("y", 0)
            element_positions[elem["id"]] = {
                "x1": x1, "y1": y1,
                "x2": x2, "y2": y2,
                "cx": (x1 + x2) / 2,
                "cy": (y1 + y2) / 2,
                "length": math.hypot(x2 - x1, y2 - y1),
                "is_column": abs(x2 - x1) < 0.01,
                "node_i": elem.get("node_i"),
                "node_j": elem.get("node_j"),
            }

    return {
        "keyframes": all_keyframes,
        "total_duration_ms": total_duration_ms,
        "element_count": len(structure.get("elements", [])),
        "planned_element_count": len(planned_elements),
        "round_count": len(plan),
        "element_positions": element_positions,
        "metadata": {
            "keyframe_count": len(all_keyframes),
            "duration_per_element_ms": total_duration_ms // max(len(planned_elements), 1),
        },
    }


# ── State query ───────────────────────────────────────────────────────────────

def get_state_at_time(timeline: dict, timestamp_ms: int) -> dict:
    """Get the animation state for a given timestamp.

    Parameters
    ----------
    timeline : dict
        Timeline object from ``create_timeline_from_plan``.
    timestamp_ms : int
        Query time in milliseconds.

    Returns
    -------
    dict
        State dict with:
          - "active" (list[int]) — elements still intact
          - "removed" (list[int]) — elements already removed
          - "falling" (list[dict]) — elements currently falling
          - "flashing" (list[dict]) — elements currently flashing
          - "exploding" (list[dict]) — elements currently exploding
          - "progress" (float) — overall progress 0..1
          - "timestamp_ms" (int)
    """
    keyframes = timeline.get("keyframes", [])
    total = timeline.get("total_duration_ms", 8000)

    relevant = [kf for kf in keyframes if kf["time_ms"] <= timestamp_ms]
    progress = min(timestamp_ms / max(total, 1), 1.0)

    removed_set: set[int] = set()
    falling: list[dict] = []
    flashing: list[dict] = []
    exploding: list[dict] = []

    for kf in relevant:
        eid = kf["element_id"]
        action = kf["action"]
        t0 = kf["time_ms"]
        dur = kf.get("duration_ms", 0)
        t_local = timestamp_ms - t0

        if action == "remove":
            removed_set.add(eid)
        elif action == "flash" and t_local <= dur:
            progress_f = _apply_easing(t_local / max(dur, 1), kf.get("easing", "linear"))
            flashing.append({
                "element_id": eid,
                "local_progress": progress_f,
                "params": kf.get("params", {}),
            })
        elif action == "fall" and t_local <= dur:
            progress_f = _apply_easing(t_local / max(dur, 1), kf.get("easing", "linear"))
            falling.append({
                "element_id": eid,
                "local_progress": progress_f,
                "params": kf.get("params", {}),
            })
        elif action == "explode" and t_local <= dur:
            progress_f = _apply_easing(t_local / max(dur, 1), "ease_out")
            exploding.append({
                "element_id": eid,
                "local_progress": progress_f,
                "params": kf.get("params", {}),
            })

    planned_elements = set(
        kf["element_id"] for kf in keyframes
    )
    all_element_ids = set(
        eid for eid in timeline.get("element_positions", {})
    )

    still_active = sorted(
        all_element_ids - planned_elements - removed_set
    )

    return {
        "active": still_active,
        "removed": sorted(removed_set),
        "falling": falling,
        "flashing": flashing,
        "exploding": exploding,
        "progress": round(progress, 4),
        "timestamp_ms": timestamp_ms,
    }


# ── Timeline class ───────────────────────────────────────────────────────────

class Timeline:
    """Holds timeline state and provides incremental query API."""

    def __init__(self, timeline_data: dict):
        self.data = timeline_data
        self._elapsed = 0

    @classmethod
    def from_plan(
        cls,
        plan: list[dict],
        structure: dict,
        total_duration_ms: int = 8000,
        config: dict | None = None,
    ) -> "Timeline":
        return cls(create_timeline_from_plan(plan, structure, total_duration_ms, config))

    @property
    def total_duration_ms(self) -> int:
        return self.data.get("total_duration_ms", 8000)

    @property
    def progress(self) -> float:
        return min(self._elapsed / max(self.total_duration_ms, 1), 1.0)

    @property
    def is_finished(self) -> bool:
        return self._elapsed >= self.total_duration_ms

    def seek(self, timestamp_ms: int) -> dict:
        """Seek to a specific timestamp and return state."""
        self._elapsed = max(0, min(timestamp_ms, self.total_duration_ms))
        return get_state_at_time(self.data, self._elapsed)

    def advance(self, delta_ms: int) -> dict:
        """Advance the timeline by *delta_ms* and return new state."""
        return self.seek(self._elapsed + delta_ms)

    def reset(self):
        """Reset timeline to beginning."""
        self._elapsed = 0

    def serialize(self) -> dict:
        """Return the full timeline data dict."""
        return copy.deepcopy(self.data)


# ── Plan → frontend-compatible animation data ───────────────────────────────

def sequence_to_animation_data(
    plan: list[dict],
    structure: dict,
    effects_config: dict | None = None,
) -> dict:
    """Convert a demolition plan to frontend-compatible animation data.

    The output format mirrors what the SVG CollapseAnimation component
    expects: a sorted cascade with delays, plus debris, dust, and impact
    ring arrays.

    Parameters
    ----------
    plan : list[dict]
        Demolition steps with "element_ids" per round.
    structure : dict
        Frame structure with "nodes" and "elements".
    effects_config : dict or None
        Optional effects config with feature toggles and params.

    Returns
    -------
    dict
        Animation data compatible with the frontend CollapseAnimation.
        Keys: cascade, debris, dust, impactRings, duration_ms, metadata.
    """
    cfg = effects_config or {}
    effects = cfg.get("effects", {})
    params = cfg.get("params", {})

    nodes_map = {n["id"]: n for n in structure.get("nodes", [])}
    elements_map = {e["id"]: e for e in structure.get("elements", [])}

    # Collect all element ids in demolition order (per round order)
    seen: set[int] = set()
    ordered_ids: list[int] = []
    for step in plan:
        for eid in step.get("element_ids", []):
            if eid not in seen:
                seen.add(eid)
                ordered_ids.append(eid)

    # Build cascade with position data and delays
    cascade = []
    for idx, eid in enumerate(ordered_ids):
        elem = elements_map.get(eid)
        if not elem:
            continue
        ni = nodes_map.get(elem.get("node_i"))
        nj = nodes_map.get(elem.get("node_j"))
        if not ni or not nj:
            continue
        min_elem_y = min(ni.get("y", 0), nj.get("y", 0))
        is_column = abs(ni.get("x", 0) - nj.get("x", 0)) < 0.01
        length = math.hypot(
            nj.get("x", 0) - ni.get("x", 0),
            nj.get("y", 0) - ni.get("y", 0),
        )
        cascade.append({
            "id": eid,
            "isColumn": is_column,
            "len": length,
            "p1": {"x": ni.get("x", 0), "y": ni.get("y", 0)},
            "p2": {"x": nj.get("x", 0), "y": nj.get("y", 0)},
            "delay": int(
                (idx / max(len(ordered_ids) - 1, 1))
                * params.get("stagger_duration_ms", 1500)
            ),
        })

    cascade.sort(key=lambda c: min(c["p1"]["y"], c["p2"]["y"]))

    # Debris
    total = len(cascade)
    debris = []
    if effects.get("explosion", True):
        for item in cascade:
            cx = (item["p1"]["x"] + item["p2"]["x"]) / 2
            cy = (item["p1"]["y"] + item["p2"]["y"]) / 2
            count = params.get("debris_count", 8)
            for i in range(count):
                angle = (i / count) * math.pi * 2 + (item["id"] * 0.1)
                speed = 2 + (i % 5) * 1.2
                debris.append({
                    "x": cx + (i % 3 - 1) * 10,
                    "y": cy,
                    "vx": math.cos(angle) * speed,
                    "vy": math.sin(angle) * speed - 3,
                    "size": 1.5 + (i % 4) * 0.8,
                    "color": "#ef4444" if item["isColumn"] else "#f97316",
                    "baseOpacity": 0.6 + (i % 3) * 0.15,
                    "rotation": i * 45,
                    "rotSpeed": (i % 5 - 2) * 2,
                    "groundY": cy * 0.05,
                    "delay": item["delay"] + 100 + i * 30,
                    "lifetime": 0.8 + (i % 4) * 0.25,
                    "didBounce": False,
                })

    # Dust
    dust = []
    if effects.get("dust", True):
        for item in cascade:
            cx = (item["p1"]["x"] + item["p2"]["x"]) / 2
            for i in range(params.get("dust_clouds_per_element", 2)):
                dust.append({
                    "cx": cx + (i - 0.5) * 30,
                    "cy": min(item["p1"]["y"], item["p2"]["y"]) - 5,
                    "maxR": 12 + i * 10,
                    "delay": item["delay"] + 400 + i * 200,
                })

    # Impact rings
    impact_rings = []
    if effects.get("shake", True):
        for item in cascade:
            cx = (item["p1"]["x"] + item["p2"]["x"]) / 2
            impact_rings.append({
                "cx": cx,
                "cy": min(item["p1"]["y"], item["p2"]["y"]),
                "maxR": params.get("impact_ring_max_radius", 40),
                "delay": item["delay"] + 700,
                "duration": params.get("impact_ring_duration_ms", 800),
            })

    fall_duration_ms = params.get("fall_duration_ms", 1000)
    total_duration = (
        (total - 1) * fall_duration_ms // max(total - 1, 1)
        + fall_duration_ms * 2
        if total > 0
        else 5000
    )

    return {
        "cascade": cascade,
        "debris": debris,
        "dust": dust,
        "impactRings": impact_rings,
        "duration_ms": total_duration,
        "metadata": {
            "element_count": total,
            "effects_enabled": list(effects.keys()),
            "total_particles": len(debris),
        },
    }
