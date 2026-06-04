"""Verification endpoints — compare fast analysis with high-fidelity solvers."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from caiao import get_parallel_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["verify"])


class VerifyRequest(BaseModel):
    fast_result: dict[str, Any]
    structure: dict[str, Any] | None = None


class MultiVerifyRequest(BaseModel):
    fast_result: dict[str, Any]
    structure: dict[str, Any]


SOLVER_ORDER: list[tuple[str, str]] = [
    ("high_fidelity_analysis", "OpenSees"),
    ("pynite_analysis", "PyNite"),
    ("fapp_analysis", "FAPP"),
]

DIMENSION_GROUPS: dict[str, set[str]] = {
    "2D": {"anastruct", "opensees"},
    "3D": {"pynite", "fapp"},
}

SOLVER_DIMENSION: dict[str, str] = {}
for dim, solvers in DIMENSION_GROUPS.items():
    for s in solvers:
        SOLVER_DIMENSION[s] = dim


def _safe_pct_diff(a: float, b: float) -> float:
    if abs(a) < 1e-9 and abs(b) < 1e-9:
        return 0.0
    denom = max(abs(a), abs(b))
    return abs(a - b) / denom * 100


def _median(vals: list[float]) -> float:
    if not vals:
        return 0
    s = sorted(vals)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _extract_solver_result(raw: dict | Any, results: dict, key: str) -> None:
    if isinstance(raw, dict) and "result" in raw:
        data = json.loads(raw["result"]) if isinstance(raw["result"], str) else raw["result"]
        if "error" in data:
            results[key] = {"error": str(data["error"])}
        else:
            results[key] = {
                "max_displacement": data.get("max_displacement", 0),
                "max_axial_force": data.get("max_axial_force", 0),
            }
    elif isinstance(raw, dict) and "error" in raw:
        results[key] = {"error": str(raw["error"])}
    else:
        results[key] = {"error": "Solver returned no result"}


async def _try_solver(hub, tool_name: str, structure: dict) -> dict | None:
    try:
        raw = await hub.call_tool(tool_name, {"structure": structure})
        if raw and "result" in raw:
            data = json.loads(raw["result"]) if isinstance(raw["result"], str) else raw["result"]
            if "error" not in data and data.get("max_displacement") is not None:
                return data
            logger.warning(f"{tool_name} returned error: {data.get('error', 'unknown')}")
        return None
    except Exception as e:
        logger.warning(f"{tool_name} call failed: {e}")
        return None


async def _run_solvers(hub, structure: dict, solver_order: list[tuple[str, str]]) -> tuple[dict | None, str | None]:
    if not hub or not structure:
        return None, None

    total = len(solver_order)
    limit = get_parallel_limit(total)

    if limit >= 2:
        logger.info(f"Running {total} solvers in parallel (limit={limit})")
        tasks = [_try_solver(hub, tn, structure) for tn, _ in solver_order]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, (_, solver_label) in enumerate(solver_order):
            result = all_results[i]
            if isinstance(result, dict) and result is not None:
                logger.info(f"{solver_label} returned valid result in parallel mode")
                return result, solver_label
        return None, None
    else:
        logger.info(f"Running {total} solvers serially (limited resources)")
        for tool_name, solver_label in solver_order:
            result = await _try_solver(hub, tool_name, structure)
            if result:
                return result, solver_label
        return None, None


@router.post("/verify")
async def verify_analysis(req: VerifyRequest, request: Request):
    hub = request.app.state.hub
    fast = req.fast_result
    max_disp_fast = fast.get("max_displacement", 0)
    max_axial_fast = fast.get("max_axial_force", 0)

    if hub and req.structure:
        hf_data, solver_label = await _run_solvers(hub, req.structure, SOLVER_ORDER)
        if hf_data and solver_label:
            max_disp_hf = hf_data.get("max_displacement", 0)
            max_axial_hf = hf_data.get("max_axial_force", 0)
            disp_diff = _safe_pct_diff(max_disp_fast, max_disp_hf)
            axial_diff = _safe_pct_diff(max_axial_fast, max_axial_hf)
            status = "verified" if max(disp_diff, axial_diff) < 5.0 else "warning"

            message = None
            if abs(max_disp_fast) < 1e-9 and abs(max_disp_hf) > 1e-9:
                message = (
                    "Fast analysis returned effectively zero displacement. This usually means the structure "
                    "was not correctly passed to the fast solver (anaStruct). The high-fidelity result is "
                    "likely correct. Consider re-running the analysis."
                )

            logger.info(f"{solver_label} comparison: disp_diff={disp_diff:.1f}%, axial_diff={axial_diff:.1f}%, status={status}")
            return {
                "status": status,
                "demo_mode": False,
                "solver": solver_label,
                "message": message,
                "comparison": {
                    "max_displacement": {"fast": round(max_disp_fast, 10), "high_fidelity": round(max_disp_hf, 10), "diff_percent": round(disp_diff, 2)},
                    "max_axial_force": {"fast": round(max_axial_fast, 2), "high_fidelity": round(max_axial_hf, 2), "diff_percent": round(axial_diff, 2)},
                },
            }

    return {
        "status": "unavailable",
        "demo_mode": True,
        "comparison": {
            "max_displacement": {"fast": round(max_disp_fast, 10), "high_fidelity": 0, "diff_percent": 0},
            "max_axial_force": {"fast": round(max_axial_fast, 2), "high_fidelity": 0, "diff_percent": 0},
        },
        "message": "No high-fidelity solver is available on this platform. Install OpenSees, PyNite, or FAPP for comparison verification.",
    }


@router.post("/verify/multi")
async def verify_multi(req: MultiVerifyRequest, request: Request):
    hub = request.app.state.hub
    results: dict[str, dict[str, Any]] = {}

    solver_map = [
        ("analyze_frame", "anastruct"),
        ("high_fidelity_analysis", "opensees"),
        ("pynite_analysis", "pynite"),
        ("fapp_analysis", "fapp"),
    ]

    total = len(solver_map)
    limit = get_parallel_limit(total)
    logger.info(f"Multi-verify: {total} solvers, parallel_limit={limit}")

    if limit >= 2:
        tool_calls = [(tn, {"structure": req.structure}) for tn, _ in solver_map]
        parallel_results = await hub.call_tools_parallel(tool_calls)
        for i, (_, key) in enumerate(solver_map):
            raw = parallel_results[i] if i < len(parallel_results) else {"error": "No result"}
            _extract_solver_result(raw, results, key)
    else:
        for tool_name, key in solver_map:
            try:
                raw = await hub.call_tool(tool_name, {"structure": req.structure})
                _extract_solver_result(raw, results, key)
            except Exception as e:
                logger.warning(f"Multi-verify: {key} failed: {e}")
                results[key] = {"error": str(e)}

    available_disp = [r["max_displacement"] for r in results.values() if "max_displacement" in r]
    available_axial = [r["max_axial_force"] for r in results.values() if "max_axial_force" in r]

    consensus_disp = _median(available_disp)
    consensus_axial = _median(available_axial)

    consensus_by_dimension: dict[str, dict[str, Any]] = {}
    for dim, members in DIMENSION_GROUPS.items():
        group_disp = [results[m]["max_displacement"] for m in members if m in results and "max_displacement" in results[m]]
        group_axial = [results[m]["max_axial_force"] for m in members if m in results and "max_axial_force" in results[m]]
        if group_disp:
            consensus_by_dimension[dim] = {
                "solver_count": len(group_disp),
                "solvers": [m for m in members if m in results and "max_displacement" in results[m]],
                "max_displacement": round(_median(group_disp), 10),
                "max_axial_force": round(_median(group_axial), 2),
            }

    dimension_discrepancy: dict[str, Any] = {"detected": False}
    if "2D" in consensus_by_dimension and "3D" in consensus_by_dimension:
        disp_2d = consensus_by_dimension["2D"]["max_displacement"]
        disp_3d = consensus_by_dimension["3D"]["max_displacement"]
        axial_2d = consensus_by_dimension["2D"]["max_axial_force"]
        axial_3d = consensus_by_dimension["3D"]["max_axial_force"]
        d_disp = _safe_pct_diff(disp_2d, disp_3d)
        d_axial = _safe_pct_diff(axial_2d, axial_3d)
        dimension_discrepancy = {
            "detected": d_disp > 5.0 or d_axial > 5.0,
            "displacement_diff_pct": round(d_disp, 2),
            "axial_diff_pct": round(d_axial, 2),
        }

    solver_count = len(available_disp)
    deviations = {}
    for name, r in results.items():
        if "max_displacement" not in r:
            continue
        group = SOLVER_DIMENSION.get(name)
        if group and group in consensus_by_dimension:
            ref_disp = consensus_by_dimension[group]["max_displacement"]
            ref_axial = consensus_by_dimension[group]["max_axial_force"]
        else:
            ref_disp = consensus_disp
            ref_axial = consensus_axial

        d_disp = _safe_pct_diff(r["max_displacement"], ref_disp)
        d_axial = _safe_pct_diff(r["max_axial_force"], ref_axial)
        deviations[name] = {
            "displacement_diff_pct": round(d_disp, 2),
            "axial_diff_pct": round(d_axial, 2),
            "is_outlier": d_disp > 5.0 or d_axial > 5.0,
            "group": group or "all",
        }

    return {
        "solvers": results,
        "consensus": {
            "max_displacement": round(consensus_disp, 10),
            "max_axial_force": round(consensus_axial, 2),
        },
        "consensus_by_dimension": consensus_by_dimension,
        "dimension_discrepancy": dimension_discrepancy,
        "solver_count": solver_count,
        "deviations": deviations,
    }
