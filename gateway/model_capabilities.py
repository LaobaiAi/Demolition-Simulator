"""Model capabilities registry — explicit per-model configuration.

Replaces fragile substring matching in llm_engine.py with an exact-match
registry. Unknown models get conservative defaults with a warning log.

Add new models here when they ship — do NOT add substring heuristics.
"""

import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

ThinkingFormat = Literal["deepseek_v4", "openai_o", None]


@dataclass
class ModelCapabilities:
    supports_thinking: bool = False
    thinking_format: ThinkingFormat = None
    supports_streaming: bool = True
    supports_tool_calling: bool = True
    extra_body_keys: set[str] = field(default_factory=set)


# Exact-match registry.  Aliases map to the canonical key.
KNOWN_MODELS: dict[str, ModelCapabilities] = {
    # ── DeepSeek V4 family — thinking via extra_body ──────────────────────
    "deepseek-v4-pro": ModelCapabilities(
        supports_thinking=True,
        thinking_format="deepseek_v4",
    ),
    "deepseek-v4-flash": ModelCapabilities(
        supports_thinking=True,
        thinking_format="deepseek_v4",
    ),
    "deepseek-reasoning": ModelCapabilities(
        supports_thinking=True,
        thinking_format="deepseek_v4",
    ),
    "deepseek-r1": ModelCapabilities(
        supports_thinking=True,
        thinking_format="deepseek_v4",
    ),
    # ── OpenAI models — no thinking extra_body ────────────────────────────
    "gpt-4o": ModelCapabilities(),
    "gpt-4o-mini": ModelCapabilities(),
    "gpt-4.1": ModelCapabilities(),
    "gpt-4.1-mini": ModelCapabilities(),
    "gpt-4.1-nano": ModelCapabilities(),
    "gpt-4-turbo": ModelCapabilities(),
    "gpt-3.5-turbo": ModelCapabilities(),
    # ── OpenAI o-series — native reasoning, NOT deepseek_v4 format ────────
    "o4-mini": ModelCapabilities(
        supports_thinking=True,
        thinking_format="openai_o",
    ),
    "o3-mini": ModelCapabilities(
        supports_thinking=True,
        thinking_format="openai_o",
    ),
    # ── Anthropic (routed through OpenAI-compatible proxy) ─────────────────
    "claude-sonnet-4-6": ModelCapabilities(),
    "claude-opus-4-8": ModelCapabilities(),
    "claude-haiku-4-5": ModelCapabilities(),
}

# Aliases that map to canonical names above
MODEL_ALIASES: dict[str, str] = {
    "gpt-4": "gpt-4o",
}


def get_capabilities(model: str) -> ModelCapabilities:
    """Return capabilities for *model*, with conservative fallback for unknowns.

    Checks exact match first, then aliases.  Unknown models get a logged
    warning and safe defaults (no thinking, streaming + tool-calling on).
    """
    key = model.lower().strip()
    if key in MODEL_ALIASES:
        key = MODEL_ALIASES[key]
    if key in KNOWN_MODELS:
        return KNOWN_MODELS[key]
    logger.warning(
        f"Unknown model '{model}' — using conservative defaults "
        f"(no thinking, streaming on, tool-calling on). "
        f"Add it to gateway/model_capabilities.py if it needs thinking support."
    )
    return ModelCapabilities()


def build_thinking_config(caps: ModelCapabilities, tools: list | None) -> dict:
    """Return an extra_body dict (or empty dict) for the model's thinking config.

    Only DeepSeek V4 and OpenAI o-series models get thinking parameters.
    Other models get an empty dict — we never send unknown extra_body keys.
    """
    if not caps.supports_thinking:
        return {}

    if caps.thinking_format == "deepseek_v4":
        return {
            "thinking": {"type": "enabled"},
        }

    if caps.thinking_format == "openai_o":
        return {
            "reasoning_effort": "medium" if tools else "high",
        }

    return {}
