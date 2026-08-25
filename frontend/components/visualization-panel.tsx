"use client";

import { useEffect, useMemo, useRef, useState, Suspense, lazy } from "react";
import { Terminal, Pause, PlayCircle, Loader2, Maximize, Minimize } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { t, type Lang } from "@/lib/i18n";
import { getLogIcon, formatLogEntry } from "@/lib/log-format";
import { FrameVisualization } from "@/components/frame-visualization";
import { UnityVideoPanel } from "@/components/unity-video-panel";
import { BlenderVideoPanel } from "@/components/blender-video-panel";
import { AbaqusVideoPanel } from "@/components/abaqus-video-panel";
import { VerificationPanel } from "@/components/verification-panel";
import { DemolitionController } from "@/components/demolition-controller";
import { WebGLErrorBoundary } from "@/components/webgl-error-boundary";
import { AnimationExporter } from "@/components/animation-exporter";
import type { FrameStructure, NodeDisp, StepEvent } from "@/lib/state-restore";
import type { DemolitionRound } from "@/components/mechanical-summary";

const FrameVisualization3D = lazy(() => import("@/components/frame-visualization-3d").then(m => ({ default: m.FrameVisualization3D })));
const IFCViewer = lazy(() => import("@/components/ifc-viewer").then(m => ({ default: m.IFCViewer })));

function LoadingFallback({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
      <Loader2 className="h-8 w-8 animate-spin text-primary/40" />
      <p className="text-xs">Loading {label}...</p>
    </div>
  );
}

interface VizPanelProps {
  lang: Lang;
  vizMode: "svg" | "webgl" | "unity" | "blender" | "ifc" | "abaqus";
  setVizMode: (v: "svg" | "webgl" | "unity" | "blender" | "ifc" | "abaqus") => void;
  frameStructure: FrameStructure | null;
  nodeDisplacements: NodeDisp[] | null;
  analysisResult: Record<string, unknown> | null;
  analysisSolver: string | null;
  structuralMetrics: { criticalElementId: number | null } | null;
  failedElements: number[];
  displayFailedElements: number[];
  roundStructure: FrameStructure | null;
  selectedAnalysisResult: Record<string, unknown> | null;
  verifyContext: string;
  demolitionRounds: DemolitionRound[];
  activeRoundIdx: number;
  animRequest: { key: number; targets: number[] } | null;
  animEffects: Record<string, boolean>;
  animPlaying: boolean;
  animatingRound: number;
  animSpeed: number;
  autoPlaying: boolean;
  canvas3dRef: HTMLCanvasElement | null;
  logEntries: StepEvent[];
  logPaused: boolean;
  onAnimComplete: () => void;
  onRoundClick: (idx: number) => void;
  onRoundAnimate: (idx: number) => void;
  onAutoPlay: () => void;
  onStepForward: () => void;
  onStepBackward: () => void;
  onReset: () => void;
  onSpeedChange: (v: number) => void;
  onEffectToggle: (key: string) => void;
  onPause: () => void;
  onLogPauseToggle: () => void;
  onCanvasCallback: (c: HTMLCanvasElement | null) => void;
  onUnityConnected: () => void;
}

export function VisualizationPanel({
  lang, vizMode, setVizMode, frameStructure, nodeDisplacements,
  analysisResult, analysisSolver, structuralMetrics,
  failedElements, displayFailedElements, roundStructure,
  selectedAnalysisResult, verifyContext,
  demolitionRounds, activeRoundIdx,
  animRequest, animEffects, animatingRound, animSpeed, autoPlaying,
  canvas3dRef, logEntries, logPaused,
  onAnimComplete, onRoundClick, onAutoPlay,
  onStepForward, onStepBackward, onReset, onSpeedChange, onEffectToggle, onPause,
  onLogPauseToggle, onCanvasCallback, onUnityConnected,
}: VizPanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    const onChange = () => setIsFullscreen(document.fullscreenElement === panelRef.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  const toggleFullscreen = () => {
    if (document.fullscreenElement === panelRef.current) {
      void document.exitFullscreen();
    } else {
      void panelRef.current?.requestFullscreen().catch(() => {});
    }
  };

  const stepLabels = useMemo(() =>
    demolitionRounds.map(r => `Round ${r.round + 1}: ${r.elementIds.length} elements`),
    [demolitionRounds]
  );

  return (
    <div ref={panelRef}
      className={`flex flex-col border-r border-border bg-[#0a0f1a] ${isFullscreen ? "w-full h-full" : "w-[50%]"} [&:fullscreen]:w-full`}>
      <div className="flex items-center justify-between border-b border-border px-4 py-1.5">
        <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
          {t(`viz.mode_${vizMode}`, lang)}
        </span>
        <div className="flex items-center gap-1.5">
          <div className="flex items-center gap-1 bg-secondary/50 rounded-lg p-0.5">
            {(["webgl", "svg", "unity", "blender", "ifc", "abaqus"] as const).map((mode) => (
              <button key={mode} onClick={() => setVizMode(mode)}
                className={`px-3 py-1 text-[11px] font-medium rounded-md transition-colors cursor-pointer ${vizMode === mode ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"}`}>
                {t(`viz.tab_${mode}`, lang)}
              </button>
            ))}
            <div className="ml-1.5 pl-1.5 border-l border-border/60">
              <AnimationExporter lang={lang} canvasRef={{ current: canvas3dRef }}
                fileName="demolition-animation" disabled={vizMode !== "webgl" || demolitionRounds.length === 0} />
            </div>
          </div>
          <button onClick={toggleFullscreen}
            title={isFullscreen ? (lang === "zh" ? "退出全屏" : "Exit Fullscreen") : (lang === "zh" ? "全屏" : "Fullscreen")}
            className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors cursor-pointer bg-secondary/50 hover:bg-primary/20 text-muted-foreground hover:text-primary">
            {isFullscreen ? <Minimize className="h-3.5 w-3.5" /> : <Maximize className="h-3.5 w-3.5" />}
            <span className="hidden xl:inline">{isFullscreen ? (lang === "zh" ? "退出全屏" : "Exit Fullscreen") : (lang === "zh" ? "全屏" : "Fullscreen")}</span>
          </button>
        </div>
      </div>

      <div className="relative flex-1 min-h-0 overflow-hidden">
        {vizMode === "svg" && (
          <div className="absolute inset-0 flex flex-col">
            <FrameVisualization structure={frameStructure} displacements={nodeDisplacements}
              criticalElementId={structuralMetrics?.criticalElementId ?? null}
              failedElements={displayFailedElements}
              maxDisplacement={analysisResult?.max_displacement as number | undefined}
              elementForces={analysisResult?.element_forces as Array<{element_id: number; Nmax: number; Nmin: number; Mmax: number; Mmin: number; Qmax: number; Qmin: number}> | undefined}
              animationTrigger={animRequest?.key} animatingElements={animRequest?.targets}
              onAnimationComplete={onAnimComplete} />
            {analysisResult && (
              <div className="flex items-center justify-center px-4 pb-2">
                <VerificationPanel fastResult={selectedAnalysisResult} structure={roundStructure as Record<string, unknown> | null}
                  lang={lang} analysisSolver={analysisSolver ?? undefined} verifyContext={verifyContext}
                  demolitionRounds={demolitionRounds} activeRoundIdx={activeRoundIdx} onRoundClick={onRoundClick} />
              </div>
            )}
          </div>
        )}
        <div className={`absolute inset-0 flex flex-col ${vizMode === "webgl" ? "" : "invisible pointer-events-none"}`}>
          <WebGLErrorBoundary onError={() => setVizMode("svg")}>
            <Suspense fallback={<LoadingFallback label="3D engine" />}>
              <FrameVisualization3D structure={frameStructure} displacements={nodeDisplacements}
                criticalElementId={structuralMetrics?.criticalElementId ?? null}
                failedElements={failedElements} displayFailedElements={displayFailedElements}
                maxDisplacement={analysisResult?.max_displacement as number | undefined}
                elementForces={analysisResult?.element_forces as Array<{element_id: number; Nmax: number; Nmin: number; Mmax: number; Mmin: number; Qmax: number; Qmin: number}> | undefined}
                animationTrigger={animRequest?.key} animatingElements={animRequest?.targets}
                onAnimationComplete={onAnimComplete} activeEffects={animEffects}
                canvasCallback={onCanvasCallback} />
            </Suspense>
          </WebGLErrorBoundary>
        </div>
        <div className={`absolute inset-0 ${vizMode === "unity" ? "" : "invisible pointer-events-none"}`}>
          <UnityVideoPanel onStreamConnected={onUnityConnected} frameStructure={frameStructure} />
        </div>
        <div className={`absolute inset-0 ${vizMode === "blender" ? "" : "invisible pointer-events-none"}`}>
          <BlenderVideoPanel onStreamConnected={onUnityConnected} frameStructure={frameStructure} />
        </div>
        <div className={`absolute inset-0 flex flex-col ${vizMode === "ifc" ? "" : "invisible pointer-events-none"}`}>
          <Suspense fallback={<LoadingFallback label="IFC viewer" />}>
            <IFCViewer structure={frameStructure}
              highlightedElements={structuralMetrics?.criticalElementId ? [structuralMetrics.criticalElementId] : []}
              removedElements={displayFailedElements} />
          </Suspense>
        </div>
        <div className={`absolute inset-0 ${vizMode === "abaqus" ? "" : "invisible pointer-events-none"}`}>
          <AbaqusVideoPanel lang={lang} />
        </div>
      </div>

      {demolitionRounds.length > 0 && (
        <DemolitionController lang={lang} totalSteps={demolitionRounds.length}
          currentStep={animatingRound >= 0 ? animatingRound + 1 : demolitionRounds.length}
          isPlaying={autoPlaying} isAnimating={animatingRound >= 0} speed={animSpeed} effects={animEffects}
          onPlay={onAutoPlay} onPause={onPause}
          onStep={(dir) => dir === "forward" ? onStepForward() : onStepBackward()}
          onReset={onReset}
          onSpeedChange={onSpeedChange} onEffectToggle={onEffectToggle}
          stepLabels={stepLabels} />
      )}

      <div className={`border-t border-border bg-[#060a12] ${isFullscreen ? "hidden" : ""}`}>
        <div className="flex items-center justify-between px-4 py-2 border-b border-border">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
            <Terminal className="h-3.5 w-3.5" />{t("log.header", lang)}
            {logEntries.length > 0 && <Badge variant="outline" className="text-[10px]">{logEntries.length}</Badge>}
          </div>
          <button onClick={onLogPauseToggle}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer flex items-center gap-1">
            {logPaused ? (<><PlayCircle className="h-3 w-3" /> Resume</>) : (<><Pause className="h-3 w-3" /> Pause</>)}
          </button>
        </div>
        <ScrollArea className="h-32">
          <div className="p-3 font-mono text-[11px] leading-relaxed">
            {logEntries.length === 0 ? (
              <span className="text-muted-foreground">{t("log.waiting", lang)}</span>
            ) : (
              logEntries.map((entry, i) => {
                const formatted = formatLogEntry(entry);
                return (
                  <div key={i} className="flex items-start gap-1.5 text-muted-foreground hover:text-foreground transition-colors py-0.5">
                    <span className="mt-0.5 shrink-0">{getLogIcon(entry.type)}</span>
                    <span className="text-[10px] font-semibold text-foreground/70 shrink-0">{formatted.label}</span>
                    {formatted.detail && <span className="text-[10px] text-muted-foreground/60 break-all">— {formatted.detail}</span>}
                  </div>
                );
              })
            )}
            <div id="log-end" />
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
