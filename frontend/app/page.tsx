"use client";
/* eslint-disable react-hooks/immutability */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  Send,
  Loader2,
  Wrench,
  Activity,
  Settings,
  Calculator,
  Brain,
  Play,
  CheckCircle,
  AlertCircle,
  Terminal,
  Pause,
  PlayCircle,
  Zap,
  ListOrdered,
  Square,
  Library,
  LayoutGrid,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { fetchTools, fetchScenarios, fetchScenario, type Tool, type ScenarioSummary, API_BASE, WS_BASE } from "@/lib/api";
import { VerificationPanel } from "@/components/verification-panel";
import { MechanicalSummary, type DemolitionRound, type StructuralMetrics } from "@/components/mechanical-summary";
import { FloatingToolbar } from "@/components/floating-toolbar";
import { FrameVisualization } from "@/components/frame-visualization";
import { FrameVisualization3D } from "@/components/frame-visualization-3d";
import { IFCViewer } from "@/components/ifc-viewer";
import { UnityVideoPanel } from "@/components/unity-video-panel";
import { Sidebar, type Conversation } from "@/components/sidebar";
import ServerManager from "@/components/server-manager";
import { ScenarioPicker } from "@/components/scenario-picker";
import { TimelineEditor } from "@/components/timeline-editor";
import { DemolitionController } from "@/components/demolition-controller";
import { AnimationExporter } from "@/components/animation-exporter";
import SettingsPanel from "@/components/settings-panel";
import { playCollapseSound, playRumbleSound, stopAll } from "@/lib/sound-effects";
import { t, type Lang } from "@/lib/i18n";
import { useTheme } from "@/components/theme-provider";
import {
  extractMaxAxialForce,
  extractRoundAnalysisResults,
  extractDemolitionRounds,
  restoreStateFromMessages,
  ANALYSIS_TOOLS,
  type FrameStructure,
  type NodeDisp,
  type ChatMessage,
  type StepEvent,
} from "@/lib/state-restore";
import { getLogIcon, formatLogEntry, stepBrief } from "@/lib/log-format";
import { useConversations } from "@/hooks/use-conversations";
import { useLlmSettings } from "@/hooks/use-llm-settings";
import { useWebSocket, type WebSocketCallbacks } from "@/hooks/use-websocket";

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
  const [streamingText, setStreamingText] = useState("");
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
  const chatEndRef = useRef<HTMLDivElement>(null);
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
    try {
      const saved = localStorage.getItem(CONV_STORAGE);
      const active = localStorage.getItem(CONV_ACTIVE);
      if (saved) {
        const parsed = JSON.parse(saved) as Array<{id: string; title: string; pinned: boolean; createdAt: number; messages: ChatMessage[]}>;
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
    } catch {}
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
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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
    wsRef.current?.close();
    setStatus("idle");
    setStreamingText("");
    setCurrentStep("");
    pendingStepsRef.current = [];
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };

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
      params: { mode, structure: frameStructure, strategy: vdStrategy, effects_preset: vdEffectsPreset, speed: 1,
        structure_params: { num_bays_x: 3, num_stories: 4, span_x_m: 6.0, story_height_m: 3.0, steel_grade: "Q355" } },
    }));
  }, [frameStructure, vdStrategy, vdEffectsPreset, llm.lang]);

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
      try {
        const full = await fetchScenario(scenarioName);
        if (full?.structure_params) structureParams = full.structure_params as Record<string, unknown>;
      } catch { /* use defaults */ }
      const buildingType = structureParams.building_type as string | undefined;
      const pipeline = buildingType === "steam_turbine" ? "steam_turbine_demolition" : "visual_demolition";
      wsRef.current.send(JSON.stringify({
        type: "launch_pipeline", pipeline,
        params: { mode: needsAnalysis ? "mechanics" : "topology", strategy: needsAnalysis ? "llm" : "top_down",
          effects_preset: "standard", speed: 1.0, structure_params: structureParams },
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
    setStreamingText("");
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
        {/* Left Panel: Chat (30%) */}
        <div className="flex w-[30%] min-w-[300px] flex-col border-r border-border">
          <div className="flex items-center justify-center border-b border-border px-4 py-2.5">
            <span className="text-sm font-semibold text-foreground">{t("chat.title", llm.lang)}</span>
          </div>
          <div className="min-h-0 flex-1">
            <ScrollArea className="h-full p-4">
              <div className="space-y-4">
                {messages.length === 0 && (
                  <div className="flex flex-col items-center justify-center h-full min-h-[200px] text-center text-muted-foreground">
                    <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" className="mb-3 opacity-40">
                      <text x="4" y="20" fill="#22d3ee" fontSize="20" fontWeight="bold" fontFamily="sans-serif">玄</text>
                      <text x="22" y="42" fill="#22d3ee" fontSize="20" fontWeight="bold" fontFamily="sans-serif">武</text>
                    </svg>
                    <p className="text-sm font-medium">{t("chat.empty_title", llm.lang)}</p>
                    <p className="text-xs mt-1">{t("chat.empty_subtitle", llm.lang)}</p>
                  </div>
                )}
                {messages.map((msg, i) => (
                  <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm overflow-hidden ${
                      msg.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted text-foreground max-h-[360px] overflow-y-auto"
                    } animate-fade-in-up`}>
                      {msg.role === "ai" ? (
                        <div>
                          <div
                            className="prose prose-sm prose-invert max-w-none [&_strong]:text-primary"
                            dangerouslySetInnerHTML={{
                              __html: msg.content
                                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-primary">$1</strong>')
                                .replace(/`(.*?)`/g, '<code class="text-xs bg-secondary px-1 py-0.5 rounded">$1</code>')
                                .replace(/\n/g, "<br/>"),
                            }}
                          />
                          {msg.steps && msg.steps.length > 0 && (
                            <details className="mt-2">
                              <summary className="text-[10px] text-muted-foreground cursor-pointer hover:text-foreground transition-colors select-none">
                                {msg.steps.filter((s) => s.type === "tool_call").map((s) => stepBrief(s, llm.lang)).join(" → ")}
                                {" · "}
                                {msg.steps.filter((s) => s.type === "tool_result").map((s) => stepBrief(s, llm.lang)).filter(Boolean).join(", ")}
                              </summary>
                              <div className="mt-1.5 space-y-0.5">
                                {msg.steps.map((step, j) => {
                                  const brief = stepBrief(step, llm.lang);
                                  return (
                                    <div key={j} className="text-[10px] font-mono bg-secondary/40 rounded px-2 py-0.5 flex items-center gap-1.5">
                                      <span className={step.type === "tool_call" ? "text-amber-400/80 shrink-0" : "text-emerald-400/80 shrink-0"}>
                                        {step.type === "tool_call" ? "▶" : "✔"}
                                      </span>
                                      <span className="text-muted-foreground">{step.name}</span>
                                      {brief && <span className="text-foreground/60">{brief}</span>}
                                    </div>
                                  );
                                })}
                              </div>
                            </details>
                          )}
                        </div>
                      ) : (msg.content)}
                    </div>
                  </div>
                ))}
                {status === "loading" && (
                  <div className="flex justify-start">
                    <div className="flex flex-col gap-1 rounded-xl bg-muted px-4 py-2.5">
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        {t("chat.thinking", llm.lang)}
                      </div>
                      {currentStep && (
                        <div className="flex items-center gap-1.5 text-[11px] text-primary/80 animate-pulse">
                          <ListOrdered className="h-3 w-3" />{currentStep}
                        </div>
                      )}
                      {streamingText && (
                        <div className="text-[11px] text-muted-foreground/60 max-w-[400px] leading-relaxed">
                          {streamingText.slice(-300)}
                        </div>
                      )}
                    </div>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>
            </ScrollArea>
          </div>

          {messages.length === 0 && (
            <div className="flex flex-wrap gap-1.5 px-4 pb-2">
              {quickActions.map((action) => (
                <button key={action} onClick={() => setInput(action)}
                  className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary cursor-pointer">
                  {action}
                </button>
              ))}
            </div>
          )}

          {frameStructure && !pipelineActive && (
            <div className="px-4 pb-2">
              {pipelineActive ? (
                <div className="w-full rounded-lg border border-primary/30 bg-primary/5 px-4 py-2.5">
                  <div className="flex items-center gap-2 mb-1.5">
                    <Loader2 className="h-3.5 w-3.5 text-primary animate-spin" />
                    <span className="text-sm font-medium text-primary">{t("vd.pipeline_running", llm.lang)}</span>
                  </div>
                  <div className="h-1 bg-muted rounded-full overflow-hidden">
                    <div className="h-full bg-primary rounded-full transition-all duration-500" style={{ width: `${Math.round(pipelineProgress * 100)}%` }} />
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-1">{pipelinePhase}</p>
                </div>
              ) : (
                <div>
                  <div className="flex gap-1.5">
                    <button onClick={launchVisualDemolition} disabled={!frameStructure}
                      className="flex-1 flex items-center justify-center gap-2 rounded-lg border border-primary/40 bg-primary/10 px-4 py-2.5 text-sm font-medium text-primary hover:bg-primary/20 hover:border-primary/60 transition-all cursor-pointer">
                      <Zap className="h-4 w-4" />{t("vd.button", llm.lang)}
                    </button>
                    <button onClick={() => setVdConfigOpen(!vdConfigOpen)}
                      className={`shrink-0 flex items-center justify-center w-9 rounded-lg border transition-all cursor-pointer ${vdConfigOpen ? 'border-primary/50 bg-primary/15 text-primary' : 'border-border text-muted-foreground hover:border-primary/30 hover:text-foreground'}`}
                      title={t("vd.config", llm.lang)}>
                      <Settings className="h-4 w-4" />
                    </button>
                    {demolishReady && (
                      <button onClick={() => setDemolishDialogOpen(true)}
                        className="shrink-0 flex items-center justify-center gap-1 rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2.5 text-xs font-medium text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                        title={t("confirm.title", llm.lang)}>
                        <Zap className="h-3.5 w-3.5" />x1
                      </button>
                    )}
                  </div>
                  {vdConfigOpen && (
                    <div className="mt-2 rounded-lg border border-border bg-muted/30 p-3 space-y-3">
                      <div>
                        <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1.5 block">{t("vd.strategy", llm.lang)}</label>
                        <div className="grid grid-cols-2 gap-1">
                          {DEMOLISH_STRATEGIES.map((s) => {
                            const active = vdStrategy === s.key;
                            return (
                              <button key={s.key} onClick={() => setVdStrategy(s.key)}
                                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium transition-all cursor-pointer border ${active ? "bg-primary/15 border-primary/40 text-primary" : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted"}`}>
                                {active && <span className="h-1.5 w-1.5 rounded-full bg-primary" />}
                                <span>{t(`vd.strategy.${s.key}`, llm.lang)}</span>
                                {s.category === "mechanics" && <span className="text-[9px] text-amber-400/70 ml-auto" title={t("vd.needs_analysis", llm.lang)}>⚡</span>}
                              </button>
                            );
                          })}
                        </div>
                        {DEMOLISH_STRATEGIES.find(s => s.key === vdStrategy)?.category === "mechanics" && (
                          <p className="text-[9px] text-amber-400/70 mt-1">{t("vd.needs_analysis", llm.lang)}</p>
                        )}
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="flex-1">
                          <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1 block">{t("vd.effects", llm.lang)}</label>
                          <div className="flex rounded-md border border-border bg-background overflow-hidden">
                            {(["minimal", "standard", "cinematic"] as const).map((p) => (
                              <button key={p} onClick={() => {
                                setVdEffectsPreset(p);
                                if (p === "minimal") setAnimEffects({ cascade: true, explosion: false, dust: false, shake: false, buckling: false, fracture: false, flash: false, trail: false, bounce: false });
                                else if (p === "standard") setAnimEffects({ cascade: true, explosion: true, dust: true, shake: true, buckling: false, fracture: false, flash: false, trail: false, bounce: false });
                                else setAnimEffects({ cascade: true, explosion: true, dust: true, shake: true, buckling: true, fracture: true, flash: true, trail: true, bounce: true });
                              }}
                              className={`flex-1 px-2 py-1 text-[10px] font-medium transition-colors cursor-pointer ${vdEffectsPreset === p ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-muted"}`}>
                                {t(`vd.effects.${p}`, llm.lang)}
                              </button>
                            ))}
                          </div>
                        </div>
                        <div>
                          <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1 block">{t("vd.speed", llm.lang)}</label>
                          <div className="flex rounded-md border border-border bg-background overflow-hidden">
                            {[0.5, 1, 2].map((s) => (
                              <button key={s} onClick={() => setAnimSpeed(s)}
                                className={`px-2 py-1 text-[10px] font-medium transition-colors cursor-pointer ${animSpeed === s ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-muted"}`}>
                                {s}x
                              </button>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="border-t border-border p-3">
            <div className="flex gap-2">
              <Input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown}
                placeholder={t("chat.placeholder", llm.lang)} className="flex-1" disabled={status === "loading"} />
              {status === "loading" ? (
                <Button onClick={handleStop} size="icon" variant="destructive" className="shrink-0" title={t("chat.stop", llm.lang)}>
                  <Square className="h-4 w-4" />
                </Button>
              ) : (
                <Button onClick={sendMessage} disabled={!input.trim()} size="icon">
                  <Send className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* Center Panel: Visualization (50%) */}
        <div className="flex w-[50%] flex-col border-r border-border bg-[#0a0f1a]">
          <div className="flex items-center justify-between border-b border-border px-4 py-1.5">
            <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
              {t(`viz.mode_${vizMode}`, llm.lang)}
            </span>
            <div className="flex items-center gap-1 bg-secondary/50 rounded-lg p-0.5">
              {(["webgl", "svg", "unity", "ifc"] as const).map((mode) => (
                <button key={mode} onClick={() => setVizMode(mode)}
                  className={`px-3 py-1 text-[11px] font-medium rounded-md transition-colors cursor-pointer ${vizMode === mode ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"}`}>
                  {t(`viz.tab_${mode}`, llm.lang)}
                </button>
              ))}
              <div className="ml-1.5 pl-1.5 border-l border-border/60">
                <AnimationExporter lang={llm.lang} canvasRef={{ current: canvas3dRef }}
                  fileName="demolition-animation" disabled={vizMode !== "webgl" || demolitionRounds.length === 0} />
              </div>
            </div>
          </div>

          <div className="relative flex-1 min-h-0 overflow-hidden">
            {vizMode === "svg" && (
              <div className="absolute inset-0 flex flex-col">
                <FrameVisualization structure={frameStructure} displacements={nodeDisplacements}
                  criticalElementId={structuralMetrics?.criticalElementId ?? null}
                  failedElements={displayFailedElements}
                  maxDisplacement={analysisResult?.max_displacement as number | undefined}
                  elementForces={analysisResult?.element_forces as Array<{element_id: number; Nmax: number; Nmin: number; Mmax: number; Mmin: number; Qmax: number; Qmin: number}> | undefined}
                  animationTrigger={animRequest?.key} animatingElements={animRequest?.targets}
                  onAnimationComplete={handleAnimComplete} />
                {analysisResult && (
                  <div className="flex items-center justify-center px-4 pb-2">
                    <VerificationPanel fastResult={selectedAnalysisResult} structure={roundStructure as Record<string, unknown> | null}
                      lang={llm.lang} analysisSolver={analysisSolver ?? undefined} verifyContext={verifyContext}
                      demolitionRounds={demolitionRounds} activeRoundIdx={activeRoundIdx} onRoundClick={handleRoundClick} />
                  </div>
                )}
              </div>
            )}
            <div className={`absolute inset-0 flex flex-col ${vizMode === "webgl" ? "" : "invisible pointer-events-none"}`}>
              <FrameVisualization3D structure={frameStructure} displacements={nodeDisplacements}
                criticalElementId={structuralMetrics?.criticalElementId ?? null}
                failedElements={failedElements} displayFailedElements={displayFailedElements}
                maxDisplacement={analysisResult?.max_displacement as number | undefined}
                elementForces={analysisResult?.element_forces as Array<{element_id: number; Nmax: number; Nmin: number; Mmax: number; Mmin: number; Qmax: number; Qmin: number}> | undefined}
                animationTrigger={animRequest?.key} animatingElements={animRequest?.targets}
                onAnimationComplete={handleAnimComplete} activeEffects={animEffects}
                canvasCallback={setCanvas3dRef} />
            </div>
            <div className={`absolute inset-0 ${vizMode === "unity" ? "" : "invisible pointer-events-none"}`}>
              <UnityVideoPanel onStreamConnected={handleUnityConnected} />
            </div>
            <div className={`absolute inset-0 ${vizMode === "ifc" ? "" : "invisible pointer-events-none"}`}>
              <IFCViewer structure={frameStructure}
                highlightedElements={structuralMetrics?.criticalElementId ? [structuralMetrics.criticalElementId] : []}
                removedElements={displayFailedElements} />
            </div>
          </div>

          {demolitionRounds.length > 0 && (
            <DemolitionController lang={llm.lang} totalSteps={demolitionRounds.length}
              currentStep={animatingRound >= 0 ? animatingRound + 1 : demolitionRounds.length}
              isPlaying={autoPlaying} isAnimating={animatingRound >= 0} speed={animSpeed} effects={animEffects}
              onPlay={handleAutoPlay} onPause={() => { setAutoPlaying(false); autoPlayQueueRef.current = []; stopAll(); }}
              onStep={(dir) => {
                const target = dir === "forward"
                  ? Math.min(demolitionRounds.length - 1, (animatingRound >= 0 ? animatingRound : 0) + 1)
                  : Math.max(0, animatingRound - 1);
                if (target >= 0 && target < demolitionRounds.length) {
                  setAutoPlaying(false); handleRoundAnimate(target);
                }
              }}
              onReset={() => { setAnimatingRound(-1); setAutoPlaying(false); setAnimRequest(null); setActiveRoundIdx(-1); stopAll(); }}
              onSpeedChange={setAnimSpeed} onEffectToggle={(key) => setAnimEffects(prev => ({ ...prev, [key]: !prev[key] }))}
              stepLabels={demolitionRounds.map(r => `Round ${r.round + 1}: ${r.elementIds.length} elements`)} />
          )}

          {/* Log Stream */}
          <div className="border-t border-border bg-[#060a12]">
            <div className="flex items-center justify-between px-4 py-2 border-b border-border">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                <Terminal className="h-3.5 w-3.5" />{t("log.header", llm.lang)}
                {logEntries.length > 0 && <Badge variant="outline" className="text-[10px]">{logEntries.length}</Badge>}
              </div>
              <button onClick={() => setLogPaused(!logPaused)}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer flex items-center gap-1">
                {logPaused ? (<><PlayCircle className="h-3 w-3" /> Resume</>) : (<><Pause className="h-3 w-3" /> Pause</>)}
              </button>
            </div>
            <ScrollArea className="h-32">
              <div className="p-3 font-mono text-[11px] leading-relaxed">
                {logEntries.length === 0 ? (
                  <span className="text-muted-foreground">{t("log.waiting", llm.lang)}</span>
                ) : (
                  logEntries.map((entry, i) => {
                    const formatted = formatLogEntry(entry);
                    return (
                      <div key={i} className="flex items-start gap-1.5 text-muted-foreground hover:text-foreground transition-colors py-0.5">
                        <span className="mt-0.5 shrink-0">{getLogIcon(entry.type)}</span>
                        <span className="text-[10px] font-semibold text-foreground/70 shrink-0">{formatted.label}</span>
                        {formatted.detail && <span className="text-[10px] text-muted-foreground/60 break-all">— {formatted.detail}</span>}
                      </div>
                    );
                  })
                )}
                <div ref={logEndRef} />
              </div>
            </ScrollArea>
          </div>
        </div>

        {/* Right Panel: Tools & Status (20%) */}
        <div className="flex w-[20%] min-w-[240px] flex-col bg-[#0a0f1a]">
          <div className="border-b border-border px-4 py-3">
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
              <Activity className="h-3.5 w-3.5" />{t("status.header", llm.lang)}
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className={`h-2 w-2 rounded-full ${status === "idle" ? "bg-emerald-500" : "bg-amber-500 animate-pulse"}`} />
                <span className="text-sm capitalize">{t(status === "idle" ? "status.idle" : "status.loading", llm.lang)}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className={`h-2 w-2 rounded-full ${
                  wsConnected === "connected" ? "bg-emerald-500" : wsConnected === "reconnecting" ? "bg-amber-500 animate-pulse" : "bg-red-500"}`} />
                <span className="text-xs text-muted-foreground">
                  {wsConnected === "connected" ? t("status.ws_connected", llm.lang) :
                   wsConnected === "reconnecting" ? t("status.reconnecting", llm.lang) : t("status.ws_disconnected", llm.lang)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Brain className="h-3.5 w-3.5 text-primary/60" />
                <span className="text-xs text-muted-foreground">LLM: {llm.llmModel}</span>
              </div>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-4">
            <MechanicalSummary metrics={structuralMetrics} demolitionRounds={demolitionRounds}
              activeRoundIdx={activeRoundIdx} onRoundClick={handleRoundClick} onRoundAnimate={handleRoundAnimate}
              onAutoPlay={handleAutoPlay} autoPlaying={autoPlaying} animatingRound={animatingRound} />

            {demolitionMode && timelineSteps.length > 0 && (
              <div className="mt-4">
                <TimelineEditor lang={llm.lang} steps={timelineSteps} onReorder={setTimelineSteps}
                  onStepClick={() => {}} selectedStep={-1} isPlaying={autoPlaying}
                  onPlayPause={() => demolitionRounds.length > 0 && (autoPlaying ? setAutoPlaying(false) : handleAutoPlay())}
                  onStepForward={() => {}} onStepBackward={() => {}} onSkipElement={() => {}} />
              </div>
            )}
            {demolitionMode && timelineSteps.length === 0 && (
              <div className="mt-4 rounded-lg border border-border bg-muted/20 p-4 text-center">
                <p className="text-xs text-muted-foreground">
                  {t("dc.empty_timeline", llm.lang)}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      <SettingsPanel
        lang={llm.lang} open={llm.settingsOpen} onClose={() => llm.setSettingsOpen(false)}
        tab={llm.settingsTab} onTabChange={llm.setSettingsTab}
        llmApiKey={llm.llmApiKey} setLlmApiKey={llm.setLlmApiKey}
        llmBaseUrl={llm.llmBaseUrl} setLlmBaseUrl={llm.setLlmBaseUrl}
        llmModel={llm.llmModel} onModelChange={llm.handleModelChange}
        llmStatus={llm.llmStatus} llmTestStatus={llm.llmTestStatus} llmTestMsg={llm.llmTestMsg}
        onSaveLlm={llm.saveLlmSettings} onTestLlm={llm.testLlmConnection}
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
    </div>
  );
}
