"use client";

import React, {
  forwardRef,
  useImperativeHandle,
  useRef,
  useState,
  useCallback,
  useEffect,
  useMemo,
} from "react";
import { Canvas, useThree, useFrame } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { Box, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { type Lang } from "@/lib/i18n";
import type { FrameStructure } from "@/lib/state-restore";
import { createHBeamGeometry } from "@/lib/sfd-beam-geometry";
import { getSectionParams } from "@/lib/hbeam-geometry";

export interface Frame3DNode {
  id: number;
  x: number;
  y: number;
  z: number;
}

export interface Frame3DElement {
  id: number;
  node_i: number;
  node_j: number;
  type: string;
  section_id?: string;
}

export interface Frame3DModel {
  nodes: Frame3DNode[];
  elements: Frame3DElement[];
}

export interface Effects3DViewerHandle {
  setCameraPreset: (angle: string) => void;
  captureAllAngles: () => Promise<string[]>;
}

interface Effects3DViewerProps {
  lang?: Lang;
  modelData: Frame3DModel | FrameStructure | null;
  markedColumns: number[];
  onColumnClick?: (elementId: number) => void;
  selectable?: boolean;
  compact?: boolean;
  onScreenshot?: (dataUrl: string, angle: string) => void;
}

const FLOOR_COLORS = [
  "#4FC3F7", "#81C784", "#FFB74D", "#E57373",
  "#BA68C8", "#4DD0E1", "#FFF176", "#A1887F",
];

class ViewErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center w-full h-full min-h-[200px] bg-[#0a0e1a] rounded-lg">
          <div className="flex flex-col items-center gap-3">
            <AlertCircle className="h-10 w-10 text-red-400/60" />
            <span className="text-sm text-red-400/60">3D rendering error</span>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function inferElementType(
  nodeI: { x: number; y: number; z: number },
  nodeJ: { x: number; y: number; z: number }
): string {
  const dz = Math.abs(nodeJ.z - nodeI.z);
  const dxy = Math.sqrt(
    (nodeJ.x - nodeI.x) ** 2 + (nodeJ.y - nodeI.y) ** 2
  );
  if (dxy < 0.01 || dz > dxy * 3) return "column";
  return "beam";
}

// ── ProceduralEnv (SFD, no CDN) ──

function ProceduralEnv() {
  const { scene, gl } = useThree();
  useEffect(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 512; canvas.height = 256;
    const ctx = canvas.getContext("2d")!;
    const grad = ctx.createLinearGradient(0, 0, 0, 256);
    grad.addColorStop(0, "#4488cc");
    grad.addColorStop(0.5, "#223355");
    grad.addColorStop(1, "#111122");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 512, 256);
    const texture = new THREE.CanvasTexture(canvas);
    texture.mapping = THREE.EquirectangularReflectionMapping;
    const pmrem = new THREE.PMREMGenerator(gl);
    const envMap = pmrem.fromEquirectangular(texture).texture;
    // eslint-disable-next-line react-hooks/immutability
    scene.environment = envMap;
    scene.backgroundBlurriness = 0;
    texture.dispose();
    pmrem.dispose();
    return () => { scene.environment = null; };
  }, [scene, gl]);
  return null;
}

// ── Lights (SFD) ──

function Lights({ shadows: showShadows = true }) {
  return (
    <>
      <ambientLight intensity={0.3} />
      <directionalLight position={[20, 40, 20]} intensity={2.0}
        castShadow={showShadows} shadow-mapSize-width={2048} shadow-mapSize-height={2048}
        shadow-camera-far={80} shadow-camera-left={-30} shadow-camera-right={30}
        shadow-camera-top={30} shadow-camera-bottom={-30} />
      <directionalLight position={[-20, 10, -20]} intensity={0.5} color="#7B2FBE" />
      <hemisphereLight args={["#4444aa", "#111133", 0.4]} />
      {showShadows && <pointLight position={[0, 20, 0]} intensity={0.3} color="#00D4FF" />}
    </>
  );
}

// ── Ground (SFD) ──

function Ground({ center, size }: { center: THREE.Vector3; size: number }) {
  const s = size * 1.8;
  return (
    <group>
      <mesh position={[center.x, center.y, -0.15]} receiveShadow>
        <planeGeometry args={[s, s]} />
        <meshStandardMaterial color="#080820" metalness={0.6} roughness={0.4} transparent opacity={0.5} />
      </mesh>
      <gridHelper args={[s, Math.floor(s / 1.5), "#00D4FF", "#444444"]}
        rotation={[-Math.PI / 2, 0, 0]} position={[center.x, center.y, 0]} />
    </group>
  );
}

// ── Foundations (SFD) ──

function Foundations({ groundNodes }: { groundNodes: { x: number; y: number }[] }) {
  return (
    <group>
      {groundNodes.map((n, i) => (
        <group key={i} position={[n.x, n.y, 0]}>
          <mesh position={[0, 0, -0.15]} receiveShadow>
            <boxGeometry args={[0.9, 0.9, 0.3]} />
            <meshStandardMaterial color="#787878" roughness={0.95} metalness={0.05} />
          </mesh>
          <lineSegments>
            <edgesGeometry args={[new THREE.BoxGeometry(0.9, 0.9, 0.3)]} />
            <lineBasicMaterial color="#ffffff" transparent opacity={0.08} />
          </lineSegments>
          <mesh position={[0, 0, 0.025]}>
            <boxGeometry args={[0.52, 0.52, 0.05]} />
            <meshStandardMaterial color="#3a3a3a" metalness={0.8} roughness={0.25} />
          </mesh>
          <lineSegments>
            <edgesGeometry args={[new THREE.BoxGeometry(0.52, 0.52, 0.05)]} />
            <lineBasicMaterial color="#64b4ff" transparent opacity={0.15} />
          </lineSegments>
        </group>
      ))}
    </group>
  );
}

// ── Supports (SFD) ──

function Supports({ groundNodes }: { groundNodes: { x: number; y: number; z: number }[] }) {
  return (
    <group>
      {groundNodes.map((n, i) => (
        <group key={i} position={[n.x, n.y, n.z]}>
          <mesh position={[0, 0, -0.05]}>
            <boxGeometry args={[0.5, 0.5, 0.1]} />
            <meshStandardMaterial color="#ff4444" metalness={0.6} roughness={0.3} />
          </mesh>
          <mesh position={[0, 0, 0.08]}>
            <coneGeometry args={[0.15, 0.2, 8]} />
            <meshStandardMaterial color="#ff6644" emissive="#ff4444" emissiveIntensity={0.2} />
          </mesh>
          <mesh position={[0, 0, 0]}>
            <ringGeometry args={[0.2, 0.35, 32]} />
            <meshBasicMaterial color="#ff4444" transparent opacity={0.2} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

// ── CameraSetup (SFD: Z-up + auto-dist) ──

function CameraSetup({ nodes }: { nodes: Frame3DNode[] }) {
  const { camera } = useThree();
  useEffect(() => {
    camera.up.set(0, 0, 1);
    if (nodes.length > 0) {
      const box = new THREE.Box3();
      for (const n of nodes) box.expandByPoint(new THREE.Vector3(n.x, n.y, n.z));
      const center = new THREE.Vector3();
      box.getCenter(center);
      const size = new THREE.Vector3();
      box.getSize(size);
      const maxDim = Math.max(size.x, size.y, size.z, 1);
      const fov = (camera as THREE.PerspectiveCamera).fov || 40;
      const dist = (maxDim / 2) / Math.tan(fov * Math.PI / 360) / 0.6;
      camera.position.set(center.x + dist * 0.5, center.y + dist * 0.5, center.z + dist * 0.7);
      camera.lookAt(center);
    } else {
      camera.lookAt(0, 0, 0);
    }
    camera.updateProjectionMatrix();
  }, [camera, nodes]);
  return null;
}

// ── AnimatedBeam (SFD: H-beam, floor colors, wireframe, selection glow, animation) ──

const _v = new THREE.Vector3();
const _up = new THREE.Vector3(0, 1, 0);

function AnimatedBeam({
  ni, nj, color, opacity = 1, emissive = false,
  delay = 0, animationType = "none", displayMode = "shaded", section = "",
  isSelected = false, onClick,
}: {
  ni: THREE.Vector3; nj: THREE.Vector3; color: string;
  opacity?: number; emissive?: boolean; delay?: number;
  animationType?: "rise" | "lift" | "none";
  displayMode?: string; section?: string; isSelected?: boolean;
  onClick?: () => void;
}) {
  const ref = useRef<THREE.Group>(null);
  const dir = useMemo(() => new THREE.Vector3().subVectors(nj, ni), [ni, nj]);
  const len = dir.length();
  const quat = useMemo(() => {
    if (len < 0.01) return new THREE.Quaternion();
    return new THREE.Quaternion().setFromUnitVectors(_up, dir.clone().normalize());
  }, [dir, len]);

  const [phase, setPhase] = useState<"entering" | "placed">(
    animationType === "none" ? "placed" : "entering"
  );

  const startPos = useMemo(() => {
    const m = _v.copy(ni).add(nj).multiplyScalar(0.5);
    if (animationType === "rise") {
      const baseZ = Math.min(ni.z, nj.z);
      return new THREE.Vector3(m.x, m.y, baseZ);
    }
    if (animationType === "lift") {
      const floorZ = Math.min(ni.z, nj.z);
      return new THREE.Vector3(m.x, m.y, floorZ - 2.5);
    }
    return m.clone();
  }, [animationType, ni.x, ni.y, ni.z, nj.x, nj.y, nj.z]);

  const targetPos = useMemo(
    () => _v.copy(ni).add(nj).multiplyScalar(0.5).clone(),
    [ni.x, ni.y, ni.z, nj.x, nj.y, nj.z]
  );

  const beamGeom = useMemo(() => {
    if (len < 0.01) return null;
    if (section) {
      try {
        const p = getSectionParams(section);
        return createHBeamGeometry(section, p.h / 1000, p.b / 1000, len);
      } catch { /* fallback */ }
    }
    return createHBeamGeometry("HW350x350x12x19", 0.35, 0.35, len);
  }, [section, len]);

  const edgesGeom = useMemo(() => {
    if (!beamGeom) return null;
    return new THREE.EdgesGeometry(beamGeom);
  }, [beamGeom]);

  const col = useMemo(() => new THREE.Color(color), [color]);

  const animRef = useRef({ progress: 0, started: false, startTime: 0 });

  // For "rise": grow from base
  useEffect(() => {
    if (animationType === "rise" && ref.current) {
      ref.current.scale.y = 0;
    }
  }, [animationType]);

  const offsetGeom = useMemo(() => {
    if (animationType !== "rise" || !beamGeom) return null;
    const g = beamGeom.clone();
    g.translate(0, len / 2, 0);
    g.computeVertexNormals();
    return g;
  }, [beamGeom, animationType, len]);
  const renderGeom = animationType === "rise" ? offsetGeom : beamGeom;

  // Selection pulse
  const pulseRef = useRef(0);
  const [glowIntensity, setGlowIntensity] = useState(0);
  useFrame(({ clock }) => {
    if (!isSelected) {
      if (glowIntensity !== 0) setGlowIntensity(0);
      return;
    }
    pulseRef.current = 0.7 + Math.sin(clock.elapsedTime * 3) * 0.3;
    setGlowIntensity(pulseRef.current);
  });

  // Animation frame
  useFrame(({ clock }) => {
    if (phase !== "entering") return;
    const anim = animRef.current;
    if (!anim.started) { anim.started = true; anim.startTime = clock.elapsedTime + delay; }
    const elapsed = clock.elapsedTime - anim.startTime;
    if (elapsed < 0) {
      if (animationType === "rise" && ref.current) ref.current.scale.y = 0;
      return;
    }
    anim.progress = Math.min(1, elapsed / 0.8);
    const ease = 1 - Math.pow(1 - anim.progress, 3);
    if (ref.current) {
      if (animationType === "rise") {
        ref.current.scale.y = ease;
      } else if (animationType !== "none") {
        ref.current.position.lerpVectors(startPos, targetPos, ease);
      }
    }
    if (anim.progress >= 1) setPhase("placed");
  });

  if (len < 0.01 || !renderGeom) return null;

  const isXray = displayMode === "xray";
  const isWireframe = displayMode === "wireframe";
  const SEL_COLOR = "#9C27B0";
  const selEmissive = isSelected ? new THREE.Color(SEL_COLOR) : (emissive ? col : "#000000");
  const selEmissiveIntensity = isSelected ? glowIntensity : emissive ? 0.3 : 0;

  return (
    <group ref={ref} position={animationType === "rise" ? targetPos : startPos} quaternion={quat}>
      {!isXray && (
        <mesh castShadow={!isWireframe} receiveShadow={!isWireframe}
          geometry={renderGeom}
          onClick={(e: ThreeEvent<MouseEvent>) => { if (onClick) { e.stopPropagation(); onClick(); } }}
        >
          {isWireframe ? (
            <meshStandardMaterial color="#00D4FF" wireframe metalness={0} roughness={0.8} transparent opacity={0.4} />
          ) : (
            <meshStandardMaterial color={col} metalness={0.4} roughness={0.6}
              transparent opacity={opacity}
              emissive={selEmissive} emissiveIntensity={selEmissiveIntensity} />
          )}
        </mesh>
      )}
      {onClick && !isXray && !isWireframe && (
        <mesh onClick={(e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onClick(); }}>
          <boxGeometry args={[len + 0.3, 0.5, 0.5]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
        </mesh>
      )}
      {(isXray || isWireframe) ? (
        <lineSegments>
          <edgesGeometry args={[renderGeom]} />
          <lineBasicMaterial color={isXray ? "#4488ff" : "#00D4FF"} transparent opacity={isXray ? 0.3 : 0.6} />
        </lineSegments>
      ) : (
        <lineSegments geometry={edgesGeom!}>
          <lineBasicMaterial color={isSelected ? SEL_COLOR : "#ffffff"} transparent opacity={isSelected ? 0.9 : 0.12 * opacity} />
        </lineSegments>
      )}
      {isXray && (
        <mesh geometry={renderGeom}
          onClick={(e: ThreeEvent<MouseEvent>) => { if (onClick) { e.stopPropagation(); onClick(); } }}
        >
          <meshStandardMaterial color={col} transparent opacity={0.08 * opacity} depthWrite={false} />
        </mesh>
      )}
      {isSelected && !isXray && !isWireframe && (
        <group scale={[1.06, 1.06, 1.06]}>
          <mesh geometry={renderGeom}>
            <meshBasicMaterial color={SEL_COLOR} transparent opacity={0.2 + glowIntensity * 0.12} depthWrite={false} />
          </mesh>
          <lineSegments geometry={edgesGeom!}>
            <lineBasicMaterial color={SEL_COLOR} transparent opacity={1.0} />
          </lineSegments>
        </group>
      )}
    </group>
  );
}

// ── FrameModel (SFD: floor-grouped rendering + animation) ──

function FrameModel({
  nodes, elements, markedSet, selectable, onColumnClick,
  displayMode = "shaded", animate = false, buildPhase = 1,
}: {
  nodes: Frame3DNode[]; elements: Frame3DElement[]; markedSet: Set<number>;
  selectable?: boolean; onColumnClick?: (id: number) => void;
  displayMode?: string; animate?: boolean; buildPhase?: number;
}) {
  const nodeMap = useMemo(
    () => new Map(nodes.map((n) => [n.id, new THREE.Vector3(n.x, n.y, n.z)])),
    [nodes]
  );

  const floorLevels = useMemo(() => {
    const zSet = new Set<number>();
    nodes.forEach((n) => zSet.add(n.z));
    return Array.from(zSet).sort((a, b) => a - b);
  }, [nodes]);

  const maxZ = useMemo(() => floorLevels[floorLevels.length - 1] || 1, [floorLevels]);

  const floorGroups = useMemo(() => {
    const groups: { floorIdx: number; columns: Frame3DElement[]; beams: Frame3DElement[] }[] = [];
    for (let f = 0; f < floorLevels.length - 1; f++) {
      const zBottom = floorLevels[f];
      const zTop = floorLevels[f + 1];
      const columns = elements.filter((el) => {
        if (el.type !== "column") return false;
        const ni = nodeMap.get(el.node_i), nj = nodeMap.get(el.node_j);
        if (!ni || !nj) return false;
        return Math.abs(Math.min(ni.z, nj.z) - zBottom) < 0.01;
      });
      const beamsNextFloor = elements.filter((el) => {
        if (!el.type.startsWith("beam")) return false;
        const ni = nodeMap.get(el.node_i), nj = nodeMap.get(el.node_j);
        if (!ni || !nj) return false;
        return Math.abs((ni.z + nj.z) / 2 - zTop) < 0.01;
      });
      groups.push({ floorIdx: f, columns, beams: beamsNextFloor });
    }
    return groups;
  }, [elements, floorLevels, nodeMap]);

  // SFD animation timing
  const COLUMN_TIME = 0.6;
  const BEAM_LIFT = 0.5;
  const FLOOR_GAP = 0.4;

  const elementsToShow = animate
    ? elements.filter((el) => {
        const ni = nodeMap.get(el.node_i), nj = nodeMap.get(el.node_j);
        if (!ni || !nj) return false;
        return (ni.z + nj.z) / 2 / maxZ <= buildPhase;
      })
    : elements;

  const elementSet = new Set(elementsToShow.map((el) => el.id));

  return (
    <group>
      {floorGroups.map((group) => {
        const floorBaseDelay = group.floorIdx * (COLUMN_TIME + BEAM_LIFT + FLOOR_GAP);
        return (
          <group key={group.floorIdx}>
            {group.columns.filter((el) => elementSet.has(el.id)).map((el) => {
              const ni = nodeMap.get(el.node_i), nj = nodeMap.get(el.node_j);
              if (!ni || !nj) return null;
              const isMarked = markedSet.has(el.id);
              const color = isMarked ? "#ff2222" : FLOOR_COLORS[group.floorIdx % FLOOR_COLORS.length];
              const sectionId = el.section_id || "";
              return (
                <AnimatedBeam key={el.id} ni={ni} nj={nj} color={color}
                  opacity={1} emissive={isMarked}
                  delay={animate ? floorBaseDelay : 0}
                  animationType={animate ? "rise" : "none"}
                  displayMode={displayMode} section={sectionId}
                  isSelected={isMarked}
                  onClick={selectable && onColumnClick ? () => onColumnClick(el.id) : undefined} />
              );
            })}
            {group.beams
              .filter((el) => elementSet.has(el.id))
              .sort((a, b) => {
                const na_i = nodeMap.get(a.node_i), na_j = nodeMap.get(a.node_j);
                const nb_i = nodeMap.get(b.node_i), nb_j = nodeMap.get(b.node_j);
                const ax = na_i && na_j ? (na_i.x + na_j.x) / 2 : 0;
                const bx = nb_i && nb_j ? (nb_i.x + nb_j.x) / 2 : 0;
                const ay = na_i && na_j ? (na_i.y + na_j.y) / 2 : 0;
                const by = nb_i && nb_j ? (nb_i.y + nb_j.y) / 2 : 0;
                return ay - by || ax - bx;
              })
              .map((el) => {
              const ni = nodeMap.get(el.node_i), nj = nodeMap.get(el.node_j);
              if (!ni || !nj) return null;
              const isMarked = markedSet.has(el.id);
              const color = isMarked ? "#ff2222" : FLOOR_COLORS[group.floorIdx % FLOOR_COLORS.length];
              const sectionId = el.section_id || "";
              const beamX = (ni.x + nj.x) / 2;
              const beamY = (ni.y + nj.y) / 2;
              const allX = nodes.map((n) => n.x);
              const allY = nodes.map((n) => n.y);
              const minX = Math.min(...allX);
              const maxX = Math.max(...allX);
              const minY = Math.min(...allY);
              const maxY = Math.max(...allY);
              const xNorm = maxX > minX ? (beamX - minX) / (maxX - minX) : 0.5;
              const yNorm = maxY > minY ? (beamY - minY) / (maxY - minY) : 0.5;
              const sweepNorm = xNorm * 0.7 + yNorm * 0.3;
              const beamDelay = animate ? floorBaseDelay + COLUMN_TIME + sweepNorm * BEAM_LIFT : 0;
              return (
                <AnimatedBeam key={el.id} ni={ni} nj={nj} color={color}
                  opacity={1} emissive={isMarked}
                  delay={beamDelay}
                  animationType={animate ? "lift" : "none"}
                  displayMode={displayMode} section={sectionId}
                  isSelected={isMarked}
                  onClick={undefined} />
              );
            })}
          </group>
        );
      })}
    </group>
  );
}

// ── ViewCube (SFD) ──

function ViewCube({ onSetView }: { onSetView: (angle: string) => void }) {
  return (
    <div className="bg-black/50 border border-white/10 rounded-lg p-1.5 shadow-2xl">
      <div className="grid grid-cols-3 gap-0.5">
        {[
          { l: "T", a: "top" }, { l: "", a: "" }, { l: "F", a: "front" },
          { l: "", a: "" }, { l: "R", a: "side" }, { l: "", a: "" },
          { l: "B", a: "bottom" }, { l: "", a: "" }, { l: "Back", a: "back" },
        ].map((v, i) =>
          v.a ? (
            <button key={i} onClick={() => onSetView(v.a)}
              className="w-6 h-6 rounded text-[8px] font-mono text-gray-400 hover:text-white hover:bg-white/10 transition-all flex items-center justify-center">
              {v.l}
            </button>
          ) : (
            <div key={i} className="w-6 h-6" />
          )
        )}
      </div>
    </div>
  );
}

// ── SceneContent ──

interface SceneContentProps {
  nodes: Frame3DNode[];
  elements: Frame3DElement[];
  markedSet: Set<number>;
  selectable?: boolean;
  onColumnClick?: (id: number) => void;
  displayMode: string;
  animate: boolean;
  orbitRef: React.MutableRefObject<boolean>;
  presetAngleRef: React.MutableRefObject<string | null>;
  onScreenshot?: (dataUrl: string, angle: string) => void;
}

function SceneContent({
  nodes, elements, markedSet, selectable, onColumnClick,
  displayMode, animate, orbitRef, presetAngleRef, onScreenshot,
}: SceneContentProps) {
  const { camera, gl, scene } = useThree();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const controlsRef = useRef<any>(null);

  const bbox = useMemo(() => {
    if (nodes.length === 0) return { center: new THREE.Vector3(0, 0, 0), size: 10 };
    const box = new THREE.Box3();
    for (const n of nodes) box.expandByPoint(new THREE.Vector3(n.x, n.y, n.z));
    const center = new THREE.Vector3();
    box.getCenter(center);
    const size = new THREE.Vector3();
    box.getSize(size);
    return { center, size: Math.max(size.x, size.y, size.z, 10) };
  }, [nodes]);

  const groundNodes = useMemo(() => nodes.filter((n) => Math.abs(n.z) < 0.01), [nodes]);

  const buildPhase = 1;

  const setCameraToPreset = useCallback((angle: string) => {
    if (angle === "orbit") return;
    const dist = bbox.size * 1.8;
    const c = bbox.center;
    let pos: THREE.Vector3;
    switch (angle) {
      case "top": pos = new THREE.Vector3(c.x, c.y, c.z + dist); break;
      case "bottom": pos = new THREE.Vector3(c.x, c.y, c.z - dist); break;
      case "front": pos = new THREE.Vector3(c.x, c.y - dist, c.z); break;
      case "back": pos = new THREE.Vector3(c.x, c.y + dist, c.z); break;
      case "side": pos = new THREE.Vector3(c.x + dist, c.y, c.z); break;
      case "45deg":
      default: pos = new THREE.Vector3(c.x + dist * 0.7, c.y + dist * 0.55, c.z + dist * 0.7); break;
    }
    camera.position.copy(pos);
    camera.lookAt(c);
    if (controlsRef.current) {
      controlsRef.current.target.copy(c);
      controlsRef.current.update();
    }
    requestAnimationFrame(() => {
      gl.render(scene, camera);
      const dataUrl = gl.domElement.toDataURL("image/png");
      onScreenshot?.(dataUrl, angle);
    });
  }, [bbox, camera, gl, scene, onScreenshot]);

  const prevPresetRef = useRef<string | null>(null);
  useEffect(() => {
    const angle = presetAngleRef.current;
    if (angle && angle !== prevPresetRef.current && angle !== "orbit") {
      prevPresetRef.current = angle;
      setCameraToPreset(angle);
    }
  }, [presetAngleRef, setCameraToPreset]);

  useEffect(() => {
    const handler = (e: Event) => {
      const angle = (e as CustomEvent).detail;
      setCameraToPreset(angle);
    };
    window.addEventListener("caiao-set-view", handler);
    return () => window.removeEventListener("caiao-set-view", handler);
  }, [setCameraToPreset]);

  // SFD auto-rotate during animation
  const autoRotate = animate && buildPhase < 1;

  return (
    <>
      <ProceduralEnv />
      <Lights shadows />
      <Ground center={bbox.center} size={bbox.size} />
      {buildPhase > 0.01 && <Foundations groundNodes={groundNodes} />}
      <Supports groundNodes={groundNodes} />
      <FrameModel
        nodes={nodes} elements={elements} markedSet={markedSet}
        selectable={selectable} onColumnClick={onColumnClick}
        displayMode={displayMode} animate={animate} buildPhase={buildPhase} />
      <CameraSetup nodes={nodes} />
      <OrbitControls
        ref={controlsRef}
        target={[bbox.center.x, bbox.center.y, bbox.center.z]}
        enableDamping dampingFactor={0.06}
        autoRotate={autoRotate}
        autoRotateSpeed={1.5}
        minDistance={5}
        maxDistance={bbox.size * 3}
        onStart={() => { if (autoRotate) orbitRef.current = false; }}
      />
    </>
  );
}

// ── Main Component ──

const Effects3DViewer = forwardRef<Effects3DViewerHandle, Effects3DViewerProps>(
  ({ modelData, markedColumns, onColumnClick, selectable, onScreenshot }, ref) => {
    const orbitRef = useRef(false);
    const presetAngleRef = useRef<string | null>(null);
    const captureResolveRef = useRef<((url: string) => void) | null>(null);
    const [displayMode, setDisplayMode] = useState("shaded");
    const animate = false;

    useEffect(() => {
      const handler = (e: Event) => {
        const mode = (e as CustomEvent).detail;
        if (typeof mode === "string" && ["shaded", "wireframe", "xray"].includes(mode)) {
          setDisplayMode(mode);
        }
      };
      window.addEventListener("caiao-set-display", handler);
      return () => window.removeEventListener("caiao-set-display", handler);
    }, []);

    const normalized = useMemo(() => {
      if (!modelData) return null;
      const nodeList: Frame3DNode[] = modelData.nodes.map((n) => ({
        id: n.id,
        x: n.x,
        y: n.y,
        z: n.z ?? 0,
      }));
      const nm = new Map(nodeList.map((n) => [n.id, n]));
      // Reassign IDs: server returns columns/beam_x/beam_y each starting from 1
      let nextId = 1;
      const elemList: Frame3DElement[] = (modelData.elements || []).map((e) => {
        const anyElem = e as unknown as Record<string, unknown>;
        let type = anyElem.type as string | undefined;
        if (!type) {
          const ni = nm.get(e.node_i), nj = nm.get(e.node_j);
          type = ni && nj ? inferElementType(ni, nj) : "beam";
        }
        return {
          id: nextId++,
          node_i: e.node_i,
          node_j: e.node_j,
          type,
          section_id: (anyElem.section_id || anyElem.section) as string | undefined,
        };
      });
      return { nodes: nodeList, elements: elemList };
    }, [modelData]);

    const markedSet = useMemo(() => new Set(markedColumns), [markedColumns]);

    useImperativeHandle(ref, () => ({
      setCameraPreset: (angle: string) => {
        orbitRef.current = angle === "orbit";
        presetAngleRef.current = angle;
      },
      captureAllAngles: async (): Promise<string[]> => {
        const angles = ["front", "side", "45deg", "top"];
        const results: string[] = [];
        for (const angle of angles) {
          try {
            const dataUrl = await new Promise<string>((resolve) => {
              captureResolveRef.current = resolve;
              window.dispatchEvent(new CustomEvent("caiao-set-view", { detail: angle }));
              // Safety timeout in case onScreenshot never fires
              setTimeout(() => {
                if (captureResolveRef.current === resolve) {
                  captureResolveRef.current = null;
                  resolve("");
                }
              }, 2000);
            });
            if (dataUrl && dataUrl.length > 1000) results.push(dataUrl);
          } catch { /* skip failed capture */ }
        }
        return results;
      },
    }), []);

    const handleScreenshot = useCallback((dataUrl: string, angle: string) => {
      if (captureResolveRef.current) {
        captureResolveRef.current(dataUrl);
        captureResolveRef.current = null;
      }
      onScreenshot?.(dataUrl, angle);
    }, [onScreenshot]);

    const handleSetView = useCallback((angle: string) => {
      if (angle === "orbit") { orbitRef.current = true; presetAngleRef.current = null; }
      else { orbitRef.current = false; presetAngleRef.current = angle; }
    }, []);

    if (!normalized || normalized.nodes.length === 0) {
      return (
        <div className="flex items-center justify-center w-full h-full min-h-[200px] bg-[#0a0e1a] rounded-lg">
          <div className="flex flex-col items-center gap-3">
            <Box className="h-10 w-10 text-muted-foreground/50" />
            <span className="text-sm text-muted-foreground/50">No model loaded. Generate a frame first.</span>
          </div>
        </div>
      );
    }

    return (
      <div className="relative w-full h-full bg-[#0a0e1a] rounded-lg overflow-hidden">
        {/* Camera presets */}
        <div className="absolute top-2 left-2 z-10 flex gap-1">
          {[["Front","front"],["Side","side"],["Top","top"],["45°","45deg"],["Orbit","orbit"]].map(([label, angle]) => (
            <button key={angle} onClick={() => handleSetView(angle)}
              className={cn("px-2 py-1 text-[10px] font-medium rounded",
                "bg-black/50 border border-white/10 text-white/70",
                "hover:text-white hover:border-white/30 transition-colors")}>
              {label}
            </button>
          ))}
        </div>

        {/* Display mode + marked count */}
        <div className="absolute top-2 right-2 z-10 flex gap-2 items-start">
          <div className="flex gap-1">
            {["shaded","wireframe","xray"].map((m) => (
              <button key={m} onClick={() => setDisplayMode(m)}
                className={cn("px-2 py-1 text-[10px] font-medium rounded transition-colors",
                  displayMode === m
                    ? "bg-purple-500/30 border border-purple-500/40 text-purple-300"
                    : "bg-black/50 border border-white/10 text-white/60 hover:text-white hover:border-white/30")}>
                {m === "shaded" ? "Shaded" : m === "wireframe" ? "Wire" : "X-Ray"}
              </button>
            ))}
          </div>
          {markedColumns.length > 0 && (
            <div className="bg-red-500/20 border border-red-500/40 rounded px-2 py-0.5 text-[11px] text-red-400 font-medium">
              {markedColumns.length}
            </div>
          )}
        </div>

        {/* ViewCube */}
        <div className="absolute bottom-2 right-2 z-10">
          <ViewCube onSetView={handleSetView} />
        </div>

        <ViewErrorBoundary>
          <Canvas className="w-full h-full" gl={{ antialias: true, alpha: false, preserveDrawingBuffer: true }}
            style={{ background: "#0a0e1a" }}
            camera={{ up: [0, 0, 1], position: [15, 10, 15], fov: 45 }}>
            <SceneContent
              nodes={normalized.nodes} elements={normalized.elements}
              markedSet={markedSet} selectable={selectable}
              onColumnClick={onColumnClick} displayMode={displayMode}
              animate={animate} orbitRef={orbitRef}
              presetAngleRef={presetAngleRef} onScreenshot={handleScreenshot} />
          </Canvas>
        </ViewErrorBoundary>

        {selectable && (
          <div className="absolute bottom-2 left-1/2 -translate-x-1/2 z-10 text-[10px] text-white/40 whitespace-nowrap">
            Click columns to mark for demolition
          </div>
        )}
      </div>
    );
  }
);

Effects3DViewer.displayName = "Effects3DViewer";

export { Effects3DViewer };
