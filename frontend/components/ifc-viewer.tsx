"use client";

import { useRef, useEffect, useState, useCallback } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RotateCw, ZoomIn, ZoomOut, Move, Loader2 } from "lucide-react";

// ── IFC Loader (optional, with fallback) ──────────────────────────────────────
const hasIFC = false;

// ── Types ─────────────────────────────────────────────────────────────────────
interface StructureNode {
  id: number;
  x: number;
  y: number;
  z?: number;
}
interface StructureElement {
  id: number;
  node_i: number;
  node_j: number;
  type?: string;
}

interface IFCViewerProps {
  ifcUrl?: string;
  ifcData?: string;
  structure?: {
    nodes: StructureNode[];
    elements: StructureElement[];
  } | null;
  onElementClick?: (elementId: number) => void;
  highlightedElements?: number[];
  removedElements?: number[];
}

// ── Constants ─────────────────────────────────────────────────────────────────
const GROUND_Y = -0.8;

// ── Helpers ───────────────────────────────────────────────────────────────────
function disposeMesh(obj: THREE.Object3D) {
  if (obj instanceof THREE.Mesh) {
    obj.geometry?.dispose();
    if (Array.isArray(obj.material)) obj.material.forEach((m) => m.dispose());
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

// ── Component ─────────────────────────────────────────────────────────────────
export function IFCViewer({
  ifcUrl,
  ifcData,
  structure,
  onElementClick,
  highlightedElements,
  removedElements,
}: IFCViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);

  // Three.js core refs
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const modelGroupRef = useRef<THREE.Group>(null!);
  const elementMeshMap = useRef<Map<number, THREE.Mesh>>(new Map());

  // State
  const [loading, setLoading] = useState(false);
  const [loadProgress, setLoadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [elementCount, setElementCount] = useState(0);
  const [hasIFCViewer] = useState(hasIFC);

  // ── 1. Init Three.js Scene (once on mount) ─────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
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

    // Camera
    const camera = new THREE.PerspectiveCamera(50, w / h, 0.5, 200);
    camera.position.set(5, 5, 10);
    cameraRef.current = camera;

    // Controls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 1;
    controls.maxDistance = 80;
    controls.maxPolarAngle = Math.PI * 0.85;
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

    // Ground + grid
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

    // Model group
    const mg = new THREE.Group();
    mg.name = "model";
    scene.add(mg);
    modelGroupRef.current = mg;

    // ResizeObserver
    const ro = new ResizeObserver(() => {
      const c = canvasRef.current;
      const cam = cameraRef.current;
      const ren = rendererRef.current;
      if (!c || !cam || !ren) return;
      const cw = c.clientWidth;
      const ch = c.clientHeight;
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
      [scene, mg].forEach((g) =>
        g.traverse((obj) => {
          if (obj instanceof THREE.Mesh) {
            obj.geometry?.dispose();
            if (Array.isArray(obj.material)) obj.material.forEach((m) => m.dispose());
            else obj.material?.dispose();
          }
        }),
      );
    };
  }, []);

  // ── 2. Fit Camera to Bounding Box ───────────────────────────
  const fitCamera = useCallback(() => {
    const mg = modelGroupRef.current;
    const cam = cameraRef.current;
    const ctrl = controlsRef.current;
    if (!mg || !cam || !ctrl) return;

    const box = new THREE.Box3().setFromObject(mg);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z, 1);
    const dist = maxDim * 2.2;

    cam.position.set(center.x + dist * 0.6, center.y + dist * 0.5, center.z + dist);
    ctrl.target.copy(center);
    ctrl.update();
  }, []);

  // Separate function for fallback to avoid duplication
  function buildFallbackStructure(group: THREE.Group) {
    if (!structure?.nodes?.length || !structure?.elements?.length) return;

    const nodeMap = new Map(structure.nodes.map((n) => [n.id, { x: n.x, y: n.y, z: n.z ?? 0 }]));

    // Build elements as boxes
    const matBeam = new THREE.MeshStandardMaterial({
      color: "#22d3ee",
      roughness: 0.35,
      metalness: 0.7,
    });
    const matCol = new THREE.MeshStandardMaterial({
      color: "#64748b",
      roughness: 0.35,
      metalness: 0.7,
    });

    for (const elem of structure.elements) {
      const ni = nodeMap.get(elem.node_i);
      const nj = nodeMap.get(elem.node_j);
      if (!ni || !nj) continue;

      const p1 = new THREE.Vector3(ni.x, ni.y, ni.z);
      const p2 = new THREE.Vector3(nj.x, nj.y, nj.z);
      const dir = new THREE.Vector3().subVectors(p2, p1);
      const len = dir.length();
      if (len < 0.001) continue;

      const isColumn = Math.abs(ni.x - nj.x) < 0.01 && Math.abs(ni.z - nj.z) < 0.01;
      const isBeam = elem.type === "beam" || (!isColumn && Math.abs(ni.y - nj.y) < 0.01);
      const section = isColumn ? 0.24 : isBeam ? 0.18 : 0.15;

      const mid = new THREE.Vector3().addVectors(p1, p2).multiplyScalar(0.5);
      const geo = new THREE.BoxGeometry(section, section, len);
      const mat = isColumn ? matCol.clone() : matBeam.clone();
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.copy(mid);
      const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), dir.normalize());
      mesh.setRotationFromQuaternion(q);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.userData = { elementId: elem.id, isColumn, isBeam };
      group.add(mesh);
      elementMeshMap.current.set(elem.id, mesh);
    }
    setElementCount(elementMeshMap.current.size);

    // Build nodes as small spheres
    const matNode = new THREE.MeshStandardMaterial({
      color: "#94a3b8",
      roughness: 0.3,
      metalness: 0.8,
    });
    for (const n of structure.nodes) {
      const sphere = new THREE.Mesh(new THREE.SphereGeometry(0.12, 12, 12), matNode.clone());
      sphere.position.set(n.x, n.y, n.z ?? 0);
      sphere.userData = { nodeId: n.id };
      group.add(sphere);
    }

    // Fit camera after a tick
    setTimeout(fitCamera, 50);
  }

  // ── 3. Load IFC or Build Fallback ───────────────────────────
  useEffect(() => {
    const mg = modelGroupRef.current;
    if (!mg) return;

    clearGroup(mg);
    elementMeshMap.current.clear();
    setError(null);

    // Attempt IFC loading
    const hasIfcData = hasIFC && (ifcUrl || ifcData);
    if (hasIfcData && typeof window !== "undefined") {
      // Dynamic import to avoid require() at module scope
      const loadIFC = async () => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        let IFCLoaderClass: any;
        try {
          const mod = await import("web-ifc-three/IFCLoader");
          IFCLoaderClass = mod.IFCLoader;
        } catch {
          // IFC not available, fallback
          buildFallbackStructure(mg);
          return;
        }
        if (!IFCLoaderClass) {
          buildFallbackStructure(mg);
          return;
        }
        // Defer setState out of effect to avoid react-hooks/set-state-in-effect
        const t = setTimeout(() => {
          setLoading(true);
          setLoadProgress(0);
        }, 0);

        const loader = new IFCLoaderClass();

        loader.setOnProgress((event: { loaded: number; total: number }) => {
          const pct = event.total > 0 ? Math.round((event.loaded / event.total) * 100) : 0;
          setLoadProgress(pct);
        });

        const onLoad = (ifcModel: THREE.Mesh & { modelID?: number }) => {
          clearTimeout(t);
          setLoading(false);
          setLoadProgress(100);
          mg.add(ifcModel);

          if (ifcModel.modelID !== undefined) {
            mg.traverse((child) => {
              if (child instanceof THREE.Mesh && child.userData?.expressID !== undefined) {
                const expressId = child.userData.expressID as number;
                elementMeshMap.current.set(expressId, child);
              }
            });
          }

          setTimeout(fitCamera, 100);
        };

        const onError = (err: Error) => {
          clearTimeout(t);
          setLoading(false);
          setError(`IFC load failed: ${err.message}`);
          console.error("IFC load error:", err);
          buildFallbackStructure(mg);
        };

        try {
          if (ifcUrl) {
            loader.load(ifcUrl, onLoad, undefined, onError);
          } else if (ifcData) {
            const isBase64 =
              ifcData.length > 100 &&
              /^[A-Za-z0-9+/=]+$/.test(ifcData.substring(0, 100));
            if (isBase64) {
              const binary = atob(ifcData);
              loader.parse(binary, onLoad);
            } else {
              loader.parse(ifcData, onLoad);
            }
          }
        } catch (e) {
          clearTimeout(t);
          setLoading(false);
          setError(`IFC operation failed: ${e instanceof Error ? e.message : "Unknown error"}`);
          buildFallbackStructure(mg);
        }
      };
      loadIFC();
      return;
    }

    // No IFC data or no IFC viewer — build fallback from structure prop
    if (!hasIfcData && structure?.nodes?.length && structure?.elements?.length) {
      buildFallbackStructure(mg);
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ifcUrl, ifcData, structure, fitCamera]);

  // ── 4. Highlight / Removed Elements ─────────────────────────
  useEffect(() => {
    const emap = elementMeshMap.current;
    if (emap.size === 0) return;

    const highlightSet = new Set(highlightedElements || []);
    const removedSet = new Set(removedElements || []);

    for (const [id, mesh] of emap) {
      const hl = highlightSet.has(id);
      const rm = removedSet.has(id);

      // eslint-disable-next-line react-hooks/immutability
      mesh.visible = !rm;

      if (hl) {
        const mat = mesh.material as THREE.MeshStandardMaterial;
        const origColor = mat.color.clone();
        mat.color.set("#f97316");
        mat.emissive?.set("#f97316");
        mat.emissiveIntensity = 0.6;
        mesh.userData._origColor = origColor;
      } else if (mesh.userData._origColor) {
        const mat = mesh.material as THREE.MeshStandardMaterial;
        mat.color.copy(mesh.userData._origColor);
        mat.emissive?.set("#000000");
        mat.emissiveIntensity = 0;
        delete mesh.userData._origColor;
      }
    }
  }, [highlightedElements, removedElements]);

  // ── 5. Raycaster Click Handler ───────────────────────────────
  useEffect(() => {
    const renderer = rendererRef.current;
    const cam = cameraRef.current;
    const mg = modelGroupRef.current;
    const ctrl = controlsRef.current;
    if (!renderer || !cam || !mg || !ctrl) return;

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();

    function onClick(event: MouseEvent) {
      if (!renderer || !cam) return;
      // Compute pointer position in normalized device coordinates
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(pointer, cam);

      // Collect all meshes in the model group
      const meshes: THREE.Mesh[] = [];
      mg.traverse((child) => {
        if (child instanceof THREE.Mesh) meshes.push(child);
      });

      const intersects = raycaster.intersectObjects(meshes, false);
      if (intersects.length > 0) {
        const hit = intersects[0].object;
        const elementId = hit.userData?.elementId ?? hit.userData?.expressID;
        if (elementId !== undefined) {
          onElementClick?.(elementId);
        }
      }
    }

    renderer.domElement.addEventListener("click", onClick);
    return () => renderer.domElement.removeEventListener("click", onClick);
  }, [onElementClick]);

  // ── Reset Camera ─────────────────────────────────────────────
  const resetCamera = useCallback(() => {
    fitCamera();
  }, [fitCamera]);

  // ── Zoom ────────────────────────────────────────────────────
  const zoomStep = useCallback((dir: number) => {
    const cam = cameraRef.current;
    const ctrl = controlsRef.current;
    if (!cam || !ctrl) return;
    const dirVec = new THREE.Vector3().subVectors(cam.position, ctrl.target).normalize();
    const dist = cam.position.distanceTo(ctrl.target);
    const newDist = Math.max(1, Math.min(80, dist + dir * dist * 0.15));
    cam.position.copy(ctrl.target).add(dirVec.multiplyScalar(newDist));
    cam.updateProjectionMatrix();
    ctrl.update();
  }, []);

  // ── Render ──────────────────────────────────────────────────
  return (
    <div ref={containerRef} className="flex-1 flex flex-col min-h-0">
      {/* Canvas */}
      <div ref={canvasRef} className="flex-1 relative bg-xuanwu-deep overflow-hidden">
        {/* Loading Overlay */}
        {loading && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-xuanwu-deep/80 gap-3">
            <Loader2 className="h-8 w-8 text-primary animate-spin" />
            <div className="flex items-center gap-2">
              <div className="w-32 h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-300"
                  style={{ width: `${loadProgress}%` }}
                />
              </div>
              <span className="text-xs text-muted-foreground tabular-nums">{loadProgress}%</span>
            </div>
            <p className="text-sm text-muted-foreground">Loading IFC model...</p>
          </div>
        )}

        {/* Error Overlay */}
        {error && (
          <div className="absolute top-3 left-3 z-20 bg-red-900/60 border border-red-500/30 rounded-md px-3 py-2 text-xs text-red-300 max-w-[300px]">
            {error}
          </div>
        )}

        {/* IFC unavailable message */}
        {!hasIFCViewer && (ifcUrl || ifcData) && (
          <div className="absolute top-12 left-3 z-20 bg-amber-900/40 border border-amber-500/30 rounded-md px-3 py-2 text-xs text-amber-300">
            IFC Viewer not available — falling back to structure display
          </div>
        )}

        {/* Toolbar */}
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
            <Move className="h-3 w-3 inline" /> Drag to orbit · Scroll to zoom · Click element to select
          </span>
        </div>

        {/* Status bar */}
        <div className="absolute bottom-3 right-3 z-10 bg-background/80 border border-border rounded-md px-2.5 py-1 pointer-events-none flex items-center gap-2">
          {structure?.elements?.length ? (
            <span className="text-[10px] text-muted-foreground tabular-nums">
              {elementCount} elements
            </span>
          ) : ifcUrl && !loading ? (
            <span className="text-[10px] text-emerald-400">IFC loaded</span>
          ) : (
            <span className="text-[10px] text-muted-foreground">No data</span>
          )}
        </div>
      </div>
    </div>
  );
}
