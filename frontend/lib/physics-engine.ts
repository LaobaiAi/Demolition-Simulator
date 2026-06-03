import {
  World,
  Body,
  Box,
  Vec3,
  Plane,
  GSSolver,
  SplitSolver,
  NaiveBroadphase,
  Material,
  ContactMaterial,
} from "cannon-es";

export interface PhysicsElement {
  id: number;
  body: Body;
  halfExtents: { x: number; y: number; z: number };
}

export interface PhysicsState {
  positions: Map<number, { x: number; y: number; z: number }>;
  quaternions: Map<number, { x: number; y: number; z: number; w: number }>;
  velocities: Map<number, { x: number; y: number; z: number }>;
}

export class PhysicsEngine {
  world: World;
  private elements: Map<number, PhysicsElement> = new Map();
  private groundBody: Body;

  constructor() {
    const solver = new GSSolver();
    solver.iterations = 10;
    solver.tolerance = 0.001;

    const splitSolver = new SplitSolver(solver);

    this.world = new World();
    this.world.gravity = new Vec3(0, -9.82, 0);
    this.world.solver = splitSolver;
    this.world.broadphase = new NaiveBroadphase();
    this.world.allowSleep = true;

    const groundShape = new Plane();
    this.groundBody = new Body({ mass: 0, material: new Material("ground") });
    this.groundBody.addShape(groundShape);
    this.groundBody.quaternion.setFromAxisAngle(new Vec3(1, 0, 0), -Math.PI / 2);
    this.world.addBody(this.groundBody);

    const defaultMaterial = new Material("default");
    const contactMat = new ContactMaterial(defaultMaterial, defaultMaterial, {
      friction: 0.5,
      restitution: 0.2,
    });
    this.world.addContactMaterial(contactMat);
    this.world.defaultContactMaterial = contactMat;
  }

  addElement(
    elementId: number,
    position: { x: number; y: number; z: number },
    size: { x: number; y: number; z: number }
  ): Body {
    const halfExtents = { x: size.x / 2, y: size.y / 2, z: size.z / 2 };
    const shape = new Box(new Vec3(halfExtents.x, halfExtents.y, halfExtents.z));

    const body = new Body({
      mass: 1,
      shape,
      position: new Vec3(position.x, position.y, position.z),
      linearDamping: 0.05,
      angularDamping: 0.1,
    });

    this.world.addBody(body);
    this.elements.set(elementId, { id: elementId, body, halfExtents });
    return body;
  }

  removeElement(elementId: number): boolean {
    const entry = this.elements.get(elementId);
    if (!entry) return false;
    this.world.removeBody(entry.body);
    this.elements.delete(elementId);
    return true;
  }

  step(dt: number): void {
    this.world.step(1 / 60, dt, 3);
  }

  getState(): PhysicsState {
    const positions = new Map<number, { x: number; y: number; z: number }>();
    const quaternions = new Map<number, { x: number; y: number; z: number; w: number }>();
    const velocities = new Map<number, { x: number; y: number; z: number }>();

    for (const [id, entry] of this.elements) {
      const p = entry.body.position;
      const q = entry.body.quaternion;
      const v = entry.body.velocity;
      positions.set(id, { x: p.x, y: p.y, z: p.z });
      quaternions.set(id, { x: q.x, y: q.y, z: q.z, w: q.w });
      velocities.set(id, { x: v.x, y: v.y, z: v.z });
    }

    return { positions, quaternions, velocities };
  }

  clear(): void {
    for (const [, entry] of this.elements) {
      this.world.removeBody(entry.body);
    }
    this.elements.clear();
  }

  get elementCount(): number {
    return this.elements.size;
  }

  getElement(elementId: number): PhysicsElement | undefined {
    return this.elements.get(elementId);
  }
}
