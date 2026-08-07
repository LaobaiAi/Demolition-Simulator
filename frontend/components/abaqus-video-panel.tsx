"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Play, Pause, Volume2, VolumeX, AlertTriangle, Loader2, Maximize2, Minimize2 } from "lucide-react";

const VIDEO_SRC = "/resource/Abaqus/煤仓间.mp4";

export function AbaqusVideoPanel() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  const [ended, setEnded] = useState(false);
  const [videoError, setVideoError] = useState(false);
  const [videoLoaded, setVideoLoaded] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

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

  return (
    <div className="flex-1 flex flex-col bg-[#0a0f1a]">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <span className="text-sm font-medium text-foreground">Abaqus — 煤仓间倒塌模拟</span>
        {videoError && (
          <span className="text-[10px] text-amber-500/80 flex items-center gap-1">
            <AlertTriangle className="h-3 w-3" /> 视频未生成
          </span>
        )}
      </div>
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
            ref={videoRef}
            src={VIDEO_SRC}
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
