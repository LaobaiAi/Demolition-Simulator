"""Visual effects presets for demolition animation.

Each preset defines which visual features are enabled and their parameters,
mapping directly to the frontend EffectKey system:
  cascade, explosion, dust, shake, buckling, fracture, flash, trail, bounce
"""

# ── Preset type ──────────────────────────────────────────────────────────────

PRESETS = {}


def _register(name, label, enabled, params):
    entry = {
        "preset": name,
        "label": label,
        "effects": enabled,
        "params": params,
        "total_score": sum(
            _SCORES[k] for k in enabled if enabled[k]
        ),
    }
    PRESETS[name] = entry
    return entry


_SCORES = {
    "cascade": 25,
    "explosion": 15,
    "dust": 10,
    "shake": 10,
    "buckling": 15,
    "fracture": 10,
    "flash": 5,
    "trail": 5,
    "bounce": 5,
}

# ── Presets ──────────────────────────────────────────────────────────────────

LOW_INTENSITY = _register(
    "low",
    "低强度 — 简单移除，无特效",
    {
        "cascade": True,
        "explosion": False,
        "dust": False,
        "shake": False,
        "buckling": False,
        "fracture": False,
        "flash": False,
        "trail": False,
        "bounce": False,
    },
    {
        "fall_duration_ms": 600,
        "stagger_duration_ms": 800,
        "ground_rest_offset_ms": 200,
        "settle_duration_ms": 300,
        "easing": "linear",
        "debris_count": 0,
        "dust_clouds_per_element": 0,
    },
)

MEDIUM_INTENSITY = _register(
    "medium",
    "中强度 — 闪烁后移除，简单下落",
    {
        "cascade": True,
        "explosion": True,
        "dust": True,
        "shake": False,
        "buckling": False,
        "fracture": False,
        "flash": True,
        "trail": False,
        "bounce": False,
    },
    {
        "fall_duration_ms": 800,
        "stagger_duration_ms": 1200,
        "ground_rest_offset_ms": 400,
        "settle_duration_ms": 500,
        "easing": "ease_out",
        "debris_count": 6,
        "dust_clouds_per_element": 2,
        "flash_duration_ms": 300,
        "flash_color": "#ef4444",
    },
)

HIGH_INTENSITY = _register(
    "high",
    "高强度 — 闪烁、抖动、碎片、烟尘、弹跳",
    {
        "cascade": True,
        "explosion": True,
        "dust": True,
        "shake": True,
        "buckling": True,
        "fracture": True,
        "flash": True,
        "trail": True,
        "bounce": True,
    },
    {
        "fall_duration_ms": 1000,
        "stagger_duration_ms": 1500,
        "ground_rest_offset_ms": 600,
        "settle_duration_ms": 800,
        "easing": "bounce",
        "debris_count": 10,
        "dust_clouds_per_element": 3,
        "flash_duration_ms": 500,
        "flash_color": "#ef4444",
        "shake_intensity": 4,
        "shake_decay_ms": 1000,
        "pre_rumble_ms": 80,
        "fracture_long_element_min": 3,
        "buckle_chance": 0.4,
        "impact_ring_max_radius": 40,
        "impact_ring_duration_ms": 800,
        "trail_opacity": 0.4,
        "bounce_restitution": 0.5,
    },
)

CINEMATIC = _register(
    "cinematic",
    "电影级 — 全部特效，相机抖动，关键柱慢动作",
    {
        "cascade": True,
        "explosion": True,
        "dust": True,
        "shake": True,
        "buckling": True,
        "fracture": True,
        "flash": True,
        "trail": True,
        "bounce": True,
    },
    {
        "fall_duration_ms": 1400,
        "stagger_duration_ms": 2000,
        "ground_rest_offset_ms": 800,
        "settle_duration_ms": 1200,
        "easing": "bounce",
        "debris_count": 16,
        "dust_clouds_per_element": 5,
        "flash_duration_ms": 600,
        "flash_color": "#ef4444",
        "shake_intensity": 6,
        "shake_decay_ms": 1500,
        "pre_rumble_ms": 150,
        "fracture_long_element_min": 2,
        "buckle_chance": 0.6,
        "impact_ring_max_radius": 60,
        "impact_ring_duration_ms": 1200,
        "trail_opacity": 0.6,
        "bounce_restitution": 0.7,
        "slow_motion_on_critical": True,
        "slow_motion_factor": 0.3,
        "slow_motion_duration_ms": 1000,
        "camera_shake_pattern": "combined",
        "tension_pulse_before_impact": True,
    },
)

# ── Style overlays ───────────────────────────────────────────────────────────

STYLE_OVERLAYS = {
    "realistic": {
        "label": "写实风格",
        "overrides": {
            "dust_opacity": 0.5,
            "debris_gravity": 980,
            "bounce_restitution_factor": 0.4,
            "color_palette": "realistic",
        },
    },
    "dramatic": {
        "label": "戏剧风格",
        "overrides": {
            "dust_opacity": 0.8,
            "debris_gravity": 600,
            "bounce_restitution_factor": 0.7,
            "color_palette": "dramatic",
        },
    },
    "technical": {
        "label": "技术风格",
        "overrides": {
            "dust_opacity": 0.2,
            "debris_gravity": 980,
            "bounce_restitution_factor": 0.3,
            "color_palette": "technical",
            "show_element_ids": True,
            "show_forces": True,
        },
    },
}


def get_preset(intensity: str) -> dict:
    """Get a preset by intensity key. Falls back to medium on unknown key."""
    return PRESETS.get(intensity, PRESETS["medium"])


def list_presets() -> list[dict]:
    """Return all available presets (without full params blob for display)."""
    return [
        {
            "preset": p["preset"],
            "label": p["label"],
            "total_score": p["total_score"],
            "effects": p["effects"],
        }
        for p in PRESETS.values()
    ]


def merge_preset_with_style(
    intensity: str, style: str = "realistic"
) -> dict:
    """Merge an intensity preset with a style overlay into a single config."""
    base = dict(get_preset(intensity))
    style_info = STYLE_OVERLAYS.get(style, STYLE_OVERLAYS["realistic"])
    merged_params = dict(base["params"])
    merged_params.update(style_info["overrides"])
    return {
        "preset": base["preset"],
        "label": f'{base["label"]} + {style_info["label"]}',
        "effects": dict(base["effects"]),
        "params": merged_params,
        "total_score": base["total_score"],
        "style": style,
    }
