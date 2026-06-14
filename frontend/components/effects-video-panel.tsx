"use client";

import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import {
  Loader2, Box, Film, Sparkles, X,
  Camera, RefreshCw, SunMoon, Grid3X3, Layers, Building2, Ruler,
  Zap, BookTemplate, Cpu, ArrowRight, ChevronDown, CheckCircle2, AlertCircle,
  Plus, History, ImageIcon, Download,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Effects3DViewer, type Effects3DViewerHandle } from "@/components/effects-3d-viewer";
import { EffectsVideoPlayer } from "@/components/effects-video-player";
import { t, type Lang } from "@/lib/i18n";
import type { FrameStructure } from "@/lib/state-restore";
import { cn } from "@/lib/utils";

const API_BASE = "http://localhost:8000";

const COLUMN_SECTIONS = [
  "HW150x150x7x10", "HW200x200x8x12", "HW250x250x9x14",
  "HW300x300x10x15", "HW350x350x12x19", "HW400x400x13x21",
  "HW450x450x14x23", "HW500x500x16x25",
];

const BEAM_SECTIONS = [
  "HM200x150x6x9", "HM244x175x7x11", "HM294x200x8x12",
  "HM340x250x9x14", "HM390x300x10x16", "HM440x300x11x18",
  "HM500x300x11x18", "HM550x300x12x20", "HM600x300x12x22",
];

const MATERIALS = ["Q235", "Q355", "Q390", "Q420"];

const PRESETS = [
  {
    label: "标准办公楼", icon: "🏢",
    params: {
      grid_x: "6,6,6", grid_y: "6,6,6", num_stories: 4,
      story_heights: "4.5,3.6,3.6,3.6",
      column_section: "HW400x400x13x21", beam_section: "HM390x300x10x16",
      material: "Q355",
    },
  },
  {
    label: "轻型厂房", icon: "🏭",
    params: {
      grid_x: "9,9,9", grid_y: "6,6", num_stories: 2,
      story_heights: "6.0,4.5",
      column_section: "HW350x350x12x19", beam_section: "HM340x250x9x14",
      material: "Q235",
    },
  },
  {
    label: "高层框架", icon: "🏗️",
    params: {
      grid_x: "8,8", grid_y: "8,8", num_stories: 8,
      story_heights: "4.5,4.2,4.2,4.2,4.2,4.2,4.2,4.2",
      column_section: "HW400x400x13x21", beam_section: "HM390x300x10x16",
      material: "Q355",
    },
  },
];

interface HistoryEntry {
  id: string;
  name: string;
  createdAt: number;
  taskId: string;
  videoUrl: string;
  imageUrl?: string;
  entryType: "video" | "image";
  modelData: FrameStructure | null;
  markedColumns: number[];
  quality: string;
  prompt: string;
  // Generation params for model regeneration
  gridX: string;
  gridY: string;
  numStories: number;
  storyHeights: string;
  columnSection: string;
  beamSection: string;
  material: string;
}

const HISTORY_KEY = "caiao_effects_history";

function loadHistory(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveHistory(entries: HistoryEntry[]) {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, 50))); } catch { /* ignore */ }
}

function strVal(v: unknown): string {
  if (!v) return "";
  if (typeof v === "string") return v;
  try { return JSON.stringify(v); } catch { return String(v); }
}

function formatTs(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

interface Props {
  lang: Lang;
  onClose: () => void;
}

type ExportStage = "idle" | "submitting" | "queued" | "processing" | "completed" | "failed";

function FloatingInput({ label, value, onChange, icon, placeholder, type = "text", step }: {
  label: string; value: string; onChange: (v: string) => void;
  icon?: React.ReactNode; placeholder?: string; type?: string; step?: string;
}) {
  return (
    <div className="relative">
      <input type={type} step={step} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        className="w-full h-8 rounded border border-border/60 bg-transparent px-2 pt-3 pb-1 text-xs text-white outline-none focus:border-cyan/50 transition-colors" />
      <label className="absolute left-2 top-0.5 text-[8px] text-muted-foreground pointer-events-none">{label}</label>
      {icon && <span className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/40">{icon}</span>}
    </div>
  );
}

function SelectInput({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: string[];
}) {
  return (
    <div className="relative">
      <select value={value} onChange={e => onChange(e.target.value)}
        className="w-full h-8 rounded border border-border/60 bg-transparent px-2 pt-2 pb-1 text-xs text-white outline-none focus:border-cyan/50 appearance-none">
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
      <label className="absolute left-2 top-0.5 text-[8px] text-muted-foreground pointer-events-none">{label}</label>
      <ChevronDown size={10} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/40 pointer-events-none" />
    </div>
  );
}

export function EffectsVideoPanel({ lang, onClose }: Props) {
  const [gridX, setGridX] = useState("6,6,6");
  const [gridY, setGridY] = useState("6,6,6");
  const [stories, setStories] = useState(4);
  const [storyHeights, setStoryHeights] = useState("4.5,3.6,3.6,3.6");
  const [columnSection, setColumnSection] = useState("HW400x400x13x21");
  const [beamSection, setBeamSection] = useState("HM390x300x10x16");
  const [material, setMaterial] = useState("Q355");
  const [modelData, setModelData] = useState<FrameStructure | null>(null);
  const [status, setStatus] = useState<"ready" | "generating" | "complete">("ready");
  const [customPrompt, setCustomPrompt] = useState("");
  const [markedColumns, setMarkedColumns] = useState<number[]>([]);
  const [displayMode, setDisplayMode] = useState("shaded");
  const [autoRotate, setAutoRotate] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const [activePreset, setActivePreset] = useState<number | null>(0);
  const [exportStage, setExportStage] = useState<ExportStage>("idle");
  const [exportMsg, setExportMsg] = useState<string>("");
  const [videoUrl, setVideoUrl] = useState<string>("");
  const [videoTaskId, setVideoTaskId] = useState<string>("");
  const [quality, setQuality] = useState<"low" | "medium" | "high" | "cinematic">("high");
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [viewMode, setViewMode] = useState<"video" | "model">("video");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameInput, setRenameInput] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const viewerRef = useRef<Effects3DViewerHandle>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const progressRef = useRef(0);
  const [genImageStage, setGenImageStage] = useState<"idle" | "capturing" | "generating" | "completed" | "failed">("idle");
  const [genImageMsg, setGenImageMsg] = useState("");
  const [genImageUrl, setGenImageUrl] = useState("");
  const [imgScale, setImgScale] = useState(1);
  const [imgPan, setImgPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });

  // Load history on mount
  useEffect(() => { setHistory(loadHistory()); }, []);

  // Auto-save on completion
  useEffect(() => {
    if (exportStage !== "completed" || !videoUrl || !videoTaskId) return;
    const entries = loadHistory();
    // Avoid duplicate save for same taskId
    if (entries.some(e => e.taskId === videoTaskId)) return;
    const ts = Date.now();
    const entry: HistoryEntry = {
      id: `task_${ts}`,
      name: formatTs(ts),
      createdAt: ts,
      taskId: videoTaskId,
      videoUrl,
      entryType: "video",
      modelData,
      markedColumns: [...markedColumns],
      quality,
      prompt: customPrompt,
      gridX,
      gridY,
      numStories: stories,
      storyHeights,
      columnSection,
      beamSection,
      material,
    };
    const updated = [entry, ...entries].slice(0, 50);
    saveHistory(updated);
    setHistory(updated);
  }, [exportStage, videoUrl, videoTaskId, modelData, markedColumns, quality, customPrompt,
      gridX, gridY, stories, storyHeights, columnSection, beamSection, material]);

  // Auto-save generated images to history
  useEffect(() => {
    if (genImageStage !== "completed" || !genImageUrl) return;
    const entries = loadHistory();
    const ts = Date.now();
    const entry: HistoryEntry = {
      id: `img_${ts}`,
      name: `图片 ${formatTs(ts)}`,
      createdAt: ts,
      taskId: "",
      videoUrl: "",
      imageUrl: genImageUrl,
      entryType: "image",
      modelData: null,
      markedColumns: [],
      quality: "",
      prompt: customPrompt,
      gridX: "",
      gridY: "",
      numStories: 0,
      storyHeights: "",
      columnSection: "",
      beamSection: "",
      material: "",
    };
    const updated = [entry, ...entries].slice(0, 50);
    saveHistory(updated);
    setHistory(updated);
  }, [genImageStage, genImageUrl, customPrompt]);

  const handleNewTask = useCallback(() => {
    if (pollTimerRef.current) { clearInterval(pollTimerRef.current); pollTimerRef.current = null; }
    setModelData(null); setStatus("ready"); setMarkedColumns([]);
    setExportStage("idle"); setExportMsg(""); setVideoUrl(""); setVideoTaskId(""); setViewMode("video");
    setGenImageStage("idle"); setGenImageUrl(""); setGenImageMsg("");
    setImgScale(1); setImgPan({ x: 0, y: 0 });
    progressRef.current = 0;
    setActivePreset(0);
  }, []);

  const handleOpenHistory = useCallback(async (entry: HistoryEntry) => {
    setShowHistory(false);
    if (entry.entryType === "image") {
      setGenImageStage("completed");
      setGenImageUrl(entry.imageUrl || "");
      if (entry.prompt) setCustomPrompt(entry.prompt);
      return;
    }
    if (!entry.videoUrl) return;
    // Restore all UI state from history
    setExportStage("completed");
    setExportMsg("视频生成完成 ✓");
    setViewMode("video");
    setVideoUrl(entry.videoUrl);
    setVideoTaskId(entry.taskId);
    if (entry.gridX) setGridX(entry.gridX);
    if (entry.gridY) setGridY(entry.gridY);
    if (entry.numStories) setStories(entry.numStories);
    if (entry.storyHeights) setStoryHeights(entry.storyHeights);
    if (entry.columnSection) setColumnSection(entry.columnSection);
    if (entry.beamSection) setBeamSection(entry.beamSection);
    if (entry.material) setMaterial(entry.material);
    setMarkedColumns(entry.markedColumns || []);
    setQuality(entry.quality as "low" | "medium" | "high" | "cinematic");
    setCustomPrompt(entry.prompt || "");
    try { sessionStorage.setItem("caiao_effects_video", JSON.stringify({ url: entry.videoUrl, taskId: entry.taskId })); } catch { /* ignore */ }
    // Regenerate model if not saved
    if (!entry.modelData && entry.gridX) {
      try {
        const parseArr = (s: string) => s.split(",").map(Number).filter(v => !isNaN(v));
        const resp = await fetch(`${API_BASE}/api/effects/generate-frame`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            grid_x: parseArr(entry.gridX),
            grid_y: parseArr(entry.gridY),
            num_stories: entry.numStories,
            story_heights: parseArr(entry.storyHeights || "3.6"),
            column_section: entry.columnSection || "HW400x400x13x21",
            beam_section: entry.beamSection || "HM390x300x10x16",
            material: entry.material || "Q355",
          }),
        });
        if (resp.ok) {
          const data = await resp.json();
          if (data.nodes && data.elements) {
            setModelData(data as unknown as FrameStructure);
          }
        }
      } catch { /* model regeneration failed, user can regenerate manually */ }
    } else if (entry.modelData) {
      setModelData(entry.modelData);
    }
  }, []);

  const handleDeleteHistory = useCallback((e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (deletingId !== id) {
      // First click: ask confirmation
      setDeletingId(id);
      setTimeout(() => setDeletingId(prev => prev === id ? null : prev), 3000);
      return;
    }
    // Second click within 3s: confirm delete
    setDeletingId(null);
    const updated = history.filter(h => h.id !== id);
    saveHistory(updated);
    setHistory(updated);
  }, [history, deletingId]);

  const handleStartRename = useCallback((e: React.MouseEvent, entry: HistoryEntry) => {
    e.stopPropagation();
    setRenamingId(entry.id);
    setRenameInput(entry.name);
  }, []);

  const handleConfirmRename = useCallback(() => {
    if (!renamingId || !renameInput.trim()) {
      setRenamingId(null);
      return;
    }
    const updated = history.map(h =>
      h.id === renamingId ? { ...h, name: renameInput.trim() } : h
    );
    saveHistory(updated);
    setHistory(updated);
    setRenamingId(null);
    setRenameInput("");
  }, [renamingId, renameInput, history]);

  const handleRenameKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleConfirmRename();
    } else if (e.key === "Escape") {
      setRenamingId(null);
    }
  }, [handleConfirmRename]);

  // Quality preset constants
  const QUALITY_OPTIONS: { key: "low" | "medium" | "high" | "cinematic"; label: string; desc: string }[] = [
    { key: "low", label: "低", desc: "384p 最快" },
    { key: "medium", label: "中", desc: "512p 均衡" },
    { key: "high", label: "高", desc: "768p 推荐" },
    { key: "cinematic", label: "电影", desc: "1080p 最慢" },
  ];

  // Restore completed video from sessionStorage on mount
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem("caiao_effects_video");
      if (saved) {
        const { url, taskId } = JSON.parse(saved);
        if (url) { setVideoUrl(url); setVideoTaskId(taskId || ""); setExportStage("completed"); }
      }
    } catch { /* ignore */ }
  }, []);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => { if (pollTimerRef.current) clearInterval(pollTimerRef.current); };
  }, []);

  const applyPreset = (idx: number) => {
    const p = PRESETS[idx].params;
    setGridX(p.grid_x); setGridY(p.grid_y); setStories(p.num_stories);
    setStoryHeights(p.story_heights); setColumnSection(p.column_section);
    setBeamSection(p.beam_section); setMaterial(p.material); setActivePreset(idx);
  };

  const summary = useMemo(() => {
    const nx = gridX.split(",").filter(Boolean).length;
    const ny = gridY.split(",").filter(Boolean).length;
    const ns = stories || 0;
    const totalHeight = storyHeights.split(",").reduce((s, v) => s + (Number(v) || 0), 0);
    return { nx, ny, ns, totalHeight, totalColumns: (nx + 1) * (ny + 1) * ns };
  }, [gridX, gridY, stories, storyHeights]);

  const handleGenerate = useCallback(async () => {
    setStatus("generating"); setMarkedColumns([]); setExportStage("idle"); setVideoUrl(""); setViewMode("video");
    try {
      const parseArr = (s: string) => s.split(",").map(Number).filter(v => !isNaN(v));
      const resp = await fetch(`${API_BASE}/api/effects/generate-frame`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          grid_x: parseArr(gridX), grid_y: parseArr(gridY),
          num_stories: stories, story_heights: parseArr(storyHeights),
          column_section: columnSection, beam_section: beamSection, material,
        }),
      });
      if (!resp.ok) throw new Error(`Generate failed: ${resp.status}`);
      const data = await resp.json();
      if (data.nodes && data.elements) {
        setModelData(data as unknown as FrameStructure);
        setStatus("complete");
      } else throw new Error("Invalid model data");
    } catch (err) {
      console.error("Generate failed:", err);
      setStatus("ready");
    }
  }, [gridX, gridY, stories, storyHeights, columnSection, beamSection, material]);

  const handleColumnClick = useCallback((elementId: number) => {
    setMarkedColumns(prev =>
      prev.includes(elementId) ? prev.filter(id => id !== elementId) : [...prev, elementId]
    );
  }, []);

  const handleExport = useCallback(async () => {
    if (!modelData || markedColumns.length === 0) return;
    setExportStage("submitting"); setExportMsg(""); setVideoUrl("");
    progressRef.current = 0;

    // Capture multi-angle screenshots for video reference frames
    let frames: string[] = [];
    try {
      if (viewerRef.current?.captureAllAngles) {
        const captured = await viewerRef.current.captureAllAngles();
        frames = captured.filter(Boolean);
        setExportMsg(`已采集 ${frames.length} 个视角截图`);
      }
    } catch { /* multi-angle capture optional */ }

    try {
      setExportMsg(`正在提交 (${quality})...`);
      const resp = await fetch(`${API_BASE}/api/effects/export-video`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          modelData, markedColumns,
          quality,
          frames,
          scene: customPrompt || "mechanical_demolition",
          prompt: customPrompt || "",
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setExportStage("failed");
        setExportMsg(`导出失败: ${strVal(data.error) || strVal(data.message) || `HTTP ${resp.status}`}`);
        return;
      }
      const st = data.status || "";
      const err = strVal(data.error);
      const taskId = data.task_id || "";
      setVideoTaskId(taskId);

      if (err && st === "error") {
        setExportStage("failed");
        setExportMsg(`导出失败: ${err}`);
      } else if (taskId) {
        setExportStage("queued");
        setExportMsg("任务已提交，正在查询状态...");
        const startTime = Date.now();
        // Poll for status
        pollTimerRef.current = setInterval(async () => {
          try {
            const sr = await fetch(`${API_BASE}/api/effects/status/${taskId}`);
            if (!sr.ok) {
              setExportStage("failed");
              setExportMsg(`状态查询失败: HTTP ${sr.status}`);
              if (pollTimerRef.current) clearInterval(pollTimerRef.current);
              return;
            }
            const sd = await sr.json();
            const sst = sd.status || "unknown";
            if (sst === "completed" || sst === "done" || sst === "succeeded") {
              setExportStage("completed");
              setExportMsg("视频生成完成 ✓");
              const url = sd.video_url || sd.remixed_from_video_id || sd.output?.video_url || "";
              setVideoUrl(url);
              setVideoTaskId(taskId);
              try { sessionStorage.setItem("caiao_effects_video", JSON.stringify({ url, taskId })); } catch { /* ignore */ }
              if (pollTimerRef.current) clearInterval(pollTimerRef.current);
            } else if (sst === "failed" || sst === "error") {
              const errDetail = strVal(sd.error) || strVal(sd.detail) || strVal(sd.message) || "未知错误";
              setExportStage("failed");
              setExportMsg(`视频生成失败: ${errDetail}`);
              if (pollTimerRef.current) clearInterval(pollTimerRef.current);
            } else {
              const serverPct = typeof sd.progress === "number" ? Math.round(sd.progress) : 0;
              // 1% smoothing: increment by 1 each tick toward server-reported progress
              if (serverPct > progressRef.current) {
                progressRef.current = Math.min(progressRef.current + 1, serverPct);
              }
              const displayPct = progressRef.current;
              const elapsed = (Date.now() - startTime) / 1000;
              let eta = "";
              if (displayPct > 0) {
                const totalEst = elapsed / (displayPct / 100);
                const remaining = Math.round(totalEst - elapsed);
                if (remaining > 60) {
                  const m = Math.floor(remaining / 60);
                  const s = remaining % 60;
                  eta = `，剩余约 ${m} 分 ${s} 秒`;
                } else if (remaining > 0) {
                  eta = `，剩余约 ${remaining} 秒`;
                }
              }
              setExportStage("processing");
              setExportMsg(`生成中... ${displayPct}%${eta}`);
            }
          } catch (pollErr) {
            console.error("Status polling error:", pollErr);
          }
        }, 3000);
      } else {
        const errMsg = strVal(data.error) || strVal(data.message) || "后端未返回任务 ID";
        setExportStage("failed");
        setExportMsg(`导出任务失败: ${errMsg}`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setExportStage("failed");
      setExportMsg(`导出失败: ${msg}`);
      console.error("Export failed:", err);
    }
  }, [modelData, markedColumns, customPrompt, quality, gridX, gridY, stories, storyHeights, columnSection, beamSection, material]);

  const captureScreenshot = useCallback(() => {
    const canvas = document.querySelector("canvas");
    if (!canvas) return;
    const link = document.createElement("a");
    link.download = `caiao-model-${Date.now()}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
  }, []);

  const handleGenerateImage = useCallback(async () => {
    if (!viewerRef.current?.captureAllAngles || genImageStage === "generating" || genImageStage === "capturing") return;
    setGenImageStage("capturing");
    setGenImageMsg("正在采集视角...");
    setGenImageUrl("");

    try {
      // Capture a single 45-degree screenshot
      const captured = await viewerRef.current.captureAllAngles();
      const screenshot = captured?.[2]; // index 2 = 45-degree angle
      if (!screenshot) {
        setGenImageStage("failed");
        setGenImageMsg("截图失败");
        return;
      }
      setGenImageStage("generating");
      setGenImageMsg("正在生成真实渲染图...");

      const resp = await fetch(`${API_BASE}/api/effects/generate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image: screenshot,
          prompt: customPrompt || "",
          project_id: videoTaskId || "",
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setGenImageStage("failed");
        setGenImageMsg(strVal(data.error) || `HTTP ${resp.status}`);
        return;
      }
      const url = data.image_url || "";
      if (url) {
        setGenImageUrl(url);
        setGenImageStage("completed");
        setGenImageMsg("生成完成 ✓");
      } else {
        setGenImageStage("failed");
        setGenImageMsg("未返回图片 URL");
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setGenImageStage("failed");
      setGenImageMsg(msg);
      console.error("Generate image failed:", err);
    }
  }, [customPrompt, genImageStage]);

  const handleImgWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.1 : 0.1;
    setImgScale(prev => Math.max(0.2, Math.min(5, prev + delta)));
  }, []);

  const handleImgMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button === 0) {
      setIsPanning(true);
      setPanStart({ x: e.clientX - imgPan.x, y: e.clientY - imgPan.y });
    }
  }, [imgPan]);

  const handleImgMouseMove = useCallback((e: React.MouseEvent) => {
    if (isPanning) {
      setImgPan({ x: e.clientX - panStart.x, y: e.clientY - panStart.y });
    }
  }, [isPanning, panStart]);

  const handleImgMouseUp = useCallback(() => {
    setIsPanning(false);
  }, []);

  const resetImgView = useCallback(() => {
    setImgScale(1);
    setImgPan({ x: 0, y: 0 });
  }, []);

  const handleAutoRotate = useCallback(() => {
    const next = !autoRotate;
    setAutoRotate(next);
    if (next) viewerRef.current?.setCameraPreset("orbit");
  }, [autoRotate]);

  return (
    <Card className="w-full h-full flex flex-col overflow-hidden border-border/80 shadow-2xl">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <Film className="h-5 w-5 text-primary" />
          <h2 className="text-sm font-semibold">特效视频</h2>
          <div className="flex gap-0.5 ml-2 bg-white/5 rounded-md p-0.5 border border-white/10">
            <button onClick={() => setViewMode("video")}
              className={cn("px-2 py-0.5 text-[10px] font-medium rounded transition-all",
                viewMode === "video"
                  ? "bg-cyan/20 text-cyan"
                  : "text-muted-foreground/60 hover:text-white")}>
              视频
            </button>
            <button onClick={() => setViewMode("model")}
              className={cn("px-2 py-0.5 text-[10px] font-medium rounded transition-all",
                viewMode === "model"
                  ? "bg-cyan/20 text-cyan"
                  : "text-muted-foreground/60 hover:text-white"
              )}
              disabled={!modelData}>
              模型
            </button>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <button onClick={handleNewTask}
            className="flex h-7 items-center gap-1 px-2 rounded-md hover:bg-muted transition-colors text-[11px] text-muted-foreground hover:text-white">
            <Plus size={12} />新任务
          </button>
          <button onClick={() => { setHistory(loadHistory()); setShowHistory(true); }}
            className="flex h-7 items-center gap-1 px-2 rounded-md hover:bg-muted transition-colors text-[11px] text-muted-foreground hover:text-white">
            <History size={12} />历史
          </button>
          <button onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-md hover:bg-muted transition-colors cursor-pointer">
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 relative bg-gradient-to-b from-background to-muted/30">
          {/* History overlay */}
          {showHistory && (
            <div className="absolute inset-0 z-20 bg-[#0a0b0d]/98 overflow-y-auto p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-semibold flex items-center gap-1.5">
                  <History size={13} className="text-cyan" />历史任务
                </h3>
                <button onClick={() => setShowHistory(false)}
                  className="text-[10px] text-muted-foreground hover:text-white px-2 py-1 rounded hover:bg-muted transition-colors">
                  关闭
                </button>
              </div>
              {history.length === 0 ? (
                <div className="text-center py-12">
                  <Film className="h-8 w-8 text-muted-foreground/20 mx-auto mb-2" />
                  <p className="text-xs text-muted-foreground/50">暂无历史任务</p>
                </div>
              ) : (
                <div className="space-y-1.5">
                  {history.map((entry) => (
                    <div key={entry.id} onClick={() => handleOpenHistory(entry)}
                      className="flex items-center justify-between px-3 py-2 rounded-lg bg-white/[0.03] border border-border/40 hover:bg-white/[0.06] hover:border-cyan/30 transition-all cursor-pointer group">
                      <div className="flex-1 min-w-0">
                        {renamingId === entry.id ? (
                          <input
                            value={renameInput}
                            onChange={e => setRenameInput(e.target.value)}
                            onBlur={handleConfirmRename}
                            onKeyDown={handleRenameKeyDown}
                            onClick={e => e.stopPropagation()}
                            autoFocus
                            className="w-full h-6 rounded border border-cyan/50 bg-black/40 px-1.5 text-xs text-white outline-none"
                          />
                        ) : (
                          <div className="text-xs font-medium truncate">{entry.name}</div>
                        )}
                        <div className="flex items-center gap-2 mt-0.5">
                          {entry.entryType === "image" ? (
                            <span className="text-[9px] text-blue-400/60">图片</span>
                          ) : (
                            <>
                              <span className="text-[9px] text-muted-foreground/60">{entry.quality}</span>
                              <span className="text-[9px] text-muted-foreground/60">{entry.markedColumns.length} 柱</span>
                            </>
                          )}
                          {entry.prompt && <span className="text-[9px] text-muted-foreground/40 truncate max-w-[120px]">{entry.prompt}</span>}
                        </div>
                      </div>
                      <div className="flex items-center gap-1 ml-2">
                        {renamingId === entry.id ? null : (
                          <button onClick={(e) => handleStartRename(e, entry)}
                            className="opacity-0 group-hover:opacity-100 text-[9px] text-muted-foreground/50 hover:text-white transition-all px-1.5 py-0.5 rounded hover:bg-white/10">
                            重命名
                          </button>
                        )}
                        <button onClick={(e) => handleDeleteHistory(e, entry.id)}
                          className={cn("opacity-0 group-hover:opacity-100 text-[9px] transition-all px-1.5 py-0.5 rounded",
                            deletingId === entry.id
                              ? "text-red-300 bg-red-500/20 animate-pulse"
                              : "text-red-400/60 hover:text-red-300 hover:bg-red-500/10"
                          )}>
                          {deletingId === entry.id ? "确认删除" : "删除"}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          {genImageUrl ? (
            <div className="absolute inset-0 flex items-center justify-center p-4"
              onWheel={handleImgWheel}
              onMouseDown={handleImgMouseDown}
              onMouseMove={handleImgMouseMove}
              onMouseUp={handleImgMouseUp}
              onMouseLeave={handleImgMouseUp}>
              <div className="w-full h-full flex flex-col">
                <div className="flex-1 rounded-lg overflow-hidden border border-border bg-black relative flex items-center justify-center cursor-grab active:cursor-grabbing select-none">
                  <img src={genImageUrl} alt="Generated rendering"
                    style={{
                      transform: `translate(${imgPan.x}px, ${imgPan.y}px) scale(${imgScale})`,
                      transition: isPanning ? 'none' : 'transform 0.1s ease',
                    }}
                    className="max-w-full max-h-full object-contain pointer-events-none" />
                </div>
                <div className="flex items-center justify-between mt-2">
                  <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                    <span>滚轮缩放 | 拖拽平移</span>
                    <span className="ml-2 font-mono">{Math.round(imgScale * 100)}%</span>
                    <button onClick={resetImgView}
                      className="px-1.5 py-0.5 rounded hover:bg-white/10 text-[9px]">
                      重置
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" className="gap-1.5 text-xs"
                      onClick={() => {
                        const a = document.createElement("a");
                        a.href = genImageUrl;
                        a.download = `rendering-${Date.now()}.png`;
                        a.click();
                      }}>
                      <Download className="h-3.5 w-3.5" />下载
                    </Button>
                    <Button variant="outline" size="sm" className="gap-1.5 text-xs"
                      onClick={() => { setGenImageUrl(""); setGenImageStage("idle"); resetImgView(); }}>
                      <X className="h-3.5 w-3.5" />关闭
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          ) : viewMode === "video" && videoUrl ? (
            <div className="absolute inset-0 flex items-center justify-center p-4">
              <EffectsVideoPlayer lang={lang} videoUrl={videoUrl} taskId={videoTaskId}
                onRegenerate={() => { setVideoUrl(""); setExportStage("idle"); setViewMode("video"); }} />
            </div>
          ) : modelData ? (
            <Effects3DViewer
              ref={viewerRef}
              modelData={modelData}
              markedColumns={markedColumns}
              onColumnClick={handleColumnClick}
              selectable={true}
              onScreenshot={(dataUrl, angle) => { console.debug(`Captured ${angle}: ${dataUrl.slice(0, 50)}...`); }}
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center">
                <Box className="h-12 w-12 text-muted-foreground/30 mx-auto mb-3" />
                <p className="text-sm text-muted-foreground">{t("effects_video.no_model", lang)}</p>
              </div>
            </div>
          )}
        </div>

        {/* Side Panel */}
        <div className="w-80 border-l border-border overflow-y-auto shrink-0 bg-[#0a0b0d]/95">
          <div className="flex flex-col h-full">
            <div className="flex-1 space-y-3 p-4">
              {/* 快速模板 */}
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <BookTemplate size={11} className="text-muted-foreground" />
                  <span className="text-[9px] text-muted-foreground uppercase tracking-wider">快速模板</span>
                </div>
                <div className="flex gap-1.5">
                  {PRESETS.map((p, i) => (
                    <button key={i} onClick={() => applyPreset(i)}
                      className={cn("flex-1 py-1.5 px-1.5 rounded text-[10px] font-medium text-center transition-all border",
                        activePreset === i
                          ? "bg-cyan/10 border-cyan/30 text-cyan"
                          : "bg-background border-border/50 text-muted-foreground hover:border-muted-foreground/30"
                      )}>
                      <span className="text-xs">{p.icon}</span>
                      <div className="truncate mt-0.5">{p.label}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* 几何参数 */}
              <div className="border border-border/40 rounded-lg p-3 space-y-2">
                <h4 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                  <Grid3X3 size={11} className="text-cyan/60" />几何参数
                </h4>
                <div className="grid grid-cols-2 gap-2">
                  <FloatingInput label="X向柱距 (m)" icon={<Ruler size={11} />} value={gridX} onChange={setGridX} placeholder="6,6,6" />
                  <FloatingInput label="Y向柱距 (m)" icon={<Ruler size={11} />} value={gridY} onChange={setGridY} placeholder="6,6,6" />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <FloatingInput label="层数" icon={<Layers size={11} />} type="number" value={String(stories)} onChange={v => setStories(Number(v))} />
                  <FloatingInput label="层高 (m)" icon={<Building2 size={11} />} value={storyHeights} onChange={setStoryHeights} placeholder="4.5,3.6,3.6,3.6" />
                </div>
              </div>

              {/* 截面与材料 */}
              <div className="border border-border/40 rounded-lg p-3 space-y-2">
                <h4 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                  <Grid3X3 size={11} className="text-cyan/60" />截面与材料
                </h4>
                <SelectInput label="柱截面" value={columnSection} onChange={setColumnSection} options={COLUMN_SECTIONS} />
                <SelectInput label="梁截面" value={beamSection} onChange={setBeamSection} options={BEAM_SECTIONS} />
                <SelectInput label="钢材" value={material} onChange={setMaterial} options={MATERIALS} />
              </div>

              {/* 模型预览 */}
              <div className="bg-gradient-to-r from-cyan/[0.04] to-transparent border border-cyan/10 rounded-lg p-3">
                <div className="text-[9px] text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                  <Zap size={10} className="text-cyan/60" />模型预览
                </div>
                <div className="grid grid-cols-4 gap-1 text-center">
                  <div className="bg-white/[0.03] rounded py-1.5">
                    <div className="text-xs font-semibold text-cyan font-mono">{summary.nx}x{summary.ny}</div>
                    <div className="text-[8px] text-muted-foreground">柱网</div>
                  </div>
                  <div className="bg-white/[0.03] rounded py-1.5">
                    <div className="text-xs font-semibold text-cyan font-mono">{summary.ns}</div>
                    <div className="text-[8px] text-muted-foreground">层数</div>
                  </div>
                  <div className="bg-white/[0.03] rounded py-1.5">
                    <div className="text-xs font-semibold text-cyan font-mono">{summary.totalHeight.toFixed(1)}m</div>
                    <div className="text-[8px] text-muted-foreground">总高</div>
                  </div>
                  <div className="bg-white/[0.03] rounded py-1.5">
                    <div className="text-xs font-semibold text-cyan font-mono">{summary.totalColumns}</div>
                    <div className="text-[8px] text-muted-foreground">构件</div>
                  </div>
                </div>
              </div>

              {/* 场景描述 */}
              <div>
                <label className="text-[9px] font-medium text-muted-foreground uppercase tracking-wider">场景描述</label>
                <input value={customPrompt} onChange={e => setCustomPrompt(e.target.value)}
                  placeholder="描述拆除场景，如：机械拆除倒塌"
                  className="w-full h-7 rounded border border-border/60 bg-transparent px-2 text-xs mt-1" />
              </div>

              {/* 画质选择 */}
              <div className="border border-border/40 rounded-lg p-3 space-y-2">
                <h4 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                  <Cpu size={11} className="text-cyan/60" />画质与速度
                </h4>
                <div className="flex gap-1">
                  {QUALITY_OPTIONS.map((q) => (
                    <button key={q.key} onClick={() => setQuality(q.key)}
                      className={cn("flex-1 py-1.5 rounded text-[9px] font-medium text-center transition-all border",
                        quality === q.key
                          ? "bg-cyan/10 border-cyan/30 text-cyan"
                          : "bg-background border-border/50 text-muted-foreground hover:border-muted-foreground/30"
                      )}>
                      <div>{q.label}</div>
                      <div className="text-[7px] opacity-60">{q.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* 生成按钮 */}
              <Button onClick={handleGenerate} disabled={status === "generating"} className="w-full gap-1.5 text-xs h-8" size="sm">
                {status === "generating" ? (
                  <><Loader2 className="h-3.5 w-3.5 animate-spin" />生成中...</>
                ) : (
                  <><Cpu size={14} />{modelData ? "重新生成" : "生成并分析"} <ArrowRight size={12} /></>
                )}
              </Button>

              {/* 场景控制 */}
              <div className="border border-border/40 rounded-lg p-3 space-y-2">
                <div className="text-[9px] text-muted-foreground uppercase tracking-wider">场景控制</div>
                <div className="flex gap-1">
                  {(["shaded", "wireframe", "xray"] as const).map((m) => (
                    <button key={m} onClick={() => { setDisplayMode(m); window.dispatchEvent(new CustomEvent("caiao-set-display", { detail: m })); }}
                      className={cn("flex-1 py-1 rounded text-[9px] font-medium transition-all",
                        displayMode === m
                          ? "bg-purple-500/20 text-purple-300 border border-purple-500/30"
                          : "text-muted-foreground bg-background border border-border/50 hover:bg-muted/50")}>
                      {m === "shaded" ? "Shaded" : m === "wireframe" ? "Wire" : "X-Ray"}
                    </button>
                  ))}
                </div>
                <div className="flex gap-1">
                  <button onClick={handleAutoRotate}
                    className={cn("flex-1 flex items-center justify-center gap-1 py-1 rounded text-[9px] font-medium transition-all",
                      autoRotate ? "bg-cyan/20 text-cyan border border-cyan/30" : "text-muted-foreground bg-background border border-border/50 hover:bg-muted/50")}>
                    <RefreshCw className={cn("h-2.5 w-2.5", autoRotate && "animate-spin")} /> Orbit
                  </button>
                  <button onClick={() => setShowGrid(!showGrid)}
                    className={cn("flex-1 flex items-center justify-center gap-1 py-1 rounded text-[9px] font-medium transition-all",
                      showGrid ? "bg-cyan/20 text-cyan border border-cyan/30" : "text-muted-foreground bg-background border border-border/50 hover:bg-muted/50")}>
                    <SunMoon className="h-2.5 w-2.5" /> Grid
                  </button>
                  <button onClick={captureScreenshot}
                    className="flex-1 flex items-center justify-center gap-1 py-1 rounded text-[9px] font-medium text-muted-foreground bg-background border border-border/50 hover:bg-muted/50">
                    <Camera className="h-2.5 w-2.5" /> SS
                  </button>
                </div>
              </div>

              {/* 已标记柱子 */}
              {markedColumns.length > 0 && (
                <div className="p-2 rounded-lg bg-primary/5 border border-primary/20">
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-[10px] text-muted-foreground">已标记 {markedColumns.length} 根柱</p>
                    <button onClick={() => setMarkedColumns([])}
                      className="text-[9px] text-red-400/70 hover:text-red-300 transition-colors">清除</button>
                  </div>
                  <div className="mt-1 flex gap-1 flex-wrap max-h-20 overflow-y-auto">
                    {markedColumns.map(id => (
                      <Badge key={id} variant="outline" className="text-[10px]">{id}</Badge>
                    ))}
                  </div>
                </div>
              )}

              {/* 导出区 */}
              <div className="w-full h-px bg-border/50" />
              {modelData && (
                <div className="flex flex-col gap-2">
                  <Button onClick={handleGenerateImage}
                    disabled={genImageStage === "capturing" || genImageStage === "generating"}
                    className="w-full gap-1.5" size="sm" variant="secondary">
                    {genImageStage === "capturing" || genImageStage === "generating" ? (
                      <><Loader2 className="h-3.5 w-3.5 animate-spin" /> 生成中...</>
                    ) : (
                      <><ImageIcon className="h-3.5 w-3.5" />生成特效图片</>
                    )}
                  </Button>
                  <Button onClick={handleExport}
                    disabled={markedColumns.length === 0 || exportStage === "submitting" || exportStage === "queued" || exportStage === "processing"}
                    className="w-full gap-1.5" size="sm" variant="secondary">
                    {exportStage === "submitting" || exportStage === "queued" || exportStage === "processing" ? (
                      <><Loader2 className="h-3.5 w-3.5 animate-spin" /> 导出中...</>
                    ) : (
                      <><Sparkles className="h-3.5 w-3.5" />生成特效视频</>
                    )}
                  </Button>
                </div>
              )}

              {/* 导出状态 */}
              {exportStage !== "idle" && (
                <div className={cn("flex items-center gap-1.5 px-2 py-1.5 rounded text-[10px]",
                  exportStage === "completed" ? "text-green-400 bg-green-500/10" :
                  exportStage === "failed" ? "text-red-400 bg-red-500/10" :
                  exportStage === "processing" ? "text-cyan-400 bg-cyan-500/10" :
                  "text-yellow-400 bg-yellow-500/10")}>
                  {exportStage === "completed" ? <CheckCircle2 size={12} /> :
                   exportStage === "failed" ? <AlertCircle size={12} /> :
                   <Loader2 size={12} className="animate-spin" />}
                  {exportMsg || exportStage}
                </div>
              )}
              {/* 图片生成状态 */}
              {genImageStage !== "idle" && (
                <div className={cn("flex items-center gap-1.5 px-2 py-1.5 rounded text-[10px]",
                  genImageStage === "completed" ? "text-green-400 bg-green-500/10" :
                  genImageStage === "failed" ? "text-red-400 bg-red-500/10" :
                  "text-yellow-400 bg-yellow-500/10")}>
                  {genImageStage === "completed" ? <CheckCircle2 size={12} /> :
                   genImageStage === "failed" ? <AlertCircle size={12} /> :
                   <Loader2 size={12} className="animate-spin" />}
                  {genImageMsg || genImageStage}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
      <div className="flex items-center justify-end gap-2 px-4 py-2 border-t border-border shrink-0">
        <span className="text-[10px] text-muted-foreground">
          {modelData ? "参考帧: 15" : "就绪"}
        </span>
      </div>
    </Card>
  );
}
