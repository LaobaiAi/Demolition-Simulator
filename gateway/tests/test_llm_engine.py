"""Tests for LLMEngine."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_engine import LLMEngine, SYSTEM_PROMPT


class TestLLMEngine:
    def test_init_with_api_key(self):
        engine = LLMEngine(api_key="sk-test-123")
        assert engine.api_key == "sk-test-123"
        assert engine.model == "gpt-4o"

    def test_init_with_env_var(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-456")
        engine = LLMEngine()
        assert engine.api_key == "sk-env-456"

    def test_init_custom_model(self):
        engine = LLMEngine(model="gpt-4o-mini", api_key="sk-test")
        assert engine.model == "gpt-4o-mini"

    def test_format_tools_for_llm(self):
        engine = LLMEngine(api_key="sk-test")
        tools = [
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
            }
        ]
        result = engine.format_tools_for_llm(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "add"
        assert result[0]["function"]["description"] == "Add two numbers"
        assert "parameters" in result[0]["function"]

    @pytest.mark.asyncio
    async def test_chat_with_tool_calls(self):
        """Mock LLM returning a tool call."""
        engine = LLMEngine(api_key="sk-test")

        # Build mock response
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "add"
        mock_tool_call.function.arguments = '{"a": 3, "b": 4}'

        mock_message = MagicMock()
        mock_message.content = "Let me add those numbers."
        mock_message.tool_calls = [mock_tool_call]

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_create = AsyncMock(return_value=mock_response)
        engine.client.chat.completions.create = mock_create

        result = await engine.chat(
            messages=[{"role": "user", "content": "What is 3+4?"}],
            tools=engine.format_tools_for_llm([
                {"name": "add", "description": "", "input_schema": {}}
            ]),
        )

        assert result["content"] == "Let me add those numbers."
        assert result["tool_calls"] is not None
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["name"] == "add"
        assert result["tool_calls"][0]["arguments"] == {"a": 3, "b": 4}

    @pytest.mark.asyncio
    async def test_chat_text_only_response(self):
        """Mock LLM returning text only, no tool calls."""
        engine = LLMEngine(api_key="sk-test")

        mock_message = MagicMock()
        mock_message.content = "Hello! How can I help?"
        mock_message.tool_calls = None

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_create = AsyncMock(return_value=mock_response)
        engine.client.chat.completions.create = mock_create

        result = await engine.chat(
            messages=[{"role": "user", "content": "Hi!"}],
            tools=None,
        )

        assert result["content"] == "Hello! How can I help?"
        assert result["tool_calls"] is None

    @pytest.mark.asyncio
    async def test_chat_auth_error(self):
        """LLM authentication error returns friendly message."""
        engine = LLMEngine(api_key="sk-test")

        mock_create = AsyncMock(side_effect=Exception("401 Authentication failed"))
        engine.client.chat.completions.create = mock_create

        result = await engine.chat(messages=[{"role": "user", "content": "Hi"}])
        assert "Authentication failed" in result["content"]
        assert result["tool_calls"] is None

    @pytest.mark.asyncio
    async def test_chat_rate_limit_error(self):
        """Rate limit error returns friendly message."""
        engine = LLMEngine(api_key="sk-test")

        mock_create = AsyncMock(side_effect=Exception("429 Rate limit exceeded"))
        engine.client.chat.completions.create = mock_create

        result = await engine.chat(messages=[{"role": "user", "content": "Hi"}])
        assert "rate limit" in result["content"].lower()
        assert result["tool_calls"] is None

    def test_system_prompt_contains_key_directives(self):
        assert "engineering assistant" in SYSTEM_PROMPT.lower()
        assert "tool" in SYSTEM_PROMPT.lower()
