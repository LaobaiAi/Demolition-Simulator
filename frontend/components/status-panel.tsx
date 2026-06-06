"use client";

import { Activity, Brain } from "lucide-react";
import { t, type Lang } from "@/lib/i18n";
import { MechanicalSummary } from "@/components/mechanical-summary";
import { TimelineEditor } from "@/components/timeline-editor";
import type { DemolitionRound, StructuralMetrics } from "@/components/mechanical-summary";

interface StatusPanelProps {
  lang: Lang;
  status: "idle" | "loading";
  wsConnected: "connected" | "reconnecting" | "disconnected";
  llmModel: string;
  structuralMetrics: StructuralMetrics | null;
  demolitionRounds: DemolitionRound[];
  activeRoundIdx: number;
  autoPlaying: boolean;
  animatingRound: number;
  demolitionMode: boolean;
  timelineSteps: Array<{ id: number; elementId: number; elementType: string; phase: string; durationMs: number }>;
  onRoundClick: (idx: number) => void;
  onRoundAnimate: (idx: number) => void;
  onAutoPlay: () => void;
  onTimelineReorder: (steps: Array<{ id: number; elementId: number; elementType: string; phase: string; durationMs: number }>) => void;
}

export function StatusPanel({
  lang, status, wsConnected, llmModel,
  structuralMetrics, demolitionRounds, activeRoundIdx, autoPlaying, animatingRound,
  demolitionMode, timelineSteps,
  onRoundClick, onRoundAnimate, onAutoPlay, onTimelineReorder,
}: StatusPanelProps) {
  return (
    <div className="flex w-[20%] min-w-[240px] flex-col bg-[#0a0f1a]">
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
          <Activity className="h-3.5 w-3.5" />{t("status.header", lang)}
        </div>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${status === "idle" ? "bg-emerald-500" : "bg-amber-500 animate-pulse"}`} />
            <span className="text-sm capitalize">{t(status === "idle" ? "status.idle" : "status.loading", lang)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${
              wsConnected === "connected" ? "bg-emerald-500" : wsConnected === "reconnecting" ? "bg-amber-500 animate-pulse" : "bg-red-500"}`} />
            <span className="text-xs text-muted-foreground">
              {wsConnected === "connected" ? t("status.ws_connected", lang) :
               wsConnected === "reconnecting" ? t("status.reconnecting", lang) : t("status.ws_disconnected", lang)}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Brain className="h-3.5 w-3.5 text-primary/60" />
            <span className="text-xs text-muted-foreground">LLM: {llmModel}</span>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <MechanicalSummary metrics={structuralMetrics} demolitionRounds={demolitionRounds}
          activeRoundIdx={activeRoundIdx} onRoundClick={onRoundClick} onRoundAnimate={onRoundAnimate}
          onAutoPlay={onAutoPlay} autoPlaying={autoPlaying} animatingRound={animatingRound} />

        {demolitionMode && timelineSteps.length > 0 && (
          <div className="mt-4">
            <TimelineEditor lang={lang} steps={timelineSteps} onReorder={onTimelineReorder}
              onStepClick={() => {}} selectedStep={-1} isPlaying={autoPlaying}
              onPlayPause={() => demolitionRounds.length > 0 && (autoPlaying ? onAutoPlay() : onAutoPlay())}
              onStepForward={() => {}} onStepBackward={() => {}} onSkipElement={() => {}} />
          </div>
        )}
        {demolitionMode && timelineSteps.length === 0 && (
          <div className="mt-4 rounded-lg border border-border bg-muted/20 p-4 text-center">
            <p className="text-xs text-muted-foreground">
              {t("dc.empty_timeline", lang)}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
