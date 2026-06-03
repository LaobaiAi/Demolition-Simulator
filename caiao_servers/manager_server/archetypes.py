"""CAIAO Server archetypes — template definitions for 5 server kinds.

Each archetype defines what files to create, what template to use,
and what the default manifest looks like.
"""

ARCHETYPES: dict[str, dict] = {
    "atomic-mcp": {
        "label": "Atomic MCP Server",
        "description": "Standalone stdio subprocess using the MCP SDK (mcp.server.Server). "
                       "The standard pattern used by most servers in this project.",
        "has_subprocess": True,
        "has_imports": False,
        "template_files": ["server.py", "caiao.yaml"],
        "default_start_mode": "lazy",
        "manifest_defaults": {
            "kind": "atomic-mcp",
        },
    },
    "atomic-class": {
        "label": "Atomic Class Server",
        "description": "Standalone server using CAIAOServer base class + @tool decorator. "
                       "Pattern from the Steel Frame Design distillation project. "
                       "Supports both in_process and subprocess modes.",
        "has_subprocess": True,
        "has_imports": False,
        "template_files": ["server.py", "caiao.yaml"],
        "default_start_mode": "lazy",
        "manifest_defaults": {
            "kind": "atomic-class",
        },
    },
    "merged": {
        "label": "Merged Server (Pipeline in one process)",
        "description": "Composes multiple atomic servers by importing their pure logic. "
                       "No runtime dependency on source servers — import-time only. "
                       "Reduces N subprocess hops to 1.",
        "has_subprocess": True,
        "has_imports": True,
        "template_files": ["server.py", "caiao.yaml"],
        "default_start_mode": "eager",
        "manifest_defaults": {
            "kind": "merged",
        },
    },
    "composite": {
        "label": "Composite Pipeline (declarative)",
        "description": "Declarative multi-step pipeline executed in the gateway process. "
                       "No subprocess. Defined entirely in caiao.yaml. "
                       "Use for simple sequential orchestration.",
        "has_subprocess": False,
        "has_imports": False,
        "template_files": ["caiao.yaml"],
        "default_start_mode": None,
        "manifest_defaults": {
            "kind": "composite",
        },
    },
    "bridge": {
        "label": "Bridge Server (external system)",
        "description": "Bridges to an external system via TCP/HTTP/WebSocket. "
                       "The CAIAO server is a thin proxy that translates between "
                       "the CAIAO contract and the external protocol.",
        "has_subprocess": True,
        "has_imports": False,
        "template_files": ["server.py", "caiao.yaml"],
        "default_start_mode": "lazy",
        "manifest_defaults": {
            "kind": "bridge",
        },
    },
}


def list_archetypes() -> list[dict]:
    """Return all available archetypes with metadata."""
    return [
        {
            "name": key,
            "label": val["label"],
            "description": val["description"],
            "has_subprocess": val["has_subprocess"],
            "has_imports": val["has_imports"],
            "template_files": val["template_files"],
        }
        for key, val in ARCHETYPES.items()
    ]


def get_archetype(kind: str) -> dict | None:
    """Get a single archetype definition by kind name."""
    return ARCHETYPES.get(kind)
