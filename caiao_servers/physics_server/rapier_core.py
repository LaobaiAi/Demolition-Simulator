"""Physics engine core with graceful Rapier fallback.

Tries to import the `rapier` Python package (wraps the Rapier2D/3D Rust engine).
If unavailable, transparently falls back to the kinematic simulator.
"""

import logging
from typing import Any

from kinematic_fallback import KinematicSimulator

logger = logging.getLogger("physics_server.rapier_core")

try:
    import rapier as RAPIER
    _RAPIER_AVAILABLE = True
    logger.info("Rapier physics engine loaded")
except ImportError:
    _RAPIER_AVAILABLE = False
    logger.info("Rapier not installed, using kinematic fallback simulator")


class PhysicsScene:
    """Physics simulation scene backed by Rapier or kinematic fallback.

    Interface:
      - add_body(element_id, position, rotation, shape_type, mass)
      - apply_force(element_id, force_vector)
      - remove_body(element_id)
      - step(dt, substeps)
      - get_state(element_id=None)
      - reset()
    """

    def __init__(self, gravity: float = 9.81):
        self.gravity = gravity
        self._element_to_body: dict[int, int] = {}  # element_id -> rapier body handle
        self._body_to_element: dict[int, int] = {}  # rapier body handle -> element_id
        self._element_id_counter = 0

        if _RAPIER_AVAILABLE:
            self._world = RAPIER.World(gravity)
            self._bodies: dict[int, Any] = {}
            self._initial_positions: dict[int, tuple] = {}
        else:
            self._fallback = KinematicSimulator(gravity=gravity)

    def add_body(
        self,
        element_id: int,
        position: tuple[float, float, float] = (0.0, 0.0, 0.0),
        rotation: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
        shape_type: str = "box",
        mass: float = 1.0,
    ) -> int:
        if not _RAPIER_AVAILABLE:
            return self._fallback.add_body(element_id, position, rotation, shape_type, mass)

        # Build a rigid body desc
        if shape_type == "box":
            # Default 1x1x1 box
            collider = RAPIER.ColliderDesc.cuboid(0.5, 0.5, 0.5)
        elif shape_type == "cylinder":
            collider = RAPIER.ColliderDesc.cylinder(0.5, 0.5)
        elif shape_type == "sphere":
            collider = RAPIER.ColliderDesc.ball(0.5)
        else:
            collider = RAPIER.ColliderDesc.cuboid(0.5, 0.5, 0.5)

        body_desc = RAPIER.RigidBodyDesc.dynamic()
        body_desc.set_translation(*position)
        body_desc.set_rotation(*rotation)
        body_handle = self._world.create_rigid_body(body_desc)
        self._world.create_collider(collider, body_handle)

        self._bodies[body_handle] = {
            "element_id": element_id,
            "mass": mass,
            "shape_type": shape_type,
        }
        self._element_to_body[element_id] = body_handle
        self._body_to_element[body_handle] = element_id
        self._initial_positions[element_id] = (position, rotation)

        logger.debug(f"Rapier body {body_handle} for element {element_id}")
        return element_id

    def apply_force(self, element_id: int, force_vector: tuple[float, float, float]) -> None:
        if not _RAPIER_AVAILABLE:
            self._fallback.apply_force(element_id, force_vector)
            return
        body_handle = self._element_to_body.get(element_id)
        if body_handle is None:
            return
        body = self._world.get_rigid_body(body_handle)
        body.apply_force(force_vector, True)

    def remove_body(self, element_id: int) -> None:
        if not _RAPIER_AVAILABLE:
            self._fallback.remove_body(element_id)
            return
        body_handle = self._element_to_body.get(element_id)
        if body_handle is None:
            return
        try:
            self._world.remove_rigid_body(body_handle)
        except Exception as e:
            logger.warning(f"Failed to remove rigid body for element {element_id}: {e}")
        self._element_to_body.pop(element_id, None)
        self._body_to_element.pop(body_handle, None)
        self._bodies.pop(body_handle, None)
        logger.debug(f"Removed body for element {element_id}")

    def step(self, dt: float, substeps: int = 4) -> None:
        if not _RAPIER_AVAILABLE:
            self._fallback.step(dt, substeps)
            return
        self._world.step(dt)

    def get_state(self, element_id: int | None = None) -> dict:
        if not _RAPIER_AVAILABLE:
            return self._fallback.get_state(element_id)

        if element_id is not None:
            body_handle = self._element_to_body.get(element_id)
            if body_handle is None:
                return {"element_id": element_id, "error": "body not found"}
            body = self._world.get_rigid_body(body_handle)
            pos = body.translation()
            rot = body.rotation()
            vel = body.linvel()
            ang = body.angvel()
            return {
                "element_id": element_id,
                "position": [pos.x, pos.y, pos.z],
                "rotation": [rot.w, rot.x, rot.y, rot.z],
                "velocity": [vel.x, vel.y, vel.z],
                "angular_velocity": [ang.x, ang.y, ang.z],
                "active": body.is_enabled(),
            }

        result = {}
        for eid, body_handle in self._element_to_body.items():
            body = self._world.get_rigid_body(body_handle)
            pos = body.translation()
            rot = body.rotation()
            vel = body.linvel()
            ang = body.angvel()
            result[str(eid)] = {
                "element_id": eid,
                "position": [pos.x, pos.y, pos.z],
                "rotation": [rot.w, rot.x, rot.y, rot.z],
                "velocity": [vel.x, vel.y, vel.z],
                "angular_velocity": [ang.x, ang.y, ang.z],
                "active": body.is_enabled(),
            }
        return result

    def reset(self) -> None:
        if not _RAPIER_AVAILABLE:
            self._fallback.reset()
            return

        for eid, body_handle in list(self._element_to_body.items()):
            try:
                self._world.remove_rigid_body(body_handle)
            except Exception as e:
                logger.warning(f"Reset: failed to remove body {eid}: {e}")
        self._element_to_body.clear()
        self._body_to_element.clear()
        self._bodies.clear()

        # Re-add all bodies at initial positions
        for eid, (pos, rot) in self._initial_positions.items():
            self.add_body(eid, pos, rot)

        logger.info(f"Reset physics scene with {len(self._initial_positions)} bodies")
