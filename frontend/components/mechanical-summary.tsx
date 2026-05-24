"use client";

import { Ruler, Gauge, Crosshair, Zap, Building2, Play, Square } from "lucide-react";

export interface StructuralMetrics {
  maxDisplacement: number; // meters
  maxAxialForce: number; // newtons
  criticalElementId: number | null;
  criticalAxialForce: number | null; // newtons
  columnCount: number;
  failedElements: number[];
}

export interface DemolitionRound {
  round: number;
  elementIds: number[];
  cumulativeIds: number[];
}

interface MechanicalSummaryProps {
  metrics: StructuralMetrics | null;
  demolitionRounds?: DemolitionRound[];
  activeRoundIdx?: number;
  onRoundClick?: (idx: number) => void;
  onRoundAnimate?: (idx: number) => void;  // play collapse animation for this round
  onAutoPlay?: () => void;
  autoPlaying?: boolean;
  animatingRound?: number;  // currently animating round (-1 = none)
}

export function MechanicalSummary({
  metrics,
  demolitionRounds = [],
  activeRoundIdx = -1,
  onRoundClick,
  onRoundAnimate,
  onAutoPlay,
  autoPlaying = false,
  animatingRound = -1,
}: MechanicalSummaryProps) {
  if (!metrics) {
    return (
      <div className="mb-4">
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 flex items-center gap-2">
          <Building2 className="h-3.5 w-3.5" />
          Structural Mechanics
        </div>
        <p className="text-[11px] text-muted-foreground/60">
          Run structural analysis to see results here.
        </p>
      </div>
    );
  }

  const dispMm = metrics.maxDisplacement * 1000;
  const axialKn = metrics.maxAxialForce / 1000;
  const criticalKn = metrics.criticalAxialForce
    ? metrics.criticalAxialForce / 1000
    : null;

  return (
    <div className="mb-4 space-y-3">
      <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-2">
        <Building2 className="h-3.5 w-3.5" />
        Structural Mechanics
      </div>

      <div className="space-y-2">
        <div className="rounded-lg border border-border bg-card p-2.5">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground mb-0.5">
            <Ruler className="h-3 w-3 text-primary/70" />
            Max Displacement
          </div>
          <span className="text-sm font-semibold text-foreground tabular-nums">
            {dispMm.toFixed(3)} <span className="text-[10px] text-muted-foreground">mm</span>
          </span>
        </div>

        <div className="rounded-lg border border-border bg-card p-2.5">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground mb-0.5">
            <Gauge className="h-3 w-3 text-primary/70" />
            Max Axial Force
          </div>
          <span className="text-sm font-semibold text-foreground tabular-nums">
            {axialKn.toFixed(1)} <span className="text-[10px] text-muted-foreground">kN</span>
          </span>
        </div>

        {metrics.criticalElementId !== null && (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-2.5">
            <div className="flex items-center gap-2 text-[11px] text-amber-400 mb-0.5">
              <Crosshair className="h-3 w-3" />
              Critical Column
            </div>
            <div className="text-sm font-semibold text-foreground tabular-nums">
              Element #{metrics.criticalElementId}
            </div>
            {criticalKn !== null && (
              <div className="text-[11px] text-amber-400/80 mt-0.5">
                Axial: {criticalKn.toFixed(1)} kN
              </div>
            )}
            <div className="text-[10px] text-muted-foreground mt-0.5">
              of {metrics.columnCount} columns analyzed
            </div>
          </div>
        )}

        {metrics.failedElements.length > 0 && (
          <div className="rounded-lg border border-red-500/40 bg-red-500/5 p-2.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-[11px] text-red-400 mb-0.5">
                <Zap className="h-3 w-3" />
                Demolition Targets
              </div>
              {/* Auto-play button */}
              {demolitionRounds.length > 1 && onAutoPlay && (
                <button
                  onClick={onAutoPlay}
                  className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border transition-all cursor-pointer border-red-500/30 text-red-400 hover:bg-red-500/15"
                >
                  {autoPlaying ? (
                    <><Square className="h-2.5 w-2.5" /> Stop</>
                  ) : (
                    <><Play className="h-2.5 w-2.5" /> Play All</>
                  )}
                </button>
              )}
            </div>

            {/* Round-based view */}
            {demolitionRounds.length > 0 ? (
              <div className="mt-1.5 space-y-1 max-h-[260px] overflow-y-auto">
                {demolitionRounds.map((r) => {
                  const isActive = activeRoundIdx === r.round;
                  const isPast = activeRoundIdx > r.round;
                  const isAnimating = animatingRound === r.round;
                  return (
                    <button
                      key={r.round}
                      onClick={() => {
                        onRoundAnimate?.(r.round);
                        onRoundClick?.(r.round);
                      }}
                      className={`w-full text-left flex items-center gap-2 px-2 py-1 rounded text-[10px] font-mono transition-all cursor-pointer ${
                        isAnimating
                          ? "bg-red-500/30 border border-red-500/60 animate-pulse"
                          : isActive
                          ? "bg-red-500/20 border border-red-500/40"
                          : isPast
                          ? "bg-red-500/5 border border-transparent opacity-60"
                          : "bg-transparent border border-transparent hover:bg-red-500/10"
                      }`}
                    >
                      <span className={`shrink-0 w-5 h-5 flex items-center justify-center rounded text-[9px] font-bold relative ${
                        isActive ? "bg-red-500 text-white" : "bg-red-500/20 text-red-400"
                      }`}>
                        <span className={isAnimating ? "opacity-0" : ""}>{r.round + 1}</span>
                        {isAnimating && (
                          <Play className="h-3 w-3 absolute text-white animate-pulse" />
                        )}
                      </span>
                      <span className="truncate text-muted-foreground">
                        {r.elementIds.map((id) => `#${id}`).join(", ")}
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : (
              /* Flat list fallback when no round data */
              <div className="flex flex-wrap gap-1 mt-1">
                {metrics.failedElements.map((id) => (
                  <span
                    key={id}
                    className="text-[11px] bg-red-500/20 text-red-400 px-2 py-0.5 rounded font-mono"
                  >
                    #{id}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
