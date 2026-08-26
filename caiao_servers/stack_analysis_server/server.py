"""Stack Analysis CAIAO Server — thin wrapper over scripts/stack_quick_analysis.py.

Exposes the stack01 chimney (H=100m, concrete, self-weight collapse) analysis
as LLM tools. All heavy logic lives in the script module (run_stack_analysis,
stable JSON schema v1 with per-criterion PASS/FAIL acceptance on the accepted
concrete_stack_run39 baseline); this server only bridges stdio MCP calls to
those functions. The interactive flow is ASYNCHRONOUS, mirroring the cooling
tower: stack_submit_analysis returns immediately (run_name +
estimated_duration_s), the solve runs in the background, stack_get_status
polls .sta progress and returns the full acceptance dict on completion, and
stack_stop_analysis aborts. stack_run_analysis stays as the blocking one-shot
entry for CLI/收口 use.
"""

import asyncio
import json
import logging
import os
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stack_analysis_server")

_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts",
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from stack_quick_analysis import (  # noqa: E402
    run_stack_analysis,
    stack_submit_analysis,
    stack_get_status,
    stack_stop_analysis,
)

server = Server("stack-analysis-server")

_ARGS = {
    "run_name": {
        "type": "string",
        "description": "New run directory name under abaqus_projects/ (letters/digits/"
                       "underscore only; must not exist — a run is final)",
    },
    "opening_height": {
        "type": "number",
        "description": "Opening band height in m (default 1.5, stack01 baseline; range [0.1, 30])",
    },
    "weak_ring_elev": {
        "type": "number",
        "description": "Weak ring band center elevation in m (default 33.5; range [2, 98])",
    },
    "weak_ring_cf": {
        "type": "number",
        "description": "Weak ring rebar thickness per face in m (default 0.0001; range [1e-5, 0.01])",
    },
    "sim_time": {
        "type": "number",
        "description": "Collapse step duration in s (default 7.6 display regime, ~4 min solve; "
                       "12.0 acceptance regime, ~7 min solve; range [1, 30])",
    },
    "output_interval": {
        "type": "number",
        "description": "Field output interval in s (default 0.15 dense frames; 0.6 routine)",
    },
    "n_theta": {
        "type": "integer",
        "description": "Circumferential mesh density (default 28; range [12, 96])",
    },
    "no_solve": {
        "type": "boolean",
        "description": "Dry run: copy + substitute + assemble/validate INP only, no solver (seconds)",
    },
    "solve_only": {
        "type": "boolean",
        "description": "Existing run: solve only (no metrics)",
    },
    "metrics_only": {
        "type": "boolean",
        "description": "Existing run: metrics only (ODB must exist)",
    },
}


_SUBMIT_ARGS = {k: v for k, v in _ARGS.items() if k not in ("solve_only", "metrics_only")}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="stack_run_analysis",
            description="Chemical-concrete chimney (instance stack01, H=100m) self-weight "
                        "collapse one-shot analysis on the accepted run-39 baseline. "
                        "BLOCKING call (5-15 min real solve; seconds with no_solve=true). "
                        "For interactive flows use stack_submit_analysis + "
                        "stack_get_status instead. Returns stable JSON (schema v1) with "
                        "per-criterion PASS/FAIL acceptance. "
                        "Instance guide: docs/instances/stack01/prompt.md",
            inputSchema={
                "type": "object",
                "properties": dict(_ARGS),
                "required": ["run_name"],
            },
        ),
        Tool(
            name="stack_submit_analysis",
            description="Submit the stack01 chimney (H=100m) self-weight collapse solve "
                        "ASYNCHRONOUSLY: builds the run from the accepted run-39 baseline, "
                        "launches the solver, and returns immediately with run_name + "
                        "status=submitted + estimated_duration_s + model info. DO NOT "
                        "wait — poll with stack_get_status(run_name, wait_seconds=120) "
                        "until status=completed (that poll returns the full schema-v1 "
                        "acceptance JSON); abort with stack_stop_analysis. Params: "
                        "run_name (new, letters/digits/underscore), sim_time (7.6 display "
                        "regime / 12.0 acceptance regime), opening_height, weak_ring_elev, "
                        "weak_ring_cf, output_interval, n_theta, no_solve (dry run). "
                        "Instance guide: docs/instances/stack01/prompt.md",
            inputSchema={
                "type": "object",
                "properties": dict(_SUBMIT_ARGS),
                "required": ["run_name"],
            },
        ),
        Tool(
            name="stack_get_status",
            description="Poll stack solve progress from the run's .sta file. Returns "
                        "status (submitted/running/completed/failed/terminated/not_found) "
                        "with progress percent and step/total time; wait_seconds up to "
                        "180 per call; the solve keeps running in the background between "
                        "calls. On status=completed the same call runs the metrics probe "
                        "and returns the full schema-v1 acceptance JSON (per-criterion "
                        "PASS/FAIL: deletion 15-17%, p95 55-66m, direction, penetration).",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_name": {
                        "type": "string",
                        "description": "Run name returned by stack_submit_analysis",
                    },
                    "wait_seconds": {
                        "type": "integer",
                        "description": "Block this call up to N seconds (max 180)",
                        "default": 60,
                    },
                },
                "required": ["run_name"],
            },
        ),
        Tool(
            name="stack_stop_analysis",
            description="Terminate a running stack solve: kill the wrapper/solver process "
                        "tree, sweep explicit.exe, remove the .lck. Use when the user "
                        "wants to abort a long solve. Verify afterwards with "
                        "stack_get_status (must be terminated/failed, not running).",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_name": {
                        "type": "string",
                        "description": "Run name returned by stack_submit_analysis",
                    },
                },
                "required": ["run_name"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info("Tool called: %s(%s)", name, arguments)
    try:
        if name == "stack_run_analysis":
            schema = _ARGS
            fn = run_stack_analysis
        elif name == "stack_submit_analysis":
            schema = _SUBMIT_ARGS
            fn = stack_submit_analysis
        elif name == "stack_get_status":
            run_name = str(arguments.get("run_name", ""))
            if not run_name:
                raise ValueError("stack_get_status requires 'run_name'")
            wait_seconds = arguments.get("wait_seconds", 60)
            result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: stack_get_status(run_name, wait_seconds=wait_seconds)
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
        elif name == "stack_stop_analysis":
            run_name = str(arguments.get("run_name", ""))
            if not run_name:
                raise ValueError("stack_stop_analysis requires 'run_name'")
            result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: stack_stop_analysis(run_name)
            )
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
        else:
            raise ValueError("Unknown tool: {}".format(name))
        kwargs = {}
        for key, spec in schema.items():
            if key in arguments and arguments[key] is not None:
                kwargs[key] = arguments[key]
        run_name = kwargs.pop("run_name", "")
        if not run_name:
            raise ValueError("{} requires 'run_name'".format(name))
        result = await asyncio.get_running_loop().run_in_executor(
            None, lambda: fn(run_name, **kwargs)
        )
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    except Exception as exc:
        logger.exception("Error handling tool %s", name)
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}, ensure_ascii=False))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
