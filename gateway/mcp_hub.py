"""MCPClientHub manages multiple MCP servers as stdio subprocesses."""

import asyncio
import logging
from typing import Any

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

logger = logging.getLogger(__name__)


class MCPClientHub:
    """Manages lifecycle and routing for multiple MCP Server subprocesses."""

    def __init__(self, server_configs: list[dict[str, Any]]):
        """
        Args:
            server_configs: List of dicts with keys:
                - name: str, unique server name
                - command: str, executable (e.g. "python")
                - args: list[str], command arguments
                - cwd: str (optional), working directory for the process
        """
        self._server_configs = server_configs
        self._sessions: dict[str, ClientSession] = {}
        self._contexts: list[tuple[Any, ClientSession, Any, Any]] = []
        self._tool_registry: dict[str, str] = {}  # tool_name -> server_name

    async def start_all(self) -> None:
        """Spawn all configured MCP servers and connect via stdio."""
        for config in self._server_configs:
            name = config["name"]
            server_params = StdioServerParameters(
                command=config["command"],
                args=config["args"],
                cwd=config.get("cwd"),
            )
            logger.info(f"Starting MCP server '{name}': {config['command']} {' '.join(config['args'])}")

            cm = stdio_client(server_params)
            read, write = await cm.__aenter__()
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()

            self._sessions[name] = session
            self._contexts.append((cm, session, read, write))

            # Register tools from this server
            tools_result = await session.list_tools()
            for tool in tools_result.tools:
                self._tool_registry[tool.name] = name

            logger.info(f"MCP server '{name}' ready with {len(tools_result.tools)} tools")

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return all available tools from all servers."""
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
        """Route a tool call to the correct server and return the result."""
        server_name = self._tool_registry.get(tool_name)
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
        for cm, session, read, write in self._contexts:
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
        logger.info("All MCP servers stopped")
