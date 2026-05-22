"""Demo Calculator MCP Server — basic arithmetic tools."""

import asyncio
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("demo_calculator")

app = Server("demo-calculator")

TOOLS = [
    Tool(
        name="add",
        description="Add two numbers together",
        inputSchema={
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"},
            },
            "required": ["a", "b"],
        },
    ),
    Tool(
        name="subtract",
        description="Subtract the second number from the first",
        inputSchema={
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number (minuend)"},
                "b": {"type": "number", "description": "Second number (subtrahend)"},
            },
            "required": ["a", "b"],
        },
    ),
    Tool(
        name="multiply",
        description="Multiply two numbers",
        inputSchema={
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First factor"},
                "b": {"type": "number", "description": "Second factor"},
            },
            "required": ["a", "b"],
        },
    ),
    Tool(
        name="divide",
        description="Divide the first number by the second",
        inputSchema={
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "Numerator"},
                "b": {"type": "number", "description": "Denominator (must not be zero)"},
            },
            "required": ["a", "b"],
        },
    ),
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    a = float(arguments.get("a", 0))
    b = float(arguments.get("b", 0))

    if name == "add":
        result = a + b
    elif name == "subtract":
        result = a - b
    elif name == "multiply":
        result = a * b
    elif name == "divide":
        if b == 0:
            return [TextContent(type="text", text="Error: Division by zero")]
        result = a / b
    else:
        return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]

    logger.info(f"{name}({a}, {b}) = {result}")
    return [TextContent(type="text", text=str(result))]


async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
