"""Tests for Gateway REST API endpoints."""

import json
import os
import sys

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
            assert "generate_simple_frame" in tool_names
    except httpx.ConnectError:
        pytest.skip("Gateway not running")


@pytest.mark.asyncio
async def test_tools_call_generate_frame():
    """Test POST /tools/call with generate_simple_frame. Requires gateway running."""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://localhost:8000/tools/call",
                json={"tool_name": "generate_simple_frame", "arguments": {"spans": 2, "stories": 2}},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "error" not in data
            result = data.get("result", "")
            # result is a JSON string of the frame dict
            frame = json.loads(result) if isinstance(result, str) else result
            assert "nodes" in frame
            assert "elements" in frame
            assert len(frame["nodes"]) > 0
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
async def test_tools_call_analyze_frame():
    """Test POST /tools/call with analyze_frame. Requires gateway running."""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            # First generate a frame, then analyze it
            gen_resp = await client.post(
                "http://localhost:8000/tools/call",
                json={"tool_name": "generate_simple_frame", "arguments": {}},
            )
            gen_data = gen_resp.json()
            structure = json.loads(gen_data["result"]) if isinstance(gen_data["result"], str) else gen_data["result"]

            resp = await client.post(
                "http://localhost:8000/tools/call",
                json={"tool_name": "analyze_frame", "arguments": {"structure": structure}},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "error" not in data
            result = json.loads(data["result"]) if isinstance(data["result"], str) else data["result"]
            assert "max_displacement" in result
            assert "element_forces" in result
    except httpx.ConnectError:
        pytest.skip("Gateway not running")
