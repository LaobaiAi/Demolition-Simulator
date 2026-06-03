/**
 * Particle effects system for concrete fracture, dust, and rebar visualization.
 * Used by FrameVisualization and FrameVisualization3D components.
 */

// ── Types ───────────────────────────────────────────────────────────────────────
export interface Particle {
  x: number; y: number; z: number;
  vx: number; vy: number; vz: number;
  life: number; maxLife: number;
  size: number;
  color: string;
  rotation: number;
  rotationSpeed: number;
  type: "dust" | "fragment" | "rebar" | "spark";
}

export interface ParticleEffect {
  id: string;
  particles: Particle[];
  active: boolean;
  elapsed: number;
  duration: number;
}

export interface FractureConfig {
  elementId: number;
  x: number; y: number; z: number;
  width: number; height: number; depth: number;
  material: "concrete" | "steel";
  count?: number;
}

// ── Constants ───────────────────────────────────────────────────────────────────
const GRAVITY = 9.82;
const FRAGMENT_COUNT_MIN = 4;
const FRAGMENT_COUNT_MAX = 12;
const DUST_COUNT_MIN = 8;
const DUST_COUNT_MAX = 20;
const REBAR_COUNT = 4;

// ── Color Palette ───────────────────────────────────────────────────────────────
const CONCRETE_COLORS = ["#8a8f9a", "#9ea3ae", "#7a7f8a", "#b0b5c0", "#6a6f7a"];
const DUST_COLORS = ["#c0c5d0", "#d0d5e0", "#b0b5c0", "#a0a5b0"];
const REBAR_COLORS = ["#8B4513", "#A0522D", "#6B3410", "#CD853F"];
const SPARK_COLORS = ["#ffd700", "#ffaa00", "#ff8800", "#ffff44"];

// ── Helpers ─────────────────────────────────────────────────────────────────────
function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

// ── Concrete Fracture ───────────────────────────────────────────────────────────

/** Generate concrete fragments from a fractured element using Voronoi-like splitting */
export function generateFragments(
  elementId: number,
  x: number, y: number, z: number,
  width: number, height: number, depth: number,
  count?: number
): Particle[] {
  const numFragments = count ?? Math.floor(rand(FRAGMENT_COUNT_MIN, FRAGMENT_COUNT_MAX));
  const fragments: Particle[] = [];

  for (let i = 0; i < numFragments; i++) {
    // Distribute fragments roughly within the element bounding box
    const fx = x + rand(-width / 2, width / 2);
    const fy = y + rand(-height / 2, height / 2);
    const fz = z + rand(-depth / 2, depth / 2);

    // Outward velocity from center
    const dx = fx - x;
    const dy = fy - y;
    const dz = fz - z;
    const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
    const speed = rand(1.5, 5.0);

    fragments.push({
      x: fx, y: fy, z: fz,
      vx: (dx / dist) * speed + rand(-0.5, 0.5),
      vy: (dy / dist) * speed + rand(1.0, 3.0),
      vz: (dz / dist) * speed + rand(-0.5, 0.5),
      life: 1.0,
      maxLife: rand(1.5, 3.5),
      size: rand(0.05, 0.25),
      color: pick(CONCRETE_COLORS),
      rotation: rand(0, Math.PI * 2),
      rotationSpeed: rand(-3, 3),
      type: "fragment",
    });
  }

  return fragments;
}

/** Generate dust cloud from concrete fracture */
export function generateDust(
  x: number, y: number, z: number,
  count?: number
): Particle[] {
  const numDust = count ?? Math.floor(rand(DUST_COUNT_MIN, DUST_COUNT_MAX));
  const dust: Particle[] = [];

  for (let i = 0; i < numDust; i++) {
    dust.push({
      x: x + rand(-0.5, 0.5),
      y: y + rand(-0.5, 0.5),
      z: z + rand(-0.5, 0.5),
      vx: rand(-1.5, 1.5),
      vy: rand(0.5, 2.5),
      vz: rand(-1.5, 1.5),
      life: 1.0,
      maxLife: rand(0.8, 2.0),
      size: rand(0.02, 0.08),
      color: pick(DUST_COLORS),
      rotation: 0,
      rotationSpeed: rand(-0.5, 0.5),
      type: "dust",
    });
  }

  return dust;
}

/** Generate rebar segments exposed after concrete fracture */
export function generateRebar(
  x: number, y: number, z: number,
  width: number, height: number, depth: number
): Particle[] {
  const rebars: Particle[] = [];

  // 4 longitudinal rebars at corners
  for (let i = 0; i < REBAR_COUNT; i++) {
    const angle = (i / REBAR_COUNT) * Math.PI * 2;
    const offset = Math.min(width, depth) * 0.3;
    const rx = x + Math.cos(angle) * offset;
    const rz = z + Math.sin(angle) * offset;

    rebars.push({
      x: rx, y: y, z: rz,
      vx: rand(-0.3, 0.3),
      vy: rand(-0.5, 0.5),
      vz: rand(-0.3, 0.3),
      life: 1.0,
      maxLife: rand(3.0, 6.0),
      size: rand(0.015, 0.025),
      color: pick(REBAR_COLORS),
      rotation: angle,
      rotationSpeed: rand(-1, 1),
      type: "rebar",
    });
  }

  return rebars;
}

/** Generate sparks from steel-on-steel impact */
export function generateSparks(
  x: number, y: number, z: number,
  count?: number
): Particle[] {
  const numSparks = count ?? Math.floor(rand(3, 8));
  const sparks: Particle[] = [];

  for (let i = 0; i < numSparks; i++) {
    const angle = rand(0, Math.PI * 2);
    const speed = rand(2, 6);

    sparks.push({
      x, y, z,
      vx: Math.cos(angle) * speed,
      vy: rand(1, 4),
      vz: Math.sin(angle) * speed,
      life: 1.0,
      maxLife: rand(0.3, 0.8),
      size: rand(0.01, 0.03),
      color: pick(SPARK_COLORS),
      rotation: 0,
      rotationSpeed: rand(-5, 5),
      type: "spark",
    });
  }

  return sparks;
}

// ── Full Effect Generator ───────────────────────────────────────────────────────

export interface FullEffectResult {
  fragments: Particle[];
  dust: Particle[];
  rebars: Particle[];
  sparks: Particle[];
}

/** Generate all particle effects for a fractured element */
export function generateFullFractureEffect(
  config: FractureConfig
): FullEffectResult {
  const { x, y, z, width, height, depth, material } = config;

  return {
    fragments: material === "concrete" ? generateFragments(config.elementId, x, y, z, width, height, depth) : [],
    dust: generateDust(x, y, z),
    rebars: material === "concrete" ? generateRebar(x, y, z, width, height, depth) : [],
    sparks: generateSparks(x, y, z),
  };
}

// ── Physics Update ──────────────────────────────────────────────────────────────

/** Update particle positions with simple Euler integration (gravity + damping) */
export function updateParticles(
  particles: Particle[],
  dt: number,
  groundY: number = 0
): Particle[] {
  const DAMPING = 0.98;
  const GROUND_BOUNCE = 0.3;
  const GROUND_FRICTION = 0.7;

  return particles
    .map((p) => {
      const life = p.life - dt / p.maxLife;
      if (life <= 0) return null;

      let vx = p.vx;
      let vy = p.vy - GRAVITY * dt;
      let vz = p.vz;
      const x = p.x + vx * dt;
      let y = p.y + vy * dt;
      const z = p.z + vz * dt;

      // Ground collision
      if (y < groundY) {
        y = groundY;
        vy = -vy * GROUND_BOUNCE;
        vx *= GROUND_FRICTION;
        vz *= GROUND_FRICTION;
        // Stop tiny bounces
        if (Math.abs(vy) < 0.3) vy = 0;
      }

      // Air damping
      vx *= DAMPING;
      vz *= DAMPING;

      return {
        ...p,
        x, y, z, vx, vy, vz, life,
        rotation: p.rotation + p.rotationSpeed * dt,
      };
    })
    .filter(Boolean) as Particle[];
}

// ── SVG Rendering Helpers ───────────────────────────────────────────────────────

/** Render particles as SVG elements (for SVG-mode fallback) */
export function renderParticlesToSVG(
  particles: Particle[],
  viewWidth: number,
  viewHeight: number,
  scale: number,
  offsetX: number,
  offsetY: number
): string {
  if (particles.length === 0) return "";

  const elements: string[] = [];

  for (const p of particles) {
    const sx = (p.x + offsetX) * scale + viewWidth / 2;
    const sy = (-p.y + offsetY) * scale + viewHeight / 2;
    const alpha = Math.max(0, p.life).toFixed(2);

    if (p.type === "dust") {
      elements.push(
        `<circle cx="${sx.toFixed(1)}" cy="${sy.toFixed(1)}" r="${(p.size * scale * 2).toFixed(1)}" fill="${p.color}" opacity="${alpha}" />`
      );
    } else if (p.type === "fragment") {
      elements.push(
        `<rect x="${(sx - p.size * scale).toFixed(1)}" y="${(sy - p.size * scale).toFixed(1)}" width="${(p.size * scale * 2).toFixed(1)}" height="${(p.size * scale * 2).toFixed(1)}" fill="${p.color}" opacity="${alpha}" transform="rotate(${(p.rotation * 180 / Math.PI).toFixed(0)},${sx.toFixed(1)},${sy.toFixed(1)})" />`
      );
    } else if (p.type === "rebar") {
      const barLen = 4;
      elements.push(
        `<line x1="${(sx - barLen * Math.cos(p.rotation)).toFixed(1)}" y1="${(sy - barLen * Math.sin(p.rotation)).toFixed(1)}" x2="${(sx + barLen * Math.cos(p.rotation)).toFixed(1)}" y2="${(sy + barLen * Math.sin(p.rotation)).toFixed(1)}" stroke="${p.color}" stroke-width="2" opacity="${alpha}" />`
      );
    } else if (p.type === "spark") {
      elements.push(
        `<circle cx="${sx.toFixed(1)}" cy="${sy.toFixed(1)}" r="1.5" fill="${p.color}" opacity="${alpha}" />`
      );
    }
  }

  return elements.join("\n");
}

// ── Effect Manager ──────────────────────────────────────────────────────────────

export class ParticleEffectManager {
  effects: Map<string, ParticleEffect> = new Map();
  allParticles: Particle[] = [];

  /** Create a full fracture effect at a position */
  createFracture(id: string, config: FractureConfig): void {
    const effect = generateFullFractureEffect(config);
    const all = [...effect.fragments, ...effect.dust, ...effect.rebars, ...effect.sparks];
    this.allParticles.push(...all);
    this.effects.set(id, {
      id,
      particles: all,
      active: true,
      elapsed: 0,
      duration: Math.max(...all.map(p => p.maxLife)),
    });
  }

  /** Update all active effects */
  update(dt: number): void {
    this.allParticles = updateParticles(this.allParticles, dt);

    for (const [id, effect] of this.effects) {
      effect.elapsed += dt;
      if (effect.elapsed >= effect.duration) {
        effect.active = false;
        this.effects.delete(id);
      }
    }

    // Remove dead particles
    this.allParticles = this.allParticles.filter(p => p.life > 0);
  }

  /** Clear all effects */
  clear(): void {
    this.effects.clear();
    this.allParticles = [];
  }

  /** Get current particles count */
  get count(): number {
    return this.allParticles.length;
  }
}
