"""Tests for Gateway REST API endpoints."""

import sys
import os

import pytest
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# We import the app but tests will need the gateway running or we use TestClient
# For unit-level tests, we mock the hub


@pytest.mark.asyncio
async def test_health_endpoint():
    """Test /health returns ok. Requires gateway running."""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://localhost:8000/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
    except httpx.ConnectError:
        pytest.skip("Gateway not running")


@pytest.mark.asyncio
async def test_tools_endpoint():
    """Test /tools returns tool list. Requires gateway running."""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://localhost:8000/tools")
            assert resp.status_code == 200
            data = resp.json()
            assert "tools" in data
            assert isinstance(data["tools"], list)
            tool_names = [t["name"] for t in data["tools"]]
            assert "add" in tool_names
    except httpx.ConnectError:
        pytest.skip("Gateway not running")


@pytest.mark.asyncio
async def test_tools_call_add():
    """Test POST /tools/call with add. Requires gateway running."""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://localhost:8000/tools/call",
                json={"tool_name": "add", "arguments": {"a": 5, "b": 3}},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "error" not in data
            assert "8" in str(data.get("result", ""))
    except httpx.ConnectError:
        pytest.skip("Gateway not running")


@pytest.mark.asyncio
async def test_tools_call_unknown_tool():
    """Test POST /tools/call with unknown tool returns error. Requires gateway running."""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://localhost:8000/tools/call",
                json={"tool_name": "magic_spell", "arguments": {}},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "error" in data
    except httpx.ConnectError:
        pytest.skip("Gateway not running")


@pytest.mark.asyncio
async def test_tools_call_divide():
    """Test POST /tools/call with divide. Requires gateway running."""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://localhost:8000/tools/call",
                json={"tool_name": "divide", "arguments": {"a": 10, "b": 2}},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "error" not in data
            assert "5" in str(data.get("result", ""))
    except httpx.ConnectError:
        pytest.skip("Gateway not running")
