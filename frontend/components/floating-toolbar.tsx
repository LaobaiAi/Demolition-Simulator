"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  Settings,
  Activity,
  Zap,
  Trash2,
  GripHorizontal,
  ChevronUp,
  Wifi,
  WifiOff,
} from "lucide-react";

interface FloatingToolbarProps {
  wsConnected: boolean;
  toolsCount: number;
  onOpenSettings: () => void;
  onClearChat: () => void;
  quickActions: string[];
  onQuickAction: (action: string) => void;
}

const DEFAULT_X = 16;
const DEFAULT_Y = 16;
const DRAG_THRESHOLD = 4;

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

export function FloatingToolbar({
  wsConnected,
  toolsCount,
  onOpenSettings,
  onClearChat,
  quickActions,
  onQuickAction,
}: FloatingToolbarProps) {
  const [expanded, setExpanded] = useState(false);
  const [dragging, setDragging] = useState(false);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const posRef = useRef({ x: DEFAULT_X, y: DEFAULT_Y });
  const dragRef = useRef<{ startX: number; startY: number; posX: number; posY: number; moved: boolean } | null>(null);

  // On mount, load saved position and apply via CSS variables
  useEffect(() => {
    let x = DEFAULT_X;
    let y = DEFAULT_Y;
    try {
      const saved = localStorage.getItem("xuanwu_toolbar_pos");
      if (saved) {
        const parsed = JSON.parse(saved);
        x = parsed.x ?? DEFAULT_X;
        y = parsed.y ?? DEFAULT_Y;
      }
    } catch {}
    posRef.current = { x, y };
    const el = toolbarRef.current;
    if (el) {
      el.style.setProperty("--toolbar-x", `${x}px`);
      el.style.setProperty("--toolbar-y", `${y}px`);
    }
  }, []);

  const applyPosition = useCallback((x: number, y: number) => {
    posRef.current = { x, y };
    const el = toolbarRef.current;
    if (el) {
      el.style.setProperty("--toolbar-x", `${x}px`);
      el.style.setProperty("--toolbar-y", `${y}px`);
    }
  }, []);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const { x, y } = posRef.current;
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        posX: x,
        posY: y,
        moved: false,
      };
    },
    []
  );

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!dragRef.current) return;
      const dx = e.clientX - dragRef.current.startX;
      const dy = e.clientY - dragRef.current.startY;

      if (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD) {
        dragRef.current.moved = true;
        setDragging(true);
      }

      if (dragRef.current.moved) {
        const newX = clamp(dragRef.current.posX + dx, 0, window.innerWidth - 280);
        const newY = clamp(dragRef.current.posY + dy, 0, window.innerHeight - 60);
        applyPosition(newX, newY);
      }
    };

    const handleMouseUp = (e: MouseEvent) => {
      if (!dragRef.current) return;
      const wasDrag = dragRef.current.moved;
      const wasExpanded = expanded;

      setDragging(false);
      dragRef.current = null;

      // Persist position
      try {
        localStorage.setItem("xuanwu_toolbar_pos", JSON.stringify(posRef.current));
      } catch {}

      // Short click without drag → toggle expand
      if (!wasDrag && !wasExpanded) {
        const target = e.target as HTMLElement;
        if (toolbarRef.current?.contains(target)) {
          setExpanded(true);
        }
      }
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [expanded, applyPosition]);

  // Inline style uses CSS variables with px fallback.
  // Server renders default; client useEffect sets --toolbar-x / --toolbar-y.
  const posStyle: React.CSSProperties = {
    left: `var(--toolbar-x, ${DEFAULT_X}px)`,
    top: `var(--toolbar-y, ${DEFAULT_Y}px)`,
  };

  return (
    <div
      ref={toolbarRef}
      onMouseDown={handleMouseDown}
      className={`fixed z-50 select-none rounded-xl border border-border bg-[#0f172a]/95 backdrop-blur-sm shadow-xl shadow-black/30 transition-shadow cursor-grab active:cursor-grabbing ${
        dragging ? "shadow-2xl shadow-black/50 ring-1 ring-primary/30" : ""
      }`}
      style={posStyle}
    >
      {/* Collapsed state */}
      {!expanded && (
        <div className="flex items-center gap-2 px-3 py-2 hover:bg-white/5 rounded-xl transition-colors">
          <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M4 4L16 16M16 4L4 16" stroke="#22d3ee" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="text-xs font-medium text-slate-300">XuanwuAI</span>
        </div>
      )}

      {/* Expanded state */}
      {expanded && (
        <div className="w-[260px]">
          {/* Drag handle */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-border/50 hover:bg-white/5 rounded-t-xl transition-colors">
            <div className="flex items-center gap-2 pointer-events-none">
              <GripHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
              <svg width="14" height="14" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M4 4L16 16M16 4L4 16" stroke="#22d3ee" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="text-xs font-semibold text-foreground">XuanwuAI</span>
            </div>
            <button
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => setExpanded(false)}
              className="flex h-5 w-5 items-center justify-center rounded hover:bg-muted transition-colors cursor-pointer"
            >
              <ChevronUp className="h-3 w-3 text-muted-foreground" />
            </button>
          </div>

          {/* Content */}
          <div className="p-2 space-y-1.5">
            {/* Status row */}
            <div className="flex items-center justify-between px-2 py-1.5 rounded-lg bg-white/[0.03]">
              <span className="text-[11px] text-muted-foreground">Gateway</span>
              <span className="flex items-center gap-1.5">
                {wsConnected ? (
                  <>
                    <Wifi className="h-3 w-3 text-emerald-400" />
                    <span className="text-[11px] font-medium text-emerald-400">Connected</span>
                  </>
                ) : (
                  <>
                    <WifiOff className="h-3 w-3 text-red-400" />
                    <span className="text-[11px] font-medium text-red-400">Offline</span>
                  </>
                )}
              </span>
            </div>

            <div className="flex items-center justify-between px-2 py-1.5 rounded-lg bg-white/[0.03]">
              <span className="text-[11px] text-muted-foreground">Tools</span>
              <span className="flex items-center gap-1.5">
                <Activity className="h-3 w-3 text-primary" />
                <span className="text-[11px] font-medium text-primary">{toolsCount} loaded</span>
              </span>
            </div>

            {/* Actions */}
            <div className="pt-1">
              <p className="px-2 py-1 text-[10px] text-muted-foreground uppercase tracking-wider">Actions</p>
              <button
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => onOpenSettings()}
                className="flex w-full items-center gap-2 px-2 py-1.5 rounded-md hover:bg-white/[0.05] transition-colors cursor-pointer text-left"
              >
                <Settings className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs text-foreground">LLM Settings</span>
              </button>
              <button
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => { onClearChat(); setExpanded(false); }}
                className="flex w-full items-center gap-2 px-2 py-1.5 rounded-md hover:bg-white/[0.05] transition-colors cursor-pointer text-left"
              >
                <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs text-foreground">Clear Chat</span>
              </button>
            </div>

            {/* Quick analyses */}
            <div className="pt-1">
              <p className="px-2 py-1 text-[10px] text-muted-foreground uppercase tracking-wider">
                Quick Analysis
              </p>
              <div className="space-y-0.5">
                {quickActions.slice(0, 5).map((action) => (
                  <button
                    key={action}
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={() => { onQuickAction(action); setExpanded(false); }}
                    className="flex w-full items-center gap-2 px-2 py-1.5 rounded-md hover:bg-white/[0.05] transition-colors cursor-pointer text-left"
                  >
                    <Zap className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                    <span className="text-xs text-foreground truncate">{action}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
