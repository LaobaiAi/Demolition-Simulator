import * as THREE from "three";

// ── Effect types ──────────────────────────────────────────────────────────
export type EffectKey3D = "cascade" | "explosion" | "dust" | "shake" | "buckling" | "fracture" | "flash" | "trail" | "bounce";

export const EFFECT_DEFS_3D: { key: EffectKey3D; label: string; desc: string; score: number; color: string }[] = [
  { key: "cascade", label: "Cascade", desc: "逐层倒塌", score: 25, color: "#22c55e" },
  { key: "explosion", label: "Debris", desc: "碎片飞散", score: 15, color: "#f97316" },
  { key: "dust", label: "Dust", desc: "烟尘扩散", score: 10, color: "#94a3b8" },
  { key: "shake", label: "Shake", desc: "视口抖动", score: 10, color: "#eab308" },
  { key: "buckling", label: "Buckling", desc: "梁弯折", score: 15, color: "#22d3ee" },
  { key: "fracture", label: "Fracture", desc: "断裂多段", score: 10, color: "#a855f7" },
  { key: "flash", label: "Flash", desc: "红色闪烁", score: 5, color: "#ef4444" },
  { key: "trail", label: "Trail", desc: "下落轨迹", score: 5, color: "#78716c" },
  { key: "bounce", label: "Bounce", desc: "地面弹跳", score: 5, color: "#f59e0b" },
];

export const COLLAPSE_DURATION = 8000;
export const GRAVITY = 28;
export const SECTION_COL = 0.24;
export const SECTION_BEAM = 0.18;
export const GROUND_Y = -0.8;
export const EXPLOSION_FORCE = 20;
export const DEBRIS_COUNT_PER_ELEM = 12;
export const DUST_COUNT_PER_ELEM = 3;

// ── Helpers ────────────────────────────────────────────────────────────────
export function seedRand(seed: number): number {
  const s = Math.sin(seed * 9301 + 49297) * 233280;
  return s - Math.floor(s);
}

export function stressColor(ratio: number): THREE.Color {
  if (ratio < 0.3) return new THREE.Color("#22c55e");
  if (ratio < 0.6) return new THREE.Color("#eab308");
  if (ratio < 0.85) return new THREE.Color("#f97316");
  return new THREE.Color("#ef4444");
}

export function buildBoxAlign(p1: THREE.Vector3, p2: THREE.Vector3, section: number, material: THREE.Material): THREE.Mesh {
  const dir = new THREE.Vector3().subVectors(p2, p1);
  const len = dir.length();
  const mid = new THREE.Vector3().addVectors(p1, p2).multiplyScalar(0.5);
  const geo = new THREE.BoxGeometry(section, section, len);
  const mesh = new THREE.Mesh(geo, material);
  mesh.position.copy(mid);
  const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), dir.normalize());
  mesh.setRotationFromQuaternion(q);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

// ── Three.js disposal helpers ────────────────────────────────────────────
export function disposeMesh(obj: THREE.Object3D) {
  if (obj instanceof THREE.Mesh) {
    obj.geometry?.dispose();
    if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
    else obj.material?.dispose();
  }
}

export function clearGroup(group: THREE.Group) {
  while (group.children.length) {
    const child = group.children[0];
    group.remove(child);
    disposeMesh(child);
  }
}

// ── Animation state types ──────────────────────────────────────────────────
export interface BodyState3D {
  mesh: THREE.Mesh;
  velocity: THREE.Vector3;
  angularVel: THREE.Vector3;
  delay: number;
  startTriggered: boolean;
  startTime: number;
  isColumn: boolean;
  groundY: number;
}
export interface DebrisItem3D {
  mesh: THREE.Mesh;
  velocity: THREE.Vector3;
  angularVel: THREE.Vector3;
  lifetime: number;
  active: boolean;
  delay: number;
  groundY: number;
}
export interface DustItem3D {
  mesh: THREE.Mesh;
  maxScale: number;
  lifetime: number;
  active: boolean;
  delay: number;
}
export interface FractureItem3D {
  mesh: THREE.Mesh;
  velocity: THREE.Vector3;
  angularVel: THREE.Vector3;
  lifetime: number;
  active: boolean;
  delay: number;
}
export interface AnimationState3D {
  active: boolean;
  startTime: number;
  bodies: Map<number, BodyState3D>;
  debris: DebrisItem3D[];
  dust: DustItem3D[];
  fractures: FractureItem3D[];
  collapseCount: number;
  firstBodyDelay: number;
}
