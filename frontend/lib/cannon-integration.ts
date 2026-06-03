import * as THREE from "three";
import { PhysicsEngine} from "./physics-engine";

interface FrameNode3D {
  id: number;
  x: number;
  y: number;
  z?: number;
}

interface ElementPhysicsConfig {
  elementId: number;
  nodeI: FrameNode3D;
  nodeJ: FrameNode3D;
  sectionSize: number;
  mass?: number;
  initialVelocity?: { x: number; y: number; z: number };
}

function getElementDirectionAngle(
  nodeI: FrameNode3D,
  nodeJ: FrameNode3D
): { midpoint: THREE.Vector3; direction: THREE.Vector3; length: number } {
  const p1 = new THREE.Vector3(nodeI.x, nodeI.y, nodeI.z ?? 0);
  const p2 = new THREE.Vector3(nodeJ.x, nodeJ.y, nodeJ.z ?? 0);
  const midpoint = new THREE.Vector3().addVectors(p1, p2).multiplyScalar(0.5);
  const direction = new THREE.Vector3().subVectors(p2, p1).normalize();
  const length = p1.distanceTo(p2);
  return { midpoint, direction, length };
}

export function createPhysicsBody(
  engine: PhysicsEngine,
  config: ElementPhysicsConfig
) {
  const { elementId, nodeI, nodeJ, sectionSize, mass = 1, initialVelocity } = config;
  const { midpoint, length } = getElementDirectionAngle(nodeI, nodeJ);

  const body = engine.addElement(
    elementId,
    { x: midpoint.x, y: midpoint.y, z: midpoint.z },
    { x: sectionSize, y: sectionSize, z: length }
  );

  body.mass = mass;
  body.updateMassProperties();

  if (initialVelocity) {
    body.velocity.set(initialVelocity.x, initialVelocity.y, initialVelocity.z);
  }

  body.linearDamping = 0.05;
  body.angularDamping = 0.1;

  return body;
}

export function syncPhysicsToThree(
  engine: PhysicsEngine,
  meshMap: Map<number, THREE.Mesh>
): void {
  const state = engine.getState();

  for (const [id, pos] of state.positions) {
    const mesh = meshMap.get(id);
    if (!mesh) continue;
    mesh.position.set(pos.x, pos.y, pos.z);
  }

  for (const [id, quat] of state.quaternions) {
    const mesh = meshMap.get(id);
    if (!mesh) continue;
    mesh.quaternion.set(quat.x, quat.y, quat.z, quat.w);
  }
}

export interface PhysicsAnimationConfig {
  speed?: number;
  groundY?: number;
  cascadeDelay?: number;
  damping?: number;
  bounce?: number;
}

/**
 * Run one frame of physics simulation and sync results to Three.js meshes.
 * Returns true if any body is still above ground / moving.
 */
export function animateWithPhysics(
  engine: PhysicsEngine,
  meshMap: Map<number, THREE.Mesh>,
  dt: number,
  config?: PhysicsAnimationConfig
): boolean {
  const speed = config?.speed ?? 1;
  const groundY = config?.groundY ?? -0.8;
  const cascadeDelay = config?.cascadeDelay ?? 0;

  if (cascadeDelay > 0) {
    // Defer first step if cascade delay is active
    // (handled externally by staggering body activation)
  }

  if (dt <= 0 || !isFinite(dt)) return false;

  engine.step(dt * speed);
  syncPhysicsToThree(engine, meshMap);

  const state = engine.getState();
  let anyActive = false;

  for (const [, pos] of state.positions) {
    if (pos.y > groundY) {
      anyActive = true;
      break;
    }
  }

  if (!anyActive) {
    for (const [, vel] of state.velocities) {
      const speed_mag = Math.sqrt(vel.x * vel.x + vel.y * vel.y + vel.z * vel.z);
      if (speed_mag > 0.1) {
        anyActive = true;
        break;
      }
    }
  }

  return anyActive;
}
