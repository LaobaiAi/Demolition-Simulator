"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Play, Pause, Volume2, VolumeX, AlertTriangle, Loader2, Maximize2, Minimize2, XCircle } from "lucide-react";
import { t, type Lang } from "@/lib/i18n";
import { API_BASE } from "@/lib/api";

interface FootprintData {
  max_radius_m: number;
  p95_radius_m: number;
  direction_deg: number;
  tower_base_radius_m: number;
  final_height_m: number;
  ratio_max: number;
}

interface SolveStatus {
  status: string;
  progress_percent?: number | null;
  job_id?: string;
  estimated_duration_s?: number;
  estimated_duration_range?: number[];
  error?: string;
}

const VIDEOS = [
  { id: "coal", label: "煤仓间", title: "煤仓间倒塌模拟", src: "/resource/Abaqus/煤仓间.mp4" },
  { id: "tower", label: "冷却塔侧面", title: "冷却塔倒塌模拟（侧面）", src: "/resource/Abaqus/cooling_tower_collapse.mp4" },
  { id: "tower_top", label: "冷却塔俯视", title: "冷却塔倒塌模拟（俯视）", src: "/resource/Abaqus/cooling_tower_collapse_top.mp4" },
  { id: "stack", label: "烟囱侧面", title: "烟囱倒塌模拟（侧面）", src: "/resource/Abaqus/concrete_stack_side.mp4" },
  { id: "stack_top", label: "烟囱俯视", title: "烟囱倒塌模拟（俯视）", src: "/resource/Abaqus/concrete_stack_top.mp4" },
];

const FOOTPRINT_URLS: Record<string, string> = {
  tower: "/resource/Abaqus/cooling_tower_footprint.json",
  stack: "/resource/Abaqus/concrete_stack_footprint.json",
};

const footprintUrlFor = (id: string) => {
  if (id.startsWith("tower")) return FOOTPRINT_URLS.tower;
  if (id.startsWith("stack")) return FOOTPRINT_URLS.stack;
  return null;
};
const SOLVE_ACTIVE_STATUSES = new Set(["submitted", "running"]);

const round1 = (v: number) => Math.round(v * 10) / 10;
const round2 = (v: number) => Math.round(v * 100) / 100;

export function AbaqusVideoPanel({ lang }: { lang: Lang }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  const [ended, setEnded] = useState(false);
  const [videoError, setVideoError] = useState(false);
  const [videoLoaded, setVideoLoaded] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [videoIdx, setVideoIdx] = useState(1);
  const [footprint, setFootprint] = useState<FootprintData | null>(null);
  const [footprintVideoId, setFootprintVideoId] = useState<string | null>(null);
  const [solveStyle, setSolveStyle] = useState<"rendered" | "raw" | "native">("rendered");
  const [solveStatus, setSolveStatus] = useState<SolveStatus | null>(null);
  const [stopError, setStopError] = useState<string | null>(null);

  useEffect(() => {
    const url = footprintUrlFor(VIDEOS[videoIdx].id);
    let cancelled = false;
    if (url) {
      fetch(url)
        .then((r) => (r.ok ? r.json() : null))
        .then((d: FootprintData | null) => {
          if (!cancelled) {
            setFootprint(d);
            setFootprintVideoId(VIDEOS[videoIdx].id);
          }
        })
        .catch(() => {});
    }
    return () => {
      cancelled = true;
    };
  }, [videoIdx]);

  const hasRaw = VIDEOS[videoIdx].id.startsWith("tower");
  const hasNative = VIDEOS[videoIdx].id.startsWith("tower") || VIDEOS[videoIdx].id.startsWith("stack");
  const videoSrc = solveStyle === "raw" && hasRaw
    ? VIDEOS[videoIdx].src.replace(".mp4", "_raw.mp4")
    : solveStyle === "native" && hasNative
      ? VIDEOS[videoIdx].src.replace(".mp4", "_native.mp4")
      : VIDEOS[videoIdx].src;
  const videoKey = hasRaw || hasNative ? `${VIDEOS[videoIdx].id}-${solveStyle}` : VIDEOS[videoIdx].id;

  const selectVideo = (idx: number) => {
    setVideoIdx(idx);
    const v = videoRef.current;
    if (v) {
      v.pause();
      v.currentTime = 0;
    }
    setPlaying(false);
    setEnded(false);
    setVideoError(false);
    setVideoLoaded(false);
  };

  const selectStyle = (style: "rendered" | "raw" | "native") => {
    if (style === solveStyle) return;
    setSolveStyle(style);
    const v = videoRef.current;
    if (v) {
      v.pause();
      v.currentTime = 0;
    }
    setPlaying(false);
    setEnded(false);
    setVideoError(false);
    setVideoLoaded(false);
  };

  // Poll the solve progress via REST — independent of the LLM's WebSocket polling
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const r = await fetch(`${API_BASE}/api/abaqus/solve-status`);
        if (!r.ok) {
          timer = setTimeout(poll, 8000);
          return;
        }
        const d: SolveStatus = await r.json();
        if (cancelled) return;
        setSolveStatus(d);
        timer = setTimeout(poll, SOLVE_ACTIVE_STATUSES.has(d.status) ? 4000 : 10000);
      } catch {
        if (!cancelled) timer = setTimeout(poll, 8000);
      }
    };
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  const stopSolve = async () => {
    setStopError(null);
    try {
      const r = await fetch(`${API_BASE}/api/abaqus/solve-stop`, { method: "POST" });
      const d: SolveStatus = await r.json();
      if (!r.ok || d.error) {
        setStopError(t("abaqus.stop_failed", lang));
        return;
      }
      setSolveStatus((s) => (s ? { ...s, status: "terminated" } : s));
    } catch {
      setStopError(t("abaqus.stop_failed", lang));
    }
  };

  // Sync fullscreen state with browser events
  useEffect(() => {
    const onFsChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused || v.ended) {
      if (v.ended) { v.currentTime = 0; setEnded(false); }
      v.play().catch(() => {});
      setPlaying(true);
    } else {
      v.pause();
      setPlaying(false);
    }
  };

  const toggleFullscreen = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    } else {
      el.requestFullscreen().catch(() => {});
    }
  }, []);

  const handleError = () => {
    setVideoError(true);
    setPlaying(false);
  };

  const handleLoadedData = () => {
    setVideoLoaded(true);
    setVideoError(false);
  };

  const solveActive = !!solveStatus && SOLVE_ACTIVE_STATUSES.has(solveStatus.status);
  const progressPct = solveStatus?.progress_percent ?? null;
  const est = solveStatus?.estimated_duration_range;
  const estLo = est ? String(Math.max(1, Math.round(est[0] / 60))) : "?";
  const estHi = est ? String(Math.max(1, Math.round(est[1] / 60))) : "?";

  return (
    <div className="flex-1 flex flex-col bg-[#0a0f1a]">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <span className="text-sm font-medium text-foreground">Abaqus — {VIDEOS[videoIdx].title}</span>
        <div className="flex items-center gap-1.5">
          {VIDEOS.map((v, i) => (
            <button
              key={v.id}
              onClick={() => selectVideo(i)}
              className={`px-2 py-0.5 text-[11px] rounded-md transition-colors cursor-pointer ${i === videoIdx ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"}`}
            >
              {v.label}
            </button>
          ))}
          {(hasRaw || hasNative) && (
            <>
              <span className="w-px h-3 bg-border/60 mx-0.5" />
              <button
                onClick={() => selectStyle("rendered")}
                className={`px-2 py-0.5 text-[11px] rounded-md transition-colors cursor-pointer ${solveStyle === "rendered" ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"}`}
              >
                {t("abaqus.style_rendered", lang)}
              </button>
              {/* raw 与 native 互斥：选中其一后隐藏另一个入口，需先回简洁版再切换 */}
              {hasRaw && solveStyle !== "native" && (
                <button
                  onClick={() => selectStyle("raw")}
                  className={`px-2 py-0.5 text-[11px] rounded-md transition-colors cursor-pointer ${solveStyle === "raw" ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"}`}
                >
                  {t("abaqus.style_raw", lang)}
                </button>
              )}
              {hasNative && solveStyle !== "raw" && (
                <button
                  onClick={() => selectStyle("native")}
                  className={`px-2 py-0.5 text-[11px] rounded-md transition-colors cursor-pointer ${solveStyle === "native" ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"}`}
                >
                  原生云图版
                </button>
              )}
            </>
          )}
          {videoError && (
            <span className="text-[10px] text-amber-500/80 flex items-center gap-1">
              <AlertTriangle className="h-3 w-3" /> 视频未生成
            </span>
          )}
        </div>
      </div>
      {solveActive && (
        <div className="flex items-center gap-3 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2">
          <Loader2 className="h-4 w-4 text-amber-500 animate-spin shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2 mb-1">
              <span className="text-[11px] text-foreground/90 truncate">
                {progressPct !== null
                  ? t("abaqus.solving", lang).replace("{p}", String(progressPct)).replace("{lo}", estLo).replace("{hi}", estHi)
                  : t("abaqus.solving_started", lang).replace("{lo}", estLo).replace("{hi}", estHi)}
              </span>
              {stopError && <span className="text-[10px] text-red-500/90 shrink-0">{stopError}</span>}
            </div>
            <div className="h-1.5 w-full rounded-full bg-border/50 overflow-hidden">
              <div
                className="h-full rounded-full bg-amber-500 transition-all duration-500"
                style={{ width: `${progressPct ?? 0}%` }}
              />
            </div>
          </div>
          <button
            onClick={stopSolve}
            className="flex items-center gap-1 px-2.5 py-1 rounded-md border border-red-500/40 text-red-500 hover:bg-red-500/10 transition-colors cursor-pointer text-[11px] shrink-0"
          >
            <XCircle className="h-3.5 w-3.5" /> {t("abaqus.stop", lang)}
          </button>
        </div>
      )}
      {footprint && footprintVideoId === VIDEOS[videoIdx].id && (
        <div className="flex items-center gap-3 border-b border-border/60 px-4 py-1.5 text-[11px] text-muted-foreground flex-wrap">
          <span>最大占地半径 {round1(footprint.max_radius_m)}m（塔底 {round1(footprint.tower_base_radius_m)}m，比值 {round2(footprint.ratio_max)}）</span>
          <span>P95 占地半径 {round1(footprint.p95_radius_m)}m</span>
          <span>倒塌方向约 {Math.round(footprint.direction_deg)}°</span>
          <span>末帧塔最高点约 {round1(footprint.final_height_m)}m</span>
        </div>
      )}
      <div ref={containerRef} className="flex-1 flex items-center justify-center bg-black/40 relative">
        {/* Fallback: video source not available */}
        {videoError ? (
          <div className="flex flex-col items-center gap-4 text-center px-8">
            <AlertTriangle className="h-12 w-12 text-amber-500/50" />
            <div>
              <p className="text-sm text-foreground font-medium mb-1">模拟视频尚未生成</p>
              <p className="text-xs text-muted-foreground leading-relaxed max-w-[280px]">
                需要通过 Abaqus 仿真引擎运行倒塌模拟后生成。
                <br />
                请确保 Abaqus 环境已正确安装，然后通过对话指令触发仿真管线。
              </p>
            </div>
            <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground/60 mt-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              等待 Abaqus 服务就绪...
            </div>
          </div>
        ) : (
          <video
            key={videoKey}
            ref={videoRef}
            src={videoSrc}
            muted={muted}
            className="max-w-full max-h-full"
            onError={handleError}
            onLoadedData={handleLoadedData}
            onEnded={() => { setPlaying(false); setEnded(true); }}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
          />
        )}
        {ended && !videoError && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50">
            <span className="text-sm text-muted-foreground">播放完毕</span>
          </div>
        )}
      </div>
      <div className="flex items-center gap-3 border-t border-border px-4 py-2">
        {videoError ? (
          <span className="text-[11px] text-muted-foreground/50 italic">
            Abaqus 服务未启动 — 请检查服务状态
          </span>
        ) : (
          <>
            <button
              onClick={togglePlay}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md hover:bg-muted/50 transition-colors cursor-pointer text-xs text-muted-foreground hover:text-foreground"
            >
              {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              {playing ? "暂停" : ended ? "重播" : "播放"}
            </button>
            <button
              onClick={() => setMuted(!muted)}
              className="flex items-center gap-1 px-3 py-1.5 rounded-md hover:bg-muted/50 transition-colors cursor-pointer text-xs text-muted-foreground hover:text-foreground"
            >
              {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
              {muted ? "取消静音" : "静音"}
            </button>
            <button
              onClick={toggleFullscreen}
              className="flex items-center gap-1 px-3 py-1.5 rounded-md hover:bg-muted/50 transition-colors cursor-pointer text-xs text-muted-foreground hover:text-foreground"
            >
              {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              {isFullscreen ? "退出全屏" : "全屏"}
            </button>
          </>
        )}
        <span className="ml-auto text-[10px] text-muted-foreground/50">
          {playing ? "播放中" : ended ? "已结束" : "已暂停"}
        </span>
      </div>
    </div>
  );
}
