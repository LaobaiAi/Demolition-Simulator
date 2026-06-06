"use client";

import { useState, useEffect, useRef, useCallback, type MutableRefObject } from "react";
import { t, type Lang } from "@/lib/i18n";
import { API_BASE, WS_BASE } from "@/lib/api";
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

export function useWebSocket(callbacks: WebSocketCallbacks) {
  const [wsConnected, setWsConnected] = useState<"connected" | "reconnecting" | "disconnected">("disconnected");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_DELAY = 30000;

    function connectWithRetry() {
      const ws = new WebSocket(`${WS_BASE}/ws/chat`);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsConnected("connected");
        reconnectAttempts = 0;
      };
      ws.onclose = () => {
        setWsConnected("reconnecting");
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY);
        reconnectTimer = setTimeout(connectWithRetry, delay);
      };
      ws.onerror = () => {
        setWsConnected("reconnecting");
        ws.close();
      };
      ws.onmessage = (event) => {
        const data: StepEvent = JSON.parse(event.data);
        if (data.type === "ping") return;

        if (data.type === "pipeline_start") {
          callbacks.setPipelineActive(true);
          callbacks.setPipelineProgress(0);
          callbacks.setPipelinePhase(t("vd.pipeline_starting", callbacks.langRef.current));
          callbacks.setDemoStatus("Building model in Blender...");
          callbacks.setMessages((prev) => { const copy = [...prev]; copy.push({ role: "user", content: "Pipeline launched" }); return copy; });
          return;
        }
        if (data.type === "pipeline_step") {
          callbacks.setPipelineProgress(data.progress || 0);
          callbacks.setPipelinePhase(data.phase || "");
          if (data.tool === "generate_frame" && (data as unknown as Record<string, unknown>).data) {
            try {
              const d = (data as unknown as Record<string, unknown>).data as Record<string, unknown>;
              const parsed = JSON.parse(d.result as string);
              if (parsed.nodes && parsed.elements) {
                callbacks.setFrameStructure(parsed as FrameStructure);
                callbacks.setDemolitionMode(true);
              }
            } catch { /* ignore */ }
          }
          if (data.tool === "build_frame_model" && (data as unknown as Record<string, unknown>).data) {
            try {
              const d = (data as unknown as Record<string, unknown>).data as Record<string, unknown>;
              const parsed = JSON.parse(d.result as string);
              if (parsed.blend_file) {
                callbacks.pipelineBuildResultRef.current = parsed;
                callbacks.setSteamTurbinePreview(parsed.preview_image || null);
                callbacks.setDemoStatus("Steam turbine building generated");
                callbacks.setLogEntries((prev) => [...prev, { type: "build", content: `Steam turbine model saved: ${parsed.blend_file}` }].slice(-200));
              }
            } catch { /* ignore */ }
          }
          if (data.tool === "plan_demolition_sequence" && (data as unknown as Record<string, unknown>).data) {
            try {
              const d = (data as unknown as Record<string, unknown>).data as Record<string, unknown>;
              const parsed = JSON.parse(d.result as string);
              if (parsed.steps && Array.isArray(parsed.steps)) {
                const elementIds = parsed.steps
                  .filter((s: Record<string, unknown>) => (s.element_id as number) > 0)
                  .map((s: Record<string, unknown>) => s.element_id as number);
                if (elementIds.length > 0) {
                  callbacks.setDemolitionRounds([{ round: 1, elementIds, cumulativeIds: elementIds }]);
                }
              }
            } catch { /* ignore */ }
          }
          return;
        }
        if (data.type === "pipeline_complete") {
          callbacks.setPipelineActive(false);
          callbacks.setPipelineProgress(1);
          callbacks.setPipelinePhase("");
          if ((data as unknown as Record<string, unknown>).timeline_steps) {
            const steps = (data as unknown as Record<string, unknown>).timeline_steps as Array<{ id: number; elementId: number; elementType: string; phase: string; durationMs: number }>;
            callbacks.setTimelineSteps(steps);
            const validIds = steps.filter((s) => s.elementId > 0).map((s) => s.elementId);
            if (validIds.length > 0) {
              const uniqueIds = [...new Set(validIds)];
              callbacks.setAnimRequest((prev) => ({ key: (prev?.key ?? 0) + 1, targets: uniqueIds }));
              callbacks.setAnimPlaying(true);
            }
          }
          callbacks.setDemoRunning(false);
          callbacks.setRunningDemoKey(null);
          callbacks.demoRef.current.running = false;
          const buildResult = callbacks.pipelineBuildResultRef.current;
          if (buildResult?.blend_file) {
            callbacks.setMessages((prev) => [...prev, { role: "ai", content: `Steam turbine building generated: ${buildResult.blend_file}` }]);
          } else {
            callbacks.setMessages((prev) => { const copy = [...prev]; copy.push({ role: "ai", content: "Pipeline complete" }); return copy; });
          }
          callbacks.pipelineBuildResultRef.current = null;
          return;
        }
        if (data.type === "pipeline_error") {
          callbacks.setPipelineActive(false);
          callbacks.setPipelineProgress(0);
          callbacks.setPipelinePhase("");
          callbacks.setLogEntries((prev) => [...prev, { type: "error", content: (data.content || "") }].slice(-200));
          callbacks.setDemoRunning(false);
          callbacks.setRunningDemoKey(null);
          callbacks.demoRef.current.running = false;
          callbacks.pipelineBuildResultRef.current = null;
          return;
        }

        if (data.type === "user_echo") {
          callbacks.setCurrentStep("");
          callbacks.setStreamingText(() => "");
          callbacks.setDemolishReady(false);
          return;
        }

        if (data.type === "memory") {
          callbacks.setMemorySnippets((prev) => [...prev, data.content || ""].slice(-5));
          callbacks.setLogEntries((prev) => [...prev, { type: "thinking", content: `Memory: ${data.content}` }].slice(-200));
          return;
        }

        if (data.type === "response") {
          const compacted = callbacks.pendingStepsRef.current.map(callbacks.compactStep);
          callbacks.setMessages((prev) => [...prev, { role: "ai", content: data.content || "", steps: compacted }]);
          callbacks.setLogEntries((prev) => [...prev, { type: "response", content: data.content }].slice(-200));
          callbacks.pendingStepsRef.current = [];
          callbacks.setStatus("idle");
          callbacks.setStreamingText(() => "");
        } else if (data.type === "error") {
          callbacks.setMessages((prev) => [...prev, { role: "ai", content: `Error: ${data.content}` }]);
          callbacks.setLogEntries((prev) => [...prev, data].slice(-200));
          callbacks.pendingStepsRef.current = [];
          callbacks.setStatus("idle");
          callbacks.setStreamingText(() => "");
        } else {
          callbacks.pendingStepsRef.current = [...callbacks.pendingStepsRef.current, data];
          callbacks.setLogEntries((prev) => [...prev, data].slice(-200));

          if (data.type === "tool_call" && data.name) {
            const L = callbacks.langRef.current;
            const stepLabels: Record<string, string> = {
              generate_simple_frame: t("step.generating", L), generate_frame: t("step.generating", L),
              analyze_frame: t("step.analyzing", L), quick_analysis: t("step.generating", L),
              pynite_analysis: t("step.analyzing", L), fapp_analysis: t("step.analyzing", L),
              select_critical_element: t("step.critical", L), apply_demolition_action: t("step.demolishing", L),
              high_fidelity_analysis: t("step.verifying", L),
            };
            callbacks.setCurrentStep(stepLabels[data.name] || `Running ${data.name}...`);
          }

          if (data.type === "thinking" && data.content) {
            callbacks.setStreamingText((prev) => prev + data.content);
          }

          if (data.type === "tool_result" && data.result &&
              (data.name === "generate_simple_frame" || data.name === "generate_frame" || data.name === "generate_from_text")) {
            try {
              const parsed = typeof data.result === "string" ? JSON.parse(data.result) : data.result;
              if (parsed.nodes && parsed.elements) callbacks.setFrameStructure(parsed as FrameStructure);
            } catch { /* ignore */ }
          }

          if (data.type === "tool_result" && data.name === "quick_analysis" && data.result) {
            try {
              const parsed = typeof data.result === "string" ? JSON.parse(data.result) : data.result;
              if (parsed.status === "complete") {
                if (parsed.structure?.nodes && parsed.structure?.elements) callbacks.setFrameStructure(parsed.structure as FrameStructure);
                if (parsed.analysis?.max_displacement !== undefined && !("error" in parsed.analysis)) {
                  callbacks.setAnalysisResult(parsed.analysis);
                  if (parsed.analysis.solver) callbacks.setAnalysisSolver(parsed.analysis.solver);
                  if (parsed.analysis.node_displacements) callbacks.setNodeDisplacements(parsed.analysis.node_displacements);
                  callbacks.setRoundAnalysisResults((prev) => ({ ...prev, [-1]: parsed.analysis }));
                  const elemForces = parsed.analysis.element_forces as Record<string, unknown>[] | undefined;
                  const extracted = extractMaxAxialForce(elemForces);
                  callbacks.setStructuralMetrics((prev) => ({
                    maxDisplacement: parsed.analysis.max_displacement ?? 0, maxAxialForce: parsed.analysis.max_axial_force ?? 0,
                    criticalElementId: extracted?.elementId ?? prev?.criticalElementId ?? null,
                    criticalAxialForce: extracted?.absMaxAxial ?? prev?.criticalAxialForce ?? null,
                    columnCount: prev?.columnCount ?? 0, failedElements: prev?.failedElements ?? [],
                  }));
                }
                if (parsed.critical_element?.critical_element_id != null) {
                  callbacks.setStructuralMetrics((prev) => ({
                    maxDisplacement: prev?.maxDisplacement ?? 0, maxAxialForce: prev?.maxAxialForce ?? 0,
                    criticalElementId: parsed.critical_element.critical_element_id,
                    criticalAxialForce: parsed.critical_element.critical_axial_force_N ?? null,
                    columnCount: parsed.critical_element.column_count ?? prev?.columnCount ?? 0,
                    failedElements: prev?.failedElements ?? [],
                  }));
                  callbacks.setDemolishReady(true);
                }
              }
            } catch { /* ignore */ }
          }

          if (data.type === "tool_result" && data.name && ANALYSIS_TOOLS.has(data.name) && data.result) {
            try {
              const parsed = typeof data.result === "string" ? JSON.parse(data.result) : data.result;
              if (parsed.max_displacement !== undefined && !("error" in parsed)) {
                callbacks.setAnalysisResult(parsed);
                if (parsed.solver) callbacks.setAnalysisSolver(parsed.solver);
                if (parsed.node_displacements) callbacks.setNodeDisplacements(parsed.node_displacements);
                if (data.name === "analyze_frame") {
                  callbacks.setRoundAnalysisResults((prev) => ({ ...prev, [callbacks.demolitionIdxRef.current]: parsed }));
                }
                const elemForces = parsed.element_forces as Record<string, unknown>[] | undefined;
                const extracted = extractMaxAxialForce(elemForces);
                callbacks.setStructuralMetrics((prev) => ({
                  maxDisplacement: parsed.max_displacement ?? 0, maxAxialForce: parsed.max_axial_force ?? 0,
                  criticalElementId: extracted?.elementId ?? prev?.criticalElementId ?? null,
                  criticalAxialForce: extracted?.absMaxAxial ?? prev?.criticalAxialForce ?? null,
                  columnCount: prev?.columnCount ?? 0, failedElements: prev?.failedElements ?? [],
                }));
              }
            } catch { /* ignore */ }
          }

          if (data.type === "tool_result" && data.name === "select_critical_element" && data.result) {
            try {
              const parsed = typeof data.result === "string" ? JSON.parse(data.result) : data.result;
              callbacks.setStructuralMetrics((prev) => ({
                maxDisplacement: prev?.maxDisplacement ?? 0, maxAxialForce: prev?.maxAxialForce ?? 0,
                criticalElementId: parsed.critical_element_id ?? null,
                criticalAxialForce: parsed.critical_axial_force_N ?? null,
                columnCount: parsed.column_count ?? prev?.columnCount ?? 0,
                failedElements: prev?.failedElements ?? [],
              }));
              callbacks.setDemolishReady(true);
            } catch { /* ignore */ }
          }

          if (data.type === "tool_result" && data.name === "apply_demolition_action" && data.result) {
            try {
              const parsed = typeof data.result === "string" ? JSON.parse(data.result) : data.result;
              if (parsed.failed_elements) {
                const feList = parsed.failed_elements as number[];
                callbacks.demolitionIdxRef.current++;
                callbacks.setFailedElements((prev) => { const merged = new Set([...prev, ...feList]); return Array.from(merged); });
                callbacks.setStructuralMetrics((prev) => {
                  const merged = new Set([...(prev?.failedElements || []), ...feList]);
                  return prev ? { ...prev, failedElements: Array.from(merged) } : { maxDisplacement: 0, maxAxialForce: 0, criticalElementId: null, criticalAxialForce: null, columnCount: 0, failedElements: Array.from(merged) };
                });
                callbacks.setAnimRequest((prev) => ({key: (prev?.key ?? 0) + 1, targets: feList}));
                callbacks.setAnimPlaying(true);
                callbacks.setAnimatingRound(callbacks.demolitionIdxRef.current);
              }
            } catch { /* ignore */ }
          }
        }
      };
    }

    connectWithRetry();
    return () => {
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, []);

  const sendMessage = useCallback((content: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "message", content }));
      return true;
    }
    return false;
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
