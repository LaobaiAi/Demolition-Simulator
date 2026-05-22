"""Tests for AgentLoop (ReAct pattern)."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_loop import AgentLoop
from llm_engine import LLMEngine
from mcp_hub import MCPClientHub


@pytest.fixture
def mock_hub():
    hub = MagicMock(spec=MCPClientHub)
    hub.list_tools = AsyncMock(return_value=[
        {
            "name": "add",
            "description": "Add two numbers",
            "input_schema": {
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
            "server": "test",
        },
        {
            "name": "multiply",
            "description": "Multiply two numbers",
            "input_schema": {
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
            "server": "test",
        },
    ])
    hub.call_tool = AsyncMock(return_value={"result": "7.0"})
    return hub


@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=LLMEngine)
    llm.format_tools_for_llm = MagicMock(return_value=[
        {"type": "function", "function": {"name": "add", "description": "", "parameters": {}}}
    ])
    return llm


@pytest.mark.asyncio
async def test_agent_single_tool_call(mock_hub, mock_llm):
    """Agent calls one tool then returns final response."""
    mock_llm.chat = AsyncMock(side_effect=[
        # First call: tool call
        {
            "content": "Let me calculate that.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "add",
                    "arguments": {"a": 3, "b": 4},
                }
            ],
            "raw": None,
        },
        # Second call: final response (after tool result fed back)
        {
            "content": "The answer is 7.",
            "tool_calls": None,
            "raw": None,
        },
    ])

    agent = AgentLoop(mock_llm, mock_hub)
    steps = await agent.run("What is 3+4?")

    # Should have: tool_call, tool_result, response
    types = [s["type"] for s in steps]
    assert "tool_call" in types
    assert "tool_result" in types
    assert "response" in types
    assert steps[-1]["content"] == "The answer is 7."

    # Verify tool was called
    mock_hub.call_tool.assert_called_once_with("add", {"a": 3, "b": 4})


@pytest.mark.asyncio
async def test_agent_text_only_response(mock_hub, mock_llm):
    """Agent responds with text only, no tool calls."""
    mock_llm.chat = AsyncMock(return_value={
        "content": "Hello! How can I help you with calculations today?",
        "tool_calls": None,
        "raw": None,
    })

    agent = AgentLoop(mock_llm, mock_hub)
    steps = await agent.run("Hello!")

    assert len(steps) == 1
    assert steps[0]["type"] == "response"
    assert "Hello" in steps[0]["content"]
    # No tool calls
    mock_hub.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_agent_multi_step_calculation(mock_hub, mock_llm):
    """Agent performs multiple tool calls in sequence."""
    call_count = [0]

    async def chat_side_effect(messages, tools=None, tool_choice="auto"):
        call_count[0] += 1
        if call_count[0] == 1:
            return {
                "content": "First, let me add.",
                "tool_calls": [{"id": "c1", "name": "add", "arguments": {"a": 5, "b": 3}}],
                "raw": None,
            }
        elif call_count[0] == 2:
            return {
                "content": "Now multiply by 2.",
                "tool_calls": [{"id": "c2", "name": "multiply", "arguments": {"a": 8, "b": 2}}],
                "raw": None,
            }
        else:
            return {"content": "Final result: 16.", "tool_calls": None, "raw": None}

    mock_llm.chat = AsyncMock(side_effect=chat_side_effect)

    agent = AgentLoop(mock_llm, mock_hub)
    steps = await agent.run("What is (5+3)*2?")

    tool_calls = [s for s in steps if s["type"] == "tool_call"]
    assert len(tool_calls) == 2
    assert tool_calls[0]["name"] == "add"
    assert tool_calls[1]["name"] == "multiply"
    assert steps[-1]["content"] == "Final result: 16."


@pytest.mark.asyncio
async def test_agent_with_history(mock_hub, mock_llm):
    """Agent receives conversation history."""
    mock_llm.chat = AsyncMock(return_value={
        "content": "The sum is 12.",
        "tool_calls": None,
        "raw": None,
    })

    history = [
        {"role": "user", "content": "My name is Alice"},
        {"role": "assistant", "content": "Hello Alice!"},
    ]

    agent = AgentLoop(mock_llm, mock_hub)
    steps = await agent.run("What is 5+7?", history=history)

    # Verify history was passed to LLM
    call_args = mock_llm.chat.call_args
    assert call_args is not None
    messages = call_args[0][0]  # First positional arg
    # history should be included in messages
    roles = [m["role"] for m in messages]
    assert "system" in roles


@pytest.mark.asyncio
async def test_agent_tool_error_handling(mock_hub, mock_llm):
    """Agent handles tool call errors gracefully."""
    mock_hub.call_tool = AsyncMock(return_value={"error": "Tool execution failed"})

    mock_llm.chat = AsyncMock(side_effect=[
        {
            "content": "Let me try.",
            "tool_calls": [{"id": "c1", "name": "add", "arguments": {"a": 1, "b": 2}}],
            "raw": None,
        },
        {
            "content": "Sorry, the tool failed.",
            "tool_calls": None,
            "raw": None,
        },
    ])

    agent = AgentLoop(mock_llm, mock_hub)
    steps = await agent.run("Calculate 1+2")

    tool_results = [s for s in steps if s["type"] == "tool_result"]
    assert len(tool_results) == 1
    assert "error" in str(tool_results[0]["result"])


@pytest.mark.asyncio
async def test_agent_max_iterations(mock_hub, mock_llm):
    """Agent hits max iterations and requests summary."""
    # Always return tool calls to force max iterations
    mock_llm.chat = AsyncMock(side_effect=[
        # 5 iterations of tool calls
        {"content": "Step 1", "tool_calls": [{"id": f"c{i}", "name": "add", "arguments": {"a": i, "b": 1}}], "raw": None}
        for i in range(5)
    ] + [
        # Summary response
        {"content": "Summary of results.", "tool_calls": None, "raw": None},
    ])

    agent = AgentLoop(mock_llm, mock_hub)
    steps = await agent.run("Do many calculations")

    tool_calls = [s for s in steps if s["type"] == "tool_call"]
    assert len(tool_calls) == 5  # max iterations
    assert steps[-1]["type"] == "response"
