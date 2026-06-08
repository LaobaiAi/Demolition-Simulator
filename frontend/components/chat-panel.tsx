"use client";

import { useState } from "react";
import { Loader2, Send, Square, Zap, Settings, ListOrdered } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { t, type Lang } from "@/lib/i18n";
import type { ChatMessage, FrameStructure } from "@/lib/state-restore";
import { stepBrief } from "@/lib/log-format";

interface DemolishStrategy { key: string; category: "topology" | "mechanics"; }
const DEMOLISH_STRATEGIES: DemolishStrategy[] = [
  { key: "top_down", category: "topology" },
  { key: "bottom_up", category: "topology" },
  { key: "center_out", category: "topology" },
  { key: "alternating_floors", category: "topology" },
  { key: "sequential", category: "topology" },
  { key: "llm", category: "mechanics" },
];

interface ChatPanelProps {
  lang: Lang;
  messages: ChatMessage[];
  status: "idle" | "loading";
  input: string;
  setInput: (v: string) => void;
  currentStep: string;
  streamingText: string;
  frameStructure: FrameStructure | null;
  pipelineActive: boolean;
  pipelineProgress: number;
  pipelinePhase: string;
  demolishReady: boolean;
  structuralMetrics: { criticalElementId: number | null; criticalAxialForce: number | null } | null;
  vdStrategy: string;
  setVdStrategy: (v: string) => void;
  vdEffectsPreset: "minimal" | "standard" | "cinematic";
  setVdEffectsPreset: (v: "minimal" | "standard" | "cinematic") => void;
  animSpeed: number;
  setAnimSpeed: (v: number) => void;
  animEffects: Record<string, boolean>;
  setAnimEffects: (v: Record<string, boolean>) => void;
  vdConfigOpen: boolean;
  setVdConfigOpen: (v: boolean) => void;
  demolishDialogOpen: boolean;
  setDemolishDialogOpen: (v: boolean) => void;
  quickActions: string[];
  onSend: () => void;
  onStop: () => void;
  onLaunchVisualDemolition: () => void;
  onTriggerDemolition: () => void;
  onQuickAction: (action: string) => void;
  analysisMode: "analysis" | "fast";
  setAnalysisMode: (v: "analysis" | "fast") => void;
}

export function ChatPanel({
  lang, messages, status, input, setInput, currentStep, streamingText,
  frameStructure, pipelineActive, pipelineProgress, pipelinePhase,
  demolishReady,
  vdStrategy, setVdStrategy, vdEffectsPreset, setVdEffectsPreset,
  animSpeed, setAnimSpeed, setAnimEffects,
  vdConfigOpen, setVdConfigOpen, setDemolishDialogOpen,
  quickActions, onSend, onStop, onLaunchVisualDemolition,
  analysisMode, setAnalysisMode,
}: ChatPanelProps) {
  return (
    <div className="flex w-[30%] min-w-[300px] flex-col border-r border-border">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <span className="text-sm font-semibold text-foreground">{t("chat.title", lang)}</span>
        <div className="flex items-center gap-1 bg-secondary/50 rounded-lg p-0.5">
          <button onClick={() => setAnalysisMode("analysis")}
            className={`px-3 py-1 text-[11px] font-medium rounded-md transition-colors cursor-pointer ${analysisMode === "analysis" ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"}`}>
            {t("chat.mode_analysis", lang)}
          </button>
          <button onClick={() => setAnalysisMode("fast")}
            className={`px-3 py-1 text-[11px] font-medium rounded-md transition-colors cursor-pointer ${analysisMode === "fast" ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"}`}>
            {t("chat.mode_fast", lang)}
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1">
        <ScrollArea className="h-full p-4">
          <div className="space-y-4">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full min-h-[200px] text-center text-muted-foreground">
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" className="mb-3 opacity-40">
                  <text x="4" y="20" fill="#22d3ee" fontSize="20" fontWeight="bold" fontFamily="sans-serif">玄</text>
                  <text x="22" y="42" fill="#22d3ee" fontSize="20" fontWeight="bold" fontFamily="sans-serif">武</text>
                </svg>
                <p className="text-sm font-medium">{t("chat.empty_title", lang)}</p>
                <p className="text-xs mt-1">{t("chat.empty_subtitle", lang)}</p>
              </div>
            )}
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm overflow-hidden ${
                  msg.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted text-foreground max-h-[360px] overflow-y-auto"
                } animate-fade-in-up`}>
                  {msg.role === "ai" ? (
                    <div>
                      <div
                        className="prose prose-sm prose-invert max-w-none [&_strong]:text-primary"
                        dangerouslySetInnerHTML={{
                          __html: msg.content
                            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-primary">$1</strong>')
                            .replace(/`(.*?)`/g, '<code class="text-xs bg-secondary px-1 py-0.5 rounded">$1</code>')
                            .replace(/\n/g, "<br/>"),
                        }}
                      />
                      {msg.steps && msg.steps.length > 0 && (
                        <details className="mt-2">
                          <summary className="text-[10px] text-muted-foreground cursor-pointer hover:text-foreground transition-colors select-none">
                            {msg.steps.filter((s) => s.type === "tool_call").map((s) => stepBrief(s, lang)).join(" → ")}
                            {" · "}
                            {msg.steps.filter((s) => s.type === "tool_result").map((s) => stepBrief(s, lang)).filter(Boolean).join(", ")}
                          </summary>
                          <div className="mt-1.5 space-y-0.5">
                            {msg.steps.map((step, j) => {
                              const brief = stepBrief(step, lang);
                              return (
                                <div key={j} className="text-[10px] font-mono bg-secondary/40 rounded px-2 py-0.5 flex items-center gap-1.5">
                                  <span className={step.type === "tool_call" ? "text-amber-400/80 shrink-0" : "text-emerald-400/80 shrink-0"}>
                                    {step.type === "tool_call" ? "▶" : "✔"}
                                  </span>
                                  <span className="text-muted-foreground">{step.name}</span>
                                  {brief && <span className="text-foreground/60">{brief}</span>}
                                </div>
                              );
                            })}
                          </div>
                        </details>
                      )}
                    </div>
                  ) : (msg.content)}
                </div>
              </div>
            ))}
            {status === "loading" && (
              <div className="flex justify-start">
                <div className="flex flex-col gap-1 rounded-xl bg-muted px-4 py-2.5">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t("chat.thinking", lang)}
                  </div>
                  {currentStep && (
                    <div className="flex items-center gap-1.5 text-[11px] text-primary/80 animate-pulse">
                      <ListOrdered className="h-3 w-3" />{currentStep}
                    </div>
                  )}
                  {streamingText && (
                    <div className="text-[11px] text-muted-foreground/60 max-w-[400px] leading-relaxed">
                      {streamingText.slice(-300)}
                    </div>
                  )}
                </div>
              </div>
            )}
            <div id="chat-end" />
          </div>
        </ScrollArea>
      </div>

      {messages.length === 0 && (
        <div className="flex flex-wrap gap-1.5 px-4 pb-2">
          {quickActions.map((action) => (
            <button key={action} onClick={() => setInput(action)} disabled={status === "loading"}
              className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed">
              {action}
            </button>
          ))}
        </div>
      )}

      {frameStructure && !pipelineActive && analysisMode !== "fast" && (
        <div className="px-4 pb-2">
          <div>
            <div className="flex gap-1.5">
              <button onClick={onLaunchVisualDemolition} disabled={!frameStructure || status === "loading" || pipelineActive}
                className="flex-1 flex items-center justify-center gap-2 rounded-lg border border-primary/40 bg-primary/10 px-4 py-2.5 text-sm font-medium text-primary hover:bg-primary/20 hover:border-primary/60 transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed">
                <Zap className="h-4 w-4" />{t("vd.button", lang)}
              </button>
              <button onClick={() => setVdConfigOpen(!vdConfigOpen)}
                className={`shrink-0 flex items-center justify-center w-9 rounded-lg border transition-all cursor-pointer ${vdConfigOpen ? 'border-primary/50 bg-primary/15 text-primary' : 'border-border text-muted-foreground hover:border-primary/30 hover:text-foreground'}`}
                title={t("vd.config", lang)}>
                <Settings className="h-4 w-4" />
              </button>
              {demolishReady && status === "idle" && (
                <button onClick={() => setDemolishDialogOpen(true)}
                  className="shrink-0 flex items-center justify-center gap-1 rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2.5 text-xs font-medium text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                  title={t("confirm.title", lang)}>
                  <Zap className="h-3.5 w-3.5" />x1
                </button>
              )}
            </div>
            {vdConfigOpen && (
              <div className="mt-2 rounded-lg border border-border bg-muted/30 p-3 space-y-3">
                <div>
                  <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1.5 block">{t("vd.strategy", lang)}</label>
                  <div className="grid grid-cols-2 gap-1">
                    {DEMOLISH_STRATEGIES.map((s) => {
                      const active = vdStrategy === s.key;
                      return (
                        <button key={s.key} onClick={() => setVdStrategy(s.key)}
                          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium transition-all cursor-pointer border ${active ? "bg-primary/15 border-primary/40 text-primary" : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted"}`}>
                          {active && <span className="h-1.5 w-1.5 rounded-full bg-primary" />}
                          <span>{t(`vd.strategy.${s.key}`, lang)}</span>
                          {s.category === "mechanics" && <span className="text-[9px] text-amber-400/70 ml-auto" title={t("vd.needs_analysis", lang)}>⚡</span>}
                        </button>
                      );
                    })}
                  </div>
                  {DEMOLISH_STRATEGIES.find(s => s.key === vdStrategy)?.category === "mechanics" && (
                    <p className="text-[9px] text-amber-400/70 mt-1">{t("vd.needs_analysis", lang)}</p>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex-1">
                    <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1 block">{t("vd.effects", lang)}</label>
                    <div className="flex rounded-md border border-border bg-background overflow-hidden">
                      {(["minimal", "standard", "cinematic"] as const).map((p) => (
                        <button key={p} onClick={() => {
                          setVdEffectsPreset(p);
                          if (p === "minimal") setAnimEffects({ cascade: true, explosion: false, dust: false, shake: false, buckling: false, fracture: false, flash: false, trail: false, bounce: false });
                          else if (p === "standard") setAnimEffects({ cascade: true, explosion: true, dust: true, shake: true, buckling: false, fracture: false, flash: false, trail: false, bounce: false });
                          else setAnimEffects({ cascade: true, explosion: true, dust: true, shake: true, buckling: true, fracture: true, flash: true, trail: true, bounce: true });
                        }}
                        className={`flex-1 px-2 py-1 text-[10px] font-medium transition-colors cursor-pointer ${vdEffectsPreset === p ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-muted"}`}>
                          {t(`vd.effects.${p}`, lang)}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1 block">{t("vd.speed", lang)}</label>
                    <div className="flex rounded-md border border-border bg-background overflow-hidden">
                      {[0.5, 1, 2].map((s) => (
                        <button key={s} onClick={() => setAnimSpeed(s)}
                          className={`px-2 py-1 text-[10px] font-medium transition-colors cursor-pointer ${animSpeed === s ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-muted"}`}>
                          {s}x
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {frameStructure && pipelineActive && (
        <div className="px-4 pb-2">
          <div className="w-full rounded-lg border border-primary/30 bg-primary/5 px-4 py-2.5">
            <div className="flex items-center gap-2 mb-1.5">
              <Loader2 className="h-3.5 w-3.5 text-primary animate-spin" />
              <span className="text-sm font-medium text-primary">{t("vd.pipeline_running", lang)}</span>
            </div>
            <div className="h-1 bg-muted rounded-full overflow-hidden">
              <div className="h-full bg-primary rounded-full transition-all duration-500" style={{ width: `${Math.round(pipelineProgress * 100)}%` }} />
            </div>
            <p className="text-[10px] text-muted-foreground mt-1">{pipelinePhase}</p>
          </div>
        </div>
      )}

      <div className="border-t border-border p-3">
        <div className="flex gap-2">
          <Input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); } }}
            placeholder={analysisMode === "fast" ? t("chat.placeholder_fast", lang) : t("chat.placeholder", lang)} className="flex-1" disabled={status === "loading"} />
          {status === "loading" ? (
            <Button onClick={onStop} size="icon" variant="destructive" className="shrink-0" title={t("chat.stop", lang)}>
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button onClick={onSend} disabled={!input.trim()} size="icon">
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
