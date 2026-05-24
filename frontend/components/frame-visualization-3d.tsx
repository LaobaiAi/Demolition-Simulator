"use client";

import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Settings2, RotateCw } from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────
interface FrameNode { id: number; x: number; y: number; }
interface FrameElement { id: number; node_i: number; node_j: number; E?: number; A?: number; I?: number; }
interface FrameLoad { node_id: number; Fx: number; Fy: number; }
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
  const e = effects;

  // Sync effects to ref for render loop
  useEffect(() => { effectsRef.current = effects; }, [effects]);

  const toggleEffect = (k: EffectKey) => setEffects(p => ({ ...p, [k]: !p[k] }));
  const activeScore = EFFECT_DEFS.filter(d => effects[d.key]).reduce((s, d) => s + d.score, 0);

  // ── 1. Init Three.js Scene (once) ──────────────────────────────────────
  useEffect(() => {
    if (!canvasRef.current) return;
    const w = canvasRef.current.clientWidth;
    const h = canvasRef.current.clientHeight;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(w, h, false);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    canvasRef.current.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0a0f1a");
    scene.fog = new THREE.Fog("#0a0f1a", 25, 90);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(50, w / h, 0.5, 200);
    camera.position.set(10, 8, 14);
    camera.lookAt(4, 2, 0);
    cameraRef.current = camera;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 3;
    controls.maxDistance = 40;
    controls.maxPolarAngle = Math.PI * 0.7;
    controls.target.set(4, 2, 0);
    controls.update();
    controlsRef.current = controls;

    // Lighting
    scene.add(new THREE.AmbientLight("#334155", 1.2));
    scene.add(new THREE.HemisphereLight("#22d3ee", "#0f172a", 0.4));
    const key = new THREE.DirectionalLight("#ffffff", 2.5);
    key.position.set(15, 20, 10);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.near = 0.5;
    key.shadow.camera.far = 80;
    key.shadow.camera.left = key.shadow.camera.bottom = -20;
    key.shadow.camera.right = key.shadow.camera.top = 20;
    key.shadow.bias = -0.0001;
    key.shadow.normalBias = 0.02;
    scene.add(key);
    const fill = new THREE.DirectionalLight("#22d3ee", 0.5);
    fill.position.set(-5, 2, -5);
    scene.add(fill);

    // Ground
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(60, 60),
      new THREE.MeshStandardMaterial({ color: "#1e293b", roughness: 0.85, metalness: 0.2 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = GROUND_Y;
    ground.receiveShadow = true;
    scene.add(ground);

    const grid = new THREE.GridHelper(40, 30, "#334155", "#1e293b");
    grid.position.y = GROUND_Y + 0.01;
    scene.add(grid);

    // Groups
    ["frame", "analysis", "debris", "dust", "fracture"].forEach(name => {
      const g = new THREE.Group();
      g.name = name;
      scene.add(g);
    });
    frameGroupRef.current = scene.getObjectByName("frame") as THREE.Group;
    analysisGroupRef.current = scene.getObjectByName("analysis") as THREE.Group;
    debrisGroupRef.current = scene.getObjectByName("debris") as THREE.Group;
    dustGroupRef.current = scene.getObjectByName("dust") as THREE.Group;
    fractureGroupRef.current = scene.getObjectByName("fracture") as THREE.Group;

    // Resize
    const onResize = () => {
      if (!canvasRef.current || !camera || !renderer) return;
      camera.aspect = canvasRef.current.clientWidth / canvasRef.current.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(canvasRef.current.clientWidth, canvasRef.current.clientHeight, false);
    };
    window.addEventListener("resize", onResize);

    function animate() {
      rafId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }
    let rafId = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", onResize);
      controls.dispose();
      renderer.dispose();
      if (canvasRef.current?.contains(renderer.domElement)) {
        canvasRef.current.removeChild(renderer.domElement);
      }
      scene.traverse(obj => {
        if (obj instanceof THREE.Mesh) {
          obj.geometry?.dispose();
          if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
          else obj.material?.dispose();
        }
      });
    };
  }, []);

  // ── 2. Build frame meshes ──────────────────────────────────────────────
  useEffect(() => {
    const frameGroup = frameGroupRef.current;
    const analysisGroup = analysisGroupRef.current;
    if (!frameGroup || !analysisGroup || !structure?.nodes?.length || !bounds) return;

    // Clear groups
    [frameGroup, analysisGroup].forEach(g => {
      while (g.children.length > 0) {
        const c = g.children[0];
        if (c instanceof THREE.Mesh) {
          c.geometry?.dispose();
          if (Array.isArray(c.material)) c.material.forEach(m => m.dispose());
          else c.material?.dispose();
        }
        g.remove(c);
      }
    });
    elementMeshMap.current.clear();
    nodeMeshMap.current.clear();

    const { nodes, elements, loads, supports } = structure;
    const nodeMap = new Map(nodes.map(n => [n.id, n]));
    const dispMap = new Map<number, { ux: number; uy: number }>();
    displacements?.forEach(d => dispMap.set(d.node_id, { ux: d.ux, uy: d.uy }));
    const hasDeformation = !!(displacements?.length);
    const rangeX = bounds.maxX - bounds.minX || 1;
    const dispScale = (maxDisplacement && maxDisplacement > 0) ? (rangeX * 0.15) / maxDisplacement : 100;

    // Stress map
    const FY = 235e6;
    const stressMap = new Map<number, number>();
    elementForces?.forEach(ef => {
      const el = elements.find(e => e.id === ef.element_id);
      if (el?.A && el.A > 0) {
        const N = Math.max(Math.abs(ef.Nmax), Math.abs(ef.Nmin));
        stressMap.set(ef.element_id, Math.min(N / (el.A * FY), 1));
      }
    });
    const hasStress = stressMap.size > 0;

    // Materials
    const matNormal = new THREE.MeshStandardMaterial({ color: "#22d3ee", roughness: 0.35, metalness: 0.7 });
    const matCrit = new THREE.MeshStandardMaterial({ color: "#f97316", roughness: 0.35, metalness: 0.7, emissive: "#f97316", emissiveIntensity: 0.3 });
    const matNode = new THREE.MeshStandardMaterial({ color: "#64748b", roughness: 0.3, metalness: 0.8 });
    const matTop = new THREE.MeshStandardMaterial({ color: "#f59e0b", roughness: 0.3, metalness: 0.8 });
    const matGhost = new THREE.MeshBasicMaterial({ color: "#334155", transparent: true, opacity: 0.25, depthWrite: false });

    function node3D(n: FrameNode, withDisp: boolean) {
      let px = n.x, py = n.y;
      if (withDisp && hasDeformation) {
        const d = dispMap.get(n.id);
        if (d) { px += d.ux * dispScale; py += d.uy * dispScale; }
      }
      return new THREE.Vector3(px, py, 0);
    }

    // Elements
    for (const elem of elements) {
      const ni = nodeMap.get(elem.node_i), nj = nodeMap.get(elem.node_j);
      if (!ni || !nj) continue;
      const isCol = Math.abs(ni.x - nj.x) < 0.01;
      const section = isCol ? SECTION_COL : SECTION_BEAM;

      let mat = matNormal.clone();
      if (elem.id === criticalElementId) mat = matCrit.clone();
      else if (hasStress) {
        const r = stressMap.get(elem.id);
        if (r !== undefined) {
          mat.color.copy(stressColor(r));
          mat.emissive?.copy(stressColor(r));
          mat.emissiveIntensity = 0.15;
        }
      }

      const p1 = node3D(ni, hasDeformation), p2 = node3D(nj, hasDeformation);
      const mesh = buildBoxAlign(p1, p2, section, mat);
      mesh.userData = { elementId: elem.id, isColumn: isCol };
      frameGroup.add(mesh);
      elementMeshMap.current.set(elem.id, mesh);

      if (hasDeformation) {
        frameGroup.add(buildBoxAlign(node3D(ni, false), node3D(nj, false), section * 0.8, matGhost));
      }
    }

    // Nodes
    for (const n of nodes) {
      const p = node3D(n, hasDeformation);
      const isTop = n.y === bounds.maxY && loads.some(l => l.node_id === n.id);
      const geo = new THREE.SphereGeometry(isTop ? 0.2 : 0.15, 16, 16);
      const nodeMesh = new THREE.Mesh(geo, (isTop ? matTop : matNode).clone());
      nodeMesh.position.copy(p);
      frameGroup.add(nodeMesh);
      nodeMeshMap.current.set(n.id, nodeMesh);

      if (hasDeformation) {
        const ghostNode = new THREE.Mesh(new THREE.SphereGeometry(isTop ? 0.14 : 0.1, 8, 8), matGhost);
        ghostNode.position.copy(node3D(n, false));
        frameGroup.add(ghostNode);

        const d = dispMap.get(n.id);
        if (d && (Math.abs(d.ux * dispScale) > 0.01 || Math.abs(d.uy * dispScale) > 0.01)) {
          const pts = [node3D(n, false), p];
          const line = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(pts),
            new THREE.LineBasicMaterial({ color: "#22d3ee", transparent: true, opacity: 0.4, depthTest: false }),
          );
          analysisGroup.add(line);
        }
      }
    }

    // Supports
    for (const sup of supports) {
      const n = nodeMap.get(sup.node_id);
      if (!n) continue;
      const p = node3D(n, false);
      const base = new THREE.Mesh(
        new THREE.BoxGeometry(0.5, 0.15, 0.5),
        new THREE.MeshStandardMaterial({ color: "#64748b", roughness: 0.5, metalness: 0.6 }),
      );
      base.position.set(p.x, GROUND_Y + 0.075, p.z);
      base.receiveShadow = true;
      base.castShadow = true;
      frameGroup.add(base);
    }

    // Load arrows
    loads.forEach(load => {
      const n = nodeMap.get(load.node_id);
      if (!n) return;
      const p = node3D(n, hasDeformation);
      const len = Math.min(1.5, Math.abs(load.Fy / 5000) * 0.8);
      const shaft = new THREE.Mesh(
        new THREE.CylinderGeometry(0.05, 0.05, len, 8),
        new THREE.MeshStandardMaterial({ color: "#f59e0b", roughness: 0.4, metalness: 0.5, emissive: "#f59e0b", emissiveIntensity: 0.4 }),
      );
      shaft.position.set(p.x, p.y - len / 2, p.z);
      frameGroup.add(shaft);
      const head = new THREE.Mesh(
        new THREE.ConeGeometry(0.12, 0.3, 8),
        new THREE.MeshStandardMaterial({ color: "#f59e0b", roughness: 0.4, metalness: 0.5, emissive: "#f59e0b", emissiveIntensity: 0.5 }),
      );
      head.rotation.x = Math.PI;
      head.position.set(p.x, p.y - len, p.z);
      frameGroup.add(head);
    });

    // Fit camera
    if (cameraRef.current && controlsRef.current) {
      const cx = (bounds.minX + bounds.maxX) / 2, cy = (bounds.minY + bounds.maxY) / 2;
      const extent = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY, 3);
      const dist = extent * 2.2;
      cameraRef.current.position.set(cx + dist * 0.6, cy + dist * 0.5, dist);
      controlsRef.current.target.set(cx, cy, 0);
      controlsRef.current.update();
    }
    // Render new structure immediately
    if (rendererRef.current && sceneRef.current && cameraRef.current) {
      rendererRef.current.render(sceneRef.current, cameraRef.current);
    }
  }, [structure, displacements, criticalElementId, elementForces, maxDisplacement, bounds]);

  // ── 3. Allocate effect pools (debris, dust, fracture) when structure loads ──
  useEffect(() => {
    const debG = debrisGroupRef.current, dustG = dustGroupRef.current, fracG = fractureGroupRef.current;
    if (!debG || !dustG || !fracG || !structure?.elements?.length) return;

    const total = structure.elements.length;

    // Clear & reallocate if needed
    const ensurePool = <T extends { mesh: THREE.Mesh }>(
      group: THREE.Group, poolRef: T[], targetCount: number, factory: (i: number) => T,
    ) => {
      if (poolRef.length >= targetCount) return;
      for (let i = poolRef.length; i < targetCount; i++) {
        const item = factory(i);
        item.mesh.visible = false;
        group.add(item.mesh);
        poolRef.push(item);
      }
    };

    ensurePool(debG, animStateRef.current.debris, total * DEBRIS_COUNT_PER_ELEM, (i) => ({
      mesh: new THREE.Mesh(
        new THREE.BoxGeometry(0.04 + seedRand(i * 7) * 0.08, 0.03 + seedRand(i * 13) * 0.06, 0.04 + seedRand(i * 17) * 0.06),
        new THREE.MeshStandardMaterial({ color: new THREE.Color().setHSL(0.08 + seedRand(i * 19) * 0.08, 0.3, 0.2 + seedRand(i * 23) * 0.3), roughness: 0.7, metalness: 0.4, transparent: true, opacity: 0.9 }),
      ),
      velocity: new THREE.Vector3(), angularVel: new THREE.Vector3(),
      lifetime: 0, active: false, delay: 0, groundY: GROUND_Y,
    }));

    ensurePool(dustG, animStateRef.current.dust, total * DUST_COUNT_PER_ELEM, () => ({
      mesh: new THREE.Mesh(
        new THREE.SphereGeometry(1, 8, 8),
        new THREE.MeshBasicMaterial({ color: "#94a3b8", transparent: true, opacity: 0, depthWrite: false }),
      ),
      maxScale: 0, lifetime: 0, active: false, delay: 0,
    }));

    ensurePool(fracG, animStateRef.current.fractures, Math.min(total * 4, 60), (i) => ({
      mesh: new THREE.Mesh(
        new THREE.BoxGeometry(0.10 + seedRand(i * 23) * 0.06, 0.06 + seedRand(i * 31) * 0.04, 0.06 + seedRand(i * 37) * 0.04),
        new THREE.MeshStandardMaterial({ color: "#ef4444", roughness: 0.6, metalness: 0.3, emissive: "#ef4444", emissiveIntensity: 0.2, transparent: true, opacity: 0.85 }),
      ),
      velocity: new THREE.Vector3(), angularVel: new THREE.Vector3(),
      lifetime: 0, active: false, delay: 0,
    }));
  }, [structure?.elements?.length]);

  // ── 4. Collapse Animation — setup state for render loop ─────────────────
  useEffect(() => {
    if (!structure || !failedElements?.length) {
      // Reset animation
      animStateRef.current.active = false;
      setAnimating(false);
      setCollapseProgress(0);
      setCollapsedCount(0);
      setFlashOpacity(0);
      // Re-show original meshes
      for (const mesh of elementMeshMap.current.values()) mesh.visible = true;
      return;
    }

    const anim = animStateRef.current;
    const nodeMap = new Map(structure.nodes.map(n => [n.id, n]));
    const failedSet = new Set(failedElements);

    // Collect failed element data sorted by minY for cascade
    const failedData: { id: number; minY: number; isColumn: boolean }[] = [];
    for (const el of structure.elements) {
      if (!failedSet.has(el.id)) continue;
      const ni = nodeMap.get(el.node_i), nj = nodeMap.get(el.node_j);
      if (!ni || !nj) continue;
      failedData.push({ id: el.id, minY: Math.min(ni.y, nj.y), isColumn: Math.abs(ni.x - nj.x) < 0.01 });
    }
    failedData.sort((a, b) => a.minY - b.minY);

    // Reset pools
    for (const p of anim.debris) p.active = false;
    for (const d of anim.dust) d.active = false;
    for (const f of anim.fractures) f.active = false;

    // Remove old cloned bodies
    if (frameGroupRef.current) {
      const toRemove: THREE.Object3D[] = [];
      frameGroupRef.current.traverse(c => {
        if (c instanceof THREE.Mesh && c.userData?._collapseClone) toRemove.push(c);
      });
      toRemove.forEach(c => {
        if (c instanceof THREE.Mesh) {
          c.geometry?.dispose();
          if (Array.isArray(c.material)) c.material.forEach(m => m.dispose());
          else c.material?.dispose();
        }
        frameGroupRef.current?.remove(c);
      });
    }

    // Bodies
    anim.bodies.clear();
    const cx = bounds ? (bounds.minX + bounds.maxX) / 2 : 0;

    for (let i = 0; i < failedData.length; i++) {
      const fd = failedData[i];
      const origMesh = elementMeshMap.current.get(fd.id);
      if (!origMesh) continue;

      // Hide original
      origMesh.visible = false;

      // Clone for animation
      const clone = origMesh.clone();
      clone.material = (origMesh.material as THREE.Material).clone();
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
      frameGroupRef.current?.add(clone);

      const dir = new THREE.Vector3(
        origMesh.position.x - cx, 0.3, (seedRand(fd.id + 50) - 0.5) * 0.6,
      ).normalize();

      const delay = (effects.cascade && failedData.length > 1) ? (i / (failedData.length - 1)) * 1500 : 50;

      anim.bodies.set(fd.id, {
        mesh: clone,
        velocity: new THREE.Vector3(dir.x * EXPLOSION_FORCE, -EXPLOSION_FORCE * 0.3, dir.z * EXPLOSION_FORCE * 0.5),
        angularVel: new THREE.Vector3((seedRand(fd.id * 3) - 0.5) * 5, (seedRand(fd.id * 5) - 0.5) * 6, (seedRand(fd.id * 7) - 0.5) * 5),
        delay, startTriggered: false, startTime: 0,
        isColumn: fd.isColumn, groundY: GROUND_Y + (fd.isColumn ? 0.1 : 0.05),
      });
    }

    // Debris
    let di = 0;
    for (const fd of failedData) {
      const orig = elementMeshMap.current.get(fd.id);
      if (!orig) continue;
      const body = anim.bodies.get(fd.id);
      const delay = body?.delay ?? 0;
      const count = 6 + Math.floor(seedRand(fd.id * 101) * 8);
      for (let j = 0; j < count && di < anim.debris.length; j++, di++) {
        const p = anim.debris[di];
        const angle = seedRand(fd.id * 200 + j * 7) * Math.PI * 2;
        const phi = seedRand(fd.id * 300 + j * 11) * Math.PI * 0.5;
        const speed = 3 + seedRand(fd.id * 400 + j * 13) * 8;
        p.active = true;
        p.lifetime = 1.5 + seedRand(fd.id * 500 + j * 17) * 1.5;
        p.delay = delay + 80 + seedRand(fd.id * 600 + j * 19) * 300;
        p.velocity.set(Math.cos(angle) * Math.cos(phi) * speed, Math.sin(phi) * speed - 2, Math.sin(angle) * Math.cos(phi) * speed * 0.6);
        p.angularVel.set((seedRand(fd.id * 700 + j * 23) - 0.5) * 10, (seedRand(fd.id * 800 + j * 29) - 0.5) * 10, (seedRand(fd.id * 900 + j * 31) - 0.5) * 10);
        p.mesh.position.copy(orig.position);
        p.mesh.visible = false;
      }
    }

    // Dust
    let dIdx = 0;
    for (const fd of failedData) {
      const orig = elementMeshMap.current.get(fd.id);
      if (!orig) continue;
      const body = anim.bodies.get(fd.id);
      const delay = body?.delay ?? 0;
      for (let j = 0; j < 3 && dIdx < anim.dust.length; j++, dIdx++) {
        const d = anim.dust[dIdx];
        d.active = true;
        d.lifetime = 1.5 + seedRand(fd.id * 1000 + j * 37) * 1;
        d.delay = delay + 400 + seedRand(fd.id * 1100 + j * 41) * 500;
        d.maxScale = 1.5 + seedRand(fd.id * 1200 + j * 43) * 3;
        d.mesh.position.set(orig.position.x + (seedRand(fd.id * 1300 + j * 47) - 0.5) * 2, GROUND_Y + 0.3, orig.position.z + (seedRand(fd.id * 1400 + j * 53) - 0.5) * 2);
        d.mesh.scale.setScalar(0.01);
        d.mesh.visible = false;
      }
    }

    // Fractures
    let fIdx = 0;
    for (const fd of failedData) {
      if (fd.isColumn) continue;
      const orig = elementMeshMap.current.get(fd.id);
      if (!orig) continue;
      const body = anim.bodies.get(fd.id);
      const delay = body?.delay ?? 0;
      for (let j = 0; j < 3 && fIdx < anim.fractures.length; j++, fIdx++) {
        const fp = anim.fractures[fIdx];
        fp.active = true;
        fp.lifetime = 2 + seedRand(fd.id * 1500 + j * 59) * 1;
        fp.delay = delay + 200 + j * 80;
        fp.velocity.set((seedRand(fd.id * 1600 + j * 61) - 0.5) * 6, -2 - seedRand(fd.id * 1700 + j * 67) * 4, (seedRand(fd.id * 1800 + j * 71) - 0.5) * 6);
        fp.angularVel.set((seedRand(fd.id * 1900 + j * 73) - 0.5) * 8, (seedRand(fd.id * 2000 + j * 79) - 0.5) * 8, (seedRand(fd.id * 2100 + j * 83) - 0.5) * 8);
        fp.mesh.position.copy(orig.position).add(new THREE.Vector3((j - 1) * 0.5, seedRand(fd.id * 2200 + j * 89) * 0.3, 0));
        fp.mesh.visible = false;
      }
    }

    // Start animation
    anim.collapseCount = failedData.length;
    anim.firstBodyDelay = failedData.length > 0 && anim.bodies.size > 0
      ? [...anim.bodies.values()].reduce((min, b) => Math.min(min, b.delay), Infinity) : 0;
    anim.startTime = performance.now();
    anim.active = true;

    setAnimating(true);
    setCollapsedCount(failedData.length);
    setCollapseProgress(0);
    setFlashOpacity(0);

    // ── Temporary physics RAF loop (only during collapse) ──
    let animRaf: number;
    let lastPhysTime = 0;
    const preShakePos = cameraRef.current?.position.clone() ?? new THREE.Vector3();

    function physicsLoop(timestamp: number) {
      const camera = cameraRef.current;
      const scene = sceneRef.current;
      const renderer = rendererRef.current;
      if (!camera || !scene || !renderer) return;

      const a = animStateRef.current;
      if (!a.active) {
        renderer.render(scene, camera);
        return;
      }

      const dt = lastPhysTime ? Math.min(0.05, (timestamp - lastPhysTime) / 1000) : 0.016;
      lastPhysTime = timestamp;
      const elapsed = timestamp - a.startTime;
      const ef = effectsRef.current;

      // Reset camera from shake each frame (non-accumulating)
      camera.position.copy(preShakePos);

      // Camera shake
      if (ef.shake && elapsed > a.firstBodyDelay + 400 && elapsed < a.firstBodyDelay + 1400) {
        const se = elapsed - a.firstBodyDelay - 400;
        const intensity = Math.sin(se * 0.06) * 0.25 * (1 - se / 1000);
        camera.position.x += Math.sin(elapsed * 0.04 + 1) * intensity;
        camera.position.y += Math.sin(elapsed * 0.05 + 2) * intensity;
      }

      // Bodies
      for (const [, body] of a.bodies) {
        const localMs = elapsed - body.delay;
        if (localMs < 0) continue;
        if (!body.startTriggered) { body.startTriggered = true; body.startTime = elapsed; }
        const localSec = (elapsed - body.startTime) / 1000;
        body.velocity.y -= GRAVITY * dt;
        body.mesh.position.x += body.velocity.x * dt;
        body.mesh.position.y += body.velocity.y * dt;
        body.mesh.position.z += body.velocity.z * dt;
        const rotM = ef.buckling && !body.isColumn ? 1.5 : 1;
        body.mesh.rotateX(body.angularVel.x * rotM * dt);
        body.mesh.rotateY(body.angularVel.y * rotM * dt);
        body.mesh.rotateZ(body.angularVel.z * rotM * dt);
        if (body.mesh.position.y < body.groundY) {
          body.mesh.position.y = body.groundY;
          if (ef.bounce) {
            body.velocity.y = Math.abs(body.velocity.y) * 0.35;
            body.velocity.x *= 0.7; body.velocity.z *= 0.7;
            body.angularVel.multiplyScalar(0.5);
            if (body.velocity.y < 0.8) body.velocity.y = 0;
          } else { body.velocity.set(0, 0, 0); body.angularVel.set(0, 0, 0); }
        }
        if (localSec > 1.2) {
          const fade = 1 - Math.min((localSec - 1.2) / 0.8, 1);
          const mat = body.mesh.material as THREE.MeshStandardMaterial;
          mat.transparent = true; mat.opacity = Math.max(0.15, fade); mat.depthWrite = fade > 0.5;
        }
      }

      // Debris
      if (ef.explosion) {
        for (const p of a.debris) {
          if (!p.active) continue;
          const lm = elapsed - p.delay;
          if (lm < 0) continue;
          const ls = lm / 1000;
          if (ls > p.lifetime) { p.active = false; continue; }
          p.velocity.y -= GRAVITY * 0.8 * dt;
          p.mesh.position.x += p.velocity.x * dt;
          p.mesh.position.y += p.velocity.y * dt;
          p.mesh.position.z += p.velocity.z * dt;
          p.mesh.rotateX(p.angularVel.x * dt);
          p.mesh.rotateY(p.angularVel.y * dt);
          p.mesh.rotateZ(p.angularVel.z * dt);
          if (ef.bounce && p.mesh.position.y < p.groundY) {
            p.mesh.position.y = p.groundY;
            p.velocity.y = Math.abs(p.velocity.y) * 0.3;
            p.velocity.x *= 0.6; p.velocity.z *= 0.6;
            p.angularVel.multiplyScalar(0.4);
          }
          const fade = Math.max(0, 1 - ls / p.lifetime);
          (p.mesh.material as THREE.MeshStandardMaterial).opacity = fade * 0.9;
          (p.mesh.material as THREE.MeshStandardMaterial).transparent = true;
          p.mesh.visible = true;
        }
      }

      // Dust
      if (ef.dust) {
        for (const d of a.dust) {
          if (!d.active) continue;
          const lm = elapsed - d.delay;
          if (lm < 0) continue;
          const ls = lm / 1000;
          if (ls > d.lifetime) { d.active = false; continue; }
          const prog = Math.min(ls / 1.2, 1);
          d.mesh.scale.setScalar(d.maxScale * prog);
          (d.mesh.material as THREE.MeshBasicMaterial).opacity = 0.25 * (1 - prog);
          d.mesh.visible = true;
        }
      }

      // Fractures
      if (ef.fracture) {
        for (const fp of a.fractures) {
          if (!fp.active) continue;
          const lm = elapsed - fp.delay;
          if (lm < 0) continue;
          const ls = lm / 1000;
          if (ls > fp.lifetime) { fp.active = false; continue; }
          fp.velocity.y -= GRAVITY * dt;
          fp.mesh.position.addScaledVector(fp.velocity, dt);
          fp.mesh.rotateX(fp.angularVel.x * dt);
          fp.mesh.rotateY(fp.angularVel.y * dt);
          fp.mesh.rotateZ(fp.angularVel.z * dt);
          if (fp.mesh.position.y < GROUND_Y) {
            fp.mesh.position.y = GROUND_Y;
            fp.velocity.y = Math.abs(fp.velocity.y) * 0.25;
          }
          const fade = Math.max(0, 1 - ls / fp.lifetime);
          (fp.mesh.material as THREE.MeshStandardMaterial).opacity = fade * 0.85;
          (fp.mesh.material as THREE.MeshStandardMaterial).transparent = true;
          fp.mesh.visible = true;
        }
      }

      // Flash & Progress
      if (ef.flash && elapsed < 600) {
        setFlashOpacity(Math.sin((elapsed / 600) * Math.PI) * 0.35);
      } else if (ef.flash) {
        setFlashOpacity(0);
      }
      setCollapseProgress(Math.min(elapsed / COLLAPSE_DURATION, 1));

      if (elapsed >= COLLAPSE_DURATION) {
        a.active = false;
        setAnimating(false);
        setFlashOpacity(0);
        camera.position.copy(preShakePos);
        controlsRef.current?.update();
        renderer.render(scene, camera);
        return; // stop loop
      }

      renderer.render(scene, camera);
      animRaf = requestAnimationFrame(physicsLoop);
    }

    animRaf = requestAnimationFrame(physicsLoop);
    return () => {
      cancelAnimationFrame(animRaf);
      if (cameraRef.current) cameraRef.current.position.copy(preShakePos);
    };
  }, [failedElements, structure, effects.cascade, bounds]);

  // ── 5. Static round display (no collapse animation) ──────────────────
  useEffect(() => {
    if (!structure?.elements?.length) return;
    const anim = animStateRef.current;
    if (anim.active) return;

    const failedSet = new Set(displayFailedElements || []);

    if (frameGroupRef.current) {
      const toRemove: THREE.Object3D[] = [];
      frameGroupRef.current.traverse(c => {
        if (c instanceof THREE.Mesh && c.userData?._collapseClone) toRemove.push(c);
      });
      toRemove.forEach(c => {
        if (c instanceof THREE.Mesh) {
          c.geometry?.dispose();
          if (Array.isArray(c.material)) c.material.forEach(m => m.dispose());
          else c.material?.dispose();
        }
        frameGroupRef.current?.remove(c);
      });
    }

    for (const [id, mesh] of elementMeshMap.current) {
      mesh.visible = !failedSet.has(id);
    }
    if (rendererRef.current && sceneRef.current && cameraRef.current) {
      rendererRef.current.render(sceneRef.current, cameraRef.current);
    }
  }, [displayFailedElements, structure?.elements?.length]);

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

  // ── Empty State ───────────────────────────────────────────────────────
  if (!structure || !structure.nodes.length) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
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

        {/* Camera reset */}
        <div className="absolute top-3 right-3 z-10">
          <button
            onClick={resetCamera}
            className="p-1.5 rounded-md border border-border bg-background/80 text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors cursor-pointer"
            title="Reset camera"
          >
            <RotateCw className="h-4 w-4" />
          </button>
        </div>

        {/* Hint */}
        <div className="absolute bottom-3 left-3 z-10 bg-background/80 border border-border rounded-md px-2 py-1 text-[10px] text-muted-foreground/60 pointer-events-none">
          Drag to orbit · Scroll to zoom · Right-drag to pan
        </div>

        {/* Status */}
        <div className="absolute bottom-3 right-3 z-10 bg-background/80 border border-border rounded-md px-2.5 py-1 pointer-events-none">
          {animating ? (
            <span className="text-[10px] text-red-400">
              Collapse: {collapsedCount} element(s) — {(collapseProgress * 100).toFixed(0)}%
            </span>
          ) : collapsedCount > 0 ? (
            <span className="text-[10px] text-emerald-400">Collapse complete — {collapsedCount} element(s)</span>
          ) : (
            <span className="text-[10px] text-muted-foreground">
              {structure.elements.length} elements · {structure.nodes.length} nodes
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
