"""Test: Can the LLM select correct tools WITHOUT the tool catalogue in system prompt?

Compares tool selection accuracy between:
  A) Full SYSTEM_PROMPT (CORE + CATALOGUE + PATTERNS + REFERENCE)
  B) CORE_PROMPT only (no tool descriptions in system prompt, only in function defs)

Run: python tests/test_tool_selection.py
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_engine import (
    LLMEngine, CORE_PROMPT, SYSTEM_PROMPT, TOOL_CATALOGUE,
    ORCHESTRATION_PATTERNS, REFERENCE_DATA, build_system_prompt,
)

TEST_CASES = [
    {
        "name": "simple_analyze",
        "message": "Analyze a 3-bay 4-story steel frame with 6m span and 3m story height using Q355 steel",
        "expected_tools": ["quick_analysis", "generate_frame", "generate_from_text"],
    },
    {
        "name": "simple_demolish",
        "message": "demolish element 5",
        "expected_tools": ["apply_demolition_action"],
    },
    {
        "name": "bim_generate",
        "message": "Generate a BIM model of a steel frame building with HE-B columns and IPE beams, Q355 grade",
        "expected_tools": ["generate_steel_frame"],
    },
    {
        "name": "verify_analysis",
        "message": "Verify the analysis results with OpenSees",
        "expected_tools": ["high_fidelity_analysis"],
    },
    {
        "name": "abaqus_collapse",
        "message": "Run an Abaqus collapse simulation for a 3-bay 4-story building",
        "expected_tools": ["setup_collapse"],
    },
]

MOCK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "quick_analysis",
            "description": "2D frame merged pipeline: generate + analyze + select critical in ONE call",
            "parameters": {"type": "object", "properties": {
                "num_bays_x": {"type": "integer"},
                "num_stories": {"type": "integer"},
                "span_x_m": {"type": "number"},
                "story_height_m": {"type": "number"},
                "steel_grade": {"type": "string"},
            }},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_frame",
            "description": "Generate a parametric 2D frame",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_from_text",
            "description": "Generate frame from natural language description",
            "parameters": {"type": "object", "properties": {"description": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_demolition_action",
            "description": "Remove element(s) and trigger collapse animation",
            "parameters": {"type": "object", "properties": {
                "failed_elements": {"type": "array", "items": {"type": "integer"}},
                "structure": {"type": "object"},
            }},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_steel_frame",
            "description": "Generate a steel frame BIM model with IPE/HE-A/HE-B sections",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "high_fidelity_analysis",
            "description": "OpenSees high-precision 2D verification analysis",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "setup_collapse",
            "description": "End-to-end Abaqus FEM collapse simulation",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


async def test_prompt_variant(
    llm: LLMEngine,
    test_case: dict,
    system_prompt: str,
    label: str,
) -> dict:
    """Run a single test case with a given system prompt variant."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": test_case["message"]},
    ]

    start = time.time()
    response = await llm.chat(messages, tools=MOCK_TOOLS, tool_choice="auto")
    elapsed = time.time() - start

    tool_calls = response.get("tool_calls") or []
    tool_names = [tc["name"] for tc in tool_calls]

    expected = set(test_case["expected_tools"])
    actual = set(tool_names)
    hit = bool(expected & actual)

    return {
        "test": test_case["name"],
        "label": label,
        "expected": list(expected),
        "called": tool_names,
        "match": hit,
        "elapsed_s": round(elapsed, 2),
        "usage": response.get("usage", {}),
    }


async def main():
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL")
    model = os.getenv("TEST_MODEL", "deepseek-v4-flash")

    if not api_key:
        print("ERROR: Set OPENAI_API_KEY or DEEPSEEK_API_KEY env var")
        print("  e.g.: $env:OPENAI_API_KEY='sk-...'  (PowerShell)")
        return

    llm = LLMEngine(model=model, api_key=api_key, base_url=base_url)
    print(f"Model: {model}")
    print(f"Base URL: {base_url or 'default'}")
    print(f"Thinking: {llm.thinking_enabled}")
    print()

    variants = [
        ("FULL", SYSTEM_PROMPT),
        ("SMART", None),  # build_system_prompt per test case
        ("CORE_ONLY", CORE_PROMPT),
    ]

    all_results = []

    for tc in TEST_CASES:
        print(f"─ Test: {tc['name']} ─")
        print(f"  Message: {tc['message'][:80]}...")
        print(f"  Expected: {tc['expected_tools']}")

        for var_name, var_prompt in variants:
            prompt = var_prompt if var_prompt is not None else build_system_prompt(
                tc["message"], has_tools=True
            )
            prompt_tokens_est = len(prompt) // 4
            result = await test_prompt_variant(llm, tc, prompt, var_name)
            result["prompt_tokens_est"] = prompt_tokens_est
            all_results.append(result)

            status = "✓" if result["match"] else "✗"
            print(f"  {status} {var_name:12s} ({prompt_tokens_est:>5d} tok est) → {result['called']}  ({result['elapsed_s']}s)")

        print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for var_name in ["FULL", "SMART", "CORE_ONLY"]:
        var_results = [r for r in all_results if r["label"] == var_name]
        hits = sum(1 for r in var_results if r["match"])
        total_time = sum(r["elapsed_s"] for r in var_results)
        avg_tokens = sum(r["prompt_tokens_est"] for r in var_results) // len(var_results) if var_results else 0
        print(f"  {var_name:12s}: {hits}/{len(var_results)} correct  avg {total_time/len(var_results):.1f}s  avg ~{avg_tokens} prompt tok")
        for r in var_results:
            status = "✓" if r["match"] else "✗"
            print(f"    {status} {r['test']}: called {r['called']}")

    print()
    print(f"Model: {model} | Thinking: {llm.thinking_enabled}")
    print("If CORE_ONLY matches FULL accuracy, the tool catalogue can be safely removed.")


if __name__ == "__main__":
    asyncio.run(main())
