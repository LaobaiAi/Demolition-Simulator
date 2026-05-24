"""CAIAOClientHub manages multiple CAIAO servers as stdio subprocesses."""

import asyncio
import logging
from typing import Any

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

logger = logging.getLogger(__name__)


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
        """
        self._server_configs = server_configs
        self._sessions: dict[str, ClientSession] = {}
        self._contexts: dict[str, tuple[Any, ClientSession, Any, Any]] = {}
        self._tool_registry: dict[str, str] = {}  # tool_name -> server_name

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

        logger.info(f"CAIAO server '{name}' ready with {len(tools_result.tools)} tools")

    async def _ensure_server(self, tool_name: str) -> bool:
        """Ensure the server that owns *tool_name* is running (lazy start).

        Returns True if the server is now available, False otherwise.
        """
        # Find the config that registers this tool (we need to scan all configs)
        # First check if any running server already has this tool registered
        server_name = self._tool_registry.get(tool_name)
        if server_name and server_name in self._sessions:
            return True  # server already running

        # Maybe this tool belongs to a lazy server that hasn't been started yet
        # (The tool_registry is only populated for started servers, so fall back
        #  to scanning the configs and their tool lists.)
        for config in self._server_configs:
            if not config.get("lazy", False):
                continue
            if server_name is not None and config["name"] != server_name:
                continue
            # Try to start this lazy server
            try:
                await self._start_one(config)
            except Exception as e:
                logger.error(f"Failed to start lazy server '{config['name']}': {e}")
                return False

            # Check if the tool we want is now registered
            if tool_name in self._tool_registry:
                return True

        return False

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return all available tools from all running servers.

        Lazy servers that haven't been started yet are NOT listed until
        their first tool call triggers startup.
        """
        tools = []
        for name, session in self._sessions.items():
            result = await session.list_tools()
            for tool in result.tools:
                tools.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
                    "server": name,
                })
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Route a tool call to the correct server and return the result.

        Will lazily start a server if its tool is called for the first time.
        """
        server_name = self._tool_registry.get(tool_name)
        if server_name is None:
            # Not yet registered — try lazy-starting every config until found
            for config in self._server_configs:
                if config.get("lazy", False):
                    try:
                        await self._start_one(config)
                    except Exception:
                        continue
                    if tool_name in self._tool_registry:
                        server_name = self._tool_registry[tool_name]
                        break
            if server_name is None:
                return {"error": f"Tool '{tool_name}' not found in any registered server"}

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
