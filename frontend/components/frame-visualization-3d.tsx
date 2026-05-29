"use client";

import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Settings2, RotateCw, ZoomIn, ZoomOut, Move, Eye } from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────
interface FrameNode { id: number; x: number; y: number; z?: number; }
interface FrameElement { id: number; node_i: number; node_j: number; E?: number; A?: number; I?: number; Iy?: number; Iz?: number; J?: number; }
interface FrameLoad { node_id: number; Fx: number; Fy: number; Fz?: number; }
interface FrameSupport { node_id: number; type: string; }
interface FrameStructure { nodes: FrameNode[]; elements: FrameElement[]; loads: FrameLoad[]; supports: FrameSupport[]; }
interface NodeDisp { node_id: number; ux: number; uy: number; }
interface ElemForce { element_id: number; Nmax: number; Nmin: number; Mmax: number; Mmin: number; Qmax: number; Qmin: number; }

interface Props {
  structure: FrameStructure | null;
  displacements?: NodeDisp[] | null;
  criticalElementId?: number | null;
  failedElements?: number[];
  displayFailedElements?: number[];  // static display (no collapse animation)
  maxDisplacement?: number;
  elementForces?: ElemForce[];
  // Animation replay
  animationTrigger?: number;
  animatingElements?: number[];
  onAnimationComplete?: () => void;
}

// ── Constants ──────────────────────────────────────────────────────────────
type EffectKey = "cascade" | "explosion" | "dust" | "shake" | "buckling" | "fracture" | "flash" | "trail" | "bounce";
const EFFECT_DEFS: { key: EffectKey; label: string; desc: string; score: number; color: string }[] = [
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

const COLLAPSE_DURATION = 8000;
const GRAVITY = 28;
const SECTION_COL = 0.24;
const SECTION_BEAM = 0.18;
const GROUND_Y = -0.8;
const EXPLOSION_FORCE = 20;
const DEBRIS_COUNT_PER_ELEM = 12;
const DUST_COUNT_PER_ELEM = 3;

// ── Helpers ────────────────────────────────────────────────────────────────
function seedRand(seed: number): number {
  const s = Math.sin(seed * 9301 + 49297) * 233280;
  return s - Math.floor(s);
}
function stressColor(ratio: number): THREE.Color {
  if (ratio < 0.3) return new THREE.Color("#22c55e");
  if (ratio < 0.6) return new THREE.Color("#eab308");
  if (ratio < 0.85) return new THREE.Color("#f97316");
  return new THREE.Color("#ef4444");
}
function buildBoxAlign(p1: THREE.Vector3, p2: THREE.Vector3, section: number, material: THREE.Material): THREE.Mesh {
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
function disposeMesh(obj: THREE.Object3D) {
  if (obj instanceof THREE.Mesh) {
    obj.geometry?.dispose();
    if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
    else obj.material?.dispose();
  }
}

function clearGroup(group: THREE.Group) {
  while (group.children.length) {
    const child = group.children[0];
    group.remove(child);
    disposeMesh(child);
  }
}

// ── Animation state types ──────────────────────────────────────────────────
interface BodyState {
  mesh: THREE.Mesh;
  velocity: THREE.Vector3;
  angularVel: THREE.Vector3;
  delay: number;
  startTriggered: boolean;
  startTime: number;
  isColumn: boolean;
  groundY: number;
}
interface DebrisItem {
  mesh: THREE.Mesh;
  velocity: THREE.Vector3;
  angularVel: THREE.Vector3;
  lifetime: number;
  active: boolean;
  delay: number;
  groundY: number;
}
interface DustItem {
  mesh: THREE.Mesh;
  maxScale: number;
  lifetime: number;
  active: boolean;
  delay: number;
}
interface FractureItem {
  mesh: THREE.Mesh;
  velocity: THREE.Vector3;
  angularVel: THREE.Vector3;
  lifetime: number;
  active: boolean;
  delay: number;
}

interface AnimationState {
  active: boolean;
  startTime: number;
  bodies: Map<number, BodyState>;
  debris: DebrisItem[];
  dust: DustItem[];
  fractures: FractureItem[];
  collapseCount: number;
  firstBodyDelay: number;
}

// ── Component ──────────────────────────────────────────────────────────────
export function FrameVisualization3D({
  structure, displacements, criticalElementId, failedElements, displayFailedElements, maxDisplacement, elementForces,
  animationTrigger, animatingElements, onAnimationComplete,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);

  // Three.js core refs
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const frameGroupRef = useRef<THREE.Group>(null!);
  const analysisGroupRef = useRef<THREE.Group>(null!);
  const debrisGroupRef = useRef<THREE.Group>(null!);
  const dustGroupRef = useRef<THREE.Group>(null!);
  const fractureGroupRef = useRef<THREE.Group>(null!);
  const elementMeshMap = useRef<Map<number, THREE.Mesh>>(new Map());
  const nodeMeshMap = useRef<Map<number, THREE.Mesh>>(new Map());

  // Animation state (read continuously by render loop, written by collapse effect)
  const animStateRef = useRef<AnimationState>({
    active: false, startTime: 0, bodies: new Map(),
    debris: [], dust: [], fractures: [], collapseCount: 0, firstBodyDelay: 0,
  });
  const effectsRef = useRef<Record<string, boolean>>({});

  // Frame bounds
  const bounds = useMemo(() => {
    if (!structure?.nodes?.length) return null;
    const xs = structure.nodes.map(n => n.x), ys = structure.nodes.map(n => n.y);
    return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
  }, [structure]);

  // UI
  const [effectsOpen, setEffectsOpen] = useState(false);
  const [effects, setEffects] = useState<Record<string, boolean>>(() => {
    const r: Record<string, boolean> = {};
    EFFECT_DEFS.forEach(d => r[d.key] = true);
    return r;
  });
  const [animating, setAnimating] = useState(false);
  const [collapseProgress, setCollapseProgress] = useState(0);
  const [collapsedCount, setCollapsedCount] = useState(0);
  const [flashOpacity, setFlashOpacity] = useState(0);
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const e = effects;

  // Sync effects to ref for render loop
  useEffect(() => { effectsRef.current = effects; }, [effects]);

  const toggleEffect = (k: EffectKey) => setEffects(p => ({ ...p, [k]: !p[k] }));
  const activeScore = EFFECT_DEFS.filter(d => effects[d.key]).reduce((s, d) => s + d.score, 0);

  // ── 1. Init Three.js Scene (once on mount) ─────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (w === 0 || h === 0) return;

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(w, h, false);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    canvas.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // Scene
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0a0f1a");
    scene.fog = new THREE.Fog("#0a0f1a", 25, 90);
    sceneRef.current = scene;

    // Camera (default position, repositioned by frame rebuild on structure change)
    const camera = new THREE.PerspectiveCamera(50, w / h, 0.5, 200);
    camera.position.set(5, 5, 10);
    cameraRef.current = camera;

    // Controls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 3;
    controls.maxDistance = 40;
    controls.maxPolarAngle = Math.PI * 0.7;
    controls.target.set(0, 0, 0);
    controls.update();
    controlsRef.current = controls;

    // Lighting
    scene.add(new THREE.AmbientLight("#334155", 1.2));
    scene.add(new THREE.HemisphereLight("#22d3ee", "#0f172a", 0.4));
    const key = new THREE.DirectionalLight("#ffffff", 2.5);
    key.position.set(15, 20, 10);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.near = 0.5; key.shadow.camera.far = 80;
    key.shadow.camera.left = key.shadow.camera.bottom = -20;
    key.shadow.camera.right = key.shadow.camera.top = 20;
    key.shadow.bias = -0.0001; key.shadow.normalBias = 0.02;
    scene.add(key);
    const fill = new THREE.DirectionalLight("#22d3ee", 0.5);
    fill.position.set(-5, 2, -5);
    scene.add(fill);

    // Ground + grid
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(60, 60),
      new THREE.MeshStandardMaterial({ color: "#1e293b", roughness: 0.85, metalness: 0.2 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = GROUND_Y; ground.receiveShadow = true;
    scene.add(ground);
    const grid = new THREE.GridHelper(40, 30, "#334155", "#1e293b");
    grid.position.y = GROUND_Y + 0.01;
    scene.add(grid);

    // Groups
    const fg = new THREE.Group(); fg.name = "frame"; scene.add(fg); frameGroupRef.current = fg;
    const ag = new THREE.Group(); ag.name = "analysis"; scene.add(ag); analysisGroupRef.current = ag;
    const dg = new THREE.Group(); dg.name = "debris"; scene.add(dg); debrisGroupRef.current = dg;
    const dug = new THREE.Group(); dug.name = "dust"; scene.add(dug); dustGroupRef.current = dug;
    const frg = new THREE.Group(); frg.name = "fracture"; scene.add(frg); fractureGroupRef.current = frg;

    // ResizeObserver
    const ro = new ResizeObserver(() => {
      const c = canvasRef.current;
      const cam = cameraRef.current;
      const ren = rendererRef.current;
      if (!c || !cam || !ren) return;
      const cw = c.clientWidth, ch = c.clientHeight;
      if (cw === 0 || ch === 0) return;
      cam.aspect = cw / ch;
      cam.updateProjectionMatrix();
      ren.setSize(cw, ch, false);
    });
    ro.observe(canvas);

    // Animation loop
    let running = true;
    function animate() {
      if (!running) return;
      requestAnimationFrame(animate);
      controlsRef.current?.update();
      const ren = rendererRef.current;
      const sc = sceneRef.current;
      const cam = cameraRef.current;
      if (ren && sc && cam) ren.render(sc, cam);
    }
    animate();

    return () => {
      running = false;
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      if (canvas.contains(renderer.domElement)) canvas.removeChild(renderer.domElement);
      [scene, fg, ag, dg, dug, frg].forEach(g => g.traverse(obj => {
        if (obj instanceof THREE.Mesh) {
          obj.geometry?.dispose();
          if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
          else obj.material?.dispose();
        }
      }));
    };
  }, []);

  // ── 2. Build Frame (on data change) ────────────────────────
  useEffect(() => {
    const fg = frameGroupRef.current;
    const ag = analysisGroupRef.current;
    const cam = cameraRef.current;
    const ctrl = controlsRef.current;
    if (!fg || !ag || !structure?.nodes?.length || !bounds || !cam || !ctrl) return;

    // Clear previous frame and maps
    clearGroup(fg);
    clearGroup(ag);
    elementMeshMap.current.clear();
    nodeMeshMap.current.clear();

    // Position camera for new structure
    const cx = (bounds.minX + bounds.maxX) / 2;
    const cy = (bounds.minY + bounds.maxY) / 2;
    const extent = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY, 3);
    const dist = extent * 2.2;
    cam.position.set(cx + dist * 0.6, cy + dist * 0.5, dist);
    ctrl.target.set(cx, cy, 0);
    ctrl.update();

    // Build frame
    const nodeMap = new Map(structure.nodes.map(n => [n.id, n]));
    const dispMap = new Map<number, { ux: number; uy: number }>();
    displacements?.forEach(d => dispMap.set(d.node_id, { ux: d.ux, uy: d.uy }));
    const hasDeformation = !!(displacements?.length);
    const dispScale = (maxDisplacement && maxDisplacement > 0) ? ((bounds.maxX - bounds.minX || 1) * 0.15) / maxDisplacement : 100;
    const FY = 235e6;
    const stressMap = new Map<number, number>();
    elementForces?.forEach(ef => {
      const el = structure.elements.find(e => e.id === ef.element_id);
      if (el?.A && el.A > 0) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        stressMap.set(ef.element_id, Math.min(Math.max(Math.abs(ef.Nmax ?? 0), Math.abs(ef.Nmin ?? 0), Math.abs((ef as any).N ?? 0)) / (el.A * FY), 1));
      }
    });
    const hasStress = stressMap.size > 0;
    const matNormal = new THREE.MeshStandardMaterial({ color: "#22d3ee", roughness: 0.35, metalness: 0.7 });
    const matCrit = new THREE.MeshStandardMaterial({ color: "#f97316", roughness: 0.35, metalness: 0.7, emissive: "#f97316", emissiveIntensity: 0.3 });

    function n3d(n: FrameNode, d: boolean) {
      let px = n.x, py = n.y;
      if (d && hasDeformation) { const dd = dispMap.get(n.id); if (dd) { px += dd.ux * dispScale; py += dd.uy * dispScale; } }
      return new THREE.Vector3(px, py, n.z ?? 0);
    }

    const emap = elementMeshMap.current;
    const nmap = nodeMeshMap.current;

    for (const elem of structure.elements) {
      const ni = nodeMap.get(elem.node_i), nj = nodeMap.get(elem.node_j);
      if (!ni || !nj) continue;
      const isCol = Math.abs(ni.x - nj.x) < 0.01;
      const section = isCol ? SECTION_COL : SECTION_BEAM;
      let mat = matNormal.clone();
      if (elem.id === criticalElementId) mat = matCrit.clone();
      else if (hasStress) { const r = stressMap.get(elem.id); if (r !== undefined) { mat.color.copy(stressColor(r)); mat.emissive?.copy(stressColor(r)); mat.emissiveIntensity = 0.15; } }
      const p1 = n3d(ni, hasDeformation), p2 = n3d(nj, hasDeformation);
      const mesh = buildBoxAlign(p1, p2, section, mat);
      mesh.userData = { elementId: elem.id, isColumn: isCol };
      fg.add(mesh); emap.set(elem.id, mesh);
      if (hasDeformation) fg.add(buildBoxAlign(n3d(ni, false), n3d(nj, false), section * 0.8, new THREE.MeshBasicMaterial({ color: "#334155", transparent: true, opacity: 0.25, depthWrite: false })));
    }

    const matNode = new THREE.MeshStandardMaterial({ color: "#64748b", roughness: 0.3, metalness: 0.8 });
    const matTop = new THREE.MeshStandardMaterial({ color: "#f59e0b", roughness: 0.3, metalness: 0.8 });
    for (const n of structure.nodes) {
      const p = n3d(n, hasDeformation);
      const isTop = n.y === bounds.maxY && (structure.loads || []).some(l => l.node_id === n.id);
      const nodem = new THREE.Mesh(new THREE.SphereGeometry(isTop ? 0.2 : 0.15, 16, 16), (isTop ? matTop : matNode).clone());
      nodem.position.copy(p); fg.add(nodem); nmap.set(n.id, nodem);
      if (hasDeformation) {
        const ghostMat = new THREE.MeshBasicMaterial({ color: "#334155", transparent: true, opacity: 0.25, depthWrite: false });
        const gn = new THREE.Mesh(new THREE.SphereGeometry(isTop ? 0.14 : 0.1, 8, 8), ghostMat);
        gn.position.copy(n3d(n, false)); fg.add(gn);
        const d = dispMap.get(n.id);
        if (d && (Math.abs(d.ux * dispScale) > 0.01 || Math.abs(d.uy * dispScale) > 0.01)) {
          ag.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([n3d(n, false), p]), new THREE.LineBasicMaterial({ color: "#22d3ee", transparent: true, opacity: 0.4, depthTest: false })));
        }
      }
    }

    for (const sup of structure.supports || []) {
      const n = nodeMap.get(sup.node_id); if (!n) continue;
      const base = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.15, 0.5), new THREE.MeshStandardMaterial({ color: "#64748b", roughness: 0.5, metalness: 0.6 }));
      base.position.set(n3d(n, false).x, GROUND_Y + 0.075, 0); base.receiveShadow = true; base.castShadow = true; fg.add(base);
    }
    for (const load of structure.loads || []) {
      const n = nodeMap.get(load.node_id); if (!n) continue;
      const p = n3d(n, hasDeformation);
      const len = Math.min(1.5, Math.abs(load.Fy / 5000) * 0.8);
      const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, len, 8), new THREE.MeshStandardMaterial({ color: "#f59e0b", roughness: 0.4, metalness: 0.5, emissive: "#f59e0b", emissiveIntensity: 0.4 }));
      shaft.position.set(p.x, p.y - len / 2, 0); fg.add(shaft);
      const head = new THREE.Mesh(new THREE.ConeGeometry(0.12, 0.3, 8), new THREE.MeshStandardMaterial({ color: "#f59e0b", roughness: 0.4, metalness: 0.5, emissive: "#f59e0b", emissiveIntensity: 0.5 }));
      head.rotation.x = Math.PI; head.position.set(p.x, p.y - len, 0); fg.add(head);
    }
  }, [structure, displacements, criticalElementId, elementForces, maxDisplacement, bounds]);

  // ── 3. Effect Pools (on structure size change) ──────────────
  useEffect(() => {
    const dg = debrisGroupRef.current;
    const dug = dustGroupRef.current;
    const frg = fractureGroupRef.current;
    if (!dg || !dug || !frg || !structure?.elements?.length) return;

    clearGroup(dg);
    clearGroup(dug);
    clearGroup(frg);

    const total = structure.elements.length;
    const debrisPool: DebrisItem[] = [];
    const dustPool: DustItem[] = [];
    const fracturePool: FractureItem[] = [];

    for (let i = 0; i < total * DEBRIS_COUNT_PER_ELEM; i++) {
      const m = new THREE.Mesh(
        new THREE.BoxGeometry(0.04 + seedRand(i*7)*0.08, 0.03+seedRand(i*13)*0.06, 0.04+seedRand(i*17)*0.06),
        new THREE.MeshStandardMaterial({color:new THREE.Color().setHSL(0.08+seedRand(i*19)*0.08,0.3,0.2+seedRand(i*23)*0.3), roughness:0.7,metalness:0.4,transparent:true,opacity:0.9})
      );
      m.visible = false; dg.add(m);
      debrisPool.push({mesh:m, velocity:new THREE.Vector3(), angularVel:new THREE.Vector3(), lifetime:0, active:false, delay:0, groundY:GROUND_Y});
    }
    for (let i = 0; i < total * DUST_COUNT_PER_ELEM; i++) {
      const m = new THREE.Mesh(
        new THREE.SphereGeometry(1,8,8),
        new THREE.MeshBasicMaterial({color:"#94a3b8",transparent:true,opacity:0,depthWrite:false})
      );
      m.visible = false; dug.add(m);
      dustPool.push({mesh:m, maxScale:0, lifetime:0, active:false, delay:0});
    }
    for (let i = 0; i < Math.min(total * 4, 60); i++) {
      const m = new THREE.Mesh(
        new THREE.BoxGeometry(0.10+seedRand(i*23)*0.06, 0.06+seedRand(i*31)*0.04, 0.06+seedRand(i*37)*0.04),
        new THREE.MeshStandardMaterial({color:"#ef4444", roughness:0.6, metalness:0.3, emissive:"#ef4444", emissiveIntensity:0.2, transparent:true, opacity:0.85})
      );
      m.visible = false; frg.add(m);
      fracturePool.push({mesh:m, velocity:new THREE.Vector3(), angularVel:new THREE.Vector3(), lifetime:0, active:false, delay:0});
    }
    const anim = animStateRef.current;
    anim.debris = debrisPool; anim.dust = dustPool; anim.fractures = fracturePool;
    anim.bodies.clear(); anim.active = false; anim.collapseCount = 0;
    anim.startTime = 0; anim.firstBodyDelay = 0;
  }, [structure?.elements?.length]);

  // ── 4. Failed Elements Visibility ───────────────────────────
  useEffect(() => {
    const emap = elementMeshMap.current;
    if (emap.size === 0) return;

    if (failedElements?.length) {
      const failedSet = new Set(failedElements);
      for (const [id, mesh] of emap) {
        mesh.visible = !failedSet.has(id);
      }
    } else {
      const failedSet = new Set(displayFailedElements || []);
      for (const [id, mesh] of emap) {
        mesh.visible = !failedSet.has(id);
      }
    }
  }, [failedElements, displayFailedElements]);

  // ── 5. Collapse Animation ──────────────────────────────────
  useEffect(() => {
    const fg = frameGroupRef.current;
    const emap = elementMeshMap.current;
    const cam = cameraRef.current;
    const ctrl = controlsRef.current;
    const scene = sceneRef.current;
    const renderer = rendererRef.current;
    const anim = animStateRef.current;
    if (!fg || emap.size === 0 || !structure?.elements?.length || !bounds || !cam || !ctrl || !scene || !renderer) return;

    // Only animate when animatingElements is explicitly provided.
    // When undefined → no pending animation (completed or never started).
    const toAnimate = animatingElements;
    if (!toAnimate || toAnimate.length === 0) return;
    const targetSet = new Set(toAnimate);

    const nodeMap = new Map(structure.nodes.map(n => [n.id, n]));
    const cx = (bounds.minX + bounds.maxX) / 2;

    const failedData: { id: number; minY: number; isColumn: boolean }[] = [];
    for (const el of structure.elements) {
      if (!targetSet.has(el.id)) continue;
      const ni = nodeMap.get(el.node_i), nj = nodeMap.get(el.node_j);
      if (!ni || !nj) continue;
      failedData.push({ id: el.id, minY: Math.min(ni.y, nj.y), isColumn: Math.abs(ni.x - nj.x) < 0.01 });
    }
    if (failedData.length === 0) return;
    failedData.sort((a, b) => a.minY - b.minY);

    // Clone meshes and setup physics bodies
    for (let i = 0; i < failedData.length; i++) {
      const fd = failedData[i];
      const orig = emap.get(fd.id);
      if (!orig) continue;
      const clone = orig.clone();
      clone.material = (orig.material as THREE.Material).clone();
      if (clone.material instanceof THREE.MeshStandardMaterial) {
        clone.material.color.set("#ef4444");
        clone.material.emissive?.set("#ef4444");
        clone.material.emissiveIntensity = 0.5;
        clone.material.opacity = 1;
        clone.material.transparent = false;
        clone.material.depthWrite = true;
      }
      clone.userData._collapseClone = true;
      clone.visible = true;
      clone.castShadow = true;
      fg.add(clone);
      const dir = new THREE.Vector3(orig.position.x - cx, 0.3, (seedRand(fd.id + 50) - 0.5) * 0.6).normalize();
      const delay = (effectsRef.current.cascade && failedData.length > 1)
        ? (i / (failedData.length - 1)) * 1500
        : 50;
      anim.bodies.set(fd.id, {
        mesh: clone,
        velocity: new THREE.Vector3(dir.x * EXPLOSION_FORCE, -EXPLOSION_FORCE * 0.3, dir.z * EXPLOSION_FORCE * 0.5),
        angularVel: new THREE.Vector3((seedRand(fd.id * 3) - 0.5) * 5, (seedRand(fd.id * 5) - 0.5) * 6, (seedRand(fd.id * 7) - 0.5) * 5),
        delay,
        startTriggered: false,
        startTime: 0,
        isColumn: fd.isColumn,
        groundY: GROUND_Y + (fd.isColumn ? 0.1 : 0.05),
      });
    }
    anim.collapseCount = failedData.length;
    anim.firstBodyDelay = failedData.length > 0 && anim.bodies.size > 0
      ? Math.min(...[...anim.bodies.values()].map(b => b.delay))
      : 0;

    // Debris/dust/fracture setup
    const debrisPool = anim.debris;
    const dustPool = anim.dust;
    const fracturePool = anim.fractures;
    let di = 0, ddi = 0, fi = 0;
    for (const fd of failedData) {
      const orig = emap.get(fd.id);
      if (!orig) continue;
      const body = anim.bodies.get(fd.id);
      const bodyDelay = body?.delay ?? 0;
      for (let j = 0; j < 6 + Math.floor(seedRand(fd.id * 101) * 8) && di < debrisPool.length; j++, di++) {
        const p = debrisPool[di];
        const a = seedRand(fd.id * 200 + j * 7) * Math.PI * 2;
        const ph = seedRand(fd.id * 300 + j * 11) * Math.PI * 0.5;
        const sp = 3 + seedRand(fd.id * 400 + j * 13) * 8;
        p.active = true;
        p.lifetime = 1.5 + seedRand(fd.id * 500 + j * 17) * 1.5;
        p.delay = bodyDelay + 80 + seedRand(fd.id * 600 + j * 19) * 300;
        p.velocity.set(Math.cos(a) * Math.cos(ph) * sp, Math.sin(ph) * sp - 2, Math.sin(a) * Math.cos(ph) * sp * 0.6);
        p.angularVel.set((seedRand(fd.id * 700 + j * 23) - 0.5) * 10, (seedRand(fd.id * 800 + j * 29) - 0.5) * 10, (seedRand(fd.id * 900 + j * 31) - 0.5) * 10);
        p.mesh.position.copy(orig.position);
        p.mesh.visible = false;
      }
      for (let j = 0; j < 3 && ddi < dustPool.length; j++, ddi++) {
        const d = dustPool[ddi];
        d.active = true;
        d.lifetime = 1.5 + seedRand(fd.id * 1000 + j * 37) * 1;
        d.delay = bodyDelay + 400 + seedRand(fd.id * 1100 + j * 41) * 500;
        d.maxScale = 1.5 + seedRand(fd.id * 1200 + j * 43) * 3;
        d.mesh.position.set(orig.position.x + (seedRand(fd.id * 1300 + j * 47) - 0.5) * 2, GROUND_Y + 0.3, 0);
        d.mesh.scale.setScalar(0.01);
        d.mesh.visible = false;
      }
      if (!fd.isColumn) {
        for (let j = 0; j < 3 && fi < fracturePool.length; j++, fi++) {
          const fp = fracturePool[fi];
          fp.active = true;
          fp.lifetime = 2 + seedRand(fd.id * 1500 + j * 59) * 1;
          fp.delay = bodyDelay + 200 + j * 80;
          fp.velocity.set((seedRand(fd.id * 1600 + j * 61) - 0.5) * 6, -2 - seedRand(fd.id * 1700 + j * 67) * 4, (seedRand(fd.id * 1800 + j * 71) - 0.5) * 6);
          fp.angularVel.set((seedRand(fd.id * 1900 + j * 73) - 0.5) * 8, (seedRand(fd.id * 2000 + j * 79) - 0.5) * 8, (seedRand(fd.id * 2100 + j * 83) - 0.5) * 8);
          fp.mesh.position.copy(orig.position).add(new THREE.Vector3((j - 1) * 0.5, seedRand(fd.id * 2200 + j * 89) * 0.3, 0));
          fp.mesh.visible = false;
        }
      }
    }

    // Physics loop
    anim.startTime = performance.now();
    anim.active = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAnimating(true);
    setCollapsedCount(failedData.length);
    setCollapseProgress(0);
    setFlashOpacity(0);
    let lastPhysTime = 0;
    const preShakePos = cam.position.clone();

    function physicsLoop(timestamp: number) {
      if (!cam || !renderer || !scene) return;
      const a = animStateRef.current;
      if (!a.active) { renderer.render(scene, cam); return; }
      const dt = lastPhysTime ? Math.min(0.05, (timestamp - lastPhysTime) / 1000) : 0.016;
      lastPhysTime = timestamp;
      const elapsed = timestamp - a.startTime;
      const ef = effectsRef.current;

      cam.position.copy(preShakePos);
      // Pre-rumble
      const pr = ef.shake && elapsed > 80 && elapsed < a.firstBodyDelay && a.firstBodyDelay > 200
        ? Math.sin(elapsed * 0.12) * 0.08 * Math.min(elapsed / a.firstBodyDelay, 1)
        : 0;
      // Impact shake
      const ish = ef.shake && elapsed > a.firstBodyDelay + 400 && elapsed < a.firstBodyDelay + 1400
        ? Math.sin((elapsed - a.firstBodyDelay - 400) * 0.06) * 0.25 * (1 - (elapsed - a.firstBodyDelay - 400) / 1000)
        : 0;
      if (pr > 0.01 || ish > 0.01) {
        cam.position.x += Math.sin(elapsed * 0.04 + 1) * (pr + ish);
        cam.position.y += Math.sin(elapsed * 0.05 + 2) * (pr + ish);
      }

      for (const [, body] of a.bodies) {
        const lm = elapsed - body.delay; if (lm < 0) continue;
        if (!body.startTriggered) { body.startTriggered = true; body.startTime = elapsed; }
        const ls = (elapsed - body.startTime) / 1000;
        body.velocity.y -= GRAVITY * dt;
        body.mesh.position.x += body.velocity.x * dt;
        body.mesh.position.y += body.velocity.y * dt;
        body.mesh.position.z += body.velocity.z * dt;
        const rm = ef.buckling && !body.isColumn ? 1.5 : 1;
        body.mesh.rotateX(body.angularVel.x * rm * dt);
        body.mesh.rotateY(body.angularVel.y * rm * dt);
        body.mesh.rotateZ(body.angularVel.z * rm * dt);
        if (body.mesh.position.y < body.groundY) {
          body.mesh.position.y = body.groundY;
          if (ef.bounce) {
            body.velocity.y = Math.abs(body.velocity.y) * 0.35;
            body.velocity.x *= 0.7; body.velocity.z *= 0.7;
            body.angularVel.multiplyScalar(0.5);
            if (body.velocity.y < 0.8) body.velocity.y = 0;
          } else {
            body.velocity.set(0, 0, 0);
            body.angularVel.set(0, 0, 0);
          }
        }
        if (ls > 1.2) {
          const fade = 1 - Math.min((ls - 1.2) / 0.8, 1);
          const bm = body.mesh.material as THREE.MeshStandardMaterial;
          bm.transparent = true;
          bm.opacity = Math.max(0.15, fade);
          bm.depthWrite = fade > 0.5;
        }
      }
      if (ef.explosion) for (const p of debrisPool) {if(!p.active)continue;const lm=elapsed-p.delay;if(lm<0)continue;const ls=lm/1000;if(ls>p.lifetime){p.active=false;continue;}p.velocity.y-=GRAVITY*0.8*dt;p.mesh.position.x+=p.velocity.x*dt;p.mesh.position.y+=p.velocity.y*dt;p.mesh.position.z+=p.velocity.z*dt;p.mesh.rotateX(p.angularVel.x*dt);p.mesh.rotateY(p.angularVel.y*dt);p.mesh.rotateZ(p.angularVel.z*dt);if(ef.bounce&&p.mesh.position.y<p.groundY){p.mesh.position.y=p.groundY;p.velocity.y=Math.abs(p.velocity.y)*0.3;p.velocity.x*=0.6;p.velocity.z*=0.6;p.angularVel.multiplyScalar(0.4);}const fade=Math.max(0,1-ls/p.lifetime);(p.mesh.material as THREE.MeshStandardMaterial).opacity=fade*0.9;(p.mesh.material as THREE.MeshStandardMaterial).transparent=true;p.mesh.visible=true;}
      if (ef.dust) for(const d of dustPool){if(!d.active)continue;const lm=elapsed-d.delay;if(lm<0)continue;const ls=lm/1000;if(ls>d.lifetime){d.active=false;continue;}d.mesh.scale.setScalar(d.maxScale*Math.min(ls/1.2,1));(d.mesh.material as THREE.MeshBasicMaterial).opacity=0.25*(1-Math.min(ls/1.2,1));d.mesh.visible=true;}
      if (ef.fracture) for(const fp of fracturePool){if(!fp.active)continue;const lm=elapsed-fp.delay;if(lm<0)continue;const ls=lm/1000;if(ls>fp.lifetime){fp.active=false;continue;}fp.velocity.y-=GRAVITY*dt;fp.mesh.position.addScaledVector(fp.velocity,dt);fp.mesh.rotateX(fp.angularVel.x*dt);fp.mesh.rotateY(fp.angularVel.y*dt);fp.mesh.rotateZ(fp.angularVel.z*dt);if(fp.mesh.position.y<GROUND_Y){fp.mesh.position.y=GROUND_Y;fp.velocity.y=Math.abs(fp.velocity.y)*0.25;}const fade=Math.max(0,1-ls/fp.lifetime);(fp.mesh.material as THREE.MeshStandardMaterial).opacity=fade*0.85;(fp.mesh.material as THREE.MeshStandardMaterial).transparent=true;fp.mesh.visible=true;}
      if (ef.flash) {
        const warningFlash = elapsed < 800 ? Math.sin((elapsed / 800) * Math.PI) * 0.5 : 0;
        const tensionPulse = elapsed > a.firstBodyDelay - 350 && elapsed < a.firstBodyDelay - 50
          ? Math.sin(((elapsed - a.firstBodyDelay + 350) / 300) * Math.PI) * 0.25
          : 0;
        const impactFlash = elapsed > a.firstBodyDelay - 100 && elapsed < a.firstBodyDelay + 300
          ? Math.sin(((elapsed - a.firstBodyDelay + 100) / 400) * Math.PI) * 0.4
          : 0;
        setFlashOpacity(Math.max(warningFlash, tensionPulse, impactFlash));
      } else if (elapsed > 1200) {
        setFlashOpacity(0);
      }
      setCollapseProgress(Math.min(elapsed / COLLAPSE_DURATION, 1));
      if (elapsed >= COLLAPSE_DURATION) {
        a.active = false;
        setAnimating(false);
        setFlashOpacity(0);
        cam.position.copy(preShakePos);
        controlsRef.current?.update();
        renderer.render(scene, cam);
        onAnimationComplete?.();
        return;
      }
      renderer.render(scene, cam);
      requestAnimationFrame(physicsLoop);
    }
    requestAnimationFrame(physicsLoop);

    return () => {
      anim.active = false;
      setAnimating(false);
      setCollapseProgress(0);
      setFlashOpacity(0);
      // Remove clone meshes from frame group
      const toRemove: THREE.Object3D[] = [];
      for (const child of fg.children) {
        if ((child as THREE.Mesh).userData?._collapseClone) toRemove.push(child);
      }
      for (const child of toRemove) {
        fg.remove(child);
        disposeMesh(child);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [animationTrigger, structure, bounds]);

  // ── Reset Camera ─────────────────────────────────────────────────────
  const resetCamera = useCallback(() => {
    if (!cameraRef.current || !controlsRef.current || !bounds) return;
    const cx = (bounds.minX + bounds.maxX) / 2, cy = (bounds.minY + bounds.maxY) / 2;
    const extent = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY, 3);
    const dist = extent * 2.2;
    cameraRef.current.position.set(cx + dist * 0.6, cy + dist * 0.5, dist);
    controlsRef.current.target.set(cx, cy, 0);
    controlsRef.current.update();
  }, [bounds]);

  // ── Zoom ────────────────────────────────────────────────────────────
  const zoomStep = useCallback((dir: number) => {
    const cam = cameraRef.current;
    const ctrl = controlsRef.current;
    if (!cam || !ctrl) return;
    const dirVec = new THREE.Vector3().subVectors(cam.position, ctrl.target).normalize();
    const dist = cam.position.distanceTo(ctrl.target);
    const newDist = Math.max(2, Math.min(40, dist + dir * dist * 0.15));
    cam.position.copy(ctrl.target).add(dirVec.multiplyScalar(newDist));
    cam.updateProjectionMatrix();
    ctrl.update();
  }, []);

  // ── View Presets ────────────────────────────────────────────────────
  const setView = useCallback((view: "default" | "top" | "front" | "side") => {
    const cam = cameraRef.current;
    const ctrl = controlsRef.current;
    if (!cam || !ctrl || !bounds) return;
    const cx = (bounds.minX + bounds.maxX) / 2, cy = (bounds.minY + bounds.maxY) / 2;
    const extent = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY, 3);
    const dist = extent * 2.2;
    ctrl.target.set(cx, cy, 0);
    switch (view) {
      case "default":
        cam.position.set(cx + dist * 0.6, cy + dist * 0.5, dist);
        break;
      case "top":
        cam.position.set(cx, cy, dist);
        break;
      case "front":
        cam.position.set(cx, cy + extent * 0.3, -dist);
        break;
      case "side":
        cam.position.set(cx + dist, cy, 0);
        break;
    }
    cam.lookAt(ctrl.target);
    ctrl.update();
  }, [bounds]);

  // ── Empty State ───────────────────────────────────────────────────────
  if (!structure || !structure.nodes.length) {
    return (
      <div ref={containerRef} className="flex-1 flex flex-col min-h-0">
        <div ref={canvasRef} className="flex-1 relative bg-[#0a0f1a] overflow-hidden">
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="flex flex-col items-center gap-6 text-center">
              <svg width="120" height="120" viewBox="0 0 120 120" fill="none" className="opacity-60">
                <rect x="20" y="20" width="80" height="80" rx="8" stroke="#22d3ee" strokeWidth="2" strokeDasharray="8 6" />
                <rect x="35" y="35" width="50" height="50" rx="4" stroke="#22d3ee" strokeWidth="1.5" strokeDasharray="4 4" className="opacity-50" />
                <rect x="48" y="48" width="24" height="24" rx="3" stroke="#22d3ee" strokeWidth="1" strokeDasharray="3 3" className="opacity-30" />
              </svg>
              <p className="text-lg font-medium text-foreground">Visualization Panel</p>
              <p className="text-sm text-muted-foreground">Send a frame analysis request to see the structure</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────
  return (
    <div ref={containerRef} className="flex-1 flex flex-col min-h-0">
      {/* Effects bar */}
      <div className="border-b border-border shrink-0">
        <button
          onClick={() => setEffectsOpen(!effectsOpen)}
          className="flex items-center gap-2 px-4 py-1.5 w-full text-left text-xs font-medium text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
        >
          <Settings2 className="h-3 w-3" />
          Effects ({activeScore}/100)
          <span className="text-[10px] text-muted-foreground/50">{effectsOpen ? "▲" : "▼"}</span>
        </button>
        {effectsOpen && (
          <div className="px-3 pb-2.5 flex flex-wrap gap-1.5 items-center">
            <button
              onClick={() => {
                const all = EFFECT_DEFS.some(d => !effects[d.key]);
                const v: Record<string, boolean> = {};
                EFFECT_DEFS.forEach(d => v[d.key] = all);
                setEffects(v);
              }}
              className="px-2 py-1 text-[10px] rounded border border-border text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors cursor-pointer"
            >
              {EFFECT_DEFS.every(d => effects[d.key]) ? "全部禁用" : "全部启用"}
            </button>
            {EFFECT_DEFS.map(def => {
              const on = effects[def.key];
              return (
                <button
                  key={def.key} onClick={() => toggleEffect(def.key)}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-medium border transition-all cursor-pointer ${on ? "bg-primary/15 border-primary/40 text-primary" : "border-border/60 text-muted-foreground/50 hover:text-muted-foreground"}`}
                  title={`${def.label}: ${def.desc} (${def.score}分)`}
                >
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: def.color, opacity: on ? 1 : 0.3 }} />
                  {def.label}
                  <span className={`text-[8px] ${on ? "text-primary/60" : "text-muted-foreground/30"}`}>{def.score}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Canvas */}
      <div ref={canvasRef} className="flex-1 relative bg-[#0a0f1a] overflow-hidden">
        {/* Flash overlay */}
        {flashOpacity > 0 && (
          <div className="absolute inset-0 pointer-events-none z-10" style={{ backgroundColor: `rgba(239,68,68,${flashOpacity})` }} />
        )}

        {/* View Toolbar */}
        <div className="absolute top-3 right-3 z-10 flex flex-col gap-1">
          {/* Zoom controls */}
          <div className="flex items-center rounded-md border border-border bg-background/90 shadow-sm overflow-hidden">
            <button
              onClick={() => zoomStep(-1)}
              className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors cursor-pointer border-r border-border"
              title="Zoom in"
            >
              <ZoomIn className="h-4 w-4" />
            </button>
            <button
              onClick={() => zoomStep(1)}
              className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors cursor-pointer"
              title="Zoom out"
            >
              <ZoomOut className="h-4 w-4" />
            </button>
          </div>

          {/* View presets */}
          <div className="flex items-center rounded-md border border-border bg-background/90 shadow-sm overflow-hidden">
            {(["default", "top", "front", "side"] as const).map(v => (
              <button
                key={v}
                onClick={() => setView(v)}
                className="px-2 py-1.5 text-[10px] font-medium text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors cursor-pointer border-r last:border-r-0 border-border uppercase tracking-wider"
                title={`${v} view`}
              >
                {v === "default" ? <Eye className="h-3.5 w-3.5" /> : v[0].toUpperCase() + v.slice(1)}
              </button>
            ))}
          </div>

          {/* Reset camera */}
          <button
            onClick={resetCamera}
            className="p-1.5 rounded-md border border-border bg-background/90 text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors cursor-pointer shadow-sm"
            title="Reset camera"
          >
            <RotateCw className="h-4 w-4" />
          </button>
        </div>

        {/* Hint */}
        <div className="absolute bottom-3 left-3 z-10 bg-background/80 border border-border rounded-md px-2 py-1 text-[10px] text-muted-foreground/60 pointer-events-none">
          <span className="flex items-center gap-1">
            <Move className="h-3 w-3 inline" /> Drag to orbit · Scroll to zoom · Right-drag to pan
          </span>
        </div>

        {/* Status */}
        <div className="absolute bottom-3 right-3 z-10 bg-background/80 border border-border rounded-md px-2.5 py-1 pointer-events-none flex items-center gap-2">
          {animating ? (
            <span className="text-[10px] text-red-400 font-medium tabular-nums">
              ⚡ {collapsedCount} element(s) — {(collapseProgress * 100).toFixed(0)}%
            </span>
          ) : collapsedCount > 0 ? (
            <span className="text-[10px] text-emerald-400 tabular-nums">
              ✖ {collapsedCount} collapsed · {structure.elements.length - collapsedCount}/{structure.elements.length} standing
            </span>
          ) : (
            <span className="text-[10px] text-muted-foreground">
              {structure.elements.length} elements · {structure.nodes.length} nodes
            </span>
          )}
          {/* Mini health bar */}
          {structure.elements.length > 0 && (
            <div className="w-12 h-1.5 rounded-full bg-[#1e293b] overflow-hidden shrink-0">
              <div className="h-full rounded-full bg-red-500 transition-all duration-300"
                style={{ width: `${(collapsedCount / structure.elements.length) * 100}%` }} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
