"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Radio, Wifi, WifiOff, Monitor, Play, Loader2, ArrowRight } from "lucide-react";

const GATEWAY = "http://localhost:8000";
const STUN_SERVERS = { iceServers: [{ urls: "stun:stun.l.google.com:19302" }] };

type Phase =
  | "checking"
  | "not_installed"
  | "idle"
  | "launching"
  | "starting"
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

interface Props {
  onStreamConnected?: () => void;
}

export function UnityVideoPanel({ onStreamConnected }: Props) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [statusText, setStatusText] = useState("Detecting Unity...");
  const [videoScale, setVideoScale] = useState(1);
  const [hasUnity, setHasUnity] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hasConnected = useRef(false);

  const clearPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const closePeer = () => {
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }
  };

  const establishWebRTC = useCallback(async () => {
    closePeer();
    clearPoll();
    setPhase("connecting");
    setStatusText("Establishing WebRTC...");

    try {
      const offerRes = await fetch(`${GATEWAY}/webrtc/offer`);
      if (!offerRes.ok) throw new Error("No SDP offer");

      const { sdp: offerBase64 } = await offerRes.json();
      if (!offerBase64) throw new Error("Empty offer");

      const offerSdp = atob(offerBase64);
      const pc = new RTCPeerConnection(STUN_SERVERS);
      pcRef.current = pc;

      pc.ontrack = (event) => {
        if (videoRef.current && event.streams[0]) {
          videoRef.current.srcObject = event.streams[0];
          setPhase("connected");
          setStatusText("Live");
          if (!hasConnected.current) {
            hasConnected.current = true;
            onStreamConnected?.();
          }
        }
      };

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === "disconnected" || pc.connectionState === "failed") {
          setPhase("disconnected");
          setStatusText("Stream dropped");
        }
      };

      pc.oniceconnectionstatechange = () => {
        if (pc.iceConnectionState === "disconnected" || pc.iceConnectionState === "failed") {
          setPhase("disconnected");
          setStatusText("Connection lost");
        }
      };

      await pc.setRemoteDescription(
        new RTCSessionDescription({ type: "offer", sdp: offerSdp })
      );
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);

      await fetch(`${GATEWAY}/webrtc/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sdp: btoa(answer.sdp || "") }),
      });
    } catch (e: any) {
      setPhase("error");
      setStatusText(e.message || "WebRTC failed");
    }
  }, [onStreamConnected]);

  const checkAndConnect = useCallback(async () => {
    try {
      const statusRes = await fetch(`${GATEWAY}/unity/status`);
      if (!statusRes.ok) throw new Error("Gateway unreachable");
      const status = await statusRes.json();
      setHasUnity(!!status.unity_path);

      if (!status.unity_path) {
        setPhase("not_installed");
        setStatusText("Unity Editor not found");
        return;
      }

      if (status.webrtc_offer_available) {
        establishWebRTC();
        return;
      }

      if (status.process_running && status.tcp_ready) {
        setPhase("starting");
        setStatusText("Waiting for WebRTC stream...");
        return;
      }

      if (status.process_running) {
        setPhase("starting");
        setStatusText("Unity starting — waiting for TCP...");
        return;
      }

      setPhase("idle");
      setStatusText("Unity not running");
    } catch {
      setPhase("error");
      setStatusText("Gateway unreachable");
    }
  }, [establishWebRTC]);

  // Initial check
  useEffect(() => {
    checkAndConnect();
  }, [checkAndConnect]);

  // Poll while in transitional states
  useEffect(() => {
    if (phase === "launching" || phase === "starting") {
      pollRef.current = setInterval(async () => {
        try {
          const res = await fetch(`${GATEWAY}/unity/status`);
          const status = await res.json();

          if (status.webrtc_offer_available) {
            clearPoll();
            establishWebRTC();
            return;
          }

          if (phase === "launching" && status.process_running) {
            setPhase("starting");
            setStatusText(status.tcp_ready
              ? "TCP ready — waiting for WebRTC..."
              : "Unity loading — waiting for TCP...");
          }

          if (phase === "launching" && !status.process_running) {
            // Still waiting for process to appear
            setStatusText("Launching Unity Editor...");
          }
        } catch {}
      }, 2000);
    }
    return clearPoll;
  }, [phase, establishWebRTC]);

  // If disconnected/error and offer appears, auto-reconnect
  useEffect(() => {
    if (phase === "idle" || phase === "disconnected" || phase === "error") {
      pollRef.current = setInterval(async () => {
        try {
          const res = await fetch(`${GATEWAY}/webrtc/offer`);
          if (res.ok) {
            const { sdp } = await res.json();
            if (sdp) {
              clearPoll();
              establishWebRTC();
            }
          }
        } catch {}
      }, 3000);
    }
    return clearPoll;
  }, [phase, establishWebRTC]);

  // Cleanup
  useEffect(() => {
    return () => {
      clearPoll();
      closePeer();
    };
  }, []);

  const launchUnity = async () => {
    setPhase("launching");
    setStatusText("Launching Unity Editor...");
    try {
      const res = await fetch(`${GATEWAY}/unity/launch`, { method: "POST" });
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
      // Polling will pick up the status change
    } catch (e: any) {
      setPhase("error");
      setStatusText(e.message || "Failed to launch Unity");
    }
  };

  const phaseBadge = () => {
    switch (phase) {
      case "checking":
        return { color: "bg-muted-foreground", pulse: true, label: "..." };
      case "launching":
      case "starting":
      case "connecting":
        return { color: "bg-amber-500", pulse: true, label: statusText };
      case "connected":
        return { color: "bg-emerald-500", pulse: false, label: "Live" };
      default:
        return { color: "bg-red-500", pulse: false, label: "Offline" };
    }
  };

  const badge = phaseBadge();

  return (
    <div className="flex-1 flex flex-col bg-[#0a0f1a] relative">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <div className="flex items-center gap-2 text-sm font-medium text-foreground">
          <Monitor className="h-4 w-4 text-primary" />
          Unity 3D View
        </div>
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${badge.color} ${badge.pulse ? "animate-pulse" : ""}`} />
          <span className="text-[10px] text-muted-foreground">{badge.label}</span>

          {phase === "connected" && (
            <>
              <button
                onClick={() => setVideoScale((s) => Math.max(0.5, s - 0.1))}
                className="px-1.5 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground border border-border hover:border-primary/50 cursor-pointer"
              >-</button>
              <span className="text-[10px] text-muted-foreground tabular-nums">{(videoScale * 100).toFixed(0)}%</span>
              <button
                onClick={() => setVideoScale((s) => Math.min(2, s + 0.1))}
                className="px-1.5 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground border border-border hover:border-primary/50 cursor-pointer"
              >+</button>
            </>
          )}
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 flex items-center justify-center p-2 relative bg-black/40">
        {phase === "connected" ? (
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className="max-w-full max-h-full rounded-lg"
            style={{ transform: `scale(${videoScale})` }}
          />
        ) : (
          <div className="flex flex-col items-center gap-5 text-center">
            {/* Icon */}
            {phase === "checking" || phase === "launching" || phase === "starting" || phase === "connecting" ? (
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

            {/* Status text */}
            <div>
              <p className="text-sm font-medium text-foreground">
                {phase === "checking" && "Detecting Unity..."}
                {phase === "launching" && "Launching Unity Editor..."}
                {phase === "starting" && "Unity is starting up"}
                {phase === "connecting" && "Establishing WebRTC..."}
                {phase === "idle" && "Unity not running"}
                {phase === "not_installed" && "Unity Editor not found"}
                {phase === "disconnected" && "Stream disconnected"}
                {phase === "error" && statusText}
              </p>
              <p className="text-xs text-muted-foreground/60 mt-1 max-w-[340px] leading-relaxed">
                {phase === "checking" && "Checking Unity installation and connection status..."}
                {phase === "launching" && "The Unity Editor window will appear. Scene setup and Play mode are automatic — no manual steps needed."}
                {phase === "starting" && "Scene auto-building, TCP server starting, WebRTC initializing. This takes ~10-20 seconds."}
                {phase === "connecting" && "Negotiating peer-to-peer video connection..."}
                {phase === "idle" && "Click the button below to launch Unity. The editor will auto-configure the scene and start streaming."}
                {phase === "not_installed" && "Install Unity 2021.3 LTS+ or set the UNITY_PATH environment variable."}
                {phase === "disconnected" && "The WebRTC connection was lost. The stream will auto-reconnect when available."}
              </p>
            </div>

            {/* Action buttons */}
            <div className="flex gap-2">
              {phase === "idle" && (
                <button
                  onClick={launchUnity}
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
              {phase === "disconnected" || phase === "error" ? (
                <button
                  onClick={() => {
                    hasConnected.current = false;
                    checkAndConnect();
                  }}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 transition-all cursor-pointer text-xs"
                >
                  <Radio className="h-3.5 w-3.5" />
                  Reconnect
                </button>
              ) : null}
            </div>

            {/* Progress steps for launching */}
            {(phase === "launching" || phase === "starting" || phase === "connecting") && (
              <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground/50 mt-1">
                <span className={phase === "launching" ? "text-primary" : ""}>Launch Editor</span>
                <span>→</span>
                <span className={phase === "starting" ? "text-primary" : ""}>Scene Setup</span>
                <span>→</span>
                <span className={phase === "starting" ? "text-primary" : ""}>Play Mode</span>
                <span>→</span>
                <span className={phase === "connecting" ? "text-primary" : ""}>WebRTC</span>
                <span>→</span>
                <span>Live</span>
              </div>
            )}
          </div>
        )}

        {phase === "connected" && (
          <div className="absolute bottom-3 right-3 bg-black/60 rounded-md px-2.5 py-1.5 text-[10px] text-emerald-400 border border-emerald-500/20 pointer-events-none">
            <Wifi className="inline h-3 w-3 mr-1" />
            Unity Live Stream
          </div>
        )}
      </div>
    </div>
  );
}
