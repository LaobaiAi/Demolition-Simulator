"""Stack Analysis CAIAO Server — thin wrapper over scripts/stack_quick_analysis.py.

Exposes the stack01 chimney (H=100m, concrete, self-weight collapse) one-shot
quick analysis as an LLM tool. All heavy logic lives in the script module
(run_stack_analysis, stable JSON schema v1 with per-criterion PASS/FAIL
acceptance on the accepted concrete_stack_run39 baseline); this server only
bridges stdio MCP calls to that function. The run is blocking and long
(5-15 min real solve; seconds for the no_solve dry run) — the gateway grants
it the long POLL_TOOL_TIMEOUT_S budget, and the function's own
GLOBAL_BUDGET_S=9000s watchdog caps the solve.
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

from stack_quick_analysis import run_stack_analysis  # noqa: E402

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


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="stack_run_analysis",
            description="Chemical-concrete chimney (instance stack01, H=100m) self-weight "
                        "collapse one-shot analysis on the accepted run-39 baseline. "
                        "BLOCKING call (5-15 min real solve; seconds with no_solve=true). "
                        "Returns stable JSON (schema v1) with per-criterion PASS/FAIL "
                        "acceptance. Instance guide: docs/instances/stack01/prompt.md",
            inputSchema={
                "type": "object",
                "properties": dict(_ARGS),
                "required": ["run_name"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info("Tool called: %s(%s)", name, arguments)
    try:
        if name != "stack_run_analysis":
            raise ValueError("Unknown tool: {}".format(name))
        kwargs = {}
        for key, spec in _ARGS.items():
            if key in arguments and arguments[key] is not None:
                kwargs[key] = arguments[key]
        run_name = kwargs.pop("run_name", "")
        if not run_name:
            raise ValueError("stack_run_analysis requires 'run_name'")
        result = await asyncio.get_running_loop().run_in_executor(
            None, lambda: run_stack_analysis(run_name, **kwargs)
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
