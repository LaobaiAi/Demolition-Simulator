"""Physics Server CAIAO Server — rigid body physics for demolition animation.

Provides physics simulation via Rapier (when available) or a kinematic fallback.
Manages scenes with structural elements as rigid bodies, supports demolition
actions (remove/explode/push), stepping, and state queries.
"""

import asyncio
import json
import logging
import uuid

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from rapier_core import PhysicsScene

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("physics_server")

server = Server("physics-server")

# In-memory scene store (bounded to prevent memory leak)
_scenes: dict[str, PhysicsScene] = {}
_MAX_SCENES = 20
_SCENE_CREATION_ORDER: list[str] = []

TOOLS = [
    Tool(
        name="init_physics_scene",
        description="Initialize a physics scene with structural elements as rigid bodies.",
        inputSchema={
            "type": "object",
            "properties": {
                "structure": {
                    "type": "object",
                    "description": "Structure definition with nodes and elements to seed the physics scene",
                    "properties": {
                        "nodes": {"type": "array"},
                        "elements": {"type": "array"},
                    },
                    "required": ["nodes", "elements"],
                },
                "gravity": {
                    "type": "number",
                    "description": "Gravitational acceleration in m/s^2 (default 9.81)",
                    "default": 9.81,
                },
            },
            "required": ["structure"],
        },
    ),
    Tool(
        name="apply_demolition_action",
        description="Apply demolition force or removal to specified elements in a physics scene.",
        inputSchema={
            "type": "object",
            "properties": {
                "scene_id": {
                    "type": "string",
                    "description": "Physics scene ID returned by init_physics_scene",
                },
                "element_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of element IDs to act upon",
                },
                "action_type": {
                    "type": "string",
                    "enum": ["remove", "explode", "push"],
                    "description": "Type of demolition action",
                },
                "force_vector": {
                    "type": "object",
                    "description": "Force vector for explode/push actions (optional, default {x:0, y:-5000, z:0})",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"},
                    },
                },
            },
            "required": ["scene_id", "element_ids", "action_type"],
        },
    ),
    Tool(
        name="step_physics",
        description="Step the physics simulation forward by a given time delta.",
        inputSchema={
            "type": "object",
            "properties": {
                "scene_id": {
                    "type": "string",
                    "description": "Physics scene ID",
                },
                "dt_seconds": {
                    "type": "number",
                    "description": "Time step in seconds",
                },
                "substeps": {
                    "type": "integer",
                    "description": "Number of sub-steps per frame (default 4)",
                    "default": 4,
                },
            },
            "required": ["scene_id", "dt_seconds"],
        },
    ),
    Tool(
        name="get_physics_state",
        description="Get current state (position, rotation, velocity) of all or specific bodies.",
        inputSchema={
            "type": "object",
            "properties": {
                "scene_id": {
                    "type": "string",
                    "description": "Physics scene ID",
                },
                "element_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional list of specific element IDs to query. Returns all if omitted.",
                },
            },
            "required": ["scene_id"],
        },
    ),
    Tool(
        name="reset_physics",
        description="Reset the physics scene to its initial state.",
        inputSchema={
            "type": "object",
            "properties": {
                "scene_id": {
                    "type": "string",
                    "description": "Physics scene ID to reset",
                },
            },
            "required": ["scene_id"],
        },
    ),
]


def _get_or_create_scene(scene_id: str, gravity: float = 9.81) -> PhysicsScene:
    """Return existing scene or create a new one (bounded to _MAX_SCENES)."""
    if scene_id not in _scenes:
        if len(_scenes) >= _MAX_SCENES:
            # Evict oldest scene
            oldest = _SCENE_CREATION_ORDER.pop(0)
            _scenes.pop(oldest, None)
            logger.info(f"Evicted scene '{oldest}' (max {_MAX_SCENES} reached)")
        _scenes[scene_id] = PhysicsScene(gravity=gravity)
        _SCENE_CREATION_ORDER.append(scene_id)
    return _scenes[scene_id]


def _structure_to_bodies(scene: PhysicsScene, structure: dict) -> int:
    """Convert structure nodes/elements into rigid bodies and return body count."""
    nodes = structure.get("nodes", [])
    elements = structure.get("elements", [])
    node_map = {n["id"]: n for n in nodes}
    count = 0

    for elem in elements:
        eid = elem["id"]
        n_i = node_map.get(elem.get("node_i", -1))
        n_j = node_map.get(elem.get("node_j", -1))
        if n_i is None or n_j is None:
            continue
        # Midpoint of element as body position
        pos = (
            (n_i.get("x", 0) + n_j.get("x", 0)) / 2.0,
            (n_i.get("y", 0) + n_j.get("y", 0)) / 2.0,
            (n_i.get("z", 0) + n_j.get("z", 0)) / 2.0 if "z" in n_i or "z" in n_j else 0.0,
        )
        # Estimate mass from element length
        dx = n_j.get("x", 0) - n_i.get("x", 0)
        dy = n_j.get("y", 0) - n_i.get("y", 0)
        dz = n_j.get("z", 0) - n_i.get("z", 0)
        length = (dx**2 + dy**2 + dz**2) ** 0.5
        mass = max(length * 100.0, 10.0)

        shape_type = "cylinder" if length > 1.0 else "box"
        scene.add_body(eid, position=pos, shape_type=shape_type, mass=mass)
        count += 1

    # If no elements, create at least one placeholder body
    if count == 0:
        scene.add_body(element_id=0, position=(0.0, 1.0, 0.0), mass=100.0)
        count = 1

    return count


def _handle_init_physics_scene(arguments: dict) -> dict:
    structure = arguments.get("structure", {})
    gravity = arguments.get("gravity", 9.81)

    scene_id = str(uuid.uuid4())[:8]
    scene = _get_or_create_scene(scene_id, gravity=gravity)
    body_count = _structure_to_bodies(scene, structure)

    return {
        "scene_id": scene_id,
        "body_count": body_count,
        "gravity": gravity,
        "status": "initialized",
    }


def _handle_apply_demolition_action(arguments: dict) -> dict:
    scene_id = arguments.get("scene_id", "")
    element_ids = arguments.get("element_ids", [])
    action_type = arguments.get("action_type", "remove")
    force_vector = arguments.get("force_vector", {})

    if scene_id not in _scenes:
        return {"error": f"Scene '{scene_id}' not found. Call init_physics_scene first."}
    if not element_ids:
        return {"error": "At least one element_id is required"}

    scene = _scenes[scene_id]

    fx = force_vector.get("x", 0.0)
    fy = force_vector.get("y", -5000.0)
    fz = force_vector.get("z", 0.0)

    affected = []
    for eid in element_ids:
        if action_type == "remove":
            scene.remove_body(eid)
            affected.append({"element_id": eid, "action": "removed"})
        elif action_type == "explode":
            scene.apply_force(eid, (fx * 2.0, fy * 2.0 - 2000.0, fz * 2.0))
            scene.remove_body(eid)
            affected.append({"element_id": eid, "action": "exploded", "force": (fx * 2.0, fy * 2.0 - 2000.0, fz * 2.0)})
        elif action_type == "push":
            scene.apply_force(eid, (fx, fy, fz))
            affected.append({"element_id": eid, "action": "pushed", "force": (fx, fy, fz)})

    body_states = scene.get_state()
    return {
        "status": "applied",
        "action_type": action_type,
        "affected_elements": affected,
        "body_states": body_states,
    }


def _handle_step_physics(arguments: dict) -> dict:
    scene_id = arguments.get("scene_id", "")
    dt = arguments.get("dt_seconds", 0.016)
    substeps = arguments.get("substeps", 4)

    if scene_id not in _scenes:
        return {"error": f"Scene '{scene_id}' not found"}

    scene = _scenes[scene_id]
    scene.step(dt, substeps=substeps)

    body_states = scene.get_state()
    # Compute simple kinetic energy diagnostic
    total_ke = 0.0
    for state in body_states.values():
        if isinstance(state, dict) and "velocity" in state:
            v = state["velocity"]
            total_ke += 0.5 * state.get("mass", 1.0) * (v[0]**2 + v[1]**2 + v[2]**2)

    return {
        "status": "stepped",
        "dt": dt,
        "substeps": substeps,
        "body_count": len(body_states),
        "total_kinetic_energy": round(total_ke, 4),
        "body_states": body_states,
    }


def _handle_get_physics_state(arguments: dict) -> dict:
    scene_id = arguments.get("scene_id", "")
    element_ids = arguments.get("element_ids")

    if scene_id not in _scenes:
        return {"error": f"Scene '{scene_id}' not found"}

    scene = _scenes[scene_id]

    if element_ids:
        states = {}
        for eid in element_ids:
            state = scene.get_state(eid)
            states[str(eid)] = state
        return {"body_states": states}
    else:
        return {"body_states": scene.get_state()}


def _handle_reset_physics(arguments: dict) -> dict:
    scene_id = arguments.get("scene_id", "")
    if scene_id not in _scenes:
        return {"error": f"Scene '{scene_id}' not found"}

    scene = _scenes[scene_id]
    scene.reset()
    return {
        "status": "reset",
        "scene_id": scene_id,
        "body_count": len(scene.get_state()),
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "init_physics_scene":
            result = await asyncio.to_thread(_handle_init_physics_scene, arguments)

        elif name == "apply_demolition_action":
            result = await asyncio.to_thread(_handle_apply_demolition_action, arguments)

        elif name == "step_physics":
            result = await asyncio.to_thread(_handle_step_physics, arguments)

        elif name == "get_physics_state":
            result = await asyncio.to_thread(_handle_get_physics_state, arguments)

        elif name == "reset_physics":
            result = await asyncio.to_thread(_handle_reset_physics, arguments)

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        if "error" in result:
            return [TextContent(type="text", text=json.dumps(result))]
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        logger.exception(f"Tool call failed: {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}) + "\n")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
