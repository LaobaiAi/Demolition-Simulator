"""Tests for MCPClientHub."""

import asyncio
import json
import sys
import os

import pytest

# Add gateway dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_hub import MCPClientHub


def make_server_config(name: str) -> dict:
    """Create a server config pointing to the demo_calculator server."""
    mcp_servers_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "mcp_servers",
    )
    return {
        "name": name,
        "command": sys.executable,
        "args": ["server.py"],
        "cwd": os.path.join(mcp_servers_dir, "demo_calculator"),
    }


@pytest.mark.asyncio
async def test_hub_start_and_stop():
    """Hub should start and stop without errors."""
    hub = MCPClientHub([make_server_config("test_calc")])
    await hub.start_all()
    assert "test_calc" in hub._sessions
    await hub.stop_all()
    assert len(hub._sessions) == 0


@pytest.mark.asyncio
async def test_hub_list_tools():
    """Hub should list tools from demo_calculator."""
    hub = MCPClientHub([make_server_config("test_calc")])
    await hub.start_all()
    tools = await hub.list_tools()
    await hub.stop_all()

    tool_names = [t["name"] for t in tools]
    assert "add" in tool_names
    assert "subtract" in tool_names
    assert "multiply" in tool_names
    assert "divide" in tool_names

    # Each tool should have schema and server info
    for tool in tools:
        assert "input_schema" in tool
        assert tool["server"] == "test_calc"


@pytest.mark.asyncio
async def test_hub_call_tool_add():
    """Hub should correctly call the add tool."""
    hub = MCPClientHub([make_server_config("test_calc")])
    await hub.start_all()
    result = await hub.call_tool("add", {"a": 3, "b": 4})
    await hub.stop_all()

    assert "error" not in result
    assert result.get("result") == "7.0"


@pytest.mark.asyncio
async def test_hub_call_tool_divide():
    """Hub should correctly call the divide tool."""
    hub = MCPClientHub([make_server_config("test_calc")])
    await hub.start_all()
    result = await hub.call_tool("divide", {"a": 10, "b": 3})
    await hub.stop_all()

    assert "error" not in result
    assert "3.333" in result.get("result", "")


@pytest.mark.asyncio
async def test_hub_call_tool_divide_by_zero():
    """Hub should handle division by zero gracefully."""
    hub = MCPClientHub([make_server_config("test_calc")])
    await hub.start_all()
    result = await hub.call_tool("divide", {"a": 10, "b": 0})
    await hub.stop_all()

    # Should return error text in result
    result_str = str(result.get("result", ""))
    assert "error" in result_str.lower() or "Error" in result_str or "zero" in result_str.lower()


@pytest.mark.asyncio
async def test_hub_call_unknown_tool():
    """Hub should return error for unknown tool."""
    hub = MCPClientHub([make_server_config("test_calc")])
    await hub.start_all()
    result = await hub.call_tool("nonexistent_tool", {"a": 1})
    await hub.stop_all()

    assert "error" in result


@pytest.mark.asyncio
async def test_hub_call_multiply():
    """Hub should correctly handle multiply."""
    hub = MCPClientHub([make_server_config("test_calc")])
    await hub.start_all()
    result = await hub.call_tool("multiply", {"a": 6, "b": 7})
    await hub.stop_all()

    assert "error" not in result
    assert result.get("result") == "42.0"
