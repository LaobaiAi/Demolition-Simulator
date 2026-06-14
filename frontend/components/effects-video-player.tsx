"use client";

import { Download, ExternalLink, RefreshCw, Film } from "lucide-react";
import { Button } from "@/components/ui/button";
import { type Lang, t } from "@/lib/i18n";

interface EffectsVideoPlayerProps {
  lang: Lang;
  videoUrl: string;
  taskId?: string;
  onRegenerate?: () => void;
}

export function EffectsVideoPlayer({
  lang,
  videoUrl,
  taskId,
  onRegenerate,
}: EffectsVideoPlayerProps) {
  return (
    <div className="w-full space-y-3">
      {videoUrl ? (
        <div className="rounded-lg overflow-hidden border border-border bg-black">
          <video
            src={videoUrl}
            controls
            autoPlay
            loop
            className="w-full max-h-[400px] object-contain"
            poster="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='640' height='360'><rect fill='%23111' width='640' height='360'/><text fill='%23666' font-size='16' x='50%25' y='50%25' text-anchor='middle' dominant-baseline='middle'>Loading...</text></svg>"
          >
            Your browser does not support video playback.
          </video>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center h-48 rounded-lg border border-dashed border-border bg-muted/20">
          <Film className="h-10 w-10 text-muted-foreground/30 mb-2" />
          <p className="text-xs text-muted-foreground">
            {t("effects_video.no_model", lang)}
          </p>
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {taskId && (
            <span className="text-[10px] text-muted-foreground font-mono">
              Task: {taskId.slice(0, 12)}...
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {videoUrl && (
            <>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 text-xs"
                onClick={() => window.open(videoUrl, "_blank")}
              >
                <ExternalLink className="h-3.5 w-3.5" />
                Open
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 text-xs"
                onClick={async () => {
                  try {
                    const resp = await fetch(videoUrl);
                    if (!resp.ok) throw new Error("fetch failed");
                    const blob = await resp.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = `demolition-${Date.now()}.mp4`;
                    a.click();
                    URL.revokeObjectURL(url);
                  } catch {
                    window.open(videoUrl, "_blank");
                  }
                }}
              >
                <Download className="h-3.5 w-3.5" />
                Download
              </Button>
              {taskId && (
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5 text-xs"
                  onClick={() => {
                    window.open(`http://localhost:8000/api/effects/download/${taskId}`, "_blank");
                  }}
                >
                  <Download className="h-3.5 w-3.5" />
                  代理下载
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 text-xs"
                onClick={() => {
                  navigator.clipboard.writeText(videoUrl).catch(() => {});
                }}
              >
                <ExternalLink className="h-3.5 w-3.5" />
                复制链接
              </Button>
            </>
          )}
          {onRegenerate && (
            <Button
              variant="secondary"
              size="sm"
              className="gap-1.5 text-xs"
              onClick={onRegenerate}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Regenerate
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
