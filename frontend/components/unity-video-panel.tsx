"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Wifi, WifiOff, Monitor, Play, Pause, Loader2, ArrowRight, RotateCw, Radio, AlertTriangle } from "lucide-react";
import type { FrameStructure } from "@/lib/state-restore";

const GATEWAY = "http://localhost:8000";
const WS_URL = "ws://localhost:5006";
const HTTP_URL = "http://localhost:5006";
const POLL_INTERVAL_MS = 333;
const WS_CONNECT_TIMEOUT_MS = 8000;
const WS_MAX_CONSECUTIVE_FAILURES = 3;
const HTTP_UPGRADE_RETRY_INTERVAL_MS = 30000;
const BMP_HEADER_SIZE = 54;

type Phase =
  | "checking"
  | "not_installed"
  | "idle"
  | "launching"
  | "starting"
  | "connected"
  | "disconnected"
  | "error";

type Transport = "ws" | "http" | "none";

interface Props {
  onStreamConnected?: () => void;
  frameStructure?: FrameStructure | null;
}

function validateBmp(data: ArrayBuffer): boolean {
  if (data.byteLength < BMP_HEADER_SIZE) return false;
  const view = new DataView(data);
  return view.getUint8(0) === 0x42 && view.getUint8(1) === 0x4D;
}

export function UnityVideoPanel({ onStreamConnected, frameStructure }: Props) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [statusText, setStatusText] = useState("Detecting Unity...");
  const [videoScale, setVideoScale] = useState(1);
  const [imgUrl, setImgUrl] = useState("");
  const [transport, setTransport] = useState<Transport>("none");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [isPlaying, setIsPlaying] = useState(true);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const upgradeRetryRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hasConnected = useRef(false);
  const imgRef = useRef<HTMLImageElement>(null);
  const blobUrlRef = useRef<string>("");
  const reconnectAttemptRef = useRef(0);
  const mountedRef = useRef(true);
  const waitingForUnityRef = useRef(false);
  const connectWsRef = useRef<() => void>(() => {});
  const wsFailureCountRef = useRef(0);
  const transportRef = useRef<Transport>("none");
  const pollAbortRef = useRef<AbortController | null>(null);
  const frameStructureRef = useRef<FrameStructure | null | undefined>(null);
  const isPlayingRef = useRef(true);
  const lastFrameRef = useRef<string>("");

  useEffect(() => {
    frameStructureRef.current = frameStructure;
  }, [frameStructure]);

  useEffect(() => {
    isPlayingRef.current = isPlaying;
  }, [isPlaying]);

  const displayFrame = useCallback((url: string) => {
    lastFrameRef.current = url;
    if (isPlayingRef.current) {
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
      blobUrlRef.current = url;
      setImgUrl(url);
    }
  }, []);

  const syncToUnity = useCallback(async () => {
    const fs = frameStructureRef.current;
    if (!fs?.nodes?.length || !fs?.elements?.length) return;
    try {
      await fetch(GATEWAY + "/unity/build-frame", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ structure: fs }),
      });
    } catch {}
  }, []);

  useEffect(() => {
    if (frameStructure?.nodes?.length && transportRef.current !== "none") {
      syncToUnity();
    }
  }, [frameStructure, syncToUnity]);

  const setTransportBoth = useCallback((t: Transport) => {
    transportRef.current = t;
    setTransport(t);
  }, []);

  const cleanupWs = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      if (wsRef.current.readyState === WebSocket.OPEN ||
          wsRef.current.readyState === WebSocket.CONNECTING) {
        wsRef.current.close();
      }
      wsRef.current = null;
    }
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearTimeout(pollRef.current);
      pollRef.current = null;
    }
    if (pollAbortRef.current) {
      pollAbortRef.current.abort();
      pollAbortRef.current = null;
    }
    if (upgradeRetryRef.current) {
      clearInterval(upgradeRetryRef.current);
      upgradeRetryRef.current = null;
    }
  }, []);

  const startHttpPolling = useCallback(() => {
    if (!mountedRef.current) return;
    stopPolling();
    cleanupWs();
    setTransportBoth("http");
    setPhase("connected");
    setStatusText("Live (HTTP)");
    syncToUnity();

    const poll = async () => {
      if (!mountedRef.current || transportRef.current !== "http") return;
      const controller = new AbortController();
      pollAbortRef.current = controller;
      try {
        const res = await fetch(HTTP_URL + "/", {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const buf = await res.arrayBuffer();
        if (validateBmp(buf)) {
          const blob = new Blob([buf], { type: "image/bmp" });
          const url = URL.createObjectURL(blob);
          displayFrame(url);
          wsFailureCountRef.current = 0;
        }
      } catch (e: unknown) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        wsFailureCountRef.current++;
      }
      if (mountedRef.current && transportRef.current === "http") {
        pollRef.current = setTimeout(poll, POLL_INTERVAL_MS);
      }
    };

    poll();

    upgradeRetryRef.current = setInterval(() => {
      if (transportRef.current === "http" && mountedRef.current) {
        connectWsRef.current();
      }
    }, HTTP_UPGRADE_RETRY_INTERVAL_MS);
  }, [stopPolling, cleanupWs, setTransportBoth]);

  const reconnectWs = useCallback(() => {
    if (!mountedRef.current) return;
    const attempt = reconnectAttemptRef.current;

    if (!hasConnected.current && !waitingForUnityRef.current) {
      setPhase("idle");
      setStatusText("Unity not running");
      return;
    }

    if (attempt >= 3 && hasConnected.current) {
      startHttpPolling();
      return;
    }

    if (attempt > 20) {
      waitingForUnityRef.current = false;
      startHttpPolling();
      return;
    }

    const jitter = Math.random() * 1000;
    const delay = attempt < 5 ? 2000 + jitter : Math.min(5000 * Math.pow(1.3, attempt - 5) + jitter, 30000);
    reconnectAttemptRef.current = attempt + 1;
    setStatusText(`Connecting... (${attempt + 1}/20)`);
    reconnectRef.current = setTimeout(() => {
      if (mountedRef.current) connectWsRef.current();
    }, delay);
  }, [startHttpPolling]);

  const connectWs = useCallback(() => {
    if (!mountedRef.current) return;
    cleanupWs();
    if (reconnectRef.current) {
      clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }

    setPhase("starting");
    setStatusText("Connecting to Unity...");
    setTransportBoth("none");

    let wsConnectTimer: ReturnType<typeof setTimeout> | null = null;

    try {
      const ws = new WebSocket(WS_URL);
      ws.binaryType = "blob";
      wsRef.current = ws;

      wsConnectTimer = setTimeout(() => {
        if (wsRef.current === ws && ws.readyState === WebSocket.CONNECTING) {
          try { ws.close(); } catch {}
          wsRef.current = null;
          wsFailureCountRef.current++;
          if (wsFailureCountRef.current >= WS_MAX_CONSECUTIVE_FAILURES) {
            startHttpPolling();
          } else {
            reconnectWs();
          }
        }
      }, WS_CONNECT_TIMEOUT_MS);

      ws.onopen = () => {
        if (wsConnectTimer) { clearTimeout(wsConnectTimer); wsConnectTimer = null; }
        if (!mountedRef.current) { ws.close(); return; }
        if (wsRef.current !== ws) return;
        stopPolling();
        setTransportBoth("ws");
        setPhase("connected");
        setStatusText("Live (WebSocket)");
        reconnectAttemptRef.current = 0;
        waitingForUnityRef.current = false;
        wsFailureCountRef.current = 0;
        if (!hasConnected.current) {
          hasConnected.current = true;
          onStreamConnected?.();
        }
        syncToUnity();
      };

      ws.onmessage = (event) => {
        if (transportRef.current !== "ws") return;
        if (event.data instanceof Blob) {
          event.data.arrayBuffer().then((buf: ArrayBuffer) => {
            if (transportRef.current !== "ws") return;
            if (validateBmp(buf)) {
              const bmpBlob = new Blob([buf], { type: "image/bmp" });
              const url = URL.createObjectURL(bmpBlob);
              displayFrame(url);
              wsFailureCountRef.current = 0;
            } else {
              wsFailureCountRef.current++;
            }
          });
        }
      };

      ws.onclose = () => {
        if (wsConnectTimer) { clearTimeout(wsConnectTimer); wsConnectTimer = null; }
        if (!mountedRef.current) return;
        if (wsRef.current !== ws) return;
        setPhase("disconnected");
        setStatusText("Connection lost");
        wsRef.current = null;
        wsFailureCountRef.current++;
        if (transportRef.current === "ws" && wsFailureCountRef.current >= WS_MAX_CONSECUTIVE_FAILURES) {
          startHttpPolling();
        } else {
          reconnectWs();
        }
      };

      ws.onerror = () => {};
    } catch {
      if (wsConnectTimer) clearTimeout(wsConnectTimer);
      if (!mountedRef.current) return;
      wsFailureCountRef.current++;
      if (wsFailureCountRef.current >= WS_MAX_CONSECUTIVE_FAILURES) {
        startHttpPolling();
      } else {
        reconnectWs();
      }
    }
  }, [onStreamConnected, cleanupWs, reconnectWs, stopPolling, startHttpPolling, setTransportBoth]);

  useEffect(() => {
    connectWsRef.current = connectWs;
  }, [connectWs]);

  const checkAndConnect = useCallback(async () => {
    try {
      const statusRes = await fetch(GATEWAY + "/unity/status");
      if (!statusRes.ok) throw new Error("Gateway unreachable");
      const status = await statusRes.json();

      if (!status.unity_path) {
        setPhase("not_installed");
        setStatusText("Unity Editor not found");
        return;
      }

      if (status.frame_server_ready) {
        connectWs();
      } else if (status.process_running || status.tcp_ready) {
        waitingForUnityRef.current = true;
        reconnectAttemptRef.current = 0;
        setPhase("starting");
        setStatusText("Waiting for Unity...");
        reconnectWs();
      } else {
        setPhase("idle");
        setStatusText("Unity not running");
      }
    } catch {
      setPhase("error");
      setStatusText("Gateway unreachable");
    }
  }, [connectWs, reconnectWs]);

  useEffect(() => {
    mountedRef.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- connection init is side-effect
    checkAndConnect();
    return () => {
      mountedRef.current = false;
      cleanupWs();
      stopPolling();
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
    };
  }, [checkAndConnect, cleanupWs, stopPolling]);

  const confirmAndLaunch = () => {
    setConfirmOpen(false);
    launchUnity();
  };

  const launchUnity = async () => {
    setPhase("launching");
    setStatusText("Launching Unity Editor...");
    reconnectAttemptRef.current = 0;
    if (reconnectRef.current) {
      clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }
    try {
      const res = await fetch(GATEWAY + "/unity/launch", { method: "POST" });
      const data = await res.json();
      if (!res.ok && res.status === 404) {
        setPhase("not_installed");
        setStatusText(data.message || "Unity not found");
        return;
      }
      if (!res.ok) {
        setPhase("error");
        setStatusText(data.message || "Launch failed");
        return;
      }
      waitingForUnityRef.current = true;
      reconnectAttemptRef.current = 0;
      wsFailureCountRef.current = 0;
      setTimeout(() => connectWsRef.current(), 5000);
    } catch (e: unknown) {
      setPhase("error");
      setStatusText((e instanceof Error ? e.message : undefined) || "Failed to launch Unity");
    }
  };

  const reconnectUnity = useCallback(() => {
    reconnectAttemptRef.current = 0;
    wsFailureCountRef.current = 0;
    stopPolling();
    connectWs();
  }, [connectWs, stopPolling]);

  const phaseBadge = () => {
    switch (phase) {
      case "checking":
        return { color: "bg-muted-foreground", pulse: true, label: "..." };
      case "launching":
      case "starting":
        return { color: "bg-amber-500", pulse: true, label: statusText };
      case "connected":
        return { color: "bg-emerald-500", pulse: false, label: statusText };
      default:
        return { color: "bg-red-500", pulse: false, label: "Offline" };
    }
  };

  const badge = phaseBadge();

  return (
    <div className="flex-1 flex flex-col bg-xuanwu-deep relative">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <div className="flex items-center gap-2 text-sm font-medium text-foreground">
          <Monitor className="h-4 w-4 text-primary" />
          Unity 3D View
        </div>
        <div className="flex items-center gap-2">
          <span className={"h-2 w-2 rounded-full " + badge.color + (badge.pulse ? " animate-pulse" : "")} />
          <span className="text-[10px] text-muted-foreground">{badge.label}</span>
          {phase === "connected" && (
            <>
              {transport === "http" && (
                <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20" title="HTTP polling fallback — lower frame rate">
                  HTTP
                </span>
              )}
              <button
                onClick={() => setVideoScale((s) => Math.max(0.5, s - 0.1))}
                className="px-1.5 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground border border-border hover:border-primary/50 cursor-pointer"
              >-</button>
              <span className="text-[10px] text-muted-foreground tabular-nums">{(videoScale * 100).toFixed(0)}%</span>
              <button
                onClick={() => setVideoScale((s) => Math.min(2, s + 0.1))}
                className="px-1.5 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground border border-border hover:border-primary/50 cursor-pointer"
              >+</button>
              <button
                onClick={() => {
                  setIsPlaying((p) => {
                    const next = !p;
                    if (next && lastFrameRef.current) {
                      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
                      blobUrlRef.current = lastFrameRef.current;
                      setImgUrl(lastFrameRef.current);
                    }
                    return next;
                  });
                }}
                className="px-2 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground border border-border hover:border-primary/50 cursor-pointer flex items-center gap-1"
                title={isPlaying ? "Pause stream" : "Resume stream"}
              >
                {isPlaying ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="flex-1 flex items-center justify-center p-2 relative bg-black/40">
        {phase === "connected" && imgUrl ? (
          <img
            ref={imgRef}
            src={imgUrl}
            alt="Unity 3D View"
            className="max-w-full max-h-full rounded-lg"
            style={{ transform: "scale(" + videoScale + ")" }}
          />
        ) : (
          <div className="flex flex-col items-center gap-5 text-center">
            {(phase === "checking" || phase === "launching" || phase === "starting") ? (
              <div className="relative">
                <div className="w-16 h-16 rounded-full border-2 border-primary/30 border-t-primary animate-spin" />
                <Loader2 className="absolute inset-0 m-auto h-6 w-6 text-primary/60 animate-spin" />
              </div>
            ) : (
              <div className="relative">
                <Monitor className="h-16 w-16 text-muted-foreground/30" />
                {(phase === "idle" || phase === "not_installed") && (
                  <Play className="absolute inset-0 m-auto h-6 w-6 text-primary/40 translate-x-[1px]" />
                )}
                {(phase === "disconnected" || phase === "error") && (
                  <WifiOff className="absolute -bottom-1 -right-1 h-5 w-5 text-red-400" />
                )}
              </div>
            )}

            <div>
              <p className="text-sm font-medium text-foreground">
                {phase === "checking" && "Detecting Unity..."}
                {phase === "launching" && "Launching Unity Editor..."}
                {phase === "starting" && "Connecting to Unity..."}
                {phase === "idle" && "Unity not running"}
                {phase === "not_installed" && "Unity Editor not found"}
                {phase === "disconnected" && "Stream disconnected"}
                {phase === "error" && statusText}
              </p>
              <p className="text-xs text-muted-foreground/60 mt-1 max-w-[340px] leading-relaxed">
                {phase === "checking" && "Checking Unity installation and connection status..."}
                {phase === "launching" && "Launching Unity Editor. This may take 30-60 seconds the first time."}
                {phase === "starting" && "Establishing connection to Unity frame server..."}
                {phase === "idle" && "Click the button below to launch Unity and start the live 3D view."}
                {phase === "not_installed" && "Install Unity 2021.3 LTS+ or set the UNITY_PATH environment variable."}
                {phase === "disconnected" && "Connection lost. Trying WebSocket, will fall back to HTTP polling if needed."}
              </p>
            </div>

            <div className="flex gap-2">
              {phase === "idle" && (
                <button
                  onClick={() => setConfirmOpen(true)}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 transition-all cursor-pointer font-medium text-sm"
                >
                  <Play className="h-4 w-4" />
                  Launch Unity
                  <span className="text-[10px] text-muted-foreground font-normal ml-1">1-click</span>
                </button>
              )}
              {phase === "not_installed" && (
                <button
                  onClick={() => window.open("https://unity.com/download", "_blank")}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-muted/50 text-muted-foreground border border-border hover:text-foreground hover:border-primary/50 transition-all cursor-pointer text-xs"
                >
                  Download Unity
                  <ArrowRight className="h-3 w-3" />
                </button>
              )}
              {(phase === "disconnected" || phase === "error") && (
                <button
                  onClick={() => {
                    hasConnected.current = false;
                    wsFailureCountRef.current = 0;
                    reconnectUnity();
                  }}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 transition-all cursor-pointer text-xs"
                >
                  <RotateCw className="h-3.5 w-3.5" />
                  Reconnect
                </button>
              )}
            </div>

            {(phase === "launching" || phase === "starting") && (
              <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground/50 mt-1">
                <span className={phase === "launching" ? "text-primary" : ""}>Launch Editor</span>
                <span>{"→"}</span>
                <span className={phase === "starting" ? "text-primary" : ""}>Connect</span>
                <span>{"→"}</span>
                <span>Live</span>
              </div>
            )}
          </div>
        )}

        {phase === "connected" && (
          <div className="absolute bottom-3 right-3 flex items-center gap-2">
            {!isPlaying && (
              <div className="bg-black/60 rounded-md px-2.5 py-1.5 text-[10px] text-amber-400 border border-amber-500/20 pointer-events-none flex items-center gap-1.5">
                <Pause className="h-3 w-3" />
                Paused
              </div>
            )}
            <div className="bg-black/60 rounded-md px-2.5 py-1.5 text-[10px] text-emerald-400 border border-emerald-500/20 pointer-events-none flex items-center gap-1.5">
              {transport === "ws" ? <Wifi className="h-3 w-3" /> : <Radio className="h-3 w-3" />}
              {transport === "ws" ? "WebSocket" : "HTTP Polling"}
            </div>
          </div>
        )}
      </div>

      {confirmOpen && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="bg-[#0f172a] border border-amber-500/30 rounded-xl p-6 max-w-md mx-4 shadow-2xl">
            <div className="flex items-start gap-3 mb-4">
              <AlertTriangle className="h-6 w-6 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <h3 className="text-sm font-semibold text-foreground">Launch Unity Editor</h3>
                <p className="text-xs text-muted-foreground mt-2 leading-relaxed">
                  This will start the Unity Editor in the background. Please be aware:
                </p>
                <ul className="text-xs text-muted-foreground mt-2 space-y-1.5 list-disc list-inside leading-relaxed">
                  <li>Unity Editor is a heavy application — first launch may take <span className="text-amber-400">30–60 seconds</span></li>
                  <li>It will consume <span className="text-amber-400">2–4 GB of memory</span> while running</li>
                  <li>This feature is <span className="text-amber-400">experimental</span> — occasional instability is expected</li>
                  <li>If the video stream does not appear, switching to another tab and back may help</li>
                </ul>
              </div>
            </div>
            <div className="flex gap-3 justify-end mt-5">
              <button
                onClick={() => setConfirmOpen(false)}
                className="px-4 py-2 rounded-lg text-xs font-medium text-muted-foreground hover:text-foreground border border-border hover:border-primary/30 transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={confirmAndLaunch}
                className="px-5 py-2 rounded-lg text-xs font-medium bg-amber-600/20 text-amber-400 border border-amber-500/30 hover:bg-amber-600/30 transition-colors cursor-pointer flex items-center gap-2"
              >
                <Play className="h-3.5 w-3.5" />
                Yes, Launch Unity
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
