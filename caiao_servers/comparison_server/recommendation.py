"""Rule-based strategy recommendation for demolition planning.

Analyzes structure metrics and recommends the optimal demolition strategy
based on structural characteristics and safety considerations.
"""

import logging

logger = logging.getLogger("recommendation")


def recommend_strategy(
    max_stress_ratio: float = 0.5,
    max_displacement: float = 0.0,
    element_count: int = 10,
    floor_count: int = 3,
    irregularity: float = 0.0,
) -> dict:
    """Recommend the optimal demolition strategy based on structure metrics.

    Rule table:
      - max_stress_ratio < 0.3  -> sequential  (safe structure, simple approach works)
      - max_stress_ratio > 0.8  -> top_down     (high stress, be cautious)
      - irregularity > 0.5      -> llm          (irregular layout needs smart planning)
      - floor_count < 4         -> bottom_up    (low-rise -> viable)

    Multiple rules may fire simultaneously; the recommendation engine
    aggregates all triggered rules into a weighted score matrix.

    Args:
        max_stress_ratio: Maximum stress ratio across all elements (0-1+).
        max_displacement: Maximum displacement in mm.
        element_count: Total number of elements in the structure.
        floor_count: Number of floors.
        irregularity: Structural irregularity score (0-1), 0=regular, 1=highly irregular.

    Returns:
        dict with recommended strategy, explanation, and full score matrix.
    """
    rules_triggered = _get_rules_triggered(max_stress_ratio, floor_count, irregularity)
    scores = _compute_score_matrix(max_stress_ratio, floor_count, irregularity)

    ranked = sorted(scores.items(), key=lambda x: x[1]["recommendation_score"], reverse=True)
    best_strategy = ranked[0][0]
    best_score = ranked[0][1]["recommendation_score"]
    runner_up = ranked[1][0] if len(ranked) > 1 else None

    return {
        "recommended_strategy": best_strategy,
        "recommendation_score": best_score,
        "runner_up_strategy": runner_up,
        "explanation": _generate_explanation(best_strategy, rules_triggered),
        "score_matrix": scores,
        "rules_triggered": rules_triggered,
        "structure_metrics": {
            "max_stress_ratio": max_stress_ratio,
            "max_displacement_mm": max_displacement,
            "element_count": element_count,
            "floor_count": floor_count,
            "irregularity": irregularity,
        },
    }


def _get_rules_triggered(
    max_stress_ratio: float,
    floor_count: int,
    irregularity: float,
) -> list[dict]:
    """Determine which recommendation rules were triggered."""
    rules = []

    if max_stress_ratio < 0.3:
        rules.append({
            "rule": "low_stress",
            "condition": f"max_stress_ratio={max_stress_ratio:.2f} < 0.3",
            "recommendation": "sequential",
            "reason": "Low stress ratio indicates a safe structure — sequential element-by-element removal is efficient and sufficient.",
        })

    if max_stress_ratio > 0.8:
        rules.append({
            "rule": "high_stress",
            "condition": f"max_stress_ratio={max_stress_ratio:.2f} > 0.8",
            "recommendation": "top_down",
            "reason": "High stress ratio — cautious top-down approach minimizes collapse risk during demolition.",
        })

    if floor_count < 4:
        rules.append({
            "rule": "low_rise",
            "condition": f"floor_count={floor_count} < 4",
            "recommendation": "bottom_up",
            "reason": "Low-rise structure — bottom-up demolition is viable and efficient for buildings under 4 floors.",
        })

    if irregularity > 0.5:
        rules.append({
            "rule": "irregular_layout",
            "condition": f"irregularity={irregularity:.2f} > 0.5",
            "recommendation": "llm",
            "reason": "Irregular structural layout — LLM-guided smart planning adapts to non-uniform topology.",
        })

    return rules


def _compute_score_matrix(max_stress_ratio: float, floor_count: int, irregularity: float) -> dict:
    """Compute a score matrix (0-100) for each strategy.

    Weights for overall recommendation_score: safety=0.5, efficiency=0.3, visual=0.2.
    """
    # Top-down: safest for tall/high-stress structures
    top_down_safety = min(100.0, 70.0 + 30.0 * max_stress_ratio)
    top_down_efficiency = max(0.0, 100.0 - 20.0 * max(0.0, floor_count - 2.0))
    top_down_visual = 75.0 + 5.0 * min(1.0, max_stress_ratio)

    # Bottom-up: efficient for low-rise, risky for tall/high-stress
    bottom_up_safety = max(0.0, 100.0 - 25.0 * floor_count - 30.0 * max_stress_ratio)
    bottom_up_efficiency = 60.0 + 10.0 * max(0.0, 4.0 - floor_count)
    bottom_up_visual = 80.0

    # Sequential: works best for simple, low-stress structures
    sequential_safety = max(0.0, 100.0 - 20.0 * irregularity - 50.0 * max(0.0, max_stress_ratio - 0.3))
    sequential_efficiency = 70.0 + 15.0 * max(0.0, 0.3 - max_stress_ratio)
    sequential_visual = 50.0

    # LLM: adapts to irregular structures
    llm_safety = min(100.0, 70.0 + 30.0 * irregularity)
    llm_efficiency = 60.0
    llm_visual = 85.0 + 10.0 * irregularity

    scores = {
        "top_down": {
            "safety_score": round(top_down_safety, 1),
            "efficiency_score": round(top_down_efficiency, 1),
            "visual_score": round(top_down_visual, 1),
        },
        "bottom_up": {
            "safety_score": round(bottom_up_safety, 1),
            "efficiency_score": round(bottom_up_efficiency, 1),
            "visual_score": round(bottom_up_visual, 1),
        },
        "sequential": {
            "safety_score": round(sequential_safety, 1),
            "efficiency_score": round(sequential_efficiency, 1),
            "visual_score": round(sequential_visual, 1),
        },
        "llm": {
            "safety_score": round(llm_safety, 1),
            "efficiency_score": round(llm_efficiency, 1),
            "visual_score": round(llm_visual, 1),
        },
    }

    for strategy, s in scores.items():
        s["recommendation_score"] = round(
            0.5 * s["safety_score"] + 0.3 * s["efficiency_score"] + 0.2 * s["visual_score"],
            1,
        )

    return scores


def _generate_explanation(strategy: str, rules_triggered: list[dict]) -> str:
    """Generate a human-readable explanation for the recommendation."""
    labels = {
        "top_down": "Top-Down (自上而下)",
        "bottom_up": "Bottom-Up (自下而上)",
        "sequential": "Sequential (顺序拆除)",
        "llm": "LLM-Guided (AI引导)",
    }

    strategy_label = labels.get(strategy, strategy)
    parts = [f"Recommended strategy: {strategy_label}."]

    if rules_triggered:
        parts.append(" Triggered rules:")
        for r in rules_triggered:
            parts.append(f"  - {r['reason']}")

    return "".join(parts)
