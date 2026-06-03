"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { Download, Video, FileVideo, StopCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { t, type Lang } from "@/lib/i18n";

// ── Types ───────────────────────────────────────────────────────────

interface AnimationExporterProps {
  lang: Lang;
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  fileName?: string;
  disabled?: boolean;
}

// ══════════════════════════════════════════════════════════════════════
// GIF Encoder (self-contained, no external dependencies)
// ══════════════════════════════════════════════════════════════════════

const CUBE_STEP = 51;
const CUBE_SIZE = 6;
const PALETTE_ENTRIES = 256;

function buildCubePalette(): number[][] {
  const p: number[][] = [];
  for (let ri = 0; ri < CUBE_SIZE; ri++) {
    for (let gi = 0; gi < CUBE_SIZE; gi++) {
      for (let bi = 0; bi < CUBE_SIZE; bi++) {
        p.push([ri * CUBE_STEP, gi * CUBE_STEP, bi * CUBE_STEP]);
      }
    }
  }
  while (p.length < PALETTE_ENTRIES) p.push([0, 0, 0]);
  return p;
}

function pixelToPaletteIndex(r: number, g: number, b: number): number {
  const ri = Math.min(CUBE_SIZE - 1, Math.round(r / CUBE_STEP));
  const gi = Math.min(CUBE_SIZE - 1, Math.round(g / CUBE_STEP));
  const bi = Math.min(CUBE_SIZE - 1, Math.round(b / CUBE_STEP));
  return ri * CUBE_SIZE * CUBE_SIZE + gi * CUBE_SIZE + bi;
}

function quantizeFrame(
  data: Uint8ClampedArray,
  w: number,
  h: number,
): Uint8Array {
  const len = w * h;
  const indexed = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    const off = i * 4;
    if (data[off + 3] < 128) {
      indexed[i] = 0;
    } else {
      indexed[i] = pixelToPaletteIndex(data[off], data[off + 1], data[off + 2]);
    }
  }
  return indexed;
}

// ── GIF LZW Encoder ────────────────────────────────────────────────

function gifLZWEncode(data: Uint8Array, minCodeSize: number): Uint8Array {
  const clearCode = 1 << minCodeSize;
  const eoiCode = clearCode + 1;
  let codeSize = minCodeSize + 1;
  let nextCode = clearCode + 2;

  const dict = new Map<string, number>();
  for (let i = 0; i < clearCode; i++) {
    dict.set(String.fromCharCode(i), i);
  }

  const codes: number[] = [clearCode];
  let current = String.fromCharCode(data[0]);

  for (let i = 1; i < data.length; i++) {
    const ch = String.fromCharCode(data[i]);
    const combined = current + ch;

    if (dict.has(combined)) {
      current = combined;
    } else {
      codes.push(dict.get(current)!);

      if (nextCode <= 4095) {
        dict.set(combined, nextCode++);
        if (nextCode === 1 << codeSize && codeSize < 12) {
          codeSize++;
        }
      } else {
        codes.push(clearCode);
        dict.clear();
        for (let j = 0; j < clearCode; j++) {
          dict.set(String.fromCharCode(j), j);
        }
        nextCode = clearCode + 2;
        codeSize = minCodeSize + 1;
      }

      current = ch;
    }
  }

  codes.push(dict.get(current)!);
  codes.push(eoiCode);

  // Pack codes into bytes
  const bytes: number[] = [];
  let buf = 0;
  let bits = 0;
  let cs = minCodeSize + 1;
  let nc = clearCode + 2;

  for (const code of codes) {
    buf |= code << bits;
    bits += cs;

    while (bits >= 8) {
      bytes.push(buf & 0xff);
      buf >>= 8;
      bits -= 8;
    }

    if (code === clearCode) {
      nc = clearCode + 2;
      cs = minCodeSize + 1;
    } else if (code !== eoiCode) {
      nc++;
      if (nc === 1 << cs && cs < 12) {
        cs++;
      }
    }
  }

  if (bits > 0) bytes.push(buf & 0xff);

  return new Uint8Array(bytes);
}

// ── GIF Binary Writer ──────────────────────────────────────────────

function writeWord(dest: number[], val: number): void {
  dest.push(val & 0xff, (val >> 8) & 0xff);
}

function encodeGIF(
  frames: ImageData[],
  width: number,
  height: number,
  fps: number,
): Blob {
  const palette = buildCubePalette();
  const delay = Math.round(100 / fps); // GIF delay in 10ms units

  const bytes: number[] = [];

  // GIF89a Header
  bytes.push(0x47, 0x49, 0x46, 0x38, 0x39, 0x61);

  // Logical Screen Descriptor
  writeWord(bytes, width);
  writeWord(bytes, height);
  // packed: GCT=1, colorRes=7, sorted=0, GCTsize=7 (256 = 2^8)
  bytes.push(0xf7);
  bytes.push(0x00); // bg color index
  bytes.push(0x00); // pixel aspect ratio

  // Global Color Table (256 * 3 = 768 bytes)
  for (const c of palette) bytes.push(c[0], c[1], c[2]);

  // Frames
  for (let fi = 0; fi < frames.length; fi++) {
    const indexed = quantizeFrame(frames[fi].data, width, height);

    // Graphics Control Extension
    bytes.push(0x21, 0xf9, 0x04, 0x00);
    writeWord(bytes, delay);
    bytes.push(0x00, 0x00);

    // Image Descriptor
    bytes.push(0x2c);
    writeWord(bytes, 0);
    writeWord(bytes, 0);
    writeWord(bytes, width);
    writeWord(bytes, height);
    bytes.push(0x00);

    // LZW minimum code size (8 bits for 256-color)
    const lzw = gifLZWEncode(indexed, 8);
    bytes.push(8);

    // Sub-blocks
    let j = 0;
    while (j < lzw.length) {
      const chunk = Math.min(255, lzw.length - j);
      bytes.push(chunk);
      for (let k = 0; k < chunk; k++) bytes.push(lzw[j++]);
    }
    bytes.push(0x00); // block terminator
  }

  // Trailer
  bytes.push(0x3b);

  return new Blob([new Uint8Array(bytes)], { type: "image/gif" });
}

// ══════════════════════════════════════════════════════════════════════
// Component
// ══════════════════════════════════════════════════════════════════════

export function AnimationExporter({
  lang,
  canvasRef,
  fileName = "demolition-animation",
  disabled = false,
}: AnimationExporterProps) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<
    "idle" | "recording" | "processing" | "done"
  >("idle");
  const [progress, setProgress] = useState(0);
  const [format, setFormat] = useState<"webm" | "gif" | null>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [frameCount, setFrameCount] = useState(0);
  const [frameDims, setFrameDims] = useState("0x0");

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const framesRef = useRef<ImageData[]>([]);
  const captureRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelledRef = useRef(false);

  // ── Cleanup ──────────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      if (captureRef.current) clearInterval(captureRef.current);
      recorderRef.current?.stop();
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [blobUrl]);

  // ── Click-outside to close dropdown ────────────────────────────

  useEffect(() => {
    if (!open) return;
    const handler = () => setOpen(false);
    window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, [open]);

  // ── Start Export ────────────────────────────────────────────────

  const startExport = useCallback(
    (fmt: "webm" | "gif") => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      setFormat(fmt);
      setState("recording");
      setProgress(0);
      setBlobUrl(null);
      cancelledRef.current = false;

      if (fmt === "webm") {
        const stream = canvas.captureStream(30);
        const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
          ? "video/webm;codecs=vp9"
          : MediaRecorder.isTypeSupported("video/webm;codecs=vp8")
            ? "video/webm;codecs=vp8"
            : "video/webm";

        const chunks: Blob[] = [];
        chunksRef.current = chunks;

        const recorder = new MediaRecorder(stream, { mimeType });
        recorder.ondataavailable = (e) => {
          if (e.data.size > 0) chunks.push(e.data);
        };
        recorder.onstop = () => {
          if (cancelledRef.current) return;
          const blob = new Blob(chunks, { type: "video/webm" });
          setBlobUrl(URL.createObjectURL(blob));
          setState("done");
          setProgress(100);
        };
        recorder.onerror = () => setState("idle");

        recorder.start(100);
        recorderRef.current = recorder;
        setProgress(2);
      } else {
        // GIF frame capture
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        if (!ctx) {
          setState("idle");
          return;
        }

        framesRef.current = [];
        const intervalMs = 100; // 10 fps capture

        const timer = setInterval(() => {
          if (cancelledRef.current) return;
          const w = canvas.width;
          const h = canvas.height;
          if (w > 0 && h > 0) {
            try {
              framesRef.current.push(ctx.getImageData(0, 0, w, h));
              setFrameCount(framesRef.current.length);
              if (frameCount === 0) setFrameDims(`${w}x${h}`);
              setProgress((prev) => Math.min(90, prev + 1));
            } catch {
              // canvas disposed during capture
            }
          }
        }, intervalMs);

        captureRef.current = timer;
      }
    },
    [canvasRef, frameCount],
  );

  // ── Stop Recording ───────────────────────────────────────────────

  const stopExport = useCallback(() => {
    if (format === "webm") {
      recorderRef.current?.stop();
    } else {
      if (captureRef.current) {
        clearInterval(captureRef.current);
        captureRef.current = null;
      }
      setState("processing");
    }
  }, [format]);

  // ── Process GIF frames ───────────────────────────────────────────

  useEffect(() => {
    if (state !== "processing" || format !== "gif") return;
    const frames = framesRef.current;
    if (frames.length === 0) {
      setState("idle");
      return;
    }

    // Yield to let progress UI render before heavy encoding
    const timer = setTimeout(() => {
      try {
        const w = frames[0].width;
        const h = frames[0].height;
        const blob = encodeGIF(frames, w, h, 10);
        if (!cancelledRef.current) {
          setBlobUrl(URL.createObjectURL(blob));
          setProgress(100);
          setState("done");
        }
      } catch (err) {
        console.error("GIF encoding error:", err);
        setState("idle");
      }
    }, 50);

    return () => clearTimeout(timer);
  }, [state, format]);

  // ── Download ─────────────────────────────────────────────────────

  const handleDownload = useCallback(() => {
    if (!blobUrl) return;
    const ext = format === "gif" ? "gif" : "webm";
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = `${fileName}.${ext}`;
    a.click();
  }, [blobUrl, format, fileName]);

  // ── Cancel / Reset ───────────────────────────────────────────────

  const handleCancel = useCallback(() => {
    cancelledRef.current = true;
    if (format === "webm") {
      recorderRef.current?.stop();
    } else if (captureRef.current) {
      clearInterval(captureRef.current);
      captureRef.current = null;
    }
    if (blobUrl) URL.revokeObjectURL(blobUrl);
    setBlobUrl(null);
    setState("idle");
    setProgress(0);
    setFormat(null);
  }, [format, blobUrl]);

  // ── Render ───────────────────────────────────────────────────────

  return (
    <div className="relative inline-flex">
      <Button
        size="icon-xs"
        variant="outline"
        disabled={disabled || state === "processing"}
        onClick={(e) => {
          e.stopPropagation();
          if (state === "recording") {
            stopExport();
          } else {
            setOpen((v) => !v);
          }
        }}
        title={
          state === "recording"
            ? t("export.stop_recording", lang)
            : t("export.export_animation", lang)
        }
        className={cn(
          state === "recording" &&
            "border-red-500/50 text-red-400 bg-red-500/10 animate-pulse",
        )}
      >
        {state === "recording" ? (
          <StopCircle className="h-3 w-3" />
        ) : (
          <Download className="h-3 w-3" />
        )}
      </Button>

      {/* Dropdown menu */}
      {open && state === "idle" && (
        <div className="absolute bottom-full right-0 mb-1.5 w-52 rounded-lg border border-border bg-background shadow-xl py-1 z-50 overflow-hidden">
          <button
            onClick={(e) => {
              e.stopPropagation();
              setOpen(false);
              startExport("webm");
            }}
            className="flex items-center gap-2.5 w-full px-3 py-2.5 text-xs text-left hover:bg-muted transition-colors cursor-pointer"
          >
            <Video className="h-4 w-4 text-muted-foreground shrink-0" />
            <div className="flex flex-col min-w-0">
              <span className="font-medium text-foreground">
                {t("export.export_webm", lang)}
              </span>
              <span className="text-[10px] text-muted-foreground/60">
                {t("export.export_webm_desc", lang)}
              </span>
            </div>
          </button>
          <div className="border-t border-border/50 mx-2" />
          <button
            onClick={(e) => {
              e.stopPropagation();
              setOpen(false);
              startExport("gif");
            }}
            className="flex items-center gap-2.5 w-full px-3 py-2.5 text-xs text-left hover:bg-muted transition-colors cursor-pointer"
          >
            <FileVideo className="h-4 w-4 text-muted-foreground shrink-0" />
            <div className="flex flex-col min-w-0">
              <span className="font-medium text-foreground">
                {t("export.export_gif", lang)}
              </span>
              <span className="text-[10px] text-muted-foreground/60">
                {t("export.export_gif_desc", lang)}
              </span>
            </div>
          </button>
        </div>
      )}

      {/* Recording overlay */}
      {state === "recording" && (
        <div className="absolute bottom-full right-0 mb-1.5 w-52 rounded-lg border border-red-500/30 bg-background shadow-xl p-3 z-50">
          <div className="flex items-center gap-2 mb-2">
            <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse shrink-0" />
            <span className="text-xs font-medium text-red-400">
              {t("export.recording", lang).replace("{what}", format === "gif" ? t("export.recording_frames", lang) : t("export.recording_video", lang))}
            </span>
            <span className="text-[10px] text-muted-foreground/60 ml-auto tabular-nums">
              {format === "gif"
                ? t("export.frames", lang).replace("{n}", String(frameCount))
                : t("export.percent", lang).replace("{n}", String(progress))}
            </span>
          </div>
          <div className="w-full h-1 rounded-full bg-muted overflow-hidden">
            <div
              className="h-full rounded-full bg-red-500 transition-all duration-300"
              style={{ width: `${Math.max(2, Math.min(95, progress))}%` }}
            />
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              stopExport();
            }}
            className="mt-2 w-full py-1.5 text-[10px] font-medium text-center text-red-400 hover:text-red-300 bg-red-500/10 hover:bg-red-500/20 rounded-md transition-colors cursor-pointer"
          >
            {t("export.stop_and_process", lang)}
          </button>
        </div>
      )}

      {/* Processing overlay */}
      {state === "processing" && (
        <div className="absolute bottom-full right-0 mb-1.5 w-52 rounded-lg border border-border bg-background shadow-xl p-3 z-50">
          <div className="flex items-center gap-2 mb-2">
            <Loader2 className="h-3.5 w-3.5 text-primary animate-spin shrink-0" />
            <span className="text-xs font-medium text-foreground">
              {t("export.encoding_gif", lang)}
            </span>
          </div>
          <div className="w-full h-1 rounded-full bg-muted overflow-hidden">
            <div className="h-full rounded-full bg-primary animate-pulse w-3/4" />
          </div>
          <p className="mt-1.5 text-[10px] text-muted-foreground/60">
            {frameCount} frames &middot;{" "}
            {frameDims}
          </p>
        </div>
      )}

      {/* Done overlay */}
      {state === "done" && blobUrl && (
        <div className="absolute bottom-full right-0 mb-1.5 w-52 rounded-lg border border-emerald-500/30 bg-background shadow-xl p-3 z-50">
          <div className="flex items-center gap-2 mb-2.5">
            <span className="h-2 w-2 rounded-full bg-emerald-500 shrink-0" />
            <span className="text-xs font-medium text-emerald-400">
              {t("export.export_ready", lang)}
            </span>
          </div>
          <div className="flex gap-1.5">
            <Button
              size="xs"
              variant="default"
              onClick={(e) => {
                e.stopPropagation();
                handleDownload();
              }}
              className="flex-1 h-7 text-[11px]"
            >
              <Download className="h-3 w-3 mr-1" />
              {t("export.download", lang)}
            </Button>
            <Button
              size="xs"
              variant="ghost"
              onClick={(e) => {
                e.stopPropagation();
                handleCancel();
              }}
              className="h-7 text-[11px]"
            >
              {t("export.close", lang)}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
