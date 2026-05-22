"""Tests for demo_calculator MCP server."""

import pytest
from server import call_tool


@pytest.mark.asyncio
async def test_add():
    result = await call_tool("add", {"a": 2, "b": 3})
    assert result[0].text == "5.0"


@pytest.mark.asyncio
async def test_subtract():
    result = await call_tool("subtract", {"a": 10, "b": 3})
    assert result[0].text == "7.0"


@pytest.mark.asyncio
async def test_multiply():
    result = await call_tool("multiply", {"a": 4, "b": 2.5})
    assert result[0].text == "10.0"


@pytest.mark.asyncio
async def test_divide():
    result = await call_tool("divide", {"a": 10, "b": 4})
    assert result[0].text == "2.5"


@pytest.mark.asyncio
async def test_divide_by_zero():
    result = await call_tool("divide", {"a": 10, "b": 0})
    assert "Error" in result[0].text


@pytest.mark.asyncio
async def test_unknown_tool():
    result = await call_tool("unknown", {"a": 1, "b": 2})
    assert "Error" in result[0].text


@pytest.mark.asyncio
async def test_default_args():
    result = await call_tool("add", {})
    assert result[0].text == "0.0"


@pytest.mark.asyncio
async def test_negative_numbers():
    result = await call_tool("multiply", {"a": -5, "b": 3})
    assert result[0].text == "-15.0"


@pytest.mark.asyncio
async def test_subtract_negative_result():
    result = await call_tool("subtract", {"a": 3, "b": 10})
    assert result[0].text == "-7.0"
