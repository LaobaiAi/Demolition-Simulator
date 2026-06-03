"use client";

import { Zap, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { type ScenarioSummary } from "@/lib/api";
import { t, type Lang } from "@/lib/i18n";

interface Props {
  lang: Lang;
  scenarios: ScenarioSummary[];
  loading: boolean;
  disabled: boolean;
  hasWebSocket: boolean;
  runningKey: string | null;
  onLaunch: (name: string, scenario: ScenarioSummary) => void;
  onStop: () => void;
}

export function ScenarioPicker({ lang, scenarios, loading, disabled, hasWebSocket, runningKey, onLaunch, onStop }: Props) {

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        <span className="ml-2 text-sm text-muted-foreground">{t("sp.loading", lang)}</span>
      </div>
    );
  }

  if (scenarios.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4 text-center">
        {t("sp.empty", lang)}
      </p>
    );
  }

  return (
    <>
      {scenarios.map((s) => {
        const isZh = lang === "zh";
        const title = s.title[isZh ? "zh" : "en"];
        const desc = s.description[isZh ? "zh" : "en"];
        const needsAnalysis = s.category === "mechanics";

        return (
          <div
            key={s.name}
            className="rounded-xl border border-primary/20 bg-primary/5 p-4 hover:border-primary/40 transition-colors"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <Zap
                    className={`h-4 w-4 ${needsAnalysis ? "text-amber-400" : "text-cyan-400"}`}
                  />
                  {title}
                  {needsAnalysis && (
                    <Badge variant="outline" className="text-[9px] text-amber-400 border-amber-400/30">
                      {t("sp.analysis_badge", lang)}
                    </Badge>
                  )}
                </h3>
                <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed">
                  {desc}
                </p>
                <div className="mt-3 flex items-center gap-2 text-[10px] text-muted-foreground/70 flex-wrap">
                  {s.tags.map((tag) => (
                    <span
                      key={tag}
                      className="px-1.5 py-0.5 rounded bg-muted/50 text-muted-foreground"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
              <div className="shrink-0 flex flex-col items-end gap-1.5">
                {runningKey === s.name ? (
                  <>
                    <Button onClick={onStop} variant="outline" size="sm" className="h-7 text-xs">
                      {t("sp.stop", lang)}
                    </Button>
                  </>
                ) : (
                  <Button
                    onClick={() => onLaunch(s.name, s)}
                    disabled={disabled || !hasWebSocket}
                    size="sm"
                  >
                    <Zap className="h-3.5 w-3.5 mr-1.5" />
                    {t("sp.run", lang)}
                  </Button>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </>
  );
}
