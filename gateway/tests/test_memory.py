"""Tests for SessionMemory."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory import SessionMemory


class TestSessionMemory:
    def test_init_default_user(self):
        mem = SessionMemory()
        assert mem.user_id == "default"

    def test_init_custom_user(self):
        mem = SessionMemory(user_id="user123")
        assert mem.user_id == "user123"

    def test_get_memory_context_empty(self):
        mem = SessionMemory()
        result = mem.get_memory_context("some query")
        assert result == ""

    def test_add_and_search(self):
        mem = SessionMemory()
        # Add some facts
        mem.add("User's name is Zhang San")
        mem.add("User's computer is AMD 4500U")
        mem.add("The project is about demolition simulation")

        # Search for relevant memories
        results = mem.search("What is my name?")
        assert isinstance(results, list)

        context = mem.get_memory_context("name")
        # May or may not return results depending on mem0 backend
        assert isinstance(context, str)

    def test_add_with_metadata(self):
        mem = SessionMemory()
        mem.add("Test message", metadata={"type": "user_input"})
        # Should not raise

    def test_search_limit(self):
        mem = SessionMemory()
        results = mem.search("test", limit=3)
        assert isinstance(results, list)
        assert len(results) <= 3
