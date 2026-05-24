"""MCP Server Template — copy this to create a new solver.

Usage:
  cp -r mcp_servers/_template mcp_servers/my_solver
  # Edit server.py, add your tools
  # Register in gateway/main.py → SERVER_CONFIGS
"""

import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("my_solver")

server = Server("my-solver")


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="my_tool",
            description="What this tool does",
            inputSchema={
                "type": "object",
                "properties": {
                    "param1": {
                        "type": "string",
                        "description": "Description of param1",
                    },
                },
                "required": ["param1"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    logger.info(f"Tool called: {name}({arguments})")

    if name == "my_tool":
        param1 = arguments.get("param1", "")
        result = {"status": "ok", "result": f"processed: {param1}"}
    else:
        result = {"error": f"Unknown tool: {name}"}

    return [TextContent(type="text", text=json.dumps(result))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
