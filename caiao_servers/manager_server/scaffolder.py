"""CAIAO Server scaffolder — creates new server directories from archetypes."""

import os
import sys
import logging
from datetime import date
from typing import Any

from .archetypes import get_archetype, ARCHETYPES
from .manifest import write_manifest

logger = logging.getLogger(__name__)

_MCP_TEMPLATE = '''"""CAIAO Server: {server_name} — {description}"""

import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("{server_name}")

server = Server("{server_name}")


@server.list_tools()
async def list_tools():
    return [
{tools_list}
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    logger.info(f"Tool called: {{name}}({{arguments}})")

{tool_dispatch}

    return [TextContent(type="text", text=json.dumps(result))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
'''

_CLASS_TEMPLATE = '''"""CAIAO Server: {server_name} — {description}

CAIAO 原子 Server（类继承模式）
独立功能：{description}
"""

import sys
import json
import logging

_parent = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

logger = logging.getLogger(__name__)


class {class_name}:
    """{description}"""

    server_name = "{server_name}"
    server_version = "0.1.0"
    server_category = "general"
    server_description = "{description}"
    server_dependencies = []

    def __init__(self):
        self._tools = {{}}
        self._discover_tools()

    def _discover_tools(self):
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if callable(attr) and hasattr(attr, "_caiao_tool"):
                meta = attr._caiao_tool
                self._tools[meta["name"]] = attr

    def list_tools(self) -> list:
        return [getattr(self, n)._caiao_tool for n in dir(self)
                if callable(getattr(self, n)) and hasattr(getattr(self, n), "_caiao_tool")]

    def call_tool(self, tool_name: str, input_data: dict) -> dict:
        func = self._tools.get(tool_name)
        if func is None:
            return {{"error": f"Tool '{{tool_name}}' not found."}}
        try:
            return func(input_data)
        except Exception as e:
            return {{"error": f"Tool '{{tool_name}}' execution failed: {{e}}"}}

    def get_metadata(self) -> dict:
        return {{
            "name": self.server_name,
            "version": self.server_version,
            "category": self.server_category,
            "description": self.server_description,
            "tools": [{{"name": t, "description": getattr(self, n)._caiao_tool.get("description", "")}}
                      for n in dir(self)
                      if callable(getattr(self, n)) and hasattr(getattr(self, n), "_caiao_tool")
                      for t in [getattr(self, n)._caiao_tool["name"]]],
            "dependencies": self.server_dependencies,
            "compatibility": {{"caiao_spec": "1.0", "mcp": True}},
        }}

    def run_stdio_loop(self):
        import sys as _sys
        _sys.stderr.write(f"[{{self.server_name}}] CAIAO stdio loop started\\n")
        for line in _sys.stdin:
            line = line.strip()
            if not line:
                continue
            request = json.loads(line)
            method = request.get("method", "")
            req_id = request.get("id")
            if method == "list_tools":
                response = {{"id": req_id, "result": self.list_tools()}}
            elif method == "call_tool":
                params = request.get("params", {{}})
                tool_name = params.get("tool_name", "")
                input_data = params.get("input", {{}})
                result = self.call_tool(tool_name, input_data)
                response = {{"id": req_id, "result": result}}
            elif method == "get_metadata":
                response = {{"id": req_id, "result": self.get_metadata()}}
            else:
                response = {{"id": req_id, "error": f"Unknown method: {{method}}"}}
            print(json.dumps(response, ensure_ascii=False), flush=True)

{tool_methods}


if __name__ == "__main__":
    server = {class_name}()
    if len(sys.argv) > 1:
        tool_name = sys.argv[1]
        input_json = sys.argv[2] if len(sys.argv) >= 3 else "{{}}"
        result = server.call_tool(tool_name, json.loads(input_json))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        server.run_stdio_loop()
'''

_MERGED_TEMPLATE = '''"""CAIAO Server: {server_name} — {description}

Merged CAIAO Server — composes multiple atomic servers by importing pure logic.
No runtime dependency on source servers.
"""

import sys
import os
import json
import logging

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("{server_name}")

# TODO: Import pure functions from source servers
# from source_server.core import function_name
# from source_server.server import _function_name

server = Server("{server_name}")


def _run_pipeline(args: dict) -> dict:
    """Core pipeline logic — import and compose source server functions here."""
    # TODO: Implement the pipeline
    return {{"status": "ok", "result": "pipeline placeholder"}}


@server.list_tools()
async def list_tools():
    return [
{tools_list}
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    logger.info(f"Tool called: {{name}}({{arguments}})")

    try:
        if name == "{main_tool}":
            result = _run_pipeline(arguments)
        else:
            result = {{"error": f"Unknown tool: {{name}}"}}
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({{"error": str(e)}}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
'''

_BRIDGE_TEMPLATE = '''"""CAIAO Server: {server_name} — {description}

Bridge CAIAO Server — thin proxy between CAIAO contract and external system.
Communicates with external system via TCP/HTTP/WebSocket.
"""

import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("{server_name}")

server = Server("{server_name}")

# TODO: Configure external system connection
# EXTERNAL_HOST = "localhost"
# EXTERNAL_PORT = 5000


async def _connect():
    """Connect to the external system."""
    # TODO: Implement connection logic
    pass


async def _send_command(cmd: dict) -> dict:
    """Send a command to the external system and return the response."""
    # TODO: Implement communication protocol
    return {{"status": "ok"}}


@server.list_tools()
async def list_tools():
    return [
{tools_list}
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    logger.info(f"Tool called: {{name}}({{arguments}})")

    try:
{tool_dispatch}
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({{"error": str(e)}}))]


async def main():
    await _connect()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
'''

_TOOL_TEMPLATE = '''        Tool(
            name="{name}",
            description="{description}",
            inputSchema={{
                "type": "object",
                "properties": {{
                    "param1": {{
                        "type": "string",
                        "description": "Parameter 1",
                    }},
                }},
                "required": ["param1"],
            }},
        ),'''

_DISPATCH_TEMPLATE = '''        if name == "{name}":
            result = {{"status": "ok", "result": f"processed: {{arguments.get('param1', '')}}"}}'''

_CLASS_TOOL_DECORATOR = '''    def _tool_decorator(name, description, input_schema):
        def decorator(func):
            func._caiao_tool = {
                "name": name,
                "description": description,
                "inputSchema": input_schema,
            }
            return func
        return decorator

'''

_CLASS_METHOD_TEMPLATE = '''    def {method_name}(self, input_data: dict) -> dict:
        """{description}"""
        param1 = input_data.get("param1", "")
        return {{"status": "ok", "result": f"processed: {{param1}}"}}

    {method_name} = _tool_decorator(
        name="{name}",
        description="{description}",
        input_schema={{
            "type": "object",
            "properties": {{
                "param1": {{"type": "string", "description": "Parameter 1"}},
            }},
            "required": ["param1"],
        }},
    )({method_name})
'''


def scaffold_server(
    name: str,
    kind: str,
    tools: list[dict[str, Any]],
    description: str = "",
    start_mode: str = "lazy",
    _servers_dir: str | None = None,
) -> dict[str, Any]:
    """Scaffold a new CAIAO server directory from an archetype.

    Args:
        name: Server name (also used as directory name)
        kind: Archetype kind (atomic-mcp, atomic-class, merged, composite, bridge)
        tools: List of {{name, description}} dicts for initial tools
        description: One-line server description
        start_mode: eager or lazy (ignored for composite)
        _servers_dir: Override servers directory (default: auto-detect)

    Returns:
        {{status, server_name, server_dir, files_created}}
    """
    archetype = get_archetype(kind)
    if archetype is None:
        return {"error": f"Unknown archetype kind: {kind}. Valid: {list(ARCHETYPES.keys())}"}

    if _servers_dir is None:
        _servers_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    server_dir = os.path.join(_servers_dir, name)
    if os.path.exists(server_dir):
        return {"error": f"Server directory already exists: {server_dir}"}

    files_created = []

    try:
        os.makedirs(server_dir, exist_ok=False)

        manifest = _build_manifest(name, kind, tools, description, start_mode)

        if kind == "composite":
            write_manifest(server_dir, manifest)
            files_created.append("caiao.yaml")
        else:
            python_code = _generate_python_code(name, kind, tools, description)
            server_py_path = os.path.join(server_dir, "server.py")
            with open(server_py_path, "w", encoding="utf-8") as f:
                f.write(python_code)
            files_created.append("server.py")

            write_manifest(server_dir, manifest)
            files_created.append("caiao.yaml")

        logger.info(f"Scaffolded {kind} server '{name}' at {server_dir} ({len(files_created)} files)")
        return {
            "status": "ok",
            "server_name": name,
            "server_dir": server_dir,
            "kind": kind,
            "files_created": files_created,
        }

    except Exception as e:
        logger.exception(f"Failed to scaffold server '{name}'")
        return {"error": str(e)}


def _build_manifest(name: str, kind: str, tools: list[dict], description: str, start_mode: str) -> dict:
    """Build a manifest dict for a new server."""
    manifest_tools = []
    for t in tools:
        manifest_tools.append({
            "name": t.get("name", "unnamed_tool"),
            "description": t.get("description", ""),
            "tags": t.get("tags", []),
        })

    data: dict[str, Any] = {
        "name": name,
        "version": "0.1.0",
        "kind": kind,
        "description": description,
        "status": "active",
        "since": date.today().isoformat(),
        "tools": manifest_tools,
        "capabilities": [],
        "dependencies": {"python": [], "system": []},
    }

    if kind != "composite":
        data["start_mode"] = start_mode
        data["command"] = {
            "python": "auto",
            "args": ["server.py"],
            "cwd": ".",
            "env": {},
        }
        data["health"] = {
            "timeout_ms": 5000,
            "restart_on_crash": False,
            "max_restarts": 3,
            "health_check_interval_s": 0,
        }

    if kind == "merged":
        data["imports"] = []

    if kind == "composite":
        data["pipeline"] = []

    return data


def _generate_python_code(name: str, kind: str, tools: list[dict], description: str) -> str:
    """Generate server.py content for the given archetype."""
    if kind == "atomic-class":
        return _generate_class_server(name, tools, description)
    elif kind == "merged":
        return _generate_merged_server(name, tools, description)
    elif kind == "bridge":
        return _generate_bridge_server(name, tools, description)
    else:
        return _generate_mcp_server(name, tools, description)


def _generate_mcp_server(name: str, tools: list[dict], description: str) -> str:
    tools_list = _format_tools_list(tools)
    tool_dispatch = _format_tool_dispatch(tools)
    return _MCP_TEMPLATE.format(
        server_name=name,
        description=description or "A CAIAO server",
        tools_list=tools_list,
        tool_dispatch=tool_dispatch,
    )


def _generate_class_server(name: str, tools: list[dict], description: str) -> str:
    class_name = _to_class_name(name)
    methods = []
    for t in tools:
        tname = t.get("name", "unnamed")
        methods.append(_CLASS_METHOD_TEMPLATE.format(
            method_name=tname,
            name=tname,
            description=t.get("description", ""),
        ))
    tool_methods = "\n".join(methods)
    return _CLASS_TEMPLATE.format(
        server_name=name,
        class_name=class_name,
        description=description or "A CAIAO server",
        tool_methods=tool_methods,
    )


def _generate_merged_server(name: str, tools: list[dict], description: str) -> str:
    tools_list = _format_tools_list(tools)
    main_tool = tools[0]["name"] if tools else "run_pipeline"
    return _MERGED_TEMPLATE.format(
        server_name=name,
        description=description or "A merged CAIAO server",
        tools_list=tools_list,
        main_tool=main_tool,
    )


def _generate_bridge_server(name: str, tools: list[dict], description: str) -> str:
    tools_list = _format_tools_list(tools)
    tool_dispatch = _format_tool_dispatch(tools)
    return _BRIDGE_TEMPLATE.format(
        server_name=name,
        description=description or "A bridge CAIAO server",
        tools_list=tools_list,
        tool_dispatch=tool_dispatch,
    )


def _format_tools_list(tools: list[dict]) -> str:
    if not tools:
        return _TOOL_TEMPLATE.format(name="placeholder", description="Placeholder tool — replace with real logic")
    lines = []
    for t in tools:
        tname = t.get("name", "unnamed")
        tdesc = t.get("description", "").replace('"', '\\"')
        lines.append(_TOOL_TEMPLATE.format(name=tname, description=tdesc))
    return "\n".join(lines)


def _format_tool_dispatch(tools: list[dict]) -> str:
    if not tools:
        return _DISPATCH_TEMPLATE.format(name="placeholder")
    lines = []
    for t in tools:
        tname = t.get("name", "unnamed")
        lines.append(_DISPATCH_TEMPLATE.format(name=tname))
    return "\n".join(lines)


def _to_class_name(name: str) -> str:
    parts = name.replace("-", "_").split("_")
    return "".join(p.capitalize() for p in parts)
