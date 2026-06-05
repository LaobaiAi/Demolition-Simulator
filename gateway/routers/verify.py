"""Verification endpoints — compare fast analysis with high-fidelity solvers."""

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services.verify_service import (
    run_solvers,
    build_comparison,
    build_unavailable,
    run_multi_verify,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["verify"])


class VerifyRequest(BaseModel):
    fast_result: dict[str, Any]
    structure: dict[str, Any] | None = None


class MultiVerifyRequest(BaseModel):
    fast_result: dict[str, Any]
    structure: dict[str, Any]


@router.post("/verify")
async def verify_analysis(req: VerifyRequest, request: Request):
    hub = request.app.state.hub
    if hub and req.structure:
        hf_data, solver_label = await run_solvers(hub, req.structure)
        if hf_data and solver_label:
            return build_comparison(req.fast_result, hf_data, solver_label)
    return build_unavailable(req.fast_result)


@router.post("/verify/multi")
async def verify_multi(req: MultiVerifyRequest, request: Request):
    hub = request.app.state.hub
    return await run_multi_verify(hub, req.structure)
