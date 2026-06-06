"use client";
/* eslint-disable react-hooks/immutability */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  Loader2,
  Zap,
  Library,
  LayoutGrid,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { fetchTools, fetchScenarios, fetchScenario, type Tool, type ScenarioSummary, API_BASE } from "@/lib/api";
import { type DemolitionRound, type StructuralMetrics } from "@/components/mechanical-summary";
import { FloatingToolbar } from "@/components/floating-toolbar";
import { Sidebar } from "@/components/sidebar";
import ServerManager from "@/components/server-manager";
import { ScenarioPicker } from "@/components/scenario-picker";
import SettingsPanel from "@/components/settings-panel";
import { ChatPanel } from "@/components/chat-panel";
import { VisualizationPanel } from "@/components/visualization-panel";
import { StatusPanel } from "@/components/status-panel";
import { ErrorBoundary } from "@/components/error-boundary";
import { playCollapseSound, playRumbleSound, stopAll } from "@/lib/sound-effects";
import { t, type Lang } from "@/lib/i18n";
import { useTheme } from "@/components/theme-provider";
import {
  extractRoundAnalysisResults,
  extractDemolitionRounds,
  restoreStateFromMessages,
  type FrameStructure,
  type NodeDisp,
  type ChatMessage,
  type StepEvent,
} from "@/lib/state-restore";
import { safeGetItem, safeParseJson } from "@/lib/safe-storage";
import { useConversations } from "@/hooks/use-conversations";
import { useLlmSettings } from "@/hooks/use-llm-settings";
import { useWebSocket, type WebSocketCallbacks } from "@/hooks/use-websocket";
import { useErrorToast } from "@/hooks/use-error-toast.tsx";

async function fetchWithTimeout(url: string, options: RequestInit = {}, timeoutMs = 8000): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function genId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

interface DemolishStrategy { key: string; category: "topology" | "mechanics"; }
const DEMOLISH_STRATEGIES: DemolishStrategy[] = [
  { key: "top_down", category: "topology" },
  { key: "bottom_up", category: "topology" },
  { key: "center_out", category: "topology" },
  { key: "alternating_floors", category: "topology" },
  { key: "sequential", category: "topology" },
  { key: "llm", category: "mechanics" },
];

const CONV_STORAGE = "xuanwu_conversations";
const CONV_ACTIVE = "xuanwu_active_conv";

function PanelErrorFallback({ name }: { name: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[200px] p-4 text-center border border-red-500/20 rounded-lg m-2 bg-red-500/5">
      <p className="text-sm font-medium text-red-400 mb-1">{name} panel crashed</p>
      <p className="text-xs text-muted-foreground mb-3">The rest of the app is still functional</p>
      <button
        onClick={() => window.location.reload()}
        className="rounded-lg border border-red-500/30 px-4 py-1.5 text-xs text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
      >
        Reload page
      </button>
    </div>
  );
}

export default function Home() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState<"idle" | "loading">("idle");
  const [logEntries, setLogEntries] = useState<StepEvent[]>([]);
  const [logPaused, setLogPaused] = useState(false);
  const [memorySnippets, setMemorySnippets] = useState<string[]>([]);
  const [analysisResult, setAnalysisResult] = useState<Record<string, unknown> | null>(null);
  const [structuralMetrics, setStructuralMetrics] = useState<StructuralMetrics | null>(null);
  const [failedElements, setFailedElements] = useState<number[]>([]);
  const [currentStep, setCurrentStep] = useState("");
  const [toolsDialogOpen, setToolsDialogOpen] = useState(false);
  const [memoryDialogOpen, setMemoryDialogOpen] = useState(false);
  const streamingFullRef = useRef("");
  const [streamingDisplay, setStreamingDisplay] = useState("");
  const streamingText = streamingDisplay;
  const setStreamingText = useCallback((updater: (prev: string) => string) => {
    const full = updater(streamingFullRef.current);
    streamingFullRef.current = full;
    setStreamingDisplay(full.length > 300 ? full.slice(-300) : full);
  }, []);
  const [demolishDialogOpen, setDemolishDialogOpen] = useState(false);
  const [vdConfigOpen, setVdConfigOpen] = useState(false);
  const [vdStrategy, setVdStrategy] = useState("top_down");
  const [vdEffectsPreset, setVdEffectsPreset] = useState<"minimal" | "standard" | "cinematic">("standard");
  const [animSpeed, setAnimSpeed] = useState(1);
  const [animEffects, setAnimEffects] = useState<Record<string, boolean>>({
    cascade: true, explosion: true, dust: true, shake: true,
    buckling: true, fracture: true, flash: true, trail: true, bounce: true,
  });
  const [canvas3dRef, setCanvas3dRef] = useState<HTMLCanvasElement | null>(null);
  const [pipelineActive, setPipelineActive] = useState(false);
  const [pipelineProgress, setPipelineProgress] = useState(0);
  const [pipelinePhase, setPipelinePhase] = useState("");
  const [timelineSteps, setTimelineSteps] = useState<Array<{ id: number; elementId: number; elementType: string; phase: string; durationMs: number }>>([]);
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [scenariosCount, setScenariosCount] = useState(0);
  const [scenariosLoading, setScenariosLoading] = useState(false);
  const [demolitionMode, setDemolitionMode] = useState(false);
  const [demolishReady, setDemolishReady] = useState(false);
  const [frameStructure, setFrameStructure] = useState<FrameStructure | null>(null);
  const [nodeDisplacements, setNodeDisplacements] = useState<NodeDisp[] | null>(null);
  const [analysisSolver, setAnalysisSolver] = useState<string | null>(null);
  const [vizMode, setVizMode] = useState<"svg" | "webgl" | "unity" | "ifc">("webgl");
  const [demolitionRounds, setDemolitionRounds] = useState<DemolitionRound[]>([]);
  const [activeRoundIdx, setActiveRoundIdx] = useState(-1);
  const [autoPlaying, setAutoPlaying] = useState(false);
  const [animRequest, setAnimRequest] = useState<{key: number; targets: number[]} | null>(null);
  const [animPlaying, setAnimPlaying] = useState(false);
  const [animatingRound, setAnimatingRound] = useState(-1);
  const autoPlayQueueRef = useRef<number[]>([]);
  const [roundAnalysisResults, setRoundAnalysisResults] = useState<Record<number, Record<string, unknown>>>({});
  const { theme, setTheme } = useTheme();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [demoLibraryOpen, setDemoLibraryOpen] = useState(false);
  const [demoRunning, setDemoRunning] = useState(false);
  const [runningDemoKey, setRunningDemoKey] = useState<string | null>(null);
  const [demoStatus, setDemoStatus] = useState("");
  const demoRef = useRef<{ running: boolean; phase: string }>({ running: false, phase: "" });
  const [steamTurbinePreview, setSteamTurbinePreview] = useState<string | null>(null);
  const pipelineBuildResultRef = useRef<Record<string, unknown> | null>(null);

  const logEndRef = useRef<HTMLDivElement>(null);
  const pendingStepsRef = useRef<StepEvent[]>([]);
  const langRef = useRef<Lang>("en");
  const demolitionIdxRef = useRef(-1);
  const scenariosFetchId = useRef(0);

  const handleStopDemo = useCallback(() => {
    demoRef.current.running = false;
    setDemoRunning(false);
    setRunningDemoKey(null);
    setDemoStatus("");
    setPipelineActive(false);
  }, []);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("xuanwu_sidebar_collapsed");
      if (saved === "true") setSidebarCollapsed(true);
    } catch {}
  }, []);

  useEffect(() => {
    localStorage.setItem("xuanwu_sidebar_collapsed", String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  useEffect(() => {
    const id = ++scenariosFetchId.current;
    setScenariosLoading(true);
    fetchScenarios()
      .then((data) => {
        if (id !== scenariosFetchId.current) return;
        setScenarios(data);
        setScenariosCount(data.length);
      })
      .catch(() => {
        if (id !== scenariosFetchId.current) return;
        setScenarios([]);
        setScenariosCount(0);
      })
      .finally(() => {
        if (id === scenariosFetchId.current) setScenariosLoading(false);
      });
  }, [demoLibraryOpen]);

  const conv = useConversations();
  const llm = useLlmSettings();
  const { ToastContainer } = useErrorToast();

  useEffect(() => { langRef.current = llm.lang; }, [llm.lang]);

  function compactStep(step: StepEvent): StepEvent {
    if (step.type === "tool_call") return { type: step.type, name: step.name };
    if (step.type === "tool_result" && step.name && step.result) {
      let parsed: Record<string, unknown>;
      try { parsed = typeof step.result === "string" ? JSON.parse(step.result) : step.result as Record<string, unknown>; }
      catch { return { type: step.type, name: step.name }; }
      const keep: Record<string, unknown> = {};
      if (step.name === "generate_simple_frame" || step.name === "generate_frame" || step.name === "generate_from_text") {
        if (parsed.nodes) keep.nodes = parsed.nodes;
        if (parsed.elements) keep.elements = parsed.elements;
        if (parsed.loads) keep.loads = parsed.loads;
        if (parsed.supports) keep.supports = parsed.supports;
      } else if (step.name === "analyze_frame") {
        if (parsed.max_displacement !== undefined) keep.max_displacement = parsed.max_displacement;
        if (parsed.max_axial_force !== undefined) keep.max_axial_force = parsed.max_axial_force;
        if (parsed.node_displacements) keep.node_displacements = parsed.node_displacements;
        if (parsed.element_forces) keep.element_forces = parsed.element_forces;
        if (parsed.solver) keep.solver = parsed.solver;
      } else if (step.name === "select_critical_element") {
        if (parsed.critical_element_id !== undefined) keep.critical_element_id = parsed.critical_element_id;
        if (parsed.critical_axial_force_N !== undefined) keep.critical_axial_force_N = parsed.critical_axial_force_N;
        if (parsed.column_count !== undefined) keep.column_count = parsed.column_count;
      } else if (step.name === "apply_demolition_action") {
        if (parsed.failed_elements) keep.failed_elements = parsed.failed_elements;
      }
      return { type: step.type, name: step.name, result: keep };
    }
    return step;
  }

  // ---- Load conversations on mount ----
  useEffect(() => {
    const saved = safeGetItem(CONV_STORAGE);
    const active = safeGetItem(CONV_ACTIVE);
    if (saved) {
      const parsed = safeParseJson<Array<{id: string; title: string; pinned: boolean; createdAt: number; messages: ChatMessage[]}>>(saved, []);
      conv.setConversations(parsed.map((c) => ({
        id: c.id, title: c.title, pinned: c.pinned,
        createdAt: c.createdAt, messageCount: c.messages.length,
      })));
      if (active) {
        const activeConv = parsed.find((c) => c.id === active);
        if (activeConv?.messages?.length) {
          conv.setActiveConvId(active);
          setMessages(activeConv.messages);
          const restored = restoreStateFromMessages(activeConv.messages);
          setFrameStructure(restored.frameStructure);
          setAnalysisResult(restored.analysisResult);
          setNodeDisplacements(restored.nodeDisplacements);
          setStructuralMetrics(restored.structuralMetrics);
          setFailedElements(restored.failedElements);
          setDemolishReady(restored.demolishReady);
        }
      } else if (active) {
        conv.setActiveConvId(active);
      }
    }
    conv.setConvLoaded(true);
  }, []);

  // Auto-save conversations
  useEffect(() => {
    if (!conv.convLoaded || !conv.activeConvId || messages.length === 0) return;
    const timer = setTimeout(() => {
      conv.syncMessagesToStorage(conv.activeConvId!, messages);
    }, 500);
    return () => clearTimeout(timer);
  }, [messages.length, conv.activeConvId, conv.convLoaded]);

  // ---- WebSocket ----
  const wsCallbacks: WebSocketCallbacks = {
    setStatus, setCurrentStep,
    setStreamingText: (updater) => setStreamingText(updater),
    setMessages, setLogEntries,
    setMemorySnippets: (updater) => setMemorySnippets(updater),
    setPipelineActive, setPipelineProgress, setPipelinePhase,
    setDemoStatus, setFrameStructure, setDemolitionMode,
    setDemolishReady, setAnalysisResult, setAnalysisSolver,
    setNodeDisplacements,
    setStructuralMetrics: (updater) => setStructuralMetrics(updater),
    setFailedElements: (updater) => setFailedElements(updater),
    setRoundAnalysisResults: (updater) => setRoundAnalysisResults(updater),
    setDemolitionRounds, setTimelineSteps,
    setSteamTurbinePreview, setDemoRunning, setRunningDemoKey,
    setAnimRequest: (updater) => setAnimRequest(updater),
    setAnimPlaying, setAnimatingRound,
    demoRef, pendingStepsRef, pipelineBuildResultRef,
    demolitionIdxRef, langRef, compactStep,
  };
  const { wsConnected, wsRef, sendMessage: wsSend } = useWebSocket(wsCallbacks);

  // ---- Derived state ----
  useEffect(() => {
    fetchTools().then(setTools).catch(() => setTools([]));
  }, []);

  useEffect(() => {
    if (!logPaused && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logEntries, logPaused]);

  useEffect(() => {
    const rounds = extractDemolitionRounds(messages);
    setDemolitionRounds(rounds);
    const results = extractRoundAnalysisResults(messages);
    setRoundAnalysisResults(results);
    if (rounds.length > 0) setActiveRoundIdx(rounds.length - 1);
    else setActiveRoundIdx(-1);
  }, [messages]);

  const displayFailedElements = useMemo(() => {
    if (activeRoundIdx >= 0 && activeRoundIdx < demolitionRounds.length) {
      return demolitionRounds[activeRoundIdx].cumulativeIds;
    }
    if (activeRoundIdx === -1 && demolitionRounds.length > 0) return [];
    return failedElements;
  }, [activeRoundIdx, demolitionRounds, failedElements]);

  const verifyContext = useMemo(() => {
    if (failedElements.length === 0) return "完整结构";
    if (demolitionRounds.length === 0) return "已拆除";
    if (activeRoundIdx === -1) return "完整结构";
    const round = activeRoundIdx >= 0 ? activeRoundIdx + 1 : demolitionRounds.length;
    return `第${round}/${demolitionRounds.length}轮拆除 (已移除${displayFailedElements.length}个构件)`;
  }, [demolitionRounds, activeRoundIdx, displayFailedElements, failedElements]);

  const selectedAnalysisResult = useMemo(() => {
    if (activeRoundIdx === -1 && roundAnalysisResults[-1]) return roundAnalysisResults[-1];
    if (activeRoundIdx >= 0 && roundAnalysisResults[activeRoundIdx]) return roundAnalysisResults[activeRoundIdx];
    return analysisResult;
  }, [activeRoundIdx, roundAnalysisResults, analysisResult]);

  const roundStructure = useMemo(() => {
    if (!frameStructure) return null;
    if (activeRoundIdx < 0 || demolitionRounds.length === 0) return frameStructure;
    const round = demolitionRounds[activeRoundIdx];
    if (!round) return frameStructure;
    const removedIds = new Set(round.cumulativeIds);
    return {
      ...frameStructure,
      elements: frameStructure.elements.filter((el) => !removedIds.has(el.id)),
    } as FrameStructure;
  }, [frameStructure, activeRoundIdx, demolitionRounds]);

  // ---- Handlers ----
  const handleNewConversation = useCallback(() => {
    conv.newConversation();
    setMessages([]);
    setLogEntries([]);
    setAnalysisResult(null);
    setAnalysisSolver(null);
    setStructuralMetrics(null);
    setFailedElements([]);
    setMemorySnippets([]);
    setCurrentStep("");
    setDemolishReady(false);
    setFrameStructure(null);
    setNodeDisplacements(null);
    setAnimRequest(null);
    setAnimPlaying(false);
    setAnimatingRound(-1);
    setAutoPlaying(false);
    autoPlayQueueRef.current = [];
    pendingStepsRef.current = [];
  }, [conv]);

  const handleSelectConversation = useCallback((id: string) => {
    const targetMessages = conv.selectConversation(id, messages);
    setLogEntries([]);
    setMemorySnippets([]);
    setCurrentStep("");
    pendingStepsRef.current = [];
    if (targetMessages?.length) {
      setMessages(targetMessages);
      const restored = restoreStateFromMessages(targetMessages);
      setFrameStructure(restored.frameStructure);
      setAnalysisResult(restored.analysisResult);
      setNodeDisplacements(restored.nodeDisplacements);
      setStructuralMetrics(restored.structuralMetrics);
      setFailedElements(restored.failedElements);
      setDemolishReady(restored.demolishReady);
    } else {
      setMessages([]);
      setFrameStructure(null);
      setAnalysisResult(null);
      setAnalysisSolver(null);
      setNodeDisplacements(null);
      setStructuralMetrics(null);
      setFailedElements([]);
      setDemolishReady(false);
    }
  }, [conv, messages]);

  const sendMessage = useCallback(() => {
    if (!input.trim() || status === "loading") return;
    const userMsg = input.trim();
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setInput("");
    setStatus("loading");
    pendingStepsRef.current = [];
    if (!wsSend(userMsg)) {
      setMessages((prev) => [...prev, { role: "ai", content: "WebSocket not connected. Please try again." }]);
      setStatus("idle");
    }
  }, [input, status, wsSend]);

  const handleStop = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "cancel" }));
    }
    setStatus("idle");
    setStreamingText(() => "");
    setCurrentStep("");
    pendingStepsRef.current = [];
  }, []);

  const triggerDemolition = useCallback(() => {
    if (!structuralMetrics || structuralMetrics.criticalElementId === null) return;
    const msg = `demolish element ${structuralMetrics.criticalElementId}`;
    setMessages((prev) => [...prev, { role: "user", content: msg }]);
    setStatus("loading");
    setDemolishReady(false);
    setDemolishDialogOpen(false);
    pendingStepsRef.current = [];
    wsSend(msg);
  }, [structuralMetrics, wsSend]);

  const launchVisualDemolition = useCallback(() => {
    if (!frameStructure) return;
    const strategy = DEMOLISH_STRATEGIES.find(s => s.key === vdStrategy);
    const needsAnalysis = strategy?.category === "mechanics";
    const mode = needsAnalysis ? "mechanics" : "topology";
    setPipelineActive(true);
    setPipelineProgress(0);
    setPipelinePhase(t("vd.button", llm.lang));
    setVdConfigOpen(false);
    setDemolishReady(false);
    wsRef.current?.send(JSON.stringify({
      type: "launch_pipeline", pipeline: "visual_demolition",
      params: { mode, structure: frameStructure, strategy: vdStrategy, effects_preset: vdEffectsPreset,
        speed: animSpeed, effects: animEffects, structure_params: frameStructure },
    }));
  }, [frameStructure, vdStrategy, vdEffectsPreset, animSpeed, animEffects, llm.lang]);

  const launchScenarioFromDemo = useCallback(async (scenarioName: string, scenario: ScenarioSummary) => {
    setDemoLibraryOpen(false);
    setDemoRunning(true);
    demoRef.current = { running: true, phase: "launching" };
    setRunningDemoKey(scenarioName);
    const isZh = llm.lang === "zh";
    setDemoStatus(scenario.description[isZh ? "zh" : "en"].slice(0, 80) + "...");
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const needsAnalysis = scenario.category === "mechanics";
      let structureParams: Record<string, unknown> = { num_bays_x: 3, num_stories: 4, span_x_m: 6.0, story_height_m: 3.0, steel_grade: "Q355" };
      let fullStrategy = needsAnalysis ? "llm" : "top_down";
      let fullEffects = "standard";
      let fullSpeed = 1.0;
      try {
        const full = await fetchScenario(scenarioName);
        if (full?.structure_params) structureParams = full.structure_params as Record<string, unknown>;
        if (full?.strategy) fullStrategy = full.strategy;
        if (full?.effects_preset) fullEffects = full.effects_preset;
        if (full?.speed) fullSpeed = full.speed;
        if (full?.effects) setAnimEffects(full.effects as Record<string, boolean>);
      } catch { /* use defaults */ }
      if (scenario.viz_mode) setVizMode(scenario.viz_mode as "svg" | "webgl" | "unity" | "ifc");
      const buildingType = structureParams.building_type as string | undefined;
      const pipeline = buildingType === "steam_turbine" ? "steam_turbine_demolition" : "visual_demolition";
      wsRef.current.send(JSON.stringify({
        type: "launch_pipeline", pipeline,
        params: { mode: needsAnalysis ? "mechanics" : "topology", strategy: fullStrategy,
          effects_preset: fullEffects, speed: fullSpeed, structure_params: structureParams },
      }));
      setPipelineActive(true);
      setPipelineProgress(0);
      setPipelinePhase(scenario.title[isZh ? "zh" : "en"]);
    } else {
      setDemoStatus(t("demo.ws_failed", langRef.current));
      setTimeout(() => { setDemoRunning(false); demoRef.current.running = false; }, 3000);
    }
  }, [llm.lang]);

  const handleRoundClick = useCallback((roundIdx: number) => {
    setActiveRoundIdx(roundIdx);
    setAutoPlaying(false);
  }, []);

  const handleRoundAnimate = useCallback((roundIdx: number) => {
    const round = demolitionRounds[roundIdx];
    if (!round) return;
    setActiveRoundIdx(roundIdx);
    setAnimRequest(prev => ({key: (prev?.key ?? 0) + 1, targets: round.elementIds}));
    setAnimPlaying(true);
    setAnimatingRound(roundIdx);
    playCollapseSound("concrete", 0.7 + roundIdx * 0.05);
  }, [demolitionRounds]);

  const handleAnimComplete = useCallback(() => {
    setAnimPlaying(false);
    setAnimatingRound(-1);
    stopAll();
    setAnimRequest(null);
    const queue = autoPlayQueueRef.current;
    if (queue.length > 0) {
      setTimeout(() => {
        const q = autoPlayQueueRef.current;
        if (q.length > 0) {
          const nextRound = q.shift()!;
          handleRoundAnimate(nextRound);
        }
      }, 600);
    } else {
      setAutoPlaying(false);
    }
  }, [handleRoundAnimate]);

  const handleAutoPlay = useCallback(() => {
    if (autoPlaying) {
      setAutoPlaying(false);
      autoPlayQueueRef.current = [];
      setAnimPlaying(false);
      setAnimatingRound(-1);
      setActiveRoundIdx(-1);
      stopAll();
      return;
    }
    if (demolitionRounds.length === 0) return;
    const queue = demolitionRounds.map(r => r.round);
    autoPlayQueueRef.current = queue.slice(1);
    setAutoPlaying(true);
    playRumbleSound(0.4, 3);
    handleRoundAnimate(queue[0]);
  }, [autoPlaying, demolitionRounds, handleRoundAnimate]);

  const runUnityFullFlowDemo = useCallback(async () => {
    setDemoLibraryOpen(false);
    setDemoRunning(true);
    demoRef.current = { running: true, phase: "launching" };
    setDemoStatus(t("demo.launching", langRef.current));
    try {
      const res = await fetch(`${API_BASE}/unity/launch`, { method: "POST" });
      if (!res.ok) {
        setDemoStatus(t("demo.launch_failed", langRef.current));
        setTimeout(() => { setDemoRunning(false); demoRef.current.running = false; }, 3000);
        return;
      }
    } catch {
      setDemoStatus(t("demo.launch_failed", langRef.current));
      setTimeout(() => { setDemoRunning(false); demoRef.current.running = false; }, 3000);
      return;
    }
    setVizMode("unity");
    demoRef.current.phase = "analyzing";
    setDemoStatus(t("demo.sending", langRef.current));
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const msg = t("quick.2x2", langRef.current);
      setMessages((prev) => [...prev, { role: "user", content: msg }]);
      setStatus("loading");
      pendingStepsRef.current = [];
      wsRef.current.send(JSON.stringify({ type: "message", content: msg }));
    } else {
      setDemoStatus(t("demo.ws_failed", langRef.current));
      setTimeout(() => { setDemoRunning(false); demoRef.current.running = false; }, 3000);
    }
  }, []);

  const runFrameGeneratorDemo = useCallback(() => {
    setDemoLibraryOpen(false);
    setDemoRunning(true);
    demoRef.current = { running: true, phase: "analyzing" };
    setDemoStatus(t("demo.sending", langRef.current));
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const msg = "Generate a 3-bay 4-story steel frame using Q355 steel, 6m span, 3m story height. Use the frame generator to create the model, run static analysis with anaStruct, identify the critical column, and then demolish it.";
      setMessages((prev) => [...prev, { role: "user", content: msg }]);
      setStatus("loading");
      pendingStepsRef.current = [];
      wsRef.current.send(JSON.stringify({ type: "message", content: msg }));
    } else {
      setDemoStatus(t("demo.ws_failed", langRef.current));
      setTimeout(() => { setDemoRunning(false); demoRef.current.running = false; }, 3000);
    }
  }, []);

  const run3dFullFlowDemo = useCallback(() => {
    setDemoLibraryOpen(false);
    setDemoRunning(true);
    demoRef.current = { running: true, phase: "analyzing" };
    setDemoStatus(t("demo.sending", langRef.current));
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const msg = "Build a 3D steel frame with a 3x4 column grid (3 spans in X, 4 spans in Y), 4 stories, 6m span in both directions, 3m story height, Q355 steel. Use the frame generator tool to create the model, run static analysis, identify critical columns, and demolish them progressively.";
      setMessages((prev) => [...prev, { role: "user", content: msg }]);
      setStatus("loading");
      pendingStepsRef.current = [];
      wsRef.current.send(JSON.stringify({ type: "message", content: msg }));
    } else {
      setDemoStatus(t("demo.ws_failed", langRef.current));
      setTimeout(() => { setDemoRunning(false); demoRef.current.running = false; }, 3000);
    }
  }, []);

  const runBimDemolitionDemo = useCallback(() => {
    setDemoLibraryOpen(false);
    setDemoRunning(true);
    demoRef.current = { running: true, phase: "launching" };
    setDemoStatus(t("demo.sending", langRef.current));
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: "launch_pipeline", pipeline: "full_bim_demolition",
        params: { mode: "topology", structure_type: "steel", strategy: "top_down", effects_preset: "standard", speed: 1.0 },
      }));
      setPipelineActive(true);
      setPipelineProgress(0);
      setPipelinePhase(t("demo.bim_demolition", langRef.current));
    } else {
      setDemoStatus(t("demo.ws_failed", langRef.current));
      setTimeout(() => { setDemoRunning(false); demoRef.current.running = false; }, 3000);
    }
  }, []);

  useEffect(() => {
    if (!demoRef.current.running) return;
    if (!demolishReady) return;
    if (!structuralMetrics?.criticalElementId) return;
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    demoRef.current.phase = "demolishing";
    setDemoStatus(t("demo.auto_demolish", langRef.current));
    const timer = setTimeout(() => {
      const msg = `demolish element ${structuralMetrics.criticalElementId}`;
      setMessages((prev) => [...prev, { role: "user", content: msg }]);
      setStatus("loading");
      setDemolishReady(false);
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "message", content: msg }));
      }
      setDemoStatus(t("demo.completed", langRef.current));
      setTimeout(() => { demoRef.current.running = false; setDemoRunning(false); setDemoStatus(""); }, 2500);
    }, 1000);
    return () => clearTimeout(timer);
  }, [demolishReady, structuralMetrics]);

  const quickActions = [
    t("quick.2x2", llm.lang), t("quick.3x3", llm.lang),
    t("quick.2x4", llm.lang), t("quick.4x3", llm.lang),
    t("quick.1x2", llm.lang),
  ];

  const sendQuickAction = useCallback((action: string) => {
    if (status === "loading") return;
    setMessages((prev) => [...prev, { role: "user", content: action }]);
    setStatus("loading");
    pendingStepsRef.current = [];
    wsSend(action);
  }, [status, wsSend]);

  const handleUnityConnected = useCallback(() => setVizMode("unity"), []);

  const handleClearChat = useCallback(() => {
    setMessages([]);
    setLogEntries([]);
    setAnalysisResult(null);
    setAnalysisSolver(null);
    setStructuralMetrics(null);
    setFailedElements([]);
    setMemorySnippets([]);
    setCurrentStep("");
    setStreamingText(() => "");
    setDemolishReady(false);
    setFrameStructure(null);
    setNodeDisplacements(null);
    setAnimRequest(null);
    setAnimPlaying(false);
    setAnimatingRound(-1);
    setAutoPlaying(false);
    autoPlayQueueRef.current = [];
    pendingStepsRef.current = [];
  }, []);

  return (
    <div className="flex h-screen w-full overflow-hidden">
      <Sidebar
        lang={llm.lang}
        conversations={conv.conversations}
        activeId={conv.activeConvId}
        collapsed={sidebarCollapsed}
        onNew={handleNewConversation}
        onSelect={handleSelectConversation}
        onDelete={conv.deleteConversation}
        onRename={conv.renameConversation}
        onTogglePin={conv.togglePinConversation}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        onOpenSettings={() => llm.setSettingsOpen(true)}
        onOpenDemoLibrary={() => setDemoLibraryOpen(true)}
        onOpenTools={() => setToolsDialogOpen(true)}
        onOpenMemory={() => setMemoryDialogOpen(true)}
        toolsCount={tools.length}
        scenariosCount={scenariosCount}
      />

      <div className="flex flex-1 overflow-hidden">
        <ErrorBoundary fallback={<PanelErrorFallback name="Chat" />}>
          <ChatPanel
            lang={llm.lang}
            messages={messages}
            status={status}
            input={input}
            setInput={setInput}
            currentStep={currentStep}
            streamingText={streamingText}
            frameStructure={frameStructure}
            pipelineActive={pipelineActive}
            pipelineProgress={pipelineProgress}
            pipelinePhase={pipelinePhase}
            demolishReady={demolishReady}
            structuralMetrics={structuralMetrics ? { criticalElementId: structuralMetrics.criticalElementId, criticalAxialForce: structuralMetrics.criticalAxialForce } : null}
            vdStrategy={vdStrategy}
            setVdStrategy={setVdStrategy}
            vdEffectsPreset={vdEffectsPreset}
            setVdEffectsPreset={setVdEffectsPreset}
            animSpeed={animSpeed}
            setAnimSpeed={setAnimSpeed}
            animEffects={animEffects}
            setAnimEffects={setAnimEffects}
            vdConfigOpen={vdConfigOpen}
            setVdConfigOpen={setVdConfigOpen}
            demolishDialogOpen={demolishDialogOpen}
            setDemolishDialogOpen={setDemolishDialogOpen}
            quickActions={quickActions}
            onSend={sendMessage}
            onStop={handleStop}
            onLaunchVisualDemolition={launchVisualDemolition}
            onTriggerDemolition={triggerDemolition}
            onQuickAction={(action) => setInput(action)}
          />
        </ErrorBoundary>

        <ErrorBoundary fallback={<PanelErrorFallback name="Visualization" />}>
          <VisualizationPanel
          lang={llm.lang}
          vizMode={vizMode}
          setVizMode={setVizMode}
          frameStructure={frameStructure}
          nodeDisplacements={nodeDisplacements}
          analysisResult={analysisResult}
          analysisSolver={analysisSolver}
          structuralMetrics={structuralMetrics ? { criticalElementId: structuralMetrics.criticalElementId } : null}
          failedElements={failedElements}
          displayFailedElements={displayFailedElements}
          roundStructure={roundStructure}
          selectedAnalysisResult={selectedAnalysisResult}
          verifyContext={verifyContext}
          demolitionRounds={demolitionRounds}
          activeRoundIdx={activeRoundIdx}
          animRequest={animRequest}
          animEffects={animEffects}
          animPlaying={animPlaying}
          animatingRound={animatingRound}
          animSpeed={animSpeed}
          autoPlaying={autoPlaying}
          canvas3dRef={canvas3dRef}
          logEntries={logEntries}
          logPaused={logPaused}
          onAnimComplete={handleAnimComplete}
          onRoundClick={handleRoundClick}
          onRoundAnimate={handleRoundAnimate}
          onAutoPlay={handleAutoPlay}
          onStepForward={() => {
            const target = Math.min(demolitionRounds.length - 1, (animatingRound >= 0 ? animatingRound : 0) + 1);
            if (target >= 0 && target < demolitionRounds.length) { setAutoPlaying(false); handleRoundAnimate(target); }
          }}
          onStepBackward={() => {
            const target = Math.max(0, animatingRound - 1);
            if (target >= 0 && target < demolitionRounds.length) { setAutoPlaying(false); handleRoundAnimate(target); }
          }}
          onReset={() => { setAnimatingRound(-1); setAutoPlaying(false); setAnimRequest(null); setActiveRoundIdx(-1); stopAll(); }}
          onSpeedChange={setAnimSpeed}
          onEffectToggle={(key) => setAnimEffects(prev => ({ ...prev, [key]: !prev[key] }))}
          onPause={() => { setAutoPlaying(false); autoPlayQueueRef.current = []; stopAll(); }}
          onLogPauseToggle={() => setLogPaused(!logPaused)}
          onCanvasCallback={setCanvas3dRef}
          onUnityConnected={handleUnityConnected}
        />
        </ErrorBoundary>

        <ErrorBoundary fallback={<PanelErrorFallback name="Status" />}>
          <StatusPanel
          lang={llm.lang}
          status={status}
          wsConnected={wsConnected}
          llmModel={llm.llmModel}
          structuralMetrics={structuralMetrics}
          demolitionRounds={demolitionRounds}
          activeRoundIdx={activeRoundIdx}
          autoPlaying={autoPlaying}
          animatingRound={animatingRound}
          demolitionMode={demolitionMode}
          timelineSteps={timelineSteps}
          onRoundClick={handleRoundClick}
          onRoundAnimate={handleRoundAnimate}
          onAutoPlay={handleAutoPlay}
          onTimelineReorder={setTimelineSteps}
        />
        </ErrorBoundary>
      </div>

      <SettingsPanel
        lang={llm.lang} open={llm.settingsOpen} onClose={() => llm.setSettingsOpen(false)}
        tab={llm.settingsTab} onTabChange={llm.setSettingsTab}
        llmApiKey={llm.llmApiKey} setLlmApiKey={llm.setLlmApiKey}
        llmBaseUrl={llm.llmBaseUrl} setLlmBaseUrl={llm.setLlmBaseUrl}
        llmModel={llm.llmModel} onModelChange={llm.handleModelChange}
        llmStatus={llm.llmStatus} llmTestStatus={llm.llmTestStatus} llmTestMsg={llm.llmTestMsg}
        onSaveLlm={llm.saveLlmSettings} onTestLlm={llm.testLlmConnection}
        thinkingEnabled={llm.thinkingEnabled}
        setThinkingEnabled={llm.setThinkingEnabled}
        theme={theme} setTheme={setTheme} onLangChange={llm.handleLangChange}
        onClearConversations={() => {
          if (confirm(t("settings.clear_conv_confirm", llm.lang))) {
            localStorage.removeItem(CONV_STORAGE);
            localStorage.removeItem(CONV_ACTIVE);
            conv.setConversations([]);
            setMessages([]);
            conv.setActiveConvId(null);
            setFrameStructure(null);
            setAnalysisResult(null);
            setAnalysisSolver(null);
            setFailedElements([]);
            setDemolishReady(false);
          }
        }}
        onClearMemory={async () => {
          try { await fetchWithTimeout(`${API_BASE}/settings/memory/clear`, { method: "POST" }); setMemorySnippets([]); } catch {}
        }}
        onExportBackup={() => {
          const data = localStorage.getItem(CONV_STORAGE) || "[]";
          const blob = new Blob([data], { type: "application/json" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a"); a.href = url; a.download = "xuanwu_conversations_backup.json"; a.click();
          URL.revokeObjectURL(url);
        }}
        memoryOpen={memoryDialogOpen} setMemoryOpen={setMemoryDialogOpen} memorySnippets={memorySnippets}
      />

      {/* Demolition Confirm Dialog */}
      <Dialog open={demolishDialogOpen} onOpenChange={setDemolishDialogOpen}>
        <DialogContent className="border-red-500/30">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-400">
              <Zap className="h-5 w-5" />{t("confirm.title", llm.lang)}
            </DialogTitle>
            <DialogDescription className="text-muted-foreground">
              {t("confirm.desc", llm.lang)}
              {structuralMetrics?.criticalElementId !== null && (
                <span className="block mt-2 text-amber-400">
                  {t("confirm.target", llm.lang)}: Element #{structuralMetrics?.criticalElementId}
                  {structuralMetrics?.criticalAxialForce && (
                    <span> ({(structuralMetrics.criticalAxialForce / 1000).toFixed(1)} kN {t("mech.axial_force", llm.lang)})</span>
                  )}
                </span>
              )}
              <span className="block mt-2 text-muted-foreground/60 text-xs">{t("confirm.hint", llm.lang)}</span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setDemolishDialogOpen(false)}>{t("confirm.cancel", llm.lang)}</Button>
            <Button onClick={triggerDemolition} className="bg-red-600 hover:bg-red-700 text-white">
              <Zap className="h-4 w-4 mr-2" />{t("confirm.demolish", llm.lang)}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Demo Library Dialog */}
      <Dialog open={demoLibraryOpen} onOpenChange={setDemoLibraryOpen}>
        <DialogContent className="border-border max-w-6xl sm:!max-w-6xl h-[600px] flex flex-col overflow-hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Library className="h-5 w-5 text-primary" />{t("demo.title", llm.lang)}
            </DialogTitle>
            <DialogDescription className="text-muted-foreground">{t("demo.title_desc", llm.lang)}</DialogDescription>
          </DialogHeader>
          <div className="flex-1 overflow-y-auto min-h-0 space-y-3 py-2">
            <ScenarioPicker lang={llm.lang} scenarios={scenarios} loading={scenariosLoading} disabled={demoRunning}
              hasWebSocket={wsRef.current?.readyState === WebSocket.OPEN} runningKey={runningDemoKey}
              onLaunch={launchScenarioFromDemo} onStop={handleStopDemo} />

            <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 hover:border-primary/40 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                    <LayoutGrid className="h-4 w-4 text-primary" />{t("demo.frame_generator", llm.lang)}
                  </h3>
                  <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed">{t("demo.frame_generator_desc", llm.lang)}</p>
                  <div className="mt-3 flex items-center gap-3 text-[10px] text-muted-foreground/70">
                    <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-violet-400" />Generate</span>
                    <span>→</span>
                    <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-blue-400" />Analyze</span>
                    <span>→</span>
                    <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-red-400" />Demolish</span>
                  </div>
                </div>
                <Button onClick={runFrameGeneratorDemo} disabled={demoRunning} className="shrink-0" size="sm">
                  {demoRunning ? (<><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />{t("demo.running", llm.lang)}</>)
                    : (<><Zap className="h-3.5 w-3.5 mr-1.5" />{t("demo.run", llm.lang)}</>)}
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 hover:border-primary/40 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                    <LayoutGrid className="h-4 w-4 text-indigo-400" />{t("demo.3d_full_flow", llm.lang)}
                  </h3>
                  <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed">{t("demo.3d_full_flow_desc", llm.lang)}</p>
                  <div className="mt-3 flex items-center gap-3 text-[10px] text-muted-foreground/70">
                    <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-indigo-400" />3D Model</span>
                    <span>→</span>
                    <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-blue-400" />Analyze</span>
                    <span>→</span>
                    <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-amber-400" />ID Critical</span>
                    <span>→</span>
                    <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-red-400" />Demolish</span>
                  </div>
                </div>
                <Button onClick={run3dFullFlowDemo} disabled={demoRunning} className="shrink-0" size="sm">
                  {demoRunning ? (<><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />{t("demo.running", llm.lang)}</>)
                    : (<><Zap className="h-3.5 w-3.5 mr-1.5" />{t("demo.run", llm.lang)}</>)}
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4 hover:border-emerald-500/40 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                    <Library className="h-4 w-4 text-emerald-400" />{t("demo.bim_demolition", llm.lang)}
                  </h3>
                  <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed">{t("demo.bim_demolition_desc", llm.lang)}</p>
                  <div className="mt-3 flex items-center gap-3 text-[10px] text-muted-foreground/70">
                    <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />BIM Model</span>
                    <span>→</span>
                    <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-amber-400" />Plan</span>
                    <span>→</span>
                    <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-violet-400" />Timeline</span>
                  </div>
                </div>
                <Button onClick={runBimDemolitionDemo} disabled={demoRunning} className="shrink-0" size="sm">
                  {demoRunning ? (<><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />{t("demo.running", llm.lang)}</>)
                    : (<><Zap className="h-3.5 w-3.5 mr-1.5" />{t("demo.run", llm.lang)}</>)}
                </Button>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {demoRunning && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 rounded-full border border-primary/30 bg-[#0f172a]/95 backdrop-blur-sm px-5 py-2.5 shadow-xl shadow-black/30 animate-in fade-in slide-in-from-bottom-2">
          <Loader2 className="h-4 w-4 text-primary animate-spin" />
          <span className="text-sm text-foreground font-medium">{demoStatus}</span>
        </div>
      )}

      {steamTurbinePreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setSteamTurbinePreview(null)}>
          <div className="relative max-w-5xl max-h-[85vh] mx-4" onClick={e => e.stopPropagation()}>
            <img src={"data:image/jpeg;base64," + steamTurbinePreview} alt="3D Model" className="w-full h-auto max-h-[80vh] object-contain rounded-2xl shadow-2xl border border-border" />
            <div className="absolute top-3 left-4 px-3 py-1.5 rounded-full bg-black/60 backdrop-blur text-xs text-white/90 font-medium">蒸汽轮机厂房 3D 模型</div>
            <button onClick={() => setSteamTurbinePreview(null)} className="absolute top-3 right-3 w-8 h-8 rounded-full bg-black/50 hover:bg-black/70 text-white flex items-center justify-center text-lg transition-colors cursor-pointer">&#10005;</button>
          </div>
        </div>
      )}

      {toolsDialogOpen && <ServerManager lang={llm.lang} onClose={() => setToolsDialogOpen(false)} />}

      <FloatingToolbar lang={llm.lang} wsConnected={wsConnected} toolsCount={tools.length}
        demolitionMode={demolitionMode} onOpenSettings={() => llm.setSettingsOpen(true)}
        onClearChat={handleClearChat} onToggleDemolitionMode={() => setDemolitionMode(!demolitionMode)}
        quickActions={quickActions} onQuickAction={sendQuickAction} />
      {ToastContainer}
    </div>
  );
}
