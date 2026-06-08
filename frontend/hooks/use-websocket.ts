"use client";

import { useState, useEffect, useRef, useCallback, type MutableRefObject } from "react";
import { t, type Lang } from "@/lib/i18n";
import { WS_BASE } from "@/lib/api";
import {
  extractMaxAxialForce,
  ANALYSIS_TOOLS,
  type FrameStructure,
  type NodeDisp,
  type ChatMessage,
  type StepEvent,
} from "@/lib/state-restore";
import { type DemolitionRound, type StructuralMetrics } from "@/components/mechanical-summary";

export interface WebSocketCallbacks {
  setStatus: (s: "idle" | "loading") => void;
  setCurrentStep: (s: string) => void;
  setStreamingText: (updater: (prev: string) => string) => void;
  setMessages: (updater: (prev: ChatMessage[]) => ChatMessage[]) => void;
  setLogEntries: (updater: (prev: StepEvent[]) => StepEvent[]) => void;
  setMemorySnippets: (updater: (prev: string[]) => string[]) => void;
  setPipelineActive: (v: boolean) => void;
  setPipelineProgress: (v: number) => void;
  setPipelinePhase: (v: string) => void;
  setDemoStatus: (v: string) => void;
  setFrameStructure: (fs: FrameStructure) => void;
  setDemolitionMode: (v: boolean) => void;
  setDemolishReady: (v: boolean) => void;
  setAnalysisResult: (r: Record<string, unknown>) => void;
  setAnalysisSolver: (s: string) => void;
  setNodeDisplacements: (d: NodeDisp[]) => void;
  setStructuralMetrics: (updater: (prev: StructuralMetrics | null) => StructuralMetrics | null) => void;
  setFailedElements: (updater: (prev: number[]) => number[]) => void;
  setRoundAnalysisResults: (updater: (prev: Record<number, Record<string, unknown>>) => Record<number, Record<string, unknown>>) => void;
  setDemolitionRounds: (r: DemolitionRound[]) => void;
  setTimelineSteps: (steps: Array<{ id: number; elementId: number; elementType: string; phase: string; durationMs: number }>) => void;
  setSteamTurbinePreview: (v: string | null) => void;
  setDemoRunning: (v: boolean) => void;
  setRunningDemoKey: (v: string | null) => void;
  setAnimRequest: (updater: (prev: {key: number; targets: number[]} | null) => {key: number; targets: number[]} | null) => void;
  setAnimPlaying: (v: boolean) => void;
  setAnimatingRound: (v: number) => void;
  demoRef: MutableRefObject<{ running: boolean; phase: string }>;
  pendingStepsRef: MutableRefObject<StepEvent[]>;
  pipelineBuildResultRef: MutableRefObject<Record<string, unknown> | null>;
  demolitionIdxRef: MutableRefObject<number>;
  langRef: MutableRefObject<Lang>;
  compactStep: (step: StepEvent) => StepEvent;
}

type WsData = StepEvent & Record<string, unknown>;

function tryParseJson(v: unknown): Record<string, unknown> | null {
  if (!v) return null;
  if (typeof v === "object") return v as Record<string, unknown>;
  try { return JSON.parse(v as string); }
  catch { return null; }
}

// ── Step label mapping ──────────────────────────────────────────────────────

const STEP_LABELS: Record<string, string> = {
  generate_simple_frame: "step.generating",
  generate_frame: "step.generating",
  analyze_frame: "step.analyzing",
  quick_analysis: "step.generating",
  pynite_analysis: "step.analyzing",
  fapp_analysis: "step.analyzing",
  select_critical_element: "step.critical",
  apply_demolition_action: "step.demolishing",
  high_fidelity_analysis: "step.verifying",
};

// ── Message type handlers ──────────────────────────────────────────────────

type HandlerFn = (data: WsData, cb: WebSocketCallbacks) => void;

function handlePipelineStart(data: WsData, cb: WebSocketCallbacks) {
  cb.setPipelineActive(true);
  cb.setPipelineProgress(0);
  cb.setPipelinePhase(t("vd.pipeline_starting", cb.langRef.current));
  cb.setDemoStatus("Building model in Blender...");
  cb.setMessages((prev) => { const copy = [...prev]; copy.push({ role: "user", content: "Pipeline launched" }); return copy; });
}

function handlePipelineStep(data: WsData, cb: WebSocketCallbacks) {
  cb.setPipelineProgress((data.progress as number) || 0);
  cb.setPipelinePhase((data.phase as string) || "");

  const rawData = data.data as Record<string, unknown> | undefined;
  if (!rawData) return;

  if (data.tool === "generate_frame") {
    const parsed = tryParseJson(rawData.result);
    if (parsed?.nodes && parsed?.elements) {
      cb.setFrameStructure(parsed as unknown as FrameStructure);
      cb.setDemolitionMode(true);
    }
  } else if (data.tool === "build_frame_model") {
    const parsed = tryParseJson(rawData.result);
    if (parsed?.blend_file) {
      cb.pipelineBuildResultRef.current = parsed;
      cb.setSteamTurbinePreview((parsed.preview_image as string) || null);
      cb.setDemoStatus("Steam turbine building generated");
      cb.setLogEntries((prev) => [...prev, { type: "build", content: `Steam turbine model saved: ${parsed.blend_file}` }].slice(-200));
    }
  } else if (data.tool === "plan_demolition_sequence") {
    const parsed = tryParseJson(rawData.result);
    if (parsed?.steps && Array.isArray(parsed.steps)) {
      const elementIds = (parsed.steps as Record<string, unknown>[])
        .filter((s) => (s.element_id as number) > 0)
        .map((s) => s.element_id as number);
      if (elementIds.length > 0) {
        cb.setDemolitionRounds([{ round: 1, elementIds, cumulativeIds: elementIds }]);
      }
    }
  }
}

function handlePipelineComplete(data: WsData, cb: WebSocketCallbacks) {
  cb.setPipelineActive(false);
  cb.setPipelineProgress(1);
  cb.setPipelinePhase("");

  const steps = data.timeline_steps as Array<{ id: number; elementId: number; elementType: string; phase: string; durationMs: number }> | undefined;
  if (steps) {
    cb.setTimelineSteps(steps);
    const validSteps = steps.filter((s) => s.elementId > 0);
    if (validSteps.length > 0) {
      const uniqueIds = [...new Set(validSteps.map((s) => s.elementId))];
      cb.setAnimRequest((prev) => ({ key: (prev?.key ?? 0) + 1, targets: uniqueIds }));
      cb.setAnimPlaying(true);
      cb.setDemolishReady(true);
      const rounds: DemolitionRound[] = [];
      let cum: number[] = [];
      for (let i = 0; i < validSteps.length; i++) {
        cum = [...cum, validSteps[i].elementId];
        rounds.push({ round: i, elementIds: [validSteps[i].elementId], cumulativeIds: [...cum] });
      }
      cb.setDemolitionRounds(rounds);
    }
  }

  cb.setDemoRunning(false);
  cb.setRunningDemoKey(null);
  cb.demoRef.current.running = false;

  const buildResult = cb.pipelineBuildResultRef.current;
  if (buildResult?.blend_file) {
    cb.setMessages((prev) => [...prev, { role: "ai", content: `Steam turbine building generated: ${buildResult.blend_file}` }]);
  } else {
    cb.setMessages((prev) => { const copy = [...prev]; copy.push({ role: "ai", content: "Pipeline complete" }); return copy; });
  }
  cb.pipelineBuildResultRef.current = null;
}

function handlePipelineError(data: WsData, cb: WebSocketCallbacks) {
  cb.setPipelineActive(false);
  cb.setPipelineProgress(0);
  cb.setPipelinePhase("");
  cb.setLogEntries((prev) => [...prev, { type: "error", content: (data.content as string) || "" }].slice(-200));
  cb.setDemoRunning(false);
  cb.setRunningDemoKey(null);
  cb.demoRef.current.running = false;
  cb.pipelineBuildResultRef.current = null;
}

function handleUserEcho(_data: WsData, cb: WebSocketCallbacks) {
  cb.setCurrentStep("");
  cb.setStreamingText(() => "");
  cb.setDemolishReady(false);
}

function handleMemory(data: WsData, cb: WebSocketCallbacks) {
  cb.setMemorySnippets((prev) => [...prev, (data.content as string) || ""].slice(-5));
  cb.setLogEntries((prev) => [...prev, { type: "thinking", content: `Memory: ${data.content}` }].slice(-200));
}

function handleResponse(data: WsData, cb: WebSocketCallbacks) {
  const compacted = cb.pendingStepsRef.current.map(cb.compactStep);
  cb.setMessages((prev) => [...prev, { role: "ai", content: (data.content as string) || "", steps: compacted }]);
  cb.setLogEntries((prev) => [...prev, { type: "response", content: data.content }].slice(-200));
  cb.pendingStepsRef.current = [];
  cb.setStatus("idle");
  cb.setStreamingText(() => "");
}

function handleError(data: WsData, cb: WebSocketCallbacks) {
  cb.setMessages((prev) => [...prev, { role: "ai", content: `Error: ${data.content}` }]);
  cb.setLogEntries((prev) => [...prev, data as StepEvent].slice(-200));
  cb.pendingStepsRef.current = [];
  cb.setStatus("idle");
  cb.setStreamingText(() => "");
}

// ── Tool result sub-handlers ───────────────────────────────────────────────

function handleToolCall(data: WsData, cb: WebSocketCallbacks) {
  if (!data.name) return;
  const key = STEP_LABELS[data.name];
  const label = key ? t(key, cb.langRef.current) : `Running ${data.name}...`;
  cb.setCurrentStep(label);
}

const TOOL_RESULT_HANDLERS: Record<string, (parsed: Record<string, unknown>, cb: WebSocketCallbacks) => void> = {
  generate_simple_frame(p, cb) { if (p.nodes && p.elements) cb.setFrameStructure(p as unknown as FrameStructure); },
  generate_frame(p, cb) { if (p.nodes && p.elements) cb.setFrameStructure(p as unknown as FrameStructure); },
  generate_from_text(p, cb) { if (p.nodes && p.elements) cb.setFrameStructure(p as unknown as FrameStructure); },

  quick_analysis(p, cb) {
    if (p.status !== "complete") return;
    if (p.structure && (p.structure as Record<string, unknown>).nodes && (p.structure as Record<string, unknown>).elements) {
      cb.setFrameStructure(p.structure as unknown as FrameStructure);
    }
    const analysis = p.analysis as Record<string, unknown> | undefined;
    if (analysis && analysis.max_displacement !== undefined && !("error" in analysis)) {
      cb.setAnalysisResult(analysis);
      if (analysis.solver) cb.setAnalysisSolver(analysis.solver as string);
      if (analysis.node_displacements) cb.setNodeDisplacements(analysis.node_displacements as NodeDisp[]);
      cb.setRoundAnalysisResults((prev) => ({ ...prev, [-1]: analysis }));
      const extracted = extractMaxAxialForce(analysis.element_forces as Record<string, unknown>[] | undefined);
      cb.setStructuralMetrics((prev) => ({
        maxDisplacement: (analysis.max_displacement as number) ?? 0,
        maxAxialForce: (analysis.max_axial_force as number) ?? 0,
        criticalElementId: extracted?.elementId ?? prev?.criticalElementId ?? null,
        criticalAxialForce: extracted?.absMaxAxial ?? prev?.criticalAxialForce ?? null,
        columnCount: prev?.columnCount ?? 0,
        failedElements: prev?.failedElements ?? [],
      }));
    }
    const crit = p.critical_element as Record<string, unknown> | undefined;
    if (crit?.critical_element_id != null) {
      cb.setStructuralMetrics((prev) => ({
        maxDisplacement: prev?.maxDisplacement ?? 0,
        maxAxialForce: prev?.maxAxialForce ?? 0,
        criticalElementId: crit.critical_element_id as number,
        criticalAxialForce: (crit.critical_axial_force_N as number) ?? null,
        columnCount: (crit.column_count as number) ?? prev?.columnCount ?? 0,
        failedElements: prev?.failedElements ?? [],
      }));
      cb.setDemolishReady(true);
    }
  },

  select_critical_element(p, cb) {
    cb.setStructuralMetrics((prev) => ({
      maxDisplacement: prev?.maxDisplacement ?? 0,
      maxAxialForce: prev?.maxAxialForce ?? 0,
      criticalElementId: (p.critical_element_id as number) ?? null,
      criticalAxialForce: (p.critical_axial_force_N as number) ?? null,
      columnCount: (p.column_count as number) ?? prev?.columnCount ?? 0,
      failedElements: prev?.failedElements ?? [],
    }));
    cb.setDemolishReady(true);
  },

  apply_demolition_action(p, cb) {
    const feList = p.failed_elements as number[] | undefined;
    if (!feList) return;
    cb.demolitionIdxRef.current++;
    cb.setFailedElements((prev) => { const merged = new Set([...prev, ...feList]); return Array.from(merged); });
    cb.setStructuralMetrics((prev) => {
      const merged = new Set([...(prev?.failedElements || []), ...feList]);
      return prev
        ? { ...prev, failedElements: Array.from(merged) }
        : { maxDisplacement: 0, maxAxialForce: 0, criticalElementId: null, criticalAxialForce: null, columnCount: 0, failedElements: Array.from(merged) };
    });
    cb.setAnimRequest((prev) => ({ key: (prev?.key ?? 0) + 1, targets: feList }));
    cb.setAnimPlaying(true);
    cb.setAnimatingRound(cb.demolitionIdxRef.current);
  },
};

function handleAnalysisResult(p: Record<string, unknown>, toolName: string, cb: WebSocketCallbacks) {
  if (p.max_displacement === undefined || "error" in p) return;
  cb.setAnalysisResult(p);
  if (p.solver) cb.setAnalysisSolver(p.solver as string);
  if (p.node_displacements) cb.setNodeDisplacements(p.node_displacements as NodeDisp[]);
  if (toolName === "analyze_frame") {
    cb.setRoundAnalysisResults((prev) => ({ ...prev, [cb.demolitionIdxRef.current]: p }));
  }
  const extracted = extractMaxAxialForce(p.element_forces as Record<string, unknown>[] | undefined);
  cb.setStructuralMetrics((prev) => ({
    maxDisplacement: (p.max_displacement as number) ?? 0,
    maxAxialForce: (p.max_axial_force as number) ?? 0,
    criticalElementId: extracted?.elementId ?? prev?.criticalElementId ?? null,
    criticalAxialForce: extracted?.absMaxAxial ?? prev?.criticalAxialForce ?? null,
    columnCount: prev?.columnCount ?? 0,
    failedElements: prev?.failedElements ?? [],
  }));
}

function handleToolResult(data: WsData, cb: WebSocketCallbacks) {
  const name = data.name || "";

  if (TOOL_RESULT_HANDLERS[name]) {
    const parsed = tryParseJson(data.result);
    if (parsed) TOOL_RESULT_HANDLERS[name](parsed, cb);
    return;
  }

  if (ANALYSIS_TOOLS.has(name)) {
    const parsed = tryParseJson(data.result);
    if (parsed) handleAnalysisResult(parsed, name, cb);
  }
}

function handleStatus(data: WsData, cb: WebSocketCallbacks) {
  const content = (data.content as string) || "";
  if (content === "paused") {
    cb.setCurrentStep("⏸ Paused — waiting for resume");
  } else if (content === "resumed") {
    cb.setCurrentStep("");
  }
}

// ── Catch-all handler for tool_call / thinking / tool_result ───────────────

function handleCatchAll(data: WsData, cb: WebSocketCallbacks) {
  cb.pendingStepsRef.current = [...cb.pendingStepsRef.current, data as StepEvent];
  cb.setLogEntries((prev) => [...prev, data as StepEvent].slice(-200));

  if (data.type === "tool_call") handleToolCall(data, cb);
  if (data.type === "thinking" && data.content) cb.setStreamingText((prev) => prev + (data.content as string));
  if (data.type === "tool_result" && data.result) handleToolResult(data, cb);
}

// ── Dispatch table ─────────────────────────────────────────────────────────

const MESSAGE_HANDLERS: Record<string, HandlerFn> = {
  pipeline_start: handlePipelineStart,
  pipeline_step: handlePipelineStep,
  pipeline_complete: handlePipelineComplete,
  pipeline_error: handlePipelineError,
  user_echo: handleUserEcho,
  memory: handleMemory,
  response: handleResponse,
  error: handleError,
  status: handleStatus,
};

export function useWebSocket(callbacks: WebSocketCallbacks) {
  const [wsConnected, setWsConnected] = useState<"connected" | "reconnecting" | "disconnected">("disconnected");
  const wsRef = useRef<WebSocket | null>(null);
  const msgQueueRef = useRef<string[]>([]);

  useEffect(() => {
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_DELAY = 30000;
    const MAX_RECONNECT_ATTEMPTS = 15;
    let mounted = true;

    let disconnectStart = 0;

    function flushMessageQueue() {
      const queue = msgQueueRef.current;
      if (queue.length === 0) return;
      msgQueueRef.current = [];
      for (const msg of queue) {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(msg);
        } else {
          msgQueueRef.current.unshift(msg);
          break;
        }
      }
    }

    function connectWithRetry() {
      if (!mounted) return;
      const ws = new WebSocket(`${WS_BASE}/ws/chat`);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsConnected("connected");
        reconnectAttempts = 0;
        disconnectStart = 0;
        flushMessageQueue();
        if (callbacks.pendingStepsRef.current.length > 0) {
          callbacks.setLogEntries((prev) => [...prev, { type: "thinking", content: "Reconnected — resuming session" }].slice(-200));
        }
      };
      ws.onclose = () => {
        if (!mounted) return;
        if (!disconnectStart) disconnectStart = Date.now();
        const disconnectedMs = Date.now() - disconnectStart;
        const jitter = Math.random() * 1000;
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts) + jitter, MAX_RECONNECT_DELAY);
        reconnectAttempts++;
        if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS || disconnectedMs > 60000) {
          setWsConnected("disconnected");
          return;
        }
        reconnectTimer = setTimeout(connectWithRetry, delay);
        setWsConnected("reconnecting");
      };
      ws.onerror = () => {
        if (!mounted) return;
        if (!disconnectStart) disconnectStart = Date.now();
        setWsConnected("reconnecting");
        ws.close();
      };
      let _streamBuf = "";
      let _streamRaf: number | null = null;
      let _streamLastFlush = 0;

      function _flushStream() {
        if (_streamBuf.length > 0) {
          callbacks.setStreamingText((prev) => prev + _streamBuf);
          _streamBuf = "";
        }
        _streamLastFlush = performance.now();
        _streamRaf = null;
      }

      const _throttledCB: WebSocketCallbacks = {
        ...callbacks,
        setStreamingText: ((updater: string | ((prev: string) => string)) => {
          const result = typeof updater === "function" ? updater("") : updater;
          if (result === "" || (typeof result === "string" && result.length === 0)) {
            _streamBuf = "";
            if (_streamRaf !== null) { cancelAnimationFrame(_streamRaf); _streamRaf = null; }
            callbacks.setStreamingText(() => "");
          } else {
            _streamBuf += typeof result === "string" ? result : "";
            if (_streamRaf === null) {
              const elapsed = performance.now() - _streamLastFlush;
              if (elapsed >= 50) _flushStream();
              else _streamRaf = requestAnimationFrame(() => _flushStream());
            }
          }
        }) as unknown as WebSocketCallbacks["setStreamingText"],
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as WsData;
        if (data.type === "ping") return;

        const handler = MESSAGE_HANDLERS[data.type as string];
        if (handler) {
          handler(data, _throttledCB);
        } else {
          handleCatchAll(data, _throttledCB);
        }
      };
    }

    connectWithRetry();
    return () => {
      mounted = false;
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, []);

  const sendMessage = useCallback((content: string, analysisMode?: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "message", content, analysisMode }));
      return true;
    }
    msgQueueRef.current.push(JSON.stringify({ type: "message", content, analysisMode }));
    return true;
  }, []);

  const sendPipeline = useCallback((pipeline: string, params: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "launch_pipeline", pipeline, params }));
      return true;
    }
    return false;
  }, []);

  return { wsConnected, wsRef, sendMessage, sendPipeline };
}
