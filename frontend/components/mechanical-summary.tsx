"use client";

import { Ruler, Gauge, Crosshair, Zap, Building2 } from "lucide-react";

export interface StructuralMetrics {
  maxDisplacement: number; // meters
  maxAxialForce: number; // newtons
  criticalElementId: number | null;
  criticalAxialForce: number | null; // newtons
  columnCount: number;
  failedElements: number[];
}

interface MechanicalSummaryProps {
  metrics: StructuralMetrics | null;
}

export function MechanicalSummary({ metrics }: MechanicalSummaryProps) {
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
            <div className="flex items-center gap-2 text-[11px] text-red-400 mb-0.5">
              <Zap className="h-3 w-3" />
              Demolition Targets
            </div>
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
          </div>
        )}
      </div>
    </div>
  );
}
