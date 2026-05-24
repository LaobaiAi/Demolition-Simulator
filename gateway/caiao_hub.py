"""CAIAOClientHub manages multiple CAIAO servers as stdio subprocesses."""

import asyncio
import json
import logging
import os
import platform
from typing import Any

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

logger = logging.getLogger(__name__)


def _get_parallel_limit(requested: int) -> int:
    """Resource-aware parallel limit: how many of *requested* tasks can run concurrently.

    Checks CPU count and current system load. Returns a safe concurrency number.
    Falls back to serial (1) when resources are tight.
    """
    cpu_count = os.cpu_count() or 4
    # Reserve 1 core for the system / gateway
    safe_max = max(1, cpu_count - 1)
    if requested <= 1:
        return 1
    # With plenty of cores, parallelize
    if cpu_count >= 8:
        return min(requested, safe_max)
    # With fewer cores, check actual load
    try:
        if platform.system() == "Linux" and os.path.exists("/proc/loadavg"):
            with open("/proc/loadavg") as f:
                load = float(f.read().split()[0])
            available = max(1, cpu_count - int(load))
            if available < 2:
                logger.info(f"High system load ({load:.1f}), falling back to serial execution")
                return 1
            return min(requested, available)
        elif platform.system() == "Windows":
            # On Windows, moderate approach: up to 2 parallel for <=4 cores
            return min(requested, 2) if cpu_count <= 4 else min(requested, safe_max)
    except Exception:
        pass
    # Conservative default: 2 parallel max on unknown config
    return min(requested, 2)


class CAIAOClientHub:
    """Manages lifecycle and routing for multiple CAIAO Server subprocesses.

    Servers with ``lazy=True`` are NOT started during ``start_all()`` —
    they are spawned on-demand when a tool from that server is first requested.
    This saves CPU/memory when running many solver servers that may not all
    be used in a single session.
    """

    def __init__(self, server_configs: list[dict[str, Any]]):
        """
        Args:
            server_configs: List of dicts with keys:
                - name: str, unique server name
                - command: str, executable (e.g. "python")
                - args: list[str], command arguments
                - cwd: str (optional), working directory for the process
                - lazy: bool (optional), if True, defer startup until first tool call
                - tools: list[str] (optional), tool names this server provides
                        (enables O(1) lazy-start lookup without scanning)
        """
        self._server_configs = server_configs
        self._sessions: dict[str, ClientSession] = {}
        self._contexts: dict[str, tuple[Any, ClientSession, Any, Any]] = {}
        self._tool_registry: dict[str, str] = {}  # tool_name -> server_name
        # Static tool→config lookup (built from config 'tools' field with _discover_tools_from_config)
        self._tool_to_config: dict[str, str] = self._build_tool_config_map()
        # Local (gateway-registered) tool handlers — no subprocess needed
        self._local_tools: dict[str, dict[str, Any]] = {}
        self._local_handlers: dict[str, Any] = {}
        # Semantic index for P2: fuzzy tool name matching (must init BEFORE composite handlers)
        self._semantic_index: list[dict[str, Any]] = []
        self._build_semantic_index()
        # Auto-register composite pipeline handlers from config
        self._build_composite_handlers()

    def register_local_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Any,
    ) -> None:
        """Register a tool handled locally in the gateway (no CAIAO Server subprocess).

        Args:
            name: Tool name exposed to LLM.
            description: Tool description for LLM tool selection.
            input_schema: JSON Schema for tool arguments.
            handler: Async callable taking (arguments: dict) -> dict result.
        """
        self._local_tools[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
            "server": "__gateway__",
        }
        self._local_handlers[name] = handler
        # Add to semantic index
        keywords = self._tokenize(f"{name} {description}")
        self._semantic_index.append({"name": name, "keywords": keywords, "description": description})
        logger.info(f"Registered local tool '{name}' (no subprocess)")

    def _build_composite_handlers(self) -> None:
        """Scan configs for composite pipelines and auto-register handlers.

        A composite config must have ``composite: True`` and a ``pipeline`` list.
        Each pipeline step specifies:
          - server: server name from SERVER_CONFIGS
          - tool: tool name to call
          - input_map: optional dict mapping context keys to tool arguments
          - map_result: optional variable name to store the result under

        The composite tool's input_schema is taken from the config's optional
        ``input_schema`` field, or defaults to a generic schema when not specified.
        """
        for config in self._server_configs:
            if config.get("composite"):
                self._register_composite_pipeline(config)

    def _register_composite_pipeline(self, config: dict[str, Any]) -> None:
        """Register a local handler that executes a declarative pipeline."""
        name = config["name"]
        pipeline = config.get("pipeline", [])
        description = config.get(
            "description",
            f"Pipeline: {' → '.join(s.get('tool', '?') for s in pipeline)}",
        )
        input_schema = config.get("input_schema", {
            "type": "object",
            "properties": {
                "num_bays_x": {"type": "integer", "description": "Number of bays in X direction"},
                "num_bays_y": {"type": "integer", "description": "Number of bays in Y direction"},
                "num_stories": {"type": "integer", "description": "Number of stories"},
                "span_x_m": {"type": "number", "description": "Span length in X in meters"},
                "story_height_m": {"type": "number", "description": "Story height in meters"},
            },
        })

        async def _pipeline_handler(arguments: dict) -> dict:
            import json as _json
            ctx = dict(arguments)
            for i, step in enumerate(pipeline):
                tool_name = step["tool"]
                input_map = step.get("input_map", {})
                result_var = step.get("map_result", tool_name)

                # Build tool args from context using input_map
                tool_args = {}
                if input_map:
                    for arg_key, ctx_key in input_map.items():
                        tool_args[arg_key] = ctx.get(ctx_key)
                else:
                    # Pass all original args if no input_map
                    tool_args = arguments

                # Call the tool
                logger.info(f"Pipeline step {i}: calling '{tool_name}' with args keys={list(tool_args.keys())}")
                raw = await self.call_tool(tool_name, tool_args)
                if "error" in raw:
                    logger.error(f"Pipeline step {i} failed: {raw['error']}")
                    return {
                        "status": "partial",
                        "error": f"Step {i} ({tool_name}): {raw['error']}",
                        "context": {k: str(v)[:500] for k, v in ctx.items()},
                    }

                # Parse result
                result_data = raw.get("result", "{}")
                if isinstance(result_data, str):
                    try:
                        result_data = _json.loads(result_data)
                    except _json.JSONDecodeError:
                        result_data = {"raw": result_data}
                ctx[result_var] = result_data

            # Return full context with status
            result = {"status": "complete"}
            for k, v in ctx.items():
                if k == "status":
                    # Don't let step results overwrite pipeline status
                    continue
                result[k] = v
            return result

        self.register_local_tool(name, description, input_schema, _pipeline_handler)
        logger.info(f"Composite pipeline registered: '{name}' ({len(pipeline)} steps)")

    def _build_tool_config_map(self) -> dict[str, str]:
        """Build static tool_name → server_name lookup from configs.

        Uses the explicit 'tools' list in config if provided, otherwise
        falls back to starting the server temporarily — but only when
        an unknown tool is actually requested.
        """
        mapping: dict[str, str] = {}
        for config in self._server_configs:
            tools_list = config.get("tools")
            if tools_list and isinstance(tools_list, list):
                for tool in tools_list:
                    mapping[tool] = config["name"]
        return mapping

    def _build_semantic_index(self) -> None:
        """Build a keyword-based semantic index from all known tool descriptions.

        Index sources: local tools, composite tools, static config tools.
        Server tools started later are added dynamically in _start_one.
        """
        _seen = set()
        # Local/composite tools
        for name, meta in self._local_tools.items():
            desc = meta.get("description", "")
            keywords = self._tokenize(f"{name} {desc}")
            self._semantic_index.append({"name": name, "keywords": keywords, "description": desc})
            _seen.add(name)
        # Static config tools
        for config in self._server_configs:
            for tool in config.get("tools", []):
                if tool not in _seen:
                    desc = config.get("description", "")
                    keywords = self._tokenize(f"{tool} {desc}")
                    self._semantic_index.append({"name": tool, "keywords": keywords, "description": desc})
                    _seen.add(tool)

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Split text into lowercase keyword tokens for similarity matching.

        Splits on whitespace, underscores, hyphens, and camelCase boundaries.
        """
        import re
        # Normalize underscores/hyphens to spaces, then insert spaces at camelCase boundaries
        normalized = text.replace("_", " ").replace("-", " ")
        normalized = re.sub(r'([a-z])([A-Z])', r'\1 \2', normalized)
        tokens = re.findall(r'[a-zA-Z0-9]+', normalized.lower())
        return {t for t in tokens if len(t) > 1}

    @staticmethod
    def _jaccard_similarity(a: set[str], b: set[str]) -> float:
        """Jaccard similarity between two keyword sets."""
        if not a or not b:
            return 0.0
        union = a | b
        if not union:
            return 0.0
        return len(a & b) / len(union)

    @staticmethod
    def _ngram_similarity(a: str, b: str, n: int = 3) -> float:
        """Character n-gram similarity between two strings.

        Used as tie-breaker when keyword Jaccard scores are equal.
        """
        if not a or not b:
            return 0.0
        a_ngrams = {a[i:i+n] for i in range(len(a) - n + 1)}
        b_ngrams = {b[i:i+n] for i in range(len(b) - n + 1)}
        if not a_ngrams or not b_ngrams:
            return 0.0
        intersection = a_ngrams & b_ngrams
        union = a_ngrams | b_ngrams
        return len(intersection) / len(union)

    def _semantic_search(self, query: str, threshold: float = 0.20) -> dict[str, Any] | None:
        """Find the closest tool match by keyword overlap.

        Args:
            query: The tool name or description to match.
            threshold: Minimum similarity score (0-1) to accept a match.

        Returns:
            dict with 'name', 'score', 'description' or None if no match.
        """
        query_keywords = self._tokenize(query)
        if not query_keywords:
            return None

        best: dict[str, Any] | None = None
        best_score = 0.0
        best_name_score = 0.0
        best_ngram = 0.0
        for entry in self._semantic_index:
            score = self._jaccard_similarity(query_keywords, entry["keywords"])
            # Bonus for partial name match (query is a substring of tool name)
            name_score = 0.0
            if query.lower() in entry["name"].lower():
                name_score = 0.5
                score = max(score, name_score)
            # Also check reverse: tool name tokens in query
            for nt in self._tokenize(entry["name"]):
                if nt in query_keywords:
                    name_score = max(name_score, 0.3)

            # Tie-breaking: prefer higher name_score, then ngram similarity
            ngram = self._ngram_similarity(query.lower(), entry["name"].lower())
            if (score > best_score or
                (abs(score - best_score) < 0.01 and name_score > best_name_score) or
                (abs(score - best_score) < 0.01 and name_score == best_name_score and ngram > best_ngram)):
                best_score = score
                best_name_score = name_score
                best_ngram = ngram
                best = entry

        if best and best_score >= threshold:
            return {"name": best["name"], "score": round(best_score, 3), "description": best["description"]}
        return None

    async def start_all(self) -> None:
        """Spawn all *non-lazy* configured CAIAO servers and connect via stdio.

        Lazy servers (``lazy=True``) are skipped — they will be started on
        first use via :meth:`_ensure_server`.
        """
        for config in self._server_configs:
            if config.get("lazy", False):
                logger.info(
                    "Skipping lazy CAIAO server '%s' (will start on demand)",
                    config["name"],
                )
                continue
            if config.get("composite"):
                logger.info("Skipping composite pipeline '%s' (no subprocess)", config["name"])
                continue
            await self._start_one(config)

    async def _start_one(self, config: dict[str, Any]) -> None:
        """Start a single CAIAO server and register its tools."""
        name = config["name"]
        if name in self._sessions:
            return  # already running

        server_params = StdioServerParameters(
            command=config["command"],
            args=config["args"],
            cwd=config.get("cwd"),
        )
        logger.info(f"Starting CAIAO server '{name}': {config['command']} {' '.join(config['args'])}")

        cm = stdio_client(server_params)
        read, write = await cm.__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()

        self._sessions[name] = session
        self._contexts[name] = (cm, session, read, write)

        # Register tools from this server
        tools_result = await session.list_tools()
        for tool in tools_result.tools:
            self._tool_registry[tool.name] = name
            # Add to semantic index
            desc = getattr(tool, "description", "") or ""
            keywords = self._tokenize(f"{tool.name} {desc}")
            self._semantic_index.append({"name": tool.name, "keywords": keywords, "description": desc})

        logger.info(f"CAIAO server '{name}' ready with {len(tools_result.tools)} tools")

    async def _ensure_server(self, tool_name: str, config_hint: str | None = None) -> bool:
        """Ensure the server that owns *tool_name* is running (lazy start).

        Uses static tool→config map for O(1) lookup when the tool is known.
        Falls back to scanning configs when the tool isn't in the static map.

        Args:
            tool_name: The tool to find and start.
            config_hint: Optional explicit server config name to start.
        Returns True if the server is now available, False otherwise.
        """
        # Already running?
        server_name = self._tool_registry.get(tool_name)
        if server_name and server_name in self._sessions:
            return True

        # Fast path: use static tool→config map
        if config_hint:
            config = next((c for c in self._server_configs if c["name"] == config_hint), None)
            if config:
                try:
                    await self._start_one(config)
                except Exception as e:
                    logger.error(f"Failed to start server '{config_hint}': {e}")
                    return False
                return tool_name in self._tool_registry

        # Fast path: static map lookup
        config_name = self._tool_to_config.get(tool_name)
        if config_name:
            config = next((c for c in self._server_configs if c["name"] == config_name), None)
            if config:
                try:
                    await self._start_one(config)
                except Exception as e:
                    logger.error(f"Failed to start lazy server '{config_name}': {e}")
                    return False
                return tool_name in self._tool_registry

        # Fallback: scan all lazy configs (legacy)
        for config in self._server_configs:
            if not config.get("lazy", False):
                continue
            if server_name is not None and config["name"] != server_name:
                continue
            try:
                await self._start_one(config)
            except Exception as e:
                logger.error(f"Failed to start lazy server '{config['name']}': {e}")
                return False
            if tool_name in self._tool_registry:
                return True
        return False

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return all available tools from all running servers plus local handlers.

        Lazy servers that haven't been started yet are NOT listed until
        their first tool call triggers startup. Local tools are always listed.
        """
        tools = list(self._local_tools.values())
        for name, session in self._sessions.items():
            try:
                result = await session.list_tools()
                for tool in result.tools:
                    tools.append({
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
                        "server": name,
                    })
            except Exception:
                logger.warning(f"Failed to list tools from '{name}', skipping")
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Route a tool call — checks local handlers first, then CAIAO Servers.

        Local (gateway-registered) tools are handled without spawning a subprocess.
        Server tools will lazily start the owning server if needed.
        """
        # Local handler takes precedence
        handler = self._local_handlers.get(tool_name)
        if handler:
            logger.info(f"Local tool call: {tool_name}")
            try:
                result = await handler(arguments)
                return {"result": json.dumps(result) if not isinstance(result, str) else result}
            except Exception as e:
                logger.exception(f"Local tool '{tool_name}' failed")
                return {"error": str(e)}

        server_name = self._tool_registry.get(tool_name)
        if server_name is None:
            # Use static map for O(1) lookup before scanning
            config_hint = self._tool_to_config.get(tool_name)
            if not await self._ensure_server(tool_name, config_hint=config_hint):
                # P2: Semantic fallback — try fuzzy match before giving up
                semantic_match = self._semantic_search(tool_name)
                if semantic_match and semantic_match["name"] != tool_name:
                    logger.info(f"Semantic routing '{tool_name}' → '{semantic_match['name']}' (score={semantic_match['score']})")
                    # Recurse with matched name
                    logger.info(f"Arguments preserved: {list(arguments.keys())}")
                    return await self.call_tool(semantic_match["name"], arguments)
                suggestions = f" Did you mean '{semantic_match['name']}'?" if semantic_match else ""
                return {"error": f"Tool '{tool_name}' not found in any registered server.{suggestions}"}
            server_name = self._tool_registry.get(tool_name)

        session = self._sessions.get(server_name)
        if session is None:
            return {"error": f"Server '{server_name}' is not connected"}

        try:
            result = await session.call_tool(tool_name, arguments=arguments)
            # Extract text content from result
            if hasattr(result, "content") and result.content:
                texts = []
                for item in result.content:
                    if hasattr(item, "text"):
                        texts.append(item.text)
                    elif isinstance(item, dict) and "text" in item:
                        texts.append(item["text"])
                return {"result": texts[0] if len(texts) == 1 else texts}
            return {"result": str(result)}
        except Exception as e:
            logger.exception(f"Tool call '{tool_name}' failed")
            return {"error": str(e)}

    async def call_tools_parallel(
        self,
        tool_calls: list[tuple[str, dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Execute multiple tool calls concurrently with resource-aware parallelization.

        Args:
            tool_calls: List of (tool_name, arguments) tuples.

        Returns:
            List of result dicts in the same order as input.
        """
        if len(tool_calls) <= 1:
            results = []
            for tool_name, args in tool_calls:
                results.append(await self.call_tool(tool_name, args))
            return results

        limit = _get_parallel_limit(len(tool_calls))
        if limit >= len(tool_calls):
            # Full parallel
            async def _call(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
                return await self.call_tool(tool_name, args)
            tasks = [asyncio.create_task(_call(tn, a)) for tn, a in tool_calls]
            return await asyncio.gather(*tasks, return_exceptions=True)
        elif limit > 1:
            # Batched parallel (e.g. 3 calls, limit=2 → run in 2+1 batches)
            results: list[dict[str, Any]] = []
            for i in range(0, len(tool_calls), limit):
                batch = tool_calls[i:i + limit]
                async def _call_batch(tn: str, a: dict) -> dict:
                    return await self.call_tool(tn, a)
                tasks = [asyncio.create_task(_call_batch(tn, a)) for tn, a in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                results.extend([
                    r if isinstance(r, dict) else {"error": str(r)}
                    for r in batch_results
                ])
            return results
        else:
            # Serial fallback
            results = []
            for tool_name, args in tool_calls:
                results.append(await self.call_tool(tool_name, args))
            return results

    async def stop_all(self) -> None:
        """Close all sessions and terminate subprocesses."""
        for cm, session, read, write in self._contexts.values():
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass
        self._sessions.clear()
        self._contexts.clear()
        self._tool_registry.clear()
        logger.info("All CAIAO servers stopped")
