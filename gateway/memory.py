"""SessionMemory wraps mem0 for persistent conversation context."""

import logging
from typing import Any

from mem0 import Memory

logger = logging.getLogger(__name__)


class SessionMemory:
    """Manages persistent memory across conversation sessions using mem0.

    Stores key facts from conversations and retrieves relevant context
    for the current user query.
    """

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        try:
            self._memory = Memory()
        except Exception as e:
            logger.warning(f"mem0 init failed: {e}. Running without persistent memory.")
            self._memory = None

    def add(self, message: str, metadata: dict[str, Any] | None = None) -> None:
        """Store a message in memory."""
        if self._memory is None:
            return
        try:
            self._memory.add(message, user_id=self.user_id, metadata=metadata)
        except Exception as e:
            logger.warning(f"Failed to add memory: {e}")

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search for relevant memories based on the query."""
        if self._memory is None:
            return []
        try:
            results = self._memory.search(query, user_id=self.user_id, limit=limit)
            return results or []
        except Exception as e:
            logger.warning(f"Memory search failed: {e}")
            return []

    def get_memory_context(self, query: str) -> str:
        """Return a formatted context string for inclusion in the system prompt.

        Returns empty string if no relevant memories found.
        """
        results = self.search(query)
        if not results:
            return ""

        lines = ["## Relevant Context (from past conversations):"]
        for r in results[:3]:
            memory_text = r.get("memory", str(r))
            lines.append(f"- {memory_text}")

        return "\n".join(lines)
