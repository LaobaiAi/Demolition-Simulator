"""Kinematic simulator — simple Euler-integration fallback when Rapier is unavailable.

Mimics the PhysicsScene interface so it can be swapped in transparently.
No dependencies beyond numpy (optional — pure Python list math if numpy missing).
"""

import math
import logging

logger = logging.getLogger("physics_server.kinematic")

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False
    logger.info("numpy not available, using pure-python math in kinematic fallback")


def _vec_add(a, b):
    return [a[i] + b[i] for i in range(3)]


def _vec_mul(v, s):
    return [v[i] * s for i in range(3)]


def _vec_copy(v):
    return list(v)


class KinematicSimulator:
    """Simple kinematic rigid body simulator with Euler integration.

    Features:
    - Euler integration for position / velocity
    - Ground plane collision (y=0) with configurable restitution
    - No dependencies beyond optional numpy
    - State stored in a dict keyed by element_id
    """

    def __init__(self, gravity: float = 9.81):
        self.gravity = gravity
        self.bodies: dict[int, dict] = {}
        self.ground_restitution = 0.3
        self._initial_states: dict[int, dict] = {}

    def add_body(
        self,
        element_id: int,
        position: tuple[float, float, float] = (0.0, 0.0, 0.0),
        rotation: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
        shape_type: str = "box",
        mass: float = 1.0,
    ) -> int:
        body = {
            "element_id": element_id,
            "position": list(position),
            "rotation": list(rotation),
            "velocity": [0.0, 0.0, 0.0],
            "angular_velocity": [0.0, 0.0, 0.0],
            "mass": mass,
            "shape_type": shape_type,
            "active": True,
        }
        self.bodies[element_id] = body
        self._initial_states[element_id] = {
            "position": list(position),
            "rotation": list(rotation),
            "velocity": [0.0, 0.0, 0.0],
            "angular_velocity": [0.0, 0.0, 0.0],
        }
        logger.debug(f"Added body {element_id} at {position}")
        return element_id

    def apply_force(self, element_id: int, force_vector: tuple[float, float, float]) -> None:
        body = self.bodies.get(element_id)
        if body is None or not body["active"]:
            return
        if _HAS_NUMPY:
            acc = np.array(force_vector, dtype=float) / body["mass"]
            body["velocity"][0] += float(acc[0])
            body["velocity"][1] += float(acc[1])
            body["velocity"][2] += float(acc[2])
        else:
            for i in range(3):
                body["velocity"][i] += force_vector[i] / body["mass"]

    def remove_body(self, element_id: int) -> None:
        body = self.bodies.get(element_id)
        if body is not None:
            body["active"] = False

    def step(self, dt: float, substeps: int = 4) -> None:
        sub_dt = dt / max(substeps, 1)
        for _ in range(substeps):
            for body in self.bodies.values():
                if not body["active"]:
                    continue
                # Apply gravity (downward along y)
                body["velocity"][1] -= self.gravity * sub_dt
                # Euler integration
                body["position"] = _vec_add(body["position"], _vec_mul(body["velocity"], sub_dt))
                # Ground collision
                if body["position"][1] < 0.0:
                    body["position"][1] = 0.0
                    body["velocity"][1] = -body["velocity"][1] * self.ground_restitution
                    # Friction decay on horizontal velocity
                    body["velocity"][0] *= 0.95
                    body["velocity"][2] *= 0.95
                    # Stop tiny bounces
                    if abs(body["velocity"][1]) < 0.05:
                        body["velocity"][1] = 0.0

    def get_state(self, element_id: int | None = None) -> dict:
        if element_id is not None:
            body = self.bodies.get(element_id)
            if body is None:
                return {"element_id": element_id, "error": "body not found"}
            return {
                "element_id": body["element_id"],
                "position": _vec_copy(body["position"]),
                "rotation": _vec_copy(body["rotation"]),
                "velocity": _vec_copy(body["velocity"]),
                "angular_velocity": _vec_copy(body["angular_velocity"]),
                "mass": body.get("mass", 1.0),
                "active": body["active"],
            }
        return {
            str(eid): {
                "element_id": b["element_id"],
                "position": _vec_copy(b["position"]),
                "rotation": _vec_copy(b["rotation"]),
                "velocity": _vec_copy(b["velocity"]),
                "angular_velocity": _vec_copy(b["angular_velocity"]),
                "mass": b.get("mass", 1.0),
                "active": b["active"],
            }
            for eid, b in self.bodies.items()
        }

    def reset(self) -> None:
        for eid, state in self._initial_states.items():
            if eid in self.bodies:
                self.bodies[eid]["position"] = _vec_copy(state["position"])
                self.bodies[eid]["rotation"] = _vec_copy(state["rotation"])
                self.bodies[eid]["velocity"] = _vec_copy(state["velocity"])
                self.bodies[eid]["angular_velocity"] = _vec_copy(state["angular_velocity"])
                self.bodies[eid]["active"] = True
        logger.info(f"Reset {len(self._initial_states)} bodies")
