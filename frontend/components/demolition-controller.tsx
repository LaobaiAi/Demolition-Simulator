"use client";

import { useState } from "react";
import { Play, Pause, StepForward, RotateCcw, SkipForward, Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { t, type Lang } from "@/lib/i18n";

interface DemolitionControllerProps {
  lang: Lang;
  totalSteps: number;
  currentStep: number;
  isPlaying: boolean;
  isAnimating: boolean;
  speed: number;
  effects: Record<string, boolean>;
  onPlay: () => void;
  onPause: () => void;
  onStep: (direction: "forward" | "backward") => void;
  onReset: () => void;
  onSpeedChange: (speed: number) => void;
  onEffectToggle: (effect: string) => void;
  stepLabels?: string[];
}

const EFFECT_KEYS = [
  "cascade",
  "explosion",
  "dust",
  "shake",
  "buckling",
  "fracture",
  "flash",
  "trail",
  "bounce",
] as const;

const EFFECT_COLORS: Record<string, string> = {
  cascade: "#22c55e",
  explosion: "#f97316",
  dust: "#94a3b8",
  shake: "#eab308",
  buckling: "#22d3ee",
  fracture: "#a855f7",
  flash: "#ef4444",
  trail: "#78716c",
  bounce: "#f59e0b",
};

const SPEEDS = [0.5, 1, 2];

export function DemolitionController({
  lang,
  totalSteps,
  currentStep,
  isPlaying,
  isAnimating,
  speed,
  effects,
  onPlay,
  onPause,
  onStep,
  onReset,
  onSpeedChange,
  onEffectToggle,
  stepLabels,
}: DemolitionControllerProps) {
  const [effectsOpen, setEffectsOpen] = useState(false);

  if (totalSteps === 0) return null;

  return (
    <div className="flex-shrink-0 border-t border-border bg-background">
      {/* Timeline */}
      <div className="flex items-center gap-0.5 px-3 pt-2 pb-1">
        <div className="flex-1 flex items-center gap-0.5">
          {Array.from({ length: totalSteps }, (_, i) => {
            const stepNum = i + 1;
            const isDone = stepNum < currentStep;
            const isCurrent = stepNum === currentStep;
            return (
              <div
                key={i}
                className={cn(
                  "flex-1 h-1.5 rounded-full transition-colors duration-300",
                  isDone && "bg-green-500",
                  isCurrent && "bg-yellow-400",
                  !isDone && !isCurrent && "bg-muted-foreground/20"
                )}
                title={
                  stepLabels?.[i]
                    ? t("dc.step", lang).replace("{c}", String(stepNum)).replace("{t}", String(totalSteps)) + `: ${stepLabels[i]}`
                    : t("dc.step", lang).replace("{c}", String(stepNum)).replace("{t}", String(totalSteps))
                }
              />
            );
          })}
        </div>
        <span className="text-[10px] text-muted-foreground ml-2 tabular-nums shrink-0">
          {currentStep}/{totalSteps}
        </span>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-1 px-3 py-1.5">
        {/* Play/Pause */}
        <Button
          size="icon-xs"
          variant="outline"
          onClick={isPlaying ? onPause : onPlay}
          disabled={isAnimating && !isPlaying}
          title={isPlaying ? t("dc.pause", lang) : t("dc.play", lang)}
        >
          {isPlaying ? (
            <Pause className="h-3 w-3" />
          ) : (
            <Play className="h-3 w-3" />
          )}
        </Button>

        {/* Step backward */}
        <Button
          size="icon-xs"
          variant="outline"
          onClick={() => onStep("backward")}
          disabled={currentStep <= 1}
          title={t("dc.step_backward", lang)}
        >
          <StepForward className="h-3 w-3 rotate-180" />
        </Button>

        {/* Step forward */}
        <Button
          size="icon-xs"
          variant="outline"
          onClick={() => onStep("forward")}
          disabled={currentStep >= totalSteps}
          title={t("dc.step_forward", lang)}
        >
          <StepForward className="h-3 w-3" />
        </Button>

        {/* Skip to end */}
        <Button
          size="icon-xs"
          variant="outline"
          onClick={() => onStep("forward")}
          disabled={currentStep >= totalSteps}
          title={t("dc.skip_to_end", lang)}
        >
          <SkipForward className="h-3 w-3" />
        </Button>

        {/* Reset */}
        <Button
          size="icon-xs"
          variant="outline"
          onClick={onReset}
          disabled={currentStep <= 1}
          title={t("dc.reset_animation", lang)}
        >
          <RotateCcw className="h-3 w-3" />
        </Button>

        {/* Step indicator badge */}
        <Badge variant="outline" className="ml-1 text-[10px]">
          {t("dc.step", lang).replace("{c}", String(currentStep)).replace("{t}", String(totalSteps))}
        </Badge>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Speed control */}
        <div className="flex items-center rounded-md border border-border bg-background overflow-hidden">
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => onSpeedChange(s)}
              className={cn(
                "px-1.5 py-0.5 text-[10px] font-medium transition-colors cursor-pointer",
                speed === s
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted"
              )}
            >
              {s}x
            </button>
          ))}
        </div>

        {/* Effects toggle */}
        <Button
          size="icon-xs"
          variant="outline"
          onClick={() => setEffectsOpen(!effectsOpen)}
          title={t("dc.toggle_effects", lang)}
          className={cn(effectsOpen && "bg-primary/15 border-primary/40 text-primary")}
        >
          <Settings2 className="h-3 w-3" />
        </Button>
      </div>

      {/* Effects panel */}
      {effectsOpen && (
        <div className="border-t border-border px-3 py-2">
          <div className="flex flex-wrap gap-1.5 items-center">
            <button
              onClick={() => {
                const allOn = EFFECT_KEYS.some((k) => !effects[k]);
                EFFECT_KEYS.forEach((k) => {
                  if (onEffectToggle && allOn !== effects[k]) {
                    onEffectToggle(k);
                  }
                });
              }}
              className="px-2 py-1 text-[10px] rounded border border-border text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors cursor-pointer"
            >
              {EFFECT_KEYS.every((k) => effects[k]) ? t("dc.disable_all", lang) : t("dc.enable_all", lang)}
            </button>
            {EFFECT_KEYS.map((key) => {
              const on = effects[key];
              return (
                <button
                  key={key}
                  onClick={() => onEffectToggle(key)}
                  className={cn(
                    "flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-medium border transition-all cursor-pointer",
                    on
                      ? "bg-primary/15 border-primary/40 text-primary"
                      : "border-border/60 text-muted-foreground/50 hover:text-muted-foreground"
                  )}
                >
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ background: EFFECT_COLORS[key], opacity: on ? 1 : 0.3 }}
                  />
                  {t(`dc.effect_${key}`, lang)}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
