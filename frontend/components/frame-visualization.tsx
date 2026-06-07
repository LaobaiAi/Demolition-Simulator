"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Eye, Film, Maximize2, Minimize2, Settings2 } from "lucide-react";
import { CollapseAnimation } from "./frame-viz-animation";


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
