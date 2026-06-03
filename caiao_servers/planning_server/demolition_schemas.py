"""Shared schemas for demolition planning — types, visual effects, and step structures."""

from typing import TypedDict, NotRequired


class VisualEffects:
    """Visual effect tags for demolition animation steps."""
    FLASH_RED = "flash_red"
    SHAKE = "shake"
    FALL_DOWN = "fall_down"
    DEBRIS = "debris"
    DUST = "dust"
    CRACK = "crack"
    SWAY = "sway"
    COLLAPSE_CHAIN = "collapse_chain"
    SMOKE = "smoke"

    ALL_EFFECTS = [FLASH_RED, SHAKE, FALL_DOWN, DEBRIS, DUST, CRACK, SWAY, COLLAPSE_CHAIN, SMOKE]


class DemolitionStep(TypedDict):
    step: int
    action: str
    element_id: int
    element_type: str
    description: str
    duration_ms: int
    effects: list[str]
    target_floor: NotRequired[int]


class DemolitionPlan(TypedDict):
    steps: list[DemolitionStep]
    total_steps: int
    strategy: str
    estimated_duration_ms: int
    structure_summary: str


class StructuralTopology(TypedDict):
    load_paths: list[dict]
    primary_elements: list[int]
    secondary_elements: list[int]
    floor_count: int
    floor_map: dict[int, list[int]]
    dependencies: list[dict]
    critical_load_paths: list[list[int]]


# Element types used across the module
ELEMENT_TYPES = ("column", "beam", "wall", "slab")

# Default durations per element type in ms
DEFAULT_DURATIONS: dict[str, int] = {
    "slab": 2000,
    "beam": 1500,
    "column": 3000,
    "wall": 4000,
}

# Effect mappings per element type
EFFECT_MAP: dict[str, list[str]] = {
    "slab": [VisualEffects.FLASH_RED, VisualEffects.DEBRIS, VisualEffects.DUST],
    "beam": [VisualEffects.FLASH_RED, VisualEffects.SHAKE, VisualEffects.DEBRIS],
    "column": [VisualEffects.FLASH_RED, VisualEffects.SHAKE, VisualEffects.FALL_DOWN, VisualEffects.DEBRIS, VisualEffects.DUST],
    "wall": [VisualEffects.FLASH_RED, VisualEffects.CRACK, VisualEffects.DEBRIS, VisualEffects.DUST],
}
