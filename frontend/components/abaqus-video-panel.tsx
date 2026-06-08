"use client";

import { useRef, useState } from "react";
import { Play, Pause, Volume2, VolumeX } from "lucide-react";

const VIDEO_SRC = "/resource/Abaqus/煤仓间.mp4";

export function AbaqusVideoPanel() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  const [ended, setEnded] = useState(false);

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

  return (
    <div className="flex-1 flex flex-col bg-[#0a0f1a]">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <span className="text-sm font-medium text-foreground">Abaqus — 煤仓间倒塌模拟</span>
      </div>
      <div className="flex-1 flex items-center justify-center bg-black/40 relative">
        <video
          ref={videoRef}
          src={VIDEO_SRC}
          muted={muted}
          className="max-w-full max-h-full"
          onEnded={() => { setPlaying(false); setEnded(true); }}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
        {ended && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50">
            <span className="text-sm text-muted-foreground">播放完毕</span>
          </div>
        )}
      </div>
      <div className="flex items-center gap-3 border-t border-border px-4 py-2">
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
        <span className="ml-auto text-[10px] text-muted-foreground/50">
          {playing ? "播放中" : ended ? "已结束" : "已暂停"}
        </span>
      </div>
    </div>
  );
}
