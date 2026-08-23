"use client";

import { useState, useMemo } from "react";
import { Zap, Loader2, FileText, Heart } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { fetchScenarioPrompt, type ScenarioSummary } from "@/lib/api";
import { t, type Lang } from "@/lib/i18n";
import { useDemoFavorites } from "@/hooks/use-demo-favorites";

interface Props {
  lang: Lang;
  scenarios: ScenarioSummary[];
  loading: boolean;
  disabled: boolean;
  hasWebSocket: boolean;
  runningKey: string | null;
  onLaunch: (name: string, scenario: ScenarioSummary) => void;
  onStop: () => void;
  favorites?: string[];
  onToggleFavorite?: (key: string) => void;
}

export function ScenarioPicker({
  lang, scenarios, loading, disabled, hasWebSocket, runningKey, onLaunch, onStop,
  favorites: favoritesProp, onToggleFavorite: toggleProp,
}: Props) {
  const internal = useDemoFavorites();
  const favorites = favoritesProp ?? internal.favorites;
  const toggleFavorite = toggleProp ?? internal.toggleFavorite;
  const isFavorite = (key: string) => favorites.includes(key);

  const [promptName, setPromptName] = useState<string | null>(null);
  const [promptContent, setPromptContent] = useState<string | null>(null);
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptError, setPromptError] = useState(false);

  // 收藏的实例排前面
  const sortedScenarios = useMemo(
    () =>
      [...scenarios].sort(
        (a, b) => Number(isFavorite(b.name)) - Number(isFavorite(a.name))
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scenarios, favorites]
  );

  const openPrompt = async (name: string) => {
    setPromptName(name);
    setPromptContent(null);
    setPromptError(false);
    setPromptLoading(true);
    const content = await fetchScenarioPrompt(name);
    setPromptLoading(false);
    if (content === null) {
      setPromptError(true);
    } else {
      setPromptContent(content);
    }
  };

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
      {sortedScenarios.map((s) => {
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
              <div className="shrink-0 flex flex-row items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => toggleFavorite(s.name)}
                  className={`rounded-md p-1 -m-1 transition-colors ${
                    isFavorite(s.name)
                      ? "text-red-500 hover:text-red-600"
                      : "text-muted-foreground/50 hover:text-red-400"
                  }`}
                  title={isFavorite(s.name) ? t("sp.unfavorite", lang) : t("sp.favorite", lang)}
                  aria-label={isFavorite(s.name) ? t("sp.unfavorite", lang) : t("sp.favorite", lang)}
                >
                  <Heart className={`h-4 w-4 ${isFavorite(s.name) ? "fill-current" : ""}`} />
                </button>
                <Button
                  onClick={() => openPrompt(s.name)}
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  title={t("sp.prompt_view", lang)}
                >
                  <FileText className="h-3.5 w-3.5 mr-1.5" />
                  {t("sp.prompt_view", lang)}
                </Button>
                {runningKey === s.name ? (
                  <Button onClick={onStop} variant="outline" size="sm" className="h-7 text-xs">
                    {t("sp.stop", lang)}
                  </Button>
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

      {/* Prompt viewer dialog */}
      <Dialog open={promptName !== null} onOpenChange={(open) => { if (!open) setPromptName(null); }}>
        <DialogContent className="max-w-3xl max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="text-base flex items-center gap-2">
              <FileText className="h-4 w-4 text-muted-foreground" />
              {promptName ? promptName : ""}
              <span className="text-muted-foreground font-normal">
                — {t("sp.prompt", lang)}
              </span>
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 min-h-0 overflow-y-auto pr-1 text-sm leading-relaxed">
            {promptLoading && (
              <div className="flex items-center justify-center py-10 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
                {t("sp.prompt_loading", lang)}
              </div>
            )}
            {!promptLoading && promptError && (
              <p className="text-sm text-muted-foreground py-10 text-center">
                {t("sp.prompt_not_found", lang)}
              </p>
            )}
            {!promptLoading && !promptError && promptContent !== null && (
              <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{promptContent}</ReactMarkdown>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
