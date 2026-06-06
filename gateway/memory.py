"""SessionMemory wraps mem0 for persistent conversation context, with local fallback."""

import json
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_memory.json")


class SessionMemory:
    """Manages persistent memory across conversation sessions.

    Uses mem0 when available (needs OpenAI API key), falls back to local
    JSON file storage that works with any LLM provider.
    """

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self._memory = None
        self._local: list[dict[str, Any]] = []
        self._load_local()
        threading.Thread(target=self._try_init, daemon=True).start()

    def _try_init(self) -> None:
        try:
            from mem0 import Memory
            self._memory = Memory()
            logger.info("mem0 persistent memory initialized")
        except Exception as e:
            logger.warning(f"mem0 init failed: {e}. Using local file storage.")
            self._memory = None

    def _load_local(self) -> None:
        try:
            if os.path.exists(MEMORY_FILE):
                with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._local = data.get(self.user_id, [])
                    # Keep last 50 entries
                    if len(self._local) > 50:
                        self._local = self._local[-50:]
        except Exception:
            self._local = []

    def _save_local(self) -> None:
        try:
            all_data: dict[str, list[dict[str, Any]]] = {}
            if os.path.exists(MEMORY_FILE):
                with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                    all_data = json.load(f)
            all_data[self.user_id] = self._local
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save local memory: {e}")

    def reconfigure(self, api_key: str | None = None, base_url: str | None = None) -> None:
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
        if base_url:
            os.environ["OPENAI_BASE_URL"] = base_url
        # Init mem0 in background thread — avoid blocking the HTTP response
        threading.Thread(target=self._try_init, daemon=True).start()

    def add(self, message: str, metadata: dict[str, Any] | None = None) -> None:
        if self._memory is not None:
            try:
                self._memory.add(message, user_id=self.user_id, metadata=metadata)
            except Exception as e:
                logger.warning(f"Failed to add memory: {e}")

        # Always store locally
        self._local.append({
            "text": message,
            "ts": __import__("time").time(),
        })
        if len(self._local) > 50:
            self._local = self._local[-50:]
        self._save_local()

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if self._memory is not None:
            try:
                results = self._memory.search(query, user_id=self.user_id, limit=limit)
                if results:
                    return results
            except Exception as e:
                logger.warning(f"Memory search failed: {e}")

        # Local fallback: simple keyword overlap search
        query_words = set(query.lower().split())
        scored = []
        for entry in self._local:
            text = entry.get("text", "")
            text_words = set(text.lower().split())
            overlap = len(query_words & text_words)
            if overlap > 0:
                scored.append((overlap, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"memory": s[1]["text"]} for s in scored[:limit]]

    def get_memory_context(self, query: str) -> str:
        results = self.search(query)
        if not results:
            return ""

        lines = ["## Relevant Context (from past conversations):"]
        for r in results[:3]:
            memory_text = r.get("memory", str(r))
            lines.append(f"- {memory_text}")

        return "\n".join(lines)
