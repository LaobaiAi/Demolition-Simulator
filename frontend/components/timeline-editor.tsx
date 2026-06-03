"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import {
  GripVertical,
  SkipForward,
  ArrowUpToLine,
  Clock,
  Play,
  Pause,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { t, type Lang } from "@/lib/i18n";

// ── Types ───────────────────────────────────────────────────────────

export interface TimelineStep {
  id: number;
  elementId: number;
  elementType: string;
  phase: string;
  durationMs: number;
}

interface TimelineEditorProps {
  lang: Lang;
  steps: TimelineStep[];
  onReorder: (steps: TimelineStep[]) => void;
  onStepClick: (stepIndex: number) => void;
  selectedStep: number;
  isPlaying: boolean;
  onPlayPause?: () => void;
  onStepForward?: () => void;
  onStepBackward?: () => void;
  onSkipElement?: (stepIndex: number) => void;
}

// ── Constants ───────────────────────────────────────────────────────

const chevronLeft = "←";
const chevronRight = "→";

const PHASE_COLORS: Record<string, string> = {
  pending: "bg-emerald-500",
  flashing: "bg-yellow-400",
  falling: "bg-red-500",
  done: "bg-gray-400",
};

const PHASE_BG_COLORS: Record<string, string> = {
  pending: "bg-emerald-500/20 border-emerald-500/40",
  flashing: "bg-yellow-400/20 border-yellow-400/40",
  falling: "bg-red-500/20 border-red-500/40",
  done: "bg-gray-400/20 border-gray-400/40",
};

function phaseLabel(phase: string, lang: Lang): string {
  switch (phase) {
    case "pending": return t("timeline.phase_pending", lang);
    case "flashing": return t("timeline.phase_flashing", lang);
    case "falling": return t("timeline.phase_falling", lang);
    case "removed": return t("timeline.phase_removed", lang);
    default: return phase;
  }
}

// ── Component ───────────────────────────────────────────────────────

export function TimelineEditor({
  lang,
  steps,
  onReorder,
  onStepClick,
  selectedStep,
  isPlaying,
  onPlayPause,
  onStepForward,
  onStepBackward,
  onSkipElement,
}: TimelineEditorProps) {
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    index: number;
  } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // ── Keyboard shortcuts ──────────────────────────────────────────

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      )
        return;

      switch (e.key) {
        case " ":
          e.preventDefault();
          onPlayPause?.();
          break;
        case "ArrowLeft":
          e.preventDefault();
          onStepBackward?.();
          break;
        case "ArrowRight":
          e.preventDefault();
          onStepForward?.();
          break;
        case "Delete":
        case "Backspace":
          if (selectedStep >= 0 && onSkipElement) {
            e.preventDefault();
            onSkipElement(selectedStep);
          }
          break;
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onPlayPause, onStepBackward, onStepForward, onSkipElement, selectedStep]);

  // ── Close context menu on outside click ─────────────────────────

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [contextMenu]);

  // ── Drag & Drop handlers ────────────────────────────────────────

  const handleDragStart = useCallback(
    (e: React.DragEvent, index: number) => {
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(index));
      setDragIndex(index);
    },
    [],
  );

  const handleDragOver = useCallback(
    (e: React.DragEvent, index: number) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setDragOverIndex(index);
    },
    [],
  );

  const handleDragLeave = useCallback(() => {
    setDragOverIndex(null);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent, dropIndex: number) => {
      e.preventDefault();
      const srcIdx = Number(e.dataTransfer.getData("text/plain"));
      if (!isNaN(srcIdx) && srcIdx !== dropIndex) {
        const newSteps = [...steps];
        const [moved] = newSteps.splice(srcIdx, 1);
        newSteps.splice(dropIndex, 0, moved);
        onReorder(newSteps);
      }
      setDragIndex(null);
      setDragOverIndex(null);
    },
    [steps, onReorder],
  );

  const handleDragEnd = useCallback(() => {
    setDragIndex(null);
    setDragOverIndex(null);
  }, []);

  // ── Context menu handlers ───────────────────────────────────────

  const handleContextMenu = useCallback(
    (e: React.MouseEvent, index: number) => {
      e.preventDefault();
      setContextMenu({ x: e.clientX, y: e.clientY, index });
    },
    [],
  );

  const handleSkip = useCallback(() => {
    if (contextMenu) {
      onSkipElement?.(contextMenu.index);
      setContextMenu(null);
    }
  }, [contextMenu, onSkipElement]);

  const handleMoveToTop = useCallback(() => {
    if (contextMenu) {
      const newSteps = [...steps];
      const [item] = newSteps.splice(contextMenu.index, 1);
      newSteps.unshift(item);
      onReorder(newSteps);
      setContextMenu(null);
    }
  }, [contextMenu, steps, onReorder]);

  const handleAddDelay = useCallback(() => {
    if (contextMenu) {
      const newSteps = [...steps];
      newSteps[contextMenu.index] = {
        ...newSteps[contextMenu.index],
        durationMs: newSteps[contextMenu.index].durationMs + 500,
      };
      onReorder(newSteps);
      setContextMenu(null);
    }
  }, [contextMenu, steps, onReorder]);

  // ── Derived ─────────────────────────────────────────────────────

  const maxDuration = Math.max(...steps.map((s) => s.durationMs), 1);

  if (steps.length === 0) return null;

  // ── Render ──────────────────────────────────────────────────────

  return (
    <div
      ref={containerRef}
      className="rounded-lg border border-border bg-background overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-muted/30">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            {t("timeline.title", lang)}
          </span>
          <Badge variant="outline" className="text-[10px] tabular-nums">
            {t("timeline.steps", lang).replace("{n}", String(steps.length)).replace("(s)", steps.length !== 1 ? "s" : "")}
          </Badge>
        </div>

        <div className="flex items-center gap-0.5">
          <Button
            size="icon-xs"
            variant="ghost"
            onClick={onStepBackward}
            disabled={selectedStep <= 0}
            title={t("timeline.prev_step", lang)}
          >
            <ChevronLeft className="h-3 w-3" />
          </Button>
          <Button
            size="icon-xs"
            variant="outline"
            onClick={onPlayPause}
            title={isPlaying ? t("timeline.pause_space", lang) : t("timeline.play_space", lang)}
          >
            {isPlaying ? (
              <Pause className="h-3 w-3" />
            ) : (
              <Play className="h-3 w-3" />
            )}
          </Button>
          <Button
            size="icon-xs"
            variant="ghost"
            onClick={onStepForward}
            disabled={selectedStep >= steps.length - 1}
            title={t("timeline.next_step", lang)}
          >
            <ChevronRight className="h-3 w-3" />
          </Button>

          <span className="text-[10px] text-muted-foreground ml-1 tabular-nums">
            {selectedStep + 1}/{steps.length}
          </span>
        </div>
      </div>

      {/* Step list */}
      <div className="divide-y divide-border/50 max-h-[320px] overflow-y-auto">
        {steps.map((step, index) => {
          const isSelected = index === selectedStep;
          const isDragging = index === dragIndex;
          const isDragOver = index === dragOverIndex;
          const barPct = Math.max(
            8,
            Math.round((step.durationMs / maxDuration) * 100),
          );

          return (
            <div
              key={step.id}
              draggable
              onDragStart={(e) => handleDragStart(e, index)}
              onDragOver={(e) => handleDragOver(e, index)}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, index)}
              onDragEnd={handleDragEnd}
              onClick={() => onStepClick(index)}
              onContextMenu={(e) => handleContextMenu(e, index)}
              className={cn(
                "flex items-center gap-2 px-3 py-2.5 cursor-pointer transition-all select-none",
                isSelected && "bg-primary/8",
                isDragging && "opacity-40 scale-[0.97]",
                isDragOver && "border-t-2 border-t-primary",
                !isSelected && "hover:bg-muted/40",
              )}
            >
              {/* Drag handle */}
              <div className="shrink-0 text-muted-foreground/30 hover:text-muted-foreground transition-colors cursor-grab active:cursor-grabbing">
                <GripVertical className="h-3.5 w-3.5" />
              </div>

              {/* Element info */}
              <div className="flex items-center gap-2 min-w-[120px] shrink-0">
                <span className="text-xs font-semibold tabular-nums text-foreground">
                  #{step.elementId}
                </span>
                <Badge
                  variant="outline"
                  className={cn(
                    "text-[10px] capitalize",
                    PHASE_BG_COLORS[step.phase],
                  )}
                >
                  {step.elementType}
                </Badge>
              </div>

              {/* Phase bar */}
              <div className="flex-1 h-6 rounded-md bg-muted/30 overflow-hidden relative min-w-[60px]">
                <div
                  className={cn(
                    "h-full rounded-md transition-all duration-300",
                    PHASE_COLORS[step.phase] || "bg-muted",
                  )}
                  style={{ width: `${barPct}%` }}
                />
                {/* Duration label inside bar for wide bars */}
                {barPct > 30 && (
                  <span className="absolute inset-0 flex items-center px-2 text-[10px] font-medium text-white/80 tabular-nums">
                    {(step.durationMs / 1000).toFixed(1)}s
                  </span>
                )}
              </div>

              {/* Phase label + duration */}
              <div className="flex items-center gap-1.5 min-w-[90px] shrink-0 justify-end">
                <span
                  className={cn(
                    "text-[10px] font-medium",
                    step.phase === "pending" && "text-emerald-400",
                    step.phase === "flashing" && "text-yellow-400",
                    step.phase === "falling" && "text-red-400",
                    step.phase === "done" && "text-gray-400",
                  )}
                >
                  {phaseLabel(step.phase, lang)}
                </span>
                {barPct <= 30 && (
                  <span className="text-[10px] text-muted-foreground/60 tabular-nums">
                    {(step.durationMs / 1000).toFixed(1)}s
                  </span>
                )}
              </div>

              {/* Selected indicator dot */}
              <div
                className={cn(
                  "h-1.5 w-1.5 rounded-full shrink-0 transition-opacity",
                  isSelected ? "opacity-100 bg-primary" : "opacity-0",
                )}
              />
            </div>
          );
        })}
      </div>

      {/* Keyboard shortcut hints */}
      <div className="flex items-center gap-3 px-3 py-1.5 border-t border-border bg-muted/20">
        <span className="text-[10px] text-muted-foreground/50">
          <kbd className="px-1 py-0.5 rounded bg-muted border border-border text-[9px] font-mono">
            Space
          </kbd>{" "}
          {t("timeline.play_pause", lang)}
        </span>
        <span className="text-[10px] text-muted-foreground/50">
          <kbd className="px-1 py-0.5 rounded bg-muted border border-border text-[9px] font-mono">
            {chevronLeft}
          </kbd>
          <kbd className="px-1 py-0.5 rounded bg-muted border border-border text-[9px] font-mono ml-px">
            {chevronRight}
          </kbd>{" "}
          {t("timeline.step_action", lang)}
        </span>
        <span className="text-[10px] text-muted-foreground/50">
          <kbd className="px-1 py-0.5 rounded bg-muted border border-border text-[9px] font-mono">
            Del
          </kbd>{" "}
          {t("timeline.skip", lang)}
        </span>
        <span className="text-[10px] text-muted-foreground/50 ml-auto">
          {t("timeline.right_click", lang)}
        </span>
      </div>

      {/* Context menu */}
      {contextMenu && (
        <div
          className="fixed z-50 w-44 rounded-md border border-border bg-background shadow-lg py-1"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            onClick={handleSkip}
            className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-left hover:bg-muted transition-colors cursor-pointer"
          >
            <SkipForward className="h-3.5 w-3.5 text-muted-foreground" />
            <span>{t("timeline.skip_element", lang)}</span>
          </button>
          <button
            onClick={handleMoveToTop}
            className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-left hover:bg-muted transition-colors cursor-pointer"
          >
            <ArrowUpToLine className="h-3.5 w-3.5 text-muted-foreground" />
            <span>{t("timeline.move_to_top", lang)}</span>
          </button>
          <div className="border-t border-border my-1" />
          <button
            onClick={handleAddDelay}
            className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-left hover:bg-muted transition-colors cursor-pointer"
          >
            <Clock className="h-3.5 w-3.5 text-muted-foreground" />
            <span>{t("timeline.add_delay", lang)}</span>
          </button>
        </div>
      )}
    </div>
  );
}

