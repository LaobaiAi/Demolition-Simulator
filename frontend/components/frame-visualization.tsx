"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Eye, Film, Maximize2, Minimize2, Settings2 } from "lucide-react";

interface FrameNode {
  id: number;
  x: number;
  y: number;
}

interface FrameElement {
  id: number;
  node_i: number;
  node_j: number;
  E?: number;
  A?: number;
  I?: number;
}

interface FrameLoad {
  node_id: number;
  Fx: number;
  Fy: number;
}

interface FrameSupport {
  node_id: number;
  type: string;
}

interface FrameStructure {
  nodes: FrameNode[];
  elements: FrameElement[];
  loads: FrameLoad[];
  supports: FrameSupport[];
}

interface NodeDisplacement {
  node_id: number;
  ux: number;
  uy: number;
}

interface ElemForce {
  element_id: number;
  Nmax: number;
  Nmin: number;
  Mmax: number;
  Mmin: number;
  Qmax: number;
  Qmin: number;
}

interface Props {
  structure: FrameStructure | null;
  displacements?: NodeDisplacement[] | null;
  criticalElementId?: number | null;
  failedElements?: number[];
  maxDisplacement?: number;
  elementForces?: ElemForce[];
  // Animation replay
  animationTrigger?: number;
  animatingElements?: number[];
  onAnimationComplete?: () => void;
}

type ViewMode = "deformation" | "stress";

export function FrameVisualization({
  structure,
  displacements,
  criticalElementId,
  failedElements,
  maxDisplacement,
  elementForces,
  animationTrigger,
  animatingElements,
  onAnimationComplete,
}: Props) {
  const [tab, setTab] = useState<"structure" | "animation">("structure");
  const [viewMode, setViewMode] = useState<ViewMode>("deformation");

  // Explore mode: zoom/pan within the SVG
  const [exploreMode, setExploreMode] = useState(false);
  const [svgScale, setSvgScale] = useState(1);
  const [svgPanX, setSvgPanX] = useState(0);
  const [svgPanY, setSvgPanY] = useState(0);
  const [legendScale, setLegendScale] = useState(1);
  const [legendSettingsOpen, setLegendSettingsOpen] = useState(false);
  const svgContainerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ active: boolean; startX: number; startY: number; panX: number; panY: number }>({
    active: false,
    startX: 0,
    startY: 0,
    panX: 0,
    panY: 0,
  });

  const resetExplore = useCallback(() => {
    setExploreMode(false);
    setSvgScale(1);
    setSvgPanX(0);
    setSvgPanY(0);
    dragRef.current.active = false;
  }, []);

  // Mouse leave auto-disables explore mode
  const handleMouseLeave = () => {
    if (exploreMode) {
      resetExplore();
    }
  };

  const handleWheel = (e: React.WheelEvent) => {
    if (!exploreMode) return;
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setSvgScale((prev) => Math.min(5, Math.max(0.5, prev * delta)));
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if (!exploreMode) return;
    if (e.button !== 0) return; // left button only
    dragRef.current = {
      active: true,
      startX: e.clientX,
      startY: e.clientY,
      panX: svgPanX,
      panY: svgPanY,
    };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!exploreMode || !dragRef.current.active) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    setSvgPanX(dragRef.current.panX + dx);
    setSvgPanY(dragRef.current.panY + dy);
  };

  const handleMouseUp = () => {
    dragRef.current.active = false;
  };

  // Auto-switch to Animation tab when a round is triggered
  useEffect(() => {
    if (animationTrigger && animatingElements?.length) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setTab("animation");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [animationTrigger]);

  if (!structure || !structure.nodes.length) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="flex flex-col items-center gap-6 text-center">
          <div className="relative">
            <div className="logo-spin">
              <svg width="120" height="120" viewBox="0 0 120 120" fill="none" className="opacity-60">
                <circle cx="60" cy="60" r="54" stroke="#22d3ee" strokeWidth="2" strokeDasharray="8 6" />
                <circle cx="60" cy="60" r="38" stroke="#22d3ee" strokeWidth="1.5" strokeDasharray="4 4" className="opacity-50" />
                <circle cx="60" cy="60" r="22" stroke="#22d3ee" strokeWidth="1" strokeDasharray="3 3" className="opacity-30" />
              </svg>
            </div>
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="flex flex-col items-center">
                <div className="h-8 w-1 bg-primary rounded-full" />
                <div className="h-2 w-6 bg-primary/60 rounded-full mt-1" />
              </div>
            </div>
          </div>
          <p className="text-lg font-medium text-foreground">Visualization Panel</p>
          <p className="text-sm text-muted-foreground">
            Send a frame analysis request to see the structure
          </p>
        </div>
      </div>
    );
  }

  const { nodes, elements, loads = [], supports = [] } = structure;

  // Compute bounds
  const minX = Math.min(...nodes.map((n) => n.x));
  const maxX = Math.max(...nodes.map((n) => n.x));
  const minY = Math.min(...nodes.map((n) => n.y));
  const maxY = Math.max(...nodes.map((n) => n.y));
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;

  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
  const dispMap = new Map<number, { ux: number; uy: number }>();
  if (displacements) {
    for (const d of displacements) {
      dispMap.set(d.node_id, { ux: d.ux, uy: d.uy });
    }
  }

  // Deformation scale factor
  const dispScale = maxDisplacement && maxDisplacement > 0
    ? (rangeX * 0.15) / maxDisplacement
    : 100;

  // SVG viewport with padding
  const pad = 60;
  const svgW = 600;
  const svgH = 400;
  const scaleX = (svgW - pad * 2) / rangeX;
  const scaleY = (svgH - pad * 2) / rangeY;
  const scale = Math.min(scaleX, scaleY);

  function toSvg(x: number, y: number, withDisp = false) {
    let sx = pad + (x - minX) * scale;
    let sy = svgH - pad - (y - minY) * scale; // flip Y

    if (withDisp) {
      const nodeId = nodes.find((n) => n.x === x && n.y === y)?.id;
      if (nodeId !== undefined) {
        const d = dispMap.get(nodeId);
        if (d) {
          sx += d.ux * scale * dispScale;
          sy -= d.uy * scale * dispScale;
        }
      }
    }

    return { x: sx, y: sy };
  }

  const hasDeformation = !!(displacements && displacements.length > 0);

  // Stress ratio computation
  const FY = 235e6; // Steel yield strength (Pa)
  const stressMap = new Map<number, number>();
  if (elementForces && elementForces.length > 0) {
    for (const ef of elementForces) {
      const elem = elements.find((e) => e.id === ef.element_id);
      if (elem && elem.A && elem.A > 0) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const N = Math.max(Math.abs(ef.Nmax ?? 0), Math.abs(ef.Nmin ?? 0), Math.abs((ef as any).N ?? 0));
        const ratio = N / (elem.A * FY);
        stressMap.set(ef.element_id, Math.min(ratio, 1.0));
      }
    }
  }
  const hasStress = stressMap.size > 0;

  function stressColor(ratio: number): string {
    if (ratio < 0.3) return "#22c55e"; // green - safe
    if (ratio < 0.6) return "#eab308"; // yellow - moderate
    if (ratio < 0.85) return "#f97316"; // orange - high
    return "#ef4444"; // red - critical
  }

  function stressLabel(ratio: number): string {
    return (ratio * 100).toFixed(0) + "%";
  }

  return (
    <div className="flex-1 flex flex-col">
      {/* Tabs + View mode toggle */}
      <div className="flex items-center justify-between border-b border-border px-4">
        <div className="flex items-center">
          <button
            onClick={() => setTab("structure")}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors cursor-pointer ${
              tab === "structure"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <Eye className="h-4 w-4" />
            Structure Model
          </button>
          <button
            onClick={() => setTab("animation")}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors cursor-pointer ${
              tab === "animation"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <Film className="h-4 w-4" />
            Animation
          </button>
        </div>
        {/* View mode toggle + Settings */}
        <div className="flex items-center gap-2">
          {tab === "structure" && hasStress && (
            <div className="flex items-center gap-1 bg-secondary/50 rounded-lg p-0.5">
              <button
                onClick={() => setViewMode("deformation")}
                className={`px-3 py-1 text-[11px] font-medium rounded-md transition-colors cursor-pointer ${
                  viewMode === "deformation"
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Deformation
              </button>
              <button
                onClick={() => setViewMode("stress")}
                className={`px-3 py-1 text-[11px] font-medium rounded-md transition-colors cursor-pointer ${
                  viewMode === "stress"
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Stress Ratio
              </button>
            </div>
          )}
          <div className="relative">
            <button
              onClick={() => setLegendSettingsOpen(!legendSettingsOpen)}
              className={`p-1.5 rounded-md border transition-all cursor-pointer ${
                legendSettingsOpen
                  ? "bg-primary/20 border-primary text-primary"
                  : "bg-background/80 border-border text-muted-foreground hover:text-foreground hover:border-primary/50"
              }`}
              title="Legend settings"
            >
              <Settings2 className="h-3.5 w-3.5" />
            </button>
            {legendSettingsOpen && (
              <div className="absolute right-0 top-full mt-1 z-20 bg-popover border border-border rounded-lg p-3 shadow-xl min-w-[160px]">
                <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-2">Legend Size</div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setLegendScale((s) => Math.max(0.5, s - 0.1))}
                    className="w-6 h-6 rounded border border-border text-muted-foreground hover:text-foreground hover:border-primary/50 text-xs cursor-pointer"
                  >-</button>
                  <span className="text-xs font-mono text-foreground min-w-[36px] text-center">{(legendScale * 100).toFixed(0)}%</span>
                  <button
                    onClick={() => setLegendScale((s) => Math.min(2.5, s + 0.1))}
                    className="w-6 h-6 rounded border border-border text-muted-foreground hover:text-foreground hover:border-primary/50 text-xs cursor-pointer"
                  >+</button>
                </div>
                <input
                  type="range"
                  min={50}
                  max={250}
                  value={Math.round(legendScale * 100)}
                  onChange={(e) => setLegendScale(Number(e.target.value) / 100)}
                  className="w-full mt-2 h-1 accent-primary cursor-pointer"
                />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Content */}
      {tab === "structure" ? (
        <div
          ref={svgContainerRef}
          className="flex-1 flex items-center justify-center p-4 relative"
          onMouseLeave={handleMouseLeave}
        >
          {/* Explore mode toggle */}
          <button
            onClick={() => {
              if (exploreMode) resetExplore();
              else setExploreMode(true);
            }}
            className={`absolute top-3 right-3 z-10 p-1.5 rounded-md border transition-all cursor-pointer ${
              exploreMode
                ? "bg-primary/20 border-primary text-primary"
                : "bg-background/80 border-border text-muted-foreground hover:text-foreground hover:border-primary/50"
            }`}
            title={exploreMode ? "Exit explore mode" : "Explore mode: zoom & pan"}
          >
            {exploreMode ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
          {exploreMode && (
            <div className="absolute top-12 right-3 z-10 bg-background/90 border border-border rounded-md px-2 py-1 text-[10px] text-muted-foreground">
              Scroll to zoom · Drag to pan
            </div>
          )}
          <svg data-xw-svg="main"
            viewBox={`0 0 ${svgW} ${svgH}`}
            className="w-full h-full"
            // eslint-disable-next-line react-hooks/refs
            style={{ cursor: exploreMode ? (dragRef.current.active ? "grabbing" : "grab") : "default" }}
            onWheel={handleWheel}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
          >
            <g transform={`translate(${svgPanX}, ${svgPanY}) scale(${svgScale})`}>
            {/* Grid lines */}
            {Array.from({ length: 6 }).map((_, i) => (
              <line
                key={`grid-h-${i}`}
                x1={pad}
                y1={pad + i * (svgH - pad * 2) / 5}
                x2={svgW - pad}
                y2={pad + i * (svgH - pad * 2) / 5}
                stroke="var(--border)"
                strokeWidth={0.5}
              />
            ))}
            {Array.from({ length: 8 }).map((_, i) => (
              <line
                key={`grid-v-${i}`}
                x1={pad + i * (svgW - pad * 2) / 7}
                y1={pad}
                x2={pad + i * (svgW - pad * 2) / 7}
                y2={svgH - pad}
                stroke="var(--border)"
                strokeWidth={0.5}
              />
            ))}

            {/* Undeformed elements (ghost) */}
            {hasDeformation &&
              elements.map((elem) => {
                const ni = nodeMap.get(elem.node_i)!;
                const nj = nodeMap.get(elem.node_j)!;
                const p1 = toSvg(ni.x, ni.y, false);
                const p2 = toSvg(nj.x, nj.y, false);
                const isColumn = Math.abs(ni.x - nj.x) < 0.01;
                return (
                  <line
                    key={`orig-${elem.id}`}
                    x1={p1.x}
                    y1={p1.y}
                    x2={p2.x}
                    y2={p2.y}
                    stroke="var(--border)"
                    strokeWidth={isColumn ? 3 : 2}
                    strokeDasharray="4 3"
                  />
                );
              })}

            {/* Elements */}
            {elements.map((elem) => {
              const ni = nodeMap.get(elem.node_i)!;
              const nj = nodeMap.get(elem.node_j)!;
              const p1 = toSvg(ni.x, ni.y, hasDeformation);
              const p2 = toSvg(nj.x, nj.y, hasDeformation);
              const isColumn = Math.abs(ni.x - nj.x) < 0.01;
              const isCritical = elem.id === criticalElementId;
              const isFailed = failedElements?.includes(elem.id);
              const ratio = stressMap.get(elem.id);
              const isStressMode = tab === "structure" && viewMode === "stress" && hasStress;

              let strokeColor = "#22d3ee";
              if (isFailed) strokeColor = "#ef4444";
              else if (isStressMode && ratio !== undefined) strokeColor = stressColor(ratio);
              else if (isCritical) strokeColor = "#f97316";

              const midX = (p1.x + p2.x) / 2;
              const midY = (p1.y + p2.y) / 2;

              // Offset label perpendicular to element to avoid overlap
              const labelOffsetX = isColumn ? 14 : 0;
              const labelOffsetY = isColumn ? 0 : -14;

              return (
                <g key={elem.id}>
                  <line
                    x1={p1.x}
                    y1={p1.y}
                    x2={p2.x}
                    y2={p2.y}
                    stroke={strokeColor}
                    strokeWidth={
                      isCritical ? 4 : isFailed ? 3 : isColumn ? 3 : 2
                    }
                    strokeDasharray={isFailed ? "6 2" : undefined}
                    className={isCritical ? "animate-pulse" : ""}
                  />
                  {/* Stress ratio label — offset perpendicular to element */}
                  {isStressMode && ratio !== undefined && (
                    <g>
                      <rect x={midX - 16 + labelOffsetX} y={midY - 10 + labelOffsetY} width={32} height={16} rx={3}
                        fill="var(--xuanwu-surface)" stroke={stressColor(ratio)} strokeWidth={0.8} opacity={0.9} />
                      <text x={midX + labelOffsetX} y={midY + 1 + labelOffsetY} textAnchor="middle"
                        fill={stressColor(ratio)} fontSize={9} fontWeight="bold">
                        {stressLabel(ratio)}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}

            {/* Supports */}
            {supports.map((sup) => {
              const n = nodeMap.get(sup.node_id)!;
              const p = toSvg(n.x, n.y, false);
              const triSize = 10;

              if (sup.type === "fixed") {
                return (
                  <g key={`sup-${sup.node_id}`}>
                    <line
                      x1={p.x - triSize}
                      y1={p.y}
                      x2={p.x + triSize}
                      y2={p.y}
                      stroke="#94a3b8"
                      strokeWidth={2}
                    />
                    {[-triSize, 0, triSize].map((dx) => (
                      <line
                        key={dx}
                        x1={p.x + dx}
                        y1={p.y}
                        x2={p.x + dx + 5}
                        y2={p.y + 8}
                        stroke="#94a3b8"
                        strokeWidth={1.5}
                      />
                    ))}
                  </g>
                );
              }
              if (sup.type === "hinged") {
                return (
                  <g key={`sup-${sup.node_id}`}>
                    <line
                      x1={p.x - triSize}
                      y1={p.y}
                      x2={p.x + triSize}
                      y2={p.y}
                      stroke="#94a3b8"
                      strokeWidth={2}
                    />
                    <circle cx={p.x} cy={p.y} r={4} fill="none" stroke="#94a3b8" strokeWidth={1.5} />
                    {[-triSize, triSize].map((dx) => (
                      <line
                        key={dx}
                        x1={p.x + dx}
                        y1={p.y}
                        x2={p.x + dx + 5}
                        y2={p.y + 8}
                        stroke="#94a3b8"
                        strokeWidth={1.5}
                      />
                    ))}
                  </g>
                );
              }
              if (sup.type === "roller") {
                return (
                  <g key={`sup-${sup.node_id}`}>
                    <line
                      x1={p.x - triSize}
                      y1={p.y}
                      x2={p.x + triSize}
                      y2={p.y}
                      stroke="#94a3b8"
                      strokeWidth={2}
                    />
                    <circle cx={p.x - 5} cy={p.y + 6} r={3} fill="none" stroke="#94a3b8" strokeWidth={1} />
                    <circle cx={p.x + 5} cy={p.y + 6} r={3} fill="none" stroke="#94a3b8" strokeWidth={1} />
                  </g>
                );
              }
              return null;
            })}

            {/* Nodes */}
            {nodes.map((n) => {
              const p = toSvg(n.x, n.y, hasDeformation);
              const isTopNode = n.y === maxY && loads.some((l) => l.node_id === n.id);
              return (
                <g key={`node-${n.id}`}>
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r={isTopNode ? 4.5 : 3.5}
                    fill={n.y === 0 ? "#64748b" : "#0f172a"}
                    stroke={isTopNode ? "#f59e0b" : "#22d3ee"}
                    strokeWidth={1.5}
                  />
                </g>
              );
            })}

            {/* Load arrows at top nodes */}
            {loads.map((load) => {
              const n = nodeMap.get(load.node_id)!;
              const p = toSvg(n.x, n.y, hasDeformation);
              const arrowLen = Math.min(30, Math.abs(load.Fy / 5000) * 20);
              return (
                <g key={`load-${load.node_id}`}>
                  <line
                    x1={p.x}
                    y1={p.y}
                    x2={p.x}
                    y2={p.y + arrowLen}
                    stroke="#f59e0b"
                    strokeWidth={2}
                    markerEnd="url(#arrowhead)"
                  />
                  {/* Arrowhead */}
                  <defs>
                    <marker
                      id="arrowhead"
                      viewBox="0 0 10 10"
                      refX={5}
                      refY={10}
                      markerWidth={6}
                      markerHeight={6}
                      orient="auto"
                    >
                      <path d="M0 0 L5 10 L10 0" fill="#f59e0b" />
                    </marker>
                  </defs>
                </g>
              );
            })}

            </g>
            {/* Legend — fixed position, not affected by pan/zoom */}
            {tab === "structure" && viewMode === "stress" && hasStress ? (
              <g transform={`translate(10, 10) scale(${legendScale})`}>
                <rect x={0} y={0} width={170} height={90} rx={6} fill="var(--xuanwu-surface)" stroke="var(--border)" strokeWidth={1} />
                <text x={10} y={18} fill="var(--muted-foreground)" fontSize={9}>Stress Ratio</text>
                {[0, 30, 60, 85, 100].map((pct, i) => (
                  <rect key={i} x={10 + i * 31} y={24} width={29} height={10} rx={2}
                    fill={stressColor(pct / 100)} opacity={0.85} />
                ))}
                <text x={10} y={46} fill="#22c55e" fontSize={7}>Safe</text>
                <text x={165} y={46} fill="#ef4444" fontSize={7} textAnchor="end">Critical</text>
                <text x={10} y={60} fill="var(--muted-foreground)" fontSize={7}>Stress = |N| / (A * fy)</text>
                <text x={10} y={78} fill="var(--muted-foreground)" fontSize={8}>
                  {elements.length} elems, {nodes.length} nodes
                </text>
              </g>
            ) : (
              <g transform={`translate(10, 10) scale(${legendScale})`}>
                <rect x={0} y={0} width={170} height={90} rx={6} fill="var(--xuanwu-surface)" stroke="var(--border)" strokeWidth={1} />
                <text x={10} y={20} fill="var(--muted-foreground)" fontSize={9}>Legend</text>
                <line x1={10} y1={32} x2={40} y2={32} stroke="#22d3ee" strokeWidth={2} />
                <text x={44} y={35} fill="var(--muted-foreground)" fontSize={8}>Element</text>
                {criticalElementId != null && (
                  <>
                    <line x1={10} y1={48} x2={40} y2={48} stroke="#f97316" strokeWidth={3} />
                    <text x={44} y={51} fill="#f97316" fontSize={8}>Critical Column #{criticalElementId}</text>
                  </>
                )}
                {hasDeformation && (
                  <>
                    <line x1={10} y1={64} x2={40} y2={64} stroke="var(--border)" strokeWidth={2} strokeDasharray="4 3" />
                    <text x={44} y={67} fill="var(--muted-foreground)" fontSize={8}>Original shape</text>
                  </>
                )}
                <text x={10} y={80} fill="var(--muted-foreground)" fontSize={8}>
                  Scale: {rangeX.toFixed(0)}m x {rangeY.toFixed(0)}m — {elements.length} elems, {nodes.length} nodes
                </text>
              </g>
            )}
          </svg>
        </div>
      ) : (
        <CollapseAnimation
          structure={structure}
          failedElements={failedElements || []}
          animatingElements={animatingElements}
          animationTrigger={animationTrigger}
          onAnimationComplete={onAnimationComplete}
        />
      )}
    </div>
  );
}

// ── Collapse Animation Component ────────────────────────────────────────────

type EffectKey = 'cascade' | 'explosion' | 'dust' | 'shake' | 'buckling' | 'fracture' | 'flash' | 'trail' | 'bounce';

interface DebrisParticle {
  x: number; y: number;
  vx: number; vy: number;
  size: number; color: string;
  baseOpacity: number;
  rotation: number; rotSpeed: number;
  groundY: number;
  delay: number; lifetime: number;
  didBounce: boolean;
}

interface DustCloud {
  cx: number; cy: number;
  maxR: number; delay: number;
}
interface ImpactRing {
  cx: number; cy: number;
  maxR: number; delay: number;
  duration: number;
}

const EFFECT_DEFS: { key: EffectKey; label: string; desc: string; score: number; color: string }[] = [
  { key: 'cascade',  label: 'Cascade',  desc: '由下至上逐层倒塌', score: 25, color: '#22c55e' },
  { key: 'explosion',label: 'Debris',   desc: '爆炸碎片飞散',     score: 15, color: '#f97316' },
  { key: 'dust',     label: 'Dust',     desc: '底部烟尘扩散',     score: 10, color: '#94a3b8' },
  { key: 'shake',    label: 'Shake',    desc: '撞击视口抖动',     score: 10, color: '#eab308' },
  { key: 'buckling', label: 'Buckling', desc: '梁中部弯折',       score: 15, color: '#22d3ee' },
  { key: 'fracture', label: 'Fracture', desc: '长杆断裂多段',     score: 10, color: '#a855f7' },
  { key: 'flash',    label: 'Flash',    desc: '失效前红色闪烁',   score:  5, color: '#ef4444' },
  { key: 'trail',    label: 'Trail',    desc: '下落烟迹拖尾',     score:  5, color: '#78716c' },
  { key: 'bounce',   label: 'Bounce',   desc: '碎片地面弹跳',     score:  5, color: '#f59e0b' },
];

function CollapseAnimation({
  structure,
  failedElements,
  animatingElements,
  animationTrigger,
  onAnimationComplete,
}: {
  structure: FrameStructure;
  failedElements: number[];
  animatingElements?: number[];
  animationTrigger?: number;
  onAnimationComplete?: () => void;
}) {
  const { nodes, elements, loads = [], supports = [] } = structure;
  const [frame, setFrame] = useState(0);
  const rafRef = useRef<number>(0);
  const startRef = useRef<number>(0);
  const lastFrameRef = useRef<number>(0);
  const DURATION = 5000;

  // Effects toggles
  const [effectsOpen, setEffectsOpen] = useState(true);
  const [effects, setEffects] = useState<Record<string, boolean>>(() => {
    const r: Record<string, boolean> = {};
    EFFECT_DEFS.forEach(d => r[d.key] = true);
    return r;
  });
  const toggleEffect = (k: EffectKey) => setEffects(p => ({ ...p, [k]: !p[k] }));
  const e = effects;

  // Explore mode
  const [animExplore, setAnimExplore] = useState(false);
  const [animScale, setAnimScale] = useState(1);
  const [animPanX, setAnimPanX] = useState(0);
  const [animPanY, setAnimPanY] = useState(0);
  const dragRef = useRef<{active:boolean; startX:number; startY:number; panX:number; panY:number}>({active:false, startX:0, startY:0, panX:0, panY:0});
  const resetAnimExplore = () => { setAnimExplore(false); setAnimScale(1); setAnimPanX(0); setAnimPanY(0); dragRef.current.active = false; };

  // SVG bounds
  const minX = Math.min(...nodes.map(n => n.x));
  const maxX = Math.max(...nodes.map(n => n.x));
  const minY = Math.min(...nodes.map(n => n.y));
  const maxY = Math.max(...nodes.map(n => n.y));
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  const pad = 60;
  const svgW = 600;
  const svgH = 400;
  const sc = Math.min((svgW - pad*2) / rangeX, (svgH - pad*2) / rangeY);

  function toSvg(x: number, y: number) {
    return { x: pad + (x - minX) * sc, y: svgH - pad - (y - minY) * sc };
  }

  const nodeMap = new Map(nodes.map(n => [n.id, n]));
  const failedSet = useMemo(() => new Set(failedElements), [failedElements]);

  // Elements to animate in the current round — subset of failedSet.
  // When animatingElements is provided, only those are animated;
  // other failedSet elements are hidden (already collapsed in prior rounds).
  const animActiveSet = useMemo(() => {
    if (animatingElements && animatingElements.length > 0) return new Set(animatingElements);
    return failedSet;
  }, [animatingElements, failedSet]);

  const failedNodeIds = useMemo(() => {
    const ids = new Set<number>();
    for (const elem of elements) if (failedSet.has(elem.id)) { ids.add(elem.node_i); ids.add(elem.node_j); }
    return ids;
  }, [elements, failedSet]);

  // ── Pre-computed animation data ───────────────────────────────────────

  const animData = useMemo(() => {
    const failedElems = elements.filter(e => animActiveSet.has(e.id));
    const withInfo = failedElems.map(el => {
      const ni = nodeMap.get(el.node_i)!;
      const nj = nodeMap.get(el.node_j)!;
      const minElemY = Math.min(ni.y, nj.y);
      const isColumn = Math.abs(ni.x - nj.x) < 0.01;
      const len = Math.hypot(nj.x - ni.x, nj.y - ni.y);
      const p1 = toSvg(ni.x, ni.y);
      const p2 = toSvg(nj.x, nj.y);
      return { id: el.id, minElemY, isColumn, len, p1, p2, ni, nj };
    });
    withInfo.sort((a, b) => a.minElemY - b.minElemY);
    const total = withInfo.length;
    const cascade = withInfo.map((e, i) => ({
      id: e.id, isColumn: e.isColumn, len: e.len,
      p1: e.p1, p2: e.p2,
      delay: total > 1 ? (i / (total - 1)) * 1500 : 0,
    }));

    // Debris
    const debris: DebrisParticle[] = [];
    for (const item of cascade) {
      const cx = (item.p1.x + item.p2.x) / 2;
      const cy = (item.p1.y + item.p2.y) / 2;
      const count = 6 + Math.floor(seedRand(item.id) * 5);
      for (let i = 0; i < count; i++) {
        const angle = seedRand(item.id * 100 + i * 7) * Math.PI * 2;
        const speed = 2 + seedRand(item.id * 200 + i * 13) * 5;
        const groundY = svgH - pad + 5 + seedRand(item.id * 300 + i * 23) * 20;
        debris.push({
          x: cx + (seedRand(item.id * 400 + i * 31) - 0.5) * 20,
          y: cy,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed - 3,
          size: 1.5 + seedRand(item.id * 500 + i * 37) * 3,
          color: item.isColumn ? '#ef4444' : '#f97316',
          baseOpacity: 0.6 + seedRand(item.id * 600 + i * 41) * 0.4,
          rotation: seedRand(item.id * 700 + i * 47) * 360,
          rotSpeed: (seedRand(item.id * 800 + i * 53) - 0.5) * 8,
          groundY,
          delay: item.delay + 100 + seedRand(item.id * 900 + i * 59) * 200,
          lifetime: 0.8 + seedRand(item.id * 1000 + i * 61) * 0.8,
          didBounce: false,
        });
      }
    }

    // Dust
    const dust: DustCloud[] = [];
    for (const item of cascade) {
      const cx = (item.p1.x + item.p2.x) / 2;
      for (let i = 0; i < 2; i++) {
        dust.push({
          cx: cx + (seedRand(item.id * 1100 + i * 67) - 0.5) * 50,
          cy: svgH - pad + 5 + seedRand(item.id * 1200 + i * 71) * 15,
          maxR: 12 + seedRand(item.id * 1300 + i * 73) * 20,
          delay: item.delay + 400 + seedRand(item.id * 1400 + i * 79) * 400,
        });
      }
    }

    // Impact rings — expand outward when elements hit ground
    const impactRings: ImpactRing[] = [];
    for (const item of cascade) {
      const cx = (item.p1.x + item.p2.x) / 2;
      impactRings.push({
        cx,
        cy: svgH - pad + 5,
        maxR: 15 + seedRand(item.id * 1500) * 25,
        delay: item.delay + 700,
        duration: 600 + seedRand(item.id * 1600) * 300,
      });
    }

    return { cascade, debris, dust, impactRings };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elements, animActiveSet, nodeMap, minX, minY, sc, pad, svgH]);

  // Deterministic pseudo-random (seeded for stable debris between renders)
  function seedRand(seed: number): number {
    const s = Math.sin(seed * 9301 + 49297) * 233280;
    return s - Math.floor(s);
  }

  // ── Animation loop ────────────────────────────────────────────────────

  useEffect(() => {
    // Only animate when animatingElements is explicitly provided.
    // When undefined → no pending animation (completed or never started).
    // This avoids replay on tab switch or state restore.
    const toAnimate = animatingElements;
    if (!toAnimate || toAnimate.length === 0) return;

    startRef.current = performance.now();
    lastFrameRef.current = 0;
    const animate = (t: number) => {
      const elapsed = t - startRef.current;
      if (elapsed < DURATION) {
        // Throttle to ~30fps for CPU efficiency
        if (elapsed - lastFrameRef.current >= 33) {
          setFrame(elapsed);
          lastFrameRef.current = elapsed;
        }
        rafRef.current = requestAnimationFrame(animate);
      } else {
        setFrame(DURATION);
        onAnimationComplete?.();
      }
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [animationTrigger]);

  // ── Per-frame helpers ─────────────────────────────────────────────────

  const t = frame; // ms elapsed
  const hasFailed = failedElements.length > 0;
  const totalProgress = Math.min(t / DURATION, 1);

  // Ease in/out
  function ease(p: number): number {
    return p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
  }

  // Compute position of an element at a given local time offset
  function elementLocalPos(cascadeItem: typeof animData.cascade[0], localT: number) {
    if (localT <= 0) return { x1: cascadeItem.p1.x, y1: cascadeItem.p1.y, x2: cascadeItem.p2.x, y2: cascadeItem.p2.y, fallProg: 0 };
    const fallDuration = 800;
    const fallProg = Math.min(localT / fallDuration, 1);
    const eProg = ease(fallProg);
    const fallDist = svgH * 0.6 * eProg;
    const cx = (cascadeItem.p1.x + cascadeItem.p2.x) / 2;
    const cy = (cascadeItem.p1.y + cascadeItem.p2.y) / 2;

    if (cascadeItem.isColumn) {
      // Column: lay flat with rotation
      const angle = eProg * 80;
      const rad = angle * Math.PI / 180;
      const dx1 = cascadeItem.p1.x - cx; const dy1 = cascadeItem.p1.y - cy;
      const dx2 = cascadeItem.p2.x - cx; const dy2 = cascadeItem.p2.y - cy;
      return {
        x1: cx + dx1 * Math.cos(rad) - dy1 * Math.sin(rad),
        y1: cy + fallDist + dx1 * Math.sin(rad) + dy1 * Math.cos(rad),
        x2: cx + dx2 * Math.cos(rad) - dy2 * Math.sin(rad),
        y2: cy + fallDist + dx2 * Math.sin(rad) + dy2 * Math.cos(rad),
        fallProg: eProg,
      };
    } else {
      // Beam: rotate downward
      const angle = eProg * 30 * ((cascadeItem.id % 2 === 0) ? 1 : -1);
      const rad = angle * Math.PI / 180;
      const dx1 = cascadeItem.p1.x - cx; const dy1 = cascadeItem.p1.y - cy;
      const dx2 = cascadeItem.p2.x - cx; const dy2 = cascadeItem.p2.y - cy;
      return {
        x1: cx + fallDist * 0.3 + dx1 * Math.cos(rad) - dy1 * Math.sin(rad),
        y1: cy + fallDist + dx1 * Math.sin(rad) + dy1 * Math.cos(rad),
        x2: cx + fallDist * 0.3 + dx2 * Math.cos(rad) - dy2 * Math.sin(rad),
        y2: cy + fallDist + dx2 * Math.sin(rad) + dy2 * Math.cos(rad),
        fallProg: eProg,
      };
    }
  }

  // ── Ground shake with pre-rumble ──────────────────────────────────────
  const shakeOn = e.shake && hasFailed;
  const firstHit = animData.cascade.length > 0 ? animData.cascade[0].delay + 600 : 0;
  // Pre-rumble: builds tension before first element falls
  const preRumble = shakeOn && hasFailed && t > 80 && t < firstHit && firstHit > 200
    ? Math.sin(t * 0.12) * 1.8 * Math.min(t / firstHit, 1)
    : 0;
  // Main impact shake
  const shakeElapsed = Math.max(0, t - firstHit);
  const shakeIntensity = shakeOn && shakeElapsed < 1000
    ? Math.sin(shakeElapsed * 0.08) * 4 * (1 - shakeElapsed / 1000)
    : 0;
  const totalShake = preRumble + shakeIntensity;
  const shakeX = totalShake * Math.sin(t * 0.05 + 1);
  const shakeY = totalShake * Math.sin(t * 0.07 + 2);

  // ── Red flash (three-phase: tension + warning + impact) ───────────────
  const flashWarning = e.flash && hasFailed && t > 0 && t < 800
    ? Math.sin((t / 800) * Math.PI) * 0.7
    : 0;
  const tensionPulse = e.flash && hasFailed && t > firstHit - 350 && t < firstHit - 50
    ? Math.sin(((t - firstHit + 350) / 300) * Math.PI) * 0.3
    : 0;
  const flashImpact = e.flash && hasFailed && t > firstHit - 100 && t < firstHit + 250
    ? Math.sin(((t - firstHit + 100) / 350) * Math.PI) * 0.5
    : 0;
  const flashOpacity = Math.max(flashWarning, tensionPulse, flashImpact);

  // ── Buckling midpoint helper ──────────────────────────────────────────
  function buckledMidpoint(origP1: {x:number,y:number}, origP2: {x:number,y:number}, prog: number) {
    const mx = (origP1.x + origP2.x) / 2;
    const my = (origP1.y + origP2.y) / 2;
    // Deflect downward proportional to progress
    const deflect = prog * 30;
    // Midpoint moves down, creating V shape
    const normalX = -(origP2.y - origP1.y);
    const normalY = (origP2.x - origP1.x);
    const nLen = Math.hypot(normalX, normalY) || 1;
    return {
      bx: mx + (normalX / nLen) * deflect * 0.3,
      by: my + (normalY / nLen) * deflect + prog * 40,
    };
  }

  // ── Fracture helper ───────────────────────────────────────────────────
  function fractureSegments(p1: {x:number,y:number}, p2: {x:number,y:number}, len: number, id: number) {
    const count = len > 6 ? 3 : 2;
    const segs: {x1:number,y1:number,x2:number,y2:number}[] = [];
    for (let i = 0; i < count; i++) {
      const frac1 = i / count;
      const frac2 = (i + 1) / count;
      const sx1 = p1.x + (p2.x - p1.x) * frac1;
      const sy1 = p1.y + (p2.y - p1.y) * frac1;
      const sx2 = p1.x + (p2.x - p1.x) * frac2;
      const sy2 = p1.y + (p2.y - p1.y) * frac2;
      const rOff = (seedRand(id * 1500 + i * 83) - 0.5) * 6;
      const rOff2 = (seedRand(id * 1600 + i * 89) - 0.5) * 6;
      segs.push({ x1: sx1 + rOff, y1: sy1 + rOff2, x2: sx2 + rOff2, y2: sy2 + rOff });
    }
    return segs;
  }

  // ── Render ────────────────────────────────────────────────────────────

  // Active score
  const activeScore = EFFECT_DEFS.filter(d => effects[d.key]).reduce((s, d) => s + d.score, 0);

  return (
    <div className="flex-1 flex flex-col relative">

      {/* ── Effects Settings Bar ── */}
      <div className="border-b border-border shrink-0">
        <button
          onClick={() => setEffectsOpen(!effectsOpen)}
          className="flex items-center gap-2 px-4 py-1.5 w-full text-left text-xs font-medium text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
        >
          <Settings2 className="h-3 w-3" />
          Effects ({activeScore}/100)
          <span className="text-[10px] text-muted-foreground/50">{effectsOpen ? '▲' : '▼'}</span>
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
              {EFFECT_DEFS.every(d => effects[d.key]) ? '全部禁用' : '全部启用'}
            </button>
            {EFFECT_DEFS.map(def => {
              const on = effects[def.key];
              return (
                <button
                  key={def.key}
                  onClick={() => toggleEffect(def.key)}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-medium border transition-all cursor-pointer ${
                    on
                      ? 'bg-primary/15 border-primary/40 text-primary'
                      : 'border-border/60 text-muted-foreground/50 hover:text-muted-foreground'
                  }`}
                  title={`${def.label}: ${def.desc} (${def.score}分)`}
                >
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: def.color, opacity: on ? 1 : 0.3 }} />
                  {def.label}
                  <span className={`text-[8px] ${on ? 'text-primary/60' : 'text-muted-foreground/30'}`}>{def.score}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* ── SVG Area ── */}
      <div
        className="flex-1 flex items-center justify-center p-4 relative"
        onMouseLeave={resetAnimExplore}
      >
        {/* Explore mode toggle */}
        <button
          onClick={() => { if (animExplore) resetAnimExplore(); else setAnimExplore(true); }}
          className={`absolute top-3 right-3 z-10 p-1.5 rounded-md border transition-all cursor-pointer ${
            animExplore ? 'bg-primary/20 border-primary text-primary' : 'bg-background/80 border-border text-muted-foreground hover:text-foreground hover:border-primary/50'
          }`}
          title={animExplore ? 'Exit explore mode' : 'Explore mode: zoom & pan'}
        >
          {animExplore ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
        </button>
        {animExplore && (
          <div className="absolute top-12 right-3 z-10 bg-background/90 border border-border rounded-md px-2 py-1 text-[10px] text-muted-foreground">
            Scroll to zoom · Drag to pan
          </div>
        )}

        <svg
          viewBox={`0 0 ${svgW} ${svgH}`}
          className="w-full h-full"
          // eslint-disable-next-line react-hooks/refs
          style={{ cursor: animExplore ? (dragRef.current.active ? 'grabbing' : 'grab') : 'default' }}
          onWheel={e => { if (!animExplore) return; e.preventDefault(); setAnimScale(p => Math.min(5, Math.max(0.5, p * (e.deltaY > 0 ? 0.9 : 1.1)))); }}
          onMouseDown={e => { if (!animExplore || e.button !== 0) return; dragRef.current = { active: true, startX: e.clientX, startY: e.clientY, panX: animPanX, panY: animPanY }; }}
          onMouseMove={e => { if (!animExplore || !dragRef.current.active) return; setAnimPanX(dragRef.current.panX + e.clientX - dragRef.current.startX); setAnimPanY(dragRef.current.panY + e.clientY - dragRef.current.startY); }}
          onMouseUp={() => { dragRef.current.active = false; }}
        >
          <g transform={`translate(${animPanX + shakeX}, ${animPanY + shakeY}) scale(${animScale})`}>

            {/* ── Grid ── */}
            {Array.from({ length: 6 }).map((_, i) => (
              <line key={`gh-${i}`} x1={pad} y1={pad + i * (svgH - pad*2)/5} x2={svgW-pad} y2={pad + i * (svgH - pad*2)/5} stroke="var(--border)" strokeWidth={0.5} />
            ))}
            {Array.from({ length: 8 }).map((_, i) => (
              <line key={`gv-${i}`} x1={pad + i * (svgW - pad*2)/7} y1={pad} x2={pad + i * (svgW - pad*2)/7} y2={svgH-pad} stroke="var(--border)" strokeWidth={0.5} />
            ))}

            {/* ── Smoke Trails ── */}
            {e.trail && hasFailed && animData.cascade.map(item => {
              const localT = t - item.delay;
              if (localT < 50 || localT > 2000) return null;
              return [40, 80, 130].map((offset, idx) => {
                const past = elementLocalPos(item, localT - offset);
                if (localT - offset <= 0) return null;
                const trailOpacity = (1 - idx * 0.3) * (1 - Math.min(localT / 2000, 1) * 0.5);
                return (
                  <g key={`trail-${item.id}-${idx}`}>
                    <circle cx={(past.x1 + past.x2) / 2} cy={(past.y1 + past.y2) / 2} r={2.5 - idx * 0.5}
                      fill="#78716c" opacity={trailOpacity * 0.4} />
                    <circle cx={(past.x1 + past.x2) / 2 + (idx-1)*3} cy={(past.y1 + past.y2) / 2 + 3}
                      r={2 - idx * 0.3} fill="#78716c" opacity={trailOpacity * 0.25} />
                  </g>
                );
              });
            })}

            {/* ── Supports ── */}
            {supports.map(sup => {
              const n = nodeMap.get(sup.node_id)!;
              const p = toSvg(n.x, n.y);
              const ts = 10;
              if (sup.type === "fixed") {
                return (
                  <g key={`sup-${sup.node_id}`}>
                    <line x1={p.x-ts} y1={p.y} x2={p.x+ts} y2={p.y} stroke="#94a3b8" strokeWidth={2} />
                    {[-ts, 0, ts].map(dx => <line key={dx} x1={p.x+dx} y1={p.y} x2={p.x+dx+5} y2={p.y+8} stroke="#94a3b8" strokeWidth={1.5} />)}
                  </g>
                );
              }
              if (sup.type === "hinged") {
                return (
                  <g key={`sup-${sup.node_id}`}>
                    <line x1={p.x-ts} y1={p.y} x2={p.x+ts} y2={p.y} stroke="#94a3b8" strokeWidth={2} />
                    <circle cx={p.x} cy={p.y} r={4} fill="none" stroke="#94a3b8" strokeWidth={1.5} />
                    {[-ts, ts].map(dx => <line key={dx} x1={p.x+dx} y1={p.y} x2={p.x+dx+5} y2={p.y+8} stroke="#94a3b8" strokeWidth={1.5} />)}
                  </g>
                );
              }
              return null;
            })}

            {/* ── Non-failed elements (ghost) ── */}
            {elements.map(elem => {
              if (failedSet.has(elem.id)) return null;
              const ni = nodeMap.get(elem.node_i)!;
              const nj = nodeMap.get(elem.node_j)!;
              const p = toSvg(ni.x, ni.y);
              const pj = toSvg(nj.x, nj.y);
              const isCol = Math.abs(ni.x - nj.x) < 0.01;
              const op = hasFailed ? 0.5 + 0.5 * (1 - totalProgress * 0.3) : 1;
              return (
                <line key={elem.id} x1={p.x} y1={p.y} x2={pj.x} y2={pj.y}
                  stroke="#22d3ee" strokeWidth={isCol ? 3 : 2} opacity={op} />
              );
            })}

            {/* ── Non-failed nodes ── */}
            {nodes.map(n => {
              if (failedNodeIds.has(n.id) && hasFailed) return null;
              const p = toSvg(n.x, n.y);
              const isTop = n.y === maxY && loads.some(l => l.node_id === n.id);
              return (
                <circle key={`node-${n.id}`} cx={p.x} cy={p.y}
                  r={isTop ? 4.5 : 3.5} fill={n.y === 0 ? '#64748b' : '#0f172a'}
                  stroke={isTop ? '#f59e0b' : '#22d3ee'} strokeWidth={1.5}
                  opacity={hasFailed ? 0.5 + 0.5 * (1 - totalProgress * 0.3) : 1} />
              );
            })}

            {/* ── Failed elements ── */}
            {hasFailed && e.cascade ? (
              // Cascade mode: staggered falls
              animData.cascade.map(item => {
                const localT = t - item.delay;
                const globalFlashed = e.flash && t < 500 && t > 0;
                const flashing = globalFlashed || (e.flash && localT >= -200 && localT < 50);
                const falling = localT > 0;

                if (!falling) {
                  // Not yet falling: show original position
                  const flashStroke = flashing ? '#ef4444' : '#ef4444';
                  const flashOpacity2 = flashing ? 0.3 + 0.7 * Math.sin(t * 0.02) : 0.6;
                  return (
                    <line key={item.id} x1={item.p1.x} y1={item.p1.y} x2={item.p2.x} y2={item.p2.y}
                      stroke={flashing ? flashStroke : '#ef4444'}
                      strokeWidth={item.isColumn ? 3 : 2}
                      strokeDasharray="6 2"
                      opacity={flashing ? flashOpacity2 : 0.6} />
                  );
                }

                // Falling: compute position
                const pos = elementLocalPos(item, localT);
                const fallProg = pos.fallProg;
                const fade = 1 - fallProg * 0.4;

                // Determine render mode
                const shouldFracture = e.fracture && !item.isColumn && item.len > 3;
                const shouldBuckle = e.buckling && !item.isColumn && !shouldFracture;

                if (shouldFracture) {
                  const segs = fractureSegments(item.p1, item.p2, item.len, item.id);
                  return (
                    <g key={item.id}>
                      {segs.map((seg, si) => {
                        const segLocalT = localT + si * 60;
                        const segFallDur = 1000;
                        const segProg = Math.min(segLocalT / segFallDur, 1);
                        const segEased = ease(segProg);
                        const segFallDist = svgH * 0.5 * segEased;
                        const segAngle2 = segEased * 25 * (si % 2 === 0 ? 1 : -1);
                        const sRad2 = segAngle2 * Math.PI / 180;
                        const scx2 = (seg.x1 + seg.x2) / 2;
                        const scy2 = (seg.y1 + seg.y2) / 2;
                        const sdx1 = seg.x1 - scx2; const sdy1 = seg.y1 - scy2;
                        const sdx2 = seg.x2 - scx2; const sdy2 = seg.y2 - scy2;
                        const segFade = 1 - segProg * 0.5;
                        return (
                          <line key={`${item.id}-f${si}`}
                            x1={scx2 + sdx1*Math.cos(sRad2) - sdy1*Math.sin(sRad2)}
                            y1={scy2 + segFallDist + sdx1*Math.sin(sRad2) + sdy1*Math.cos(sRad2)}
                            x2={scx2 + sdx2*Math.cos(sRad2) - sdy2*Math.sin(sRad2)}
                            y2={scy2 + segFallDist + sdx2*Math.sin(sRad2) + sdy2*Math.cos(sRad2)}
                            stroke={si === 0 ? '#ef4444' : '#f87171'}
                            strokeWidth={2} strokeDasharray="4 2"
                            opacity={segFade} />
                        );
                      })}
                    </g>
                  );
                }

                if (shouldBuckle) {
                  const bm = buckledMidpoint({x:pos.x1,y:pos.y1}, {x:pos.x2,y:pos.y2}, fallProg);
                  return (
                    <polyline key={item.id}
                      points={`${pos.x1},${pos.y1} ${bm.bx},${bm.by} ${pos.x2},${pos.y2}`}
                      fill="none" stroke="#ef4444" strokeWidth={2} strokeDasharray="6 2"
                      opacity={fade} />
                  );
                }

                // Normal fall
                return (
                  <line key={item.id} x1={pos.x1} y1={pos.y1} x2={pos.x2} y2={pos.y2}
                    stroke="#ef4444" strokeWidth={item.isColumn ? 3 : 2} strokeDasharray="6 2"
                    opacity={fade} />
                );
              })
            ) : hasFailed ? (
              // Non-cascade mode: all fall simultaneously
              animData.cascade.map(item => {
                const pos = elementLocalPos(item, t);
                const fallProg = pos.fallProg;
                const fade = 1 - fallProg * 0.4;
                const shouldFracture = e.fracture && !item.isColumn && item.len > 3;
                const shouldBuckle = e.buckling && !item.isColumn && !shouldFracture;

                if (shouldFracture) {
                  const segs = fractureSegments(item.p1, item.p2, item.len, item.id);
                  return (
                    <g key={item.id}>
                      {segs.map((seg, si) => {
                        const segT = t + si * 60;
                        const segDur = 1000;
                        const segP = Math.min(segT / segDur, 1);
                        const segE = ease(segP);
                        const segFD = svgH * 0.5 * segE;
                        const segA = segE * 25 * (si % 2 === 0 ? 1 : -1);
                        const sR = segA * Math.PI / 180;
                        const sCx = (seg.x1 + seg.x2) / 2;
                        const sCy = (seg.y1 + seg.y2) / 2;
                        const sdx1 = seg.x1 - sCx; const sdy1 = seg.y1 - sCy;
                        const sdx2 = seg.x2 - sCx; const sdy2 = seg.y2 - sCy;
                        const segF = 1 - segP * 0.5;
                        return (
                          <line key={`${item.id}-f${si}`}
                            x1={sCx + sdx1*Math.cos(sR) - sdy1*Math.sin(sR)}
                            y1={sCy + segFD + sdx1*Math.sin(sR) + sdy1*Math.cos(sR)}
                            x2={sCx + sdx2*Math.cos(sR) - sdy2*Math.sin(sR)}
                            y2={sCy + segFD + sdx2*Math.sin(sR) + sdy2*Math.cos(sR)}
                            stroke={si === 0 ? '#ef4444' : '#f87171'}
                            strokeWidth={2} strokeDasharray="4 2" opacity={segF} />
                        );
                      })}
                    </g>
                  );
                }
                if (shouldBuckle) {
                  const bm = buckledMidpoint({x:pos.x1,y:pos.y1}, {x:pos.x2,y:pos.y2}, fallProg);
                  return (
                    <polyline key={item.id} points={`${pos.x1},${pos.y1} ${bm.bx},${bm.by} ${pos.x2},${pos.y2}`}
                      fill="none" stroke="#ef4444" strokeWidth={2} strokeDasharray="6 2" opacity={fade} />
                  );
                }
                return (
                  <line key={item.id} x1={pos.x1} y1={pos.y1} x2={pos.x2} y2={pos.y2}
                    stroke="#ef4444" strokeWidth={item.isColumn ? 3 : 2} strokeDasharray="6 2" opacity={fade} />
                );
              })
            ) : null}

            {/* ── Impact Rings ── */}
            {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
            {e.shake && hasFailed && (animData as any).impactRings?.map((ring: ImpactRing, idx: number) => {
              const localT = t - ring.delay;
              if (localT < 0 || localT > ring.duration) return null;
              const prog = localT / ring.duration;
              const r = ring.maxR * ease(prog);
              const op = 0.25 * (1 - prog);
              return (
                <circle key={`impact-${idx}`} cx={ring.cx} cy={ring.cy} r={r}
                  fill="none" stroke="#ef4444" strokeWidth={1.5} opacity={op} />
              );
            })}

            {/* ── Dust Clouds ── */}
            {e.dust && hasFailed && animData.dust.map((cloud, idx) => {
              const localT = t - cloud.delay;
              if (localT < 0 || localT > 1500) return null;
              const prog = localT / 800;
              const r = cloud.maxR * Math.min(prog, 1);
              const op = Math.max(0, 0.25 * (1 - Math.min(prog, 1))) * Math.min(prog * 2, 1);
              return (
                <g key={`dust-${idx}`}>
                  <circle cx={cloud.cx} cy={cloud.cy} r={r} fill="#a3a3a3" opacity={op * 0.5} />
                  <circle cx={cloud.cx + r*0.3} cy={cloud.cy - r*0.2} r={r*0.6} fill="#a3a3a3" opacity={op * 0.3} />
                </g>
              );
            })}

            {/* ── Explosion Debris ── */}
            {e.explosion && hasFailed && animData.debris.map((p, idx) => {
              const localT = t - p.delay;
              if (localT < 0) return null;
              const age = localT / 1000;
              if (age > p.lifetime) return null;

              const x = p.x + p.vx * age * 60;
              let y = p.y + p.vy * age * 60 + 0.5 * 980 * age * age * 0.6;

              // Ground bounce
              if (e.bounce) {
                if (y > p.groundY && !p.didBounce) {
                  p.didBounce = true;
                }
                if (y > p.groundY) {
                  const overshoot = y - p.groundY;
                  y = p.groundY - overshoot * 0.3;
                  p.vy = -p.vy * 0.4;
                  p.vx *= 0.85;
                }
              } else {
                if (y > p.groundY) y = p.groundY;
              }

              const op = p.baseOpacity * Math.max(0, 1 - age / p.lifetime);
              // eslint-disable-next-line @typescript-eslint/no-unused-vars
              const rot = p.rotation + p.rotSpeed * age * 60;
              return (
                <g key={`debris-${idx}`}>
                  <circle cx={x} cy={y} r={p.size} fill={p.color} opacity={op} />
                  {/* Mini trail behind debris */}
                  {e.trail && (
                    <circle cx={x - p.vx * 0.5} cy={y - p.vy * 0.5} r={p.size * 0.5}
                      fill={p.color} opacity={op * 0.3} />
                  )}
                </g>
              );
            })}

            {/* ── Red flash overlay ── */}
            {flashOpacity > 0 && (
              <rect x={0} y={0} width={svgW} height={svgH} fill="#ef4444" opacity={flashOpacity * 0.15} pointerEvents="none" />
            )}

            {/* ── Structure health bar ── */}
            {elements.length > 0 && (
              <g>
                <rect x={svgW / 2 - 80} y={svgH - 48} width={160} height={6} rx={3}
                  fill="var(--muted)" stroke="var(--border)" strokeWidth={0.5} />
                {/* Collapsed portion */}
                <rect x={svgW / 2 - 80} y={svgH - 48}
                  width={Math.round(160 * (failedElements.length / elements.length))} height={6} rx={3}
                  fill="#ef4444" opacity={hasFailed ? 0.8 : 0} />
                <text x={svgW / 2} y={svgH - 52} textAnchor="middle" fill="var(--muted-foreground)" fontSize={7}>
                  {elements.length - failedElements.length}/{elements.length} standing
                  {failedElements.length > 0 && ` · ${failedElements.length} collapsed`}
                </text>
              </g>
            )}

            {/* ── Status text ── */}
            <text x={svgW / 2} y={svgH - 20} textAnchor="middle"
              fill={hasFailed ? '#ef4444' : '#94a3b8'} fontSize={11}
              className={hasFailed ? 'animate-pulse' : ''}
              fontWeight="bold"
            >
              {hasFailed && animActiveSet.size > 0 && totalProgress < 1
                ? `⚡ Demolishing: ${[...animActiveSet].map(id => `#${id}`).join(', ')} — ${(totalProgress * 100).toFixed(0)}%`
                : hasFailed && totalProgress >= 1
                ? `✖ Collapsed: ${failedElements.length} element(s) — ${(elements.length - failedElements.length)}/${elements.length} remaining`
                : hasFailed
                ? `✖ Collapsed: ${failedElements.length} element(s) — ${(totalProgress * 100).toFixed(0)}%`
                : 'Click a round in Demolition Targets to play the collapse animation'}
            </text>

          </g>
        </svg>
      </div>
    </div>
  );
}
