"use client";

import { useState, useEffect, useCallback, useRef } from "react";
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
import { fetchTools, type Tool } from "@/lib/api";
import { VerificationPanel } from "@/components/verification-panel";
import { MechanicalSummary, type StructuralMetrics } from "@/components/mechanical-summary";
import { FloatingToolbar } from "@/components/floating-toolbar";
import { FrameVisualization } from "@/components/frame-visualization";
import { UnityVideoPanel } from "@/components/unity-video-panel";
import { Sidebar, type Conversation } from "@/components/sidebar";
import { t, getSavedLang, saveLang, type Lang } from "@/lib/i18n";
import { useTheme, THEMES } from "@/components/theme-provider";

/** Fetch with AbortController timeout. */
async function fetchWithTimeout(
  url: string,
  options: RequestInit = {},
  timeoutMs = 8000,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

interface FrameNode { id: number; x: number; y: number; }
interface FrameElement { id: number; node_i: number; node_j: number; E?: number; A?: number; I?: number; }
interface FrameLoad { node_id: number; Fx: number; Fy: number; }
interface FrameSupport { node_id: number; type: string; }
interface FrameStructure { nodes: FrameNode[]; elements: FrameElement[]; loads: FrameLoad[]; supports: FrameSupport[]; }
interface NodeDisp { node_id: number; ux: number; uy: number; }

function genId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

// Normalize element forces from any analysis tool. Different tools use different
// field names: anaStruct (Nmax/Nmin), PyNite/FAPP/OpenSees (N).
// Returns { elementId, absMaxAxial } or null.
function extractMaxAxialForce(elemForces: Record<string, unknown>[] | undefined): { elementId: number; absMaxAxial: number } | null {
  if (!elemForces || elemForces.length === 0) return null;
  let maxForce = 0;
  let bestId = 0;
  for (const ef of elemForces) {
    // anaStruct format: Nmax, Nmin
    // PyNite/FAPP/OpenSees format: N
    const Nmax = typeof ef.Nmax === "number" ? ef.Nmax : 0;
    const Nmin = typeof ef.Nmin === "number" ? ef.Nmin : 0;
    const N = typeof ef.N === "number" ? ef.N : 0;
    const absN = Nmax !== 0 || Nmin !== 0
      ? Math.max(Math.abs(Nmax), Math.abs(Nmin))
      : Math.abs(N);
    if (absN > maxForce) {
      maxForce = absN;
      bestId = (ef.element_id as number) || (ef.elem_id as number) || 0;
    }
  }
  if (bestId === 0) return null;
  return { elementId: bestId, absMaxAxial: maxForce };
}

// Rebuild full application state from stored conversation messages
interface RestoredState {
  frameStructure: FrameStructure | null;
  analysisResult: Record<string, unknown> | null;
  nodeDisplacements: NodeDisp[] | null;
  structuralMetrics: StructuralMetrics | null;
  failedElements: number[];
  demolishReady: boolean;
}

function restoreStateFromMessages(msgs: ChatMessage[]): RestoredState {
  let frameStructure: FrameStructure | null = null;
  let analysisResult: Record<string, unknown> | null = null;
  let nodeDisplacements: NodeDisp[] | null = null;
  let critElId: number | null = null;
  let critAxial: number | null = null;
  let colCount = 0;
  let maxDisp = 0;
  let maxAxial = 0;
  const failedSet = new Set<number>();
  let demolishReady = false;

  const ANALYSIS_TOOLS = new Set(["analyze_frame", "pynite_analysis", "fapp_analysis", "high_fidelity_analysis"]);

  for (const msg of msgs) {
    if (msg.role !== "ai" || !msg.steps) continue;
    for (const step of msg.steps) {
      if (step.type !== "tool_result" || !step.name) continue;
      let parsed: any;
      try {
        parsed = typeof step.result === "string" ? JSON.parse(step.result) : step.result;
      } catch { continue; }
      if (!parsed) continue;

      if (step.name === "generate_simple_frame") {
        if (parsed.nodes && parsed.elements) {
          frameStructure = parsed as FrameStructure;
        }
      } else if (ANALYSIS_TOOLS.has(step.name)) {
        if (parsed.max_displacement !== undefined && !("error" in parsed)) {
          analysisResult = parsed;
          if (parsed.node_displacements) {
            nodeDisplacements = parsed.node_displacements as NodeDisp[];
          }
          maxDisp = parsed.max_displacement ?? 0;
          maxAxial = parsed.max_axial_force ?? 0;

          // Auto-detect critical element from any analysis tool
          const elemForces = parsed.element_forces as Record<string, unknown>[] | undefined;
          const extracted = extractMaxAxialForce(elemForces);
          if (extracted) {
            critElId = extracted.elementId;
            critAxial = extracted.absMaxAxial;
            demolishReady = true;
          }
        }
      } else if (step.name === "select_critical_element") {
        if (parsed.critical_element_id !== undefined) {
          critElId = parsed.critical_element_id ?? null;
          critAxial = parsed.critical_axial_force_N ?? null;
          colCount = parsed.column_count ?? colCount;
          demolishReady = true;
        }
      } else if (step.name === "apply_demolition_action") {
        if (parsed.failed_elements) {
          for (const id of (parsed.failed_elements as number[])) failedSet.add(id);
        }
      }
    }
  }

  const allFailed = Array.from(failedSet);
  const structuralMetrics: StructuralMetrics | null = analysisResult ? {
    maxDisplacement: maxDisp,
    maxAxialForce: maxAxial,
    criticalElementId: critElId,
    criticalAxialForce: critAxial,
    columnCount: colCount,
    failedElements: allFailed,
  } : null;

  return {
    frameStructure,
    analysisResult,
    nodeDisplacements,
    structuralMetrics,
    failedElements: allFailed,
    demolishReady,
  };
}

const CONV_STORAGE = "xuanwu_conversations";
const CONV_ACTIVE = "xuanwu_active_conv";

interface StoredConv {
  id: string;
  title: string;
  pinned: boolean;
  createdAt: number;
  messages: ChatMessage[];
}

interface ChatMessage {
  role: "user" | "ai";
  content: string;
  steps?: StepEvent[];
}

interface StepEvent {
  type: string;
  name?: string;
  arguments?: Record<string, unknown>;
  result?: unknown;
  content?: string;
}

function SettingsTabs({
  tabs,
  activeTab,
  onTabChange,
}: {
  tabs: { key: string; label: string }[];
  activeTab: string;
  onTabChange: (key: string) => void;
}) {
  return (
    <div className="flex border-b border-border mb-1">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onTabChange(tab.key)}
          className={`flex-1 px-3 py-2 text-sm font-medium transition-colors cursor-pointer border-b-2 -mb-[1px] ${
            activeTab === tab.key
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          {tab.label}
        </button>
      ))}
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
  const [wsConnected, setWsConnected] = useState(false);
  const [memorySnippets, setMemorySnippets] = useState<string[]>([]);
  const [analysisResult, setAnalysisResult] = useState<Record<string, unknown> | null>(null);
  const [structuralMetrics, setStructuralMetrics] = useState<StructuralMetrics | null>(null);
  const [failedElements, setFailedElements] = useState<number[]>([]);
  const [currentStep, setCurrentStep] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [demolishDialogOpen, setDemolishDialogOpen] = useState(false);
  const [demolishReady, setDemolishReady] = useState(false);
  const [frameStructure, setFrameStructure] = useState<FrameStructure | null>(null);
  const [nodeDisplacements, setNodeDisplacements] = useState<NodeDisp[] | null>(null);
  const [analysisSolver, setAnalysisSolver] = useState<string | null>(null);
  const [vizMode, setVizMode] = useState<"svg" | "unity">("svg");
  const { theme, setTheme } = useTheme();
  const [settingsTab, setSettingsTab] = useState("llm");

  // Conversation management
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarReady, setSidebarReady] = useState(false);

  // Load sidebar collapsed state from localStorage (client-side only)
  useEffect(() => {
    try {
      const saved = localStorage.getItem("xuanwu_sidebar_collapsed");
      if (saved !== null) setSidebarCollapsed(saved === "true");
    } catch {}
    setSidebarReady(true);
  }, []);

  // Persist sidebar collapsed state
  useEffect(() => {
    if (sidebarReady) {
      localStorage.setItem("xuanwu_sidebar_collapsed", String(sidebarCollapsed));
    }
  }, [sidebarCollapsed, sidebarReady]);
  const [convLoaded, setConvLoaded] = useState(false);
  const [demoLibraryOpen, setDemoLibraryOpen] = useState(false);
  const [demoRunning, setDemoRunning] = useState(false);
  const [demoStatus, setDemoStatus] = useState("");
  const demoRef = useRef<{ running: boolean; phase: string }>({ running: false, phase: "" });

  // Load conversations from localStorage on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem(CONV_STORAGE);
      const active = localStorage.getItem(CONV_ACTIVE);
      if (saved) {
        const parsed: StoredConv[] = JSON.parse(saved);
        setConversations(parsed.map((c) => ({
          id: c.id, title: c.title, pinned: c.pinned,
          createdAt: c.createdAt, messageCount: c.messages.length,
        })));
        // Restore full state for the active conversation
        if (active) {
          const activeConv = parsed.find((c) => c.id === active);
          if (activeConv?.messages?.length) {
            setActiveConvId(active);
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
          setActiveConvId(active);
        }
      }
    } catch {}
    setConvLoaded(true);
  }, []);

  // Auto-save conversations
  const saveConvs = useCallback((convs: Conversation[], msgs: ChatMessage[], activeId: string | null) => {
    localStorage.setItem(CONV_ACTIVE, activeId || "");
    try {
      const existing = JSON.parse(localStorage.getItem(CONV_STORAGE) || "[]") as StoredConv[];
      const stored: StoredConv[] = convs.map((c) => {
        const prev = existing.find((e) => e.id === c.id);
        if (c.id === activeId) {
          return { ...c, messages: msgs };
        }
        return { ...c, messages: prev?.messages || [] };
      });
      localStorage.setItem(CONV_STORAGE, JSON.stringify(stored));
    } catch {}
  }, []);

  const newConversation = useCallback(() => {
    const id = genId();
    const now = Date.now();
    const conv: Conversation = { id, title: "New conversation", pinned: false, createdAt: now, messageCount: 0 };
    const updated = [conv, ...conversations];
    setConversations(updated);
    setActiveConvId(id);
    // Reset all state
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
    pendingStepsRef.current = [];
    saveConvs(updated, [], id);
  }, [conversations, saveConvs]);

  const selectConversation = useCallback((id: string) => {
    if (id === activeConvId) return;
    // Save current messages before switching
    const currentStored = JSON.parse(localStorage.getItem(CONV_STORAGE) || "[]") as StoredConv[];
    const updated = currentStored.map((c) => {
      if (c.id === activeConvId) return { ...c, messages };
      return c;
    });
    localStorage.setItem(CONV_STORAGE, JSON.stringify(updated));

    setActiveConvId(id);
    // Load target conversation messages & restore full state
    const target = updated.find((c) => c.id === id);
    setLogEntries([]);
    setMemorySnippets([]);
    setCurrentStep("");
    pendingStepsRef.current = [];
    if (target?.messages?.length) {
      setMessages(target.messages);
      const restored = restoreStateFromMessages(target.messages);
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
  }, [activeConvId, messages, saveConvs]);

  const deleteConversation = useCallback((id: string) => {
    const updated = conversations.filter((c) => c.id !== id);
    setConversations(updated);
    if (id === activeConvId) {
      setMessages([]);
      setActiveConvId(null);
    }
    const stored = (JSON.parse(localStorage.getItem(CONV_STORAGE) || "[]") as StoredConv[]).filter((c) => c.id !== id);
    localStorage.setItem(CONV_STORAGE, JSON.stringify(stored));
    if (id === activeConvId) localStorage.setItem(CONV_ACTIVE, "");
  }, [conversations, activeConvId]);

  const renameConversation = useCallback((id: string, title: string) => {
    setConversations((prev) => prev.map((c) => c.id === id ? { ...c, title } : c));
    const stored = JSON.parse(localStorage.getItem(CONV_STORAGE) || "[]") as StoredConv[];
    localStorage.setItem(CONV_STORAGE, JSON.stringify(stored.map((c) => c.id === id ? { ...c, title } : c)));
  }, []);

  const togglePinConversation = useCallback((id: string) => {
    setConversations((prev) => prev.map((c) => c.id === id ? { ...c, pinned: !c.pinned } : c));
    const stored = JSON.parse(localStorage.getItem(CONV_STORAGE) || "[]") as StoredConv[];
    localStorage.setItem(CONV_STORAGE, JSON.stringify(stored.map((c) => c.id === id ? { ...c, pinned: !c.pinned } : c)));
  }, []);

  // Save conversations when messages change (debounced via ref)
  useEffect(() => {
    if (!convLoaded || !activeConvId || messages.length === 0) return;
    const timer = setTimeout(() => {
      // Save messages to localStorage for this conversation
      const stored: StoredConv[] = JSON.parse(localStorage.getItem(CONV_STORAGE) || "[]");
      const idx = stored.findIndex((c) => c.id === activeConvId);
      if (idx >= 0) {
        stored[idx].messages = messages;
        localStorage.setItem(CONV_STORAGE, JSON.stringify(stored));
      }
      // Update message count in sidebar state (no re-render loop: uses function updater)
      setConversations((prev) => {
        const found = prev.find((c) => c.id === activeConvId);
        if (found && found.messageCount !== messages.length) {
          return prev.map((c) => c.id === activeConvId ? { ...c, messageCount: messages.length } : c);
        }
        return prev; // no change = no re-render
      });
      // Auto-title on first user message
      const firstUser = messages.find((m) => m.role === "user");
      if (firstUser) {
        setConversations((prev) => {
          const found = prev.find((c) => c.id === activeConvId);
          if (found && found.title === "New conversation") {
            const title = firstUser.content.slice(0, 40) + (firstUser.content.length > 40 ? "..." : "");
            // Update localStorage too
            const s = JSON.parse(localStorage.getItem(CONV_STORAGE) || "[]") as StoredConv[];
            const si = s.findIndex((c) => c.id === activeConvId);
            if (si >= 0) s[si].title = title;
            localStorage.setItem(CONV_STORAGE, JSON.stringify(s));
            return prev.map((c) => c.id === activeConvId ? { ...c, title } : c);
          }
          return prev;
        });
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [messages.length, activeConvId, convLoaded]);

  // LLM settings — per-model profiles persisted in localStorage
  const LLM_STORAGE_KEY = "xuanwu_llm_profiles";
  const COMMON_MODELS = ["gpt-4o", "gpt-4o-mini", "deepseek-v4-pro", "deepseek-v4-chat", "claude-sonnet-4-6", "claude-opus-4-7"];

  const [lang, setLang] = useState<Lang>("en");
  const [langReady, setLangReady] = useState(false);

  // Load language on mount
  useEffect(() => {
    setLang(getSavedLang());
    setLangReady(true);
  }, []);

  const handleLangChange = (newLang: Lang) => {
    setLang(newLang);
    saveLang(newLang);
  };

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [llmModel, setLlmModel] = useState("gpt-4o");
  const [llmStatus, setLlmStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  function loadProfiles(): Record<string, { api_key: string; base_url: string }> {
    try {
      const saved = localStorage.getItem(LLM_STORAGE_KEY);
      if (saved) return JSON.parse(saved);
    } catch {}
    return {};
  }

  function saveProfiles(profiles: Record<string, { api_key: string; base_url: string }>) {
    localStorage.setItem(LLM_STORAGE_KEY, JSON.stringify(profiles));
  }

  // Load saved settings on mount
  useEffect(() => {
    const initFromBackend = async () => {
      // Backend is the source of truth — fetch its config first
      try {
        const res = await fetchWithTimeout("http://localhost:8000/settings/llm");
        if (res.ok) {
          const backend = await res.json();
          if (backend.has_api_key && backend.model) {
            setLlmModel(backend.model);
            setLlmApiKey("\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"); // masked placeholder
            setLlmBaseUrl(backend.base_url || "");
            localStorage.setItem("xuanwu_last_model", backend.model);
            return; // backend has valid config, use it
          }
        }
      } catch {}

      // Fallback: load from localStorage
      const profiles = loadProfiles();
      const saved = localStorage.getItem("xuanwu_llm_settings"); // legacy migration
      if (saved && Object.keys(profiles).length === 0) {
        try {
          const parsed = JSON.parse(saved);
          const model = parsed.model || "gpt-4o";
          profiles[model] = { api_key: parsed.api_key || "", base_url: parsed.base_url || "" };
          saveProfiles(profiles);
          localStorage.removeItem("xuanwu_llm_settings");
        } catch {}
      }
      const lastModel = localStorage.getItem("xuanwu_last_model") || "gpt-4o";
      setLlmModel(lastModel);
      const profile = profiles[lastModel];
      if (profile) {
        setLlmApiKey(profile.api_key || "");
        setLlmBaseUrl(profile.base_url || "");
        // Sync localStorage value to backend so it stays consistent
        fetchWithTimeout("http://localhost:8000/settings/llm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: lastModel, api_key: profile.api_key, base_url: profile.base_url }),
        }).catch(() => {});
      }
    };
    initFromBackend();
  }, []);

  const handleModelChange = (newModel: string) => {
    setLlmModel(newModel);
    const profiles = loadProfiles();
    const profile = profiles[newModel];
    if (profile) {
      setLlmApiKey(profile.api_key || "");
      setLlmBaseUrl(profile.base_url || "");
    } else {
      setLlmApiKey("");
      setLlmBaseUrl("");
    }
  };

  const saveLlmSettings = async () => {
    setLlmStatus("saving");
    const config: Record<string, string | undefined> = {
      model: llmModel || undefined,
    };
    if (llmBaseUrl) config.base_url = llmBaseUrl;
    if (llmApiKey && llmApiKey !== "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022") {
      config.api_key = llmApiKey;
    }
    try {
      const res = await fetchWithTimeout("http://localhost:8000/settings/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      if (!res.ok) throw new Error("Failed");
      // Save per-model profile (preserve existing key if masked)
      const profiles = loadProfiles();
      const existingKey = llmApiKey !== "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" ? llmApiKey : (profiles[llmModel]?.api_key || "");
      profiles[llmModel] = { api_key: existingKey, base_url: llmBaseUrl };
      saveProfiles(profiles);
      localStorage.setItem("xuanwu_last_model", llmModel);
      setLlmStatus("saved");
      setTimeout(() => setLlmStatus("idle"), 2000);
    } catch {
      setLlmStatus("error");
      setTimeout(() => setLlmStatus("idle"), 3000);
    }
  };

  const wsRef = useRef<WebSocket | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const pendingStepsRef = useRef<StepEvent[]>([]);
  const langRef = useRef<Lang>("en");
  langRef.current = lang; // keep ref in sync for WebSocket handler closure

  // Fetch tools on mount
  useEffect(() => {
    fetchTools()
      .then(setTools)
      .catch(() => setTools([]));
  }, []);

  // Connect WebSocket
  useEffect(() => {
    function connect() {
      const ws = new WebSocket("ws://localhost:8000/ws/chat");
      wsRef.current = ws;

      ws.onopen = () => setWsConnected(true);
      ws.onclose = () => {
        setWsConnected(false);
        // Reconnect after 2s
        setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();

      ws.onmessage = (event) => {
        const data: StepEvent = JSON.parse(event.data);

        if (data.type === "user_echo") {
          // Reset for new message
          setCurrentStep("");
          setStreamingText("");
          setDemolishReady(false);
          return;
        }

        if (data.type === "memory") {
          setMemorySnippets((prev) => [...prev, data.content || ""].slice(-5));
          setLogEntries((prev) => [
            ...prev,
            { type: "thinking", content: `Memory: ${data.content}` },
          ]);
          return;
        }

        if (data.type === "response") {
          // Final response - commit to messages (compact steps to save storage)
          const compacted = pendingStepsRef.current.map(compactStep);
          setMessages((prev) => [
            ...prev,
            {
              role: "ai",
              content: data.content || "",
              steps: compacted,
            },
          ]);
          // Also add as a log entry
          setLogEntries((prev) => [
            ...prev,
            { type: "response", content: data.content },
          ]);
          pendingStepsRef.current = [];
          setStatus("idle");
          setStreamingText("");
        } else if (data.type === "error") {
          setMessages((prev) => [
            ...prev,
            { role: "ai", content: `Error: ${data.content}` },
          ]);
          setLogEntries((prev) => [...prev, data]);
          pendingStepsRef.current = [];
          setStatus("idle");
          setStreamingText("");
        } else {
          // Tool calls, tool results, thinking steps
          pendingStepsRef.current = [...pendingStepsRef.current, data];
          setLogEntries((prev) => [...prev, data]);

          // Track step progress
          if (data.type === "tool_call" && data.name) {
            const L = langRef.current;
            const stepLabels: Record<string, string> = {
              generate_simple_frame: t("step.generating", L),
              analyze_frame: t("step.analyzing", L),
              pynite_analysis: t("step.analyzing", L),
              fapp_analysis: t("step.analyzing", L),
              select_critical_element: t("step.critical", L),
              apply_demolition_action: t("step.demolishing", L),
              high_fidelity_analysis: t("step.verifying", L),
            };
            setCurrentStep(stepLabels[data.name] || `Running ${data.name}...`);
          }

          // Show streamed thinking/reasoning content in real-time
          if (data.type === "thinking" && data.content) {
            setStreamingText((prev) => prev + data.content);
          }

          // Capture generated frame structure for visualization
          if (
            data.type === "tool_result" &&
            data.name === "generate_simple_frame" &&
            data.result
          ) {
            try {
              const parsed = typeof data.result === "string"
                ? JSON.parse(data.result)
                : data.result;
              if (parsed.nodes && parsed.elements) {
                setFrameStructure(parsed as FrameStructure);
              }
            } catch { /* ignore */ }
          }

          // Capture structural analysis results for verification (all analysis tools)
          const ANALYSIS_TOOLS = new Set(["analyze_frame", "pynite_analysis", "fapp_analysis", "high_fidelity_analysis"]);
          if (
            data.type === "tool_result" &&
            data.name &&
            ANALYSIS_TOOLS.has(data.name) &&
            data.result
          ) {
            try {
              const parsed =
                typeof data.result === "string"
                  ? JSON.parse(data.result)
                  : data.result;
              if (parsed.max_displacement !== undefined && !("error" in parsed)) {
                setAnalysisResult(parsed);
                if (parsed.solver) setAnalysisSolver(parsed.solver);
                if (parsed.node_displacements) {
                  setNodeDisplacements(parsed.node_displacements);
                }

                // Auto-detect critical element from element forces (if available)
                const elemForces = parsed.element_forces as Record<string, unknown>[] | undefined;
                const extracted = extractMaxAxialForce(elemForces);
                const autoCritId = extracted?.elementId ?? null;
                const autoCritAxial = extracted?.absMaxAxial ?? null;
                if (autoCritId !== null) {
                  // Auto-activate demolish button — no need to wait for select_critical_element
                  setDemolishReady(true);
                  setCurrentStep("");
                }

                // Update mechanical summary with analysis values
                setStructuralMetrics((prev) => ({
                  maxDisplacement: parsed.max_displacement ?? 0,
                  maxAxialForce: parsed.max_axial_force ?? 0,
                  criticalElementId: autoCritId ?? prev?.criticalElementId ?? null,
                  criticalAxialForce: autoCritAxial ?? prev?.criticalAxialForce ?? null,
                  columnCount: prev?.columnCount ?? 0,
                  failedElements: prev?.failedElements ?? [],
                }));
              }
            } catch {
              // Not JSON, ignore
            }
          }

          // Capture critical element selection
          if (
            data.type === "tool_result" &&
            data.name === "select_critical_element" &&
            data.result
          ) {
            try {
              const parsed =
                typeof data.result === "string"
                  ? JSON.parse(data.result)
                  : data.result;
              setStructuralMetrics((prev) => ({
                maxDisplacement: prev?.maxDisplacement ?? 0,
                maxAxialForce: prev?.maxAxialForce ?? 0,
                criticalElementId: parsed.critical_element_id ?? null,
                criticalAxialForce: parsed.critical_axial_force_N ?? null,
                columnCount: parsed.column_count ?? prev?.columnCount ?? 0,
                failedElements: prev?.failedElements ?? [],
              }));
              setDemolishReady(true);
              setCurrentStep("");
            } catch {
              // Not JSON, ignore
            }
          }

          // Capture demolition action
          if (
            data.type === "tool_result" &&
            data.name === "apply_demolition_action" &&
            data.result
          ) {
            try {
              const parsed =
                typeof data.result === "string"
                  ? JSON.parse(data.result)
                  : data.result;
              if (parsed.failed_elements) {
                const feList = parsed.failed_elements;
                // Accumulate failed elements for progressive demolition
                setFailedElements((prev) => {
                  const merged = new Set([...prev, ...feList]);
                  return Array.from(merged);
                });
                setStructuralMetrics((prev) => {
                  const merged = new Set([...(prev?.failedElements || []), ...feList]);
                  const allFailed = Array.from(merged);
                  return prev
                    ? { ...prev, failedElements: allFailed }
                    : {
                        maxDisplacement: 0,
                        maxAxialForce: 0,
                        criticalElementId: null,
                        criticalAxialForce: null,
                        columnCount: 0,
                        failedElements: allFailed,
                      };
                });
              }
            } catch {
              // Not JSON, ignore
            }
          }
        }
      };
    }

    connect();
    return () => {
      wsRef.current?.close();
    };
  }, []);

  // Auto-scroll logs
  useEffect(() => {
    if (!logPaused && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logEntries, logPaused]);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = useCallback(() => {
    if (!input.trim() || status === "loading") return;

    const userMsg = input.trim();
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setInput("");
    setStatus("loading");
    pendingStepsRef.current = [];

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "message", content: userMsg }));
    } else {
      setMessages((prev) => [
        ...prev,
        { role: "ai", content: "WebSocket not connected. Please try again." },
      ]);
      setStatus("idle");
    }
  }, [input, status]);

  const handleStop = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
    }
    setStatus("idle");
    setStreamingText("");
    setCurrentStep("");
    pendingStepsRef.current = [];
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const triggerDemolition = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    if (!structuralMetrics || structuralMetrics.criticalElementId === null) return;

    const msg = `demolish element ${structuralMetrics.criticalElementId}`;
    setMessages((prev) => [...prev, { role: "user", content: msg }]);
    setStatus("loading");
    setDemolishReady(false);
    setDemolishDialogOpen(false);
    pendingStepsRef.current = [];

    wsRef.current.send(JSON.stringify({ type: "message", content: msg }));
  }, [structuralMetrics]);

  const runUnityFullFlowDemo = useCallback(async () => {
    setDemoLibraryOpen(false);
    setDemoRunning(true);
    demoRef.current = { running: true, phase: "launching" };
    setDemoStatus(t("demo.launching", langRef.current));

    try {
      const res = await fetch("http://localhost:8000/unity/launch", { method: "POST" });
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
      setTimeout(() => {
        demoRef.current.running = false;
        setDemoRunning(false);
        setDemoStatus("");
      }, 2500);
    }, 1000);

    return () => clearTimeout(timer);
  }, [demolishReady, structuralMetrics]);

  const quickActions = [
    t("quick.2x2", lang),
    t("quick.3x3", lang),
    t("quick.2x4", lang),
    t("quick.4x3", lang),
    t("quick.1x2", lang),
  ];

  const sendQuickAction = useCallback((action: string) => {
    if (status === "loading") return;
    setMessages((prev) => [...prev, { role: "user", content: action }]);
    setStatus("loading");
    pendingStepsRef.current = [];
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "message", content: action }));
    }
  }, [status]);

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
    pendingStepsRef.current = [];
  }, []);

  const getLogIcon = (type: string) => {
    switch (type) {
      case "tool_call":
        return <Play className="h-3 w-3 text-amber-400" />;
      case "tool_result":
        return <CheckCircle className="h-3 w-3 text-emerald-400" />;
      case "response":
        return <Brain className="h-3 w-3 text-primary" />;
      case "error":
        return <AlertCircle className="h-3 w-3 text-red-400" />;
      default:
        return <Terminal className="h-3 w-3 text-muted-foreground" />;
    }
  };

  const formatLogEntry = (entry: StepEvent): { label: string; detail: string } => {
    switch (entry.type) {
      case "tool_call": {
        const args = entry.arguments || {};
        // Extract key params for readability
        let detail = "";
        if (entry.name === "generate_simple_frame") {
          detail = `${args.stories || "?"} stories x ${args.bays || "?"} bays`;
        } else if (entry.name === "analyze_frame") {
          detail = "Running anaStruct linear analysis...";
        } else if (entry.name === "select_critical_element") {
          detail = "Identifying column with highest axial load";
        } else if (entry.name === "apply_demolition_action") {
          detail = `Removing element #${args.element_id || "?"}`;
        } else if (entry.name === "high_fidelity_analysis") {
          detail = "Running OpenSees verification...";
        } else {
          detail = JSON.stringify(args).slice(0, 80);
        }
        return { label: entry.name || "?", detail };
      }
      case "tool_result": {
        // Parse and extract key metrics
        let parsed: Record<string, unknown> | null = null;
        try {
          parsed = typeof entry.result === "string" ? JSON.parse(entry.result) : (entry.result as Record<string, unknown>);
        } catch { /* not JSON */ }
        if (!parsed) return { label: "Result", detail: String(entry.result).slice(0, 80) };

        if (entry.name === "generate_simple_frame") {
          const n = (parsed.nodes as unknown[] | undefined)?.length ?? 0;
          const e = (parsed.elements as unknown[] | undefined)?.length ?? 0;
          return { label: "Frame ready", detail: `${n} nodes, ${e} elements` };
        } else if (entry.name === "analyze_frame") {
          const disp = parsed.max_displacement;
          const axial = parsed.max_axial_force;
          return { label: "Analysis done", detail: `Max disp: ${fmtVal(disp)} m, Max axial: ${fmtVal(axial)} N` };
        } else if (entry.name === "select_critical_element") {
          return { label: "Critical element", detail: `Element #${parsed.critical_element_id}, axial: ${fmtVal(parsed.critical_axial_force_N)} N` };
        } else if (entry.name === "apply_demolition_action") {
          const fe = parsed.failed_elements as number[] | undefined;
          return { label: "Demolished!", detail: fe ? `${fe.length} element(s) collapsed: [${fe.join(", ")}]` : "Done" };
        } else if (entry.name === "high_fidelity_analysis") {
          return { label: "Hi-Fi result", detail: `Max disp: ${fmtVal(parsed.max_displacement)} m` };
        }
        return { label: entry.name || "Result", detail: JSON.stringify(parsed).slice(0, 80) };
      }
      case "response":
        return { label: "AI", detail: (entry.content || "").slice(0, 100) };
      case "error":
        return { label: "ERROR", detail: entry.content || "" };
      default:
        return { label: entry.type, detail: "" };
    }
  };

  function fmtVal(v: unknown): string {
    if (typeof v === "number") {
      if (Math.abs(v) >= 1000) return (v / 1000).toFixed(2) + "k";
      return v.toFixed(4);
    }
    return String(v);
  }

  /** Strip verbose fields from a step — keep only what restoreStateFromMessages needs. */
  function compactStep(step: StepEvent): StepEvent {
    if (step.type === "tool_call") {
      return { type: step.type, name: step.name };
    }
    if (step.type === "tool_result" && step.name && step.result) {
      let parsed: any;
      try {
        parsed = typeof step.result === "string" ? JSON.parse(step.result) : step.result;
      } catch {
        return { type: step.type, name: step.name };
      }
      const keep: Record<string, unknown> = {};
      if (step.name === "generate_simple_frame") {
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

  /** Generate a short human-readable label for one step in the tool chain. */
  function stepBrief(step: StepEvent): string {
    const toolNames: Record<string, string> = {
      generate_simple_frame: t("step.generating_brief", lang),
      analyze_frame: t("step.analyzing_brief", lang),
      select_critical_element: t("step.critical_brief", lang),
      apply_demolition_action: t("step.demolishing_brief", lang),
      high_fidelity_analysis: "OpenSees",
      pynite_analysis: "PyNite",
      fapp_analysis: "FAPP",
    };
    if (step.type === "tool_call") {
      return toolNames[step.name || ""] || step.name || "?";
    }
    if (step.type === "tool_result" && step.name) {
      const briefs: Record<string, (r: any) => string> = {
        generate_simple_frame: (r) => {
          const n = (r.nodes as any[] | undefined)?.length ?? 0;
          const e = (r.elements as any[] | undefined)?.length ?? 0;
          return `${n}点${e}杆`;
        },
        analyze_frame: (r) => `max ${((r.max_displacement ?? 0) as number * 1000).toFixed(2)}mm`,
        pynite_analysis: (r) => `${r.solver ? (r.solver as string).split(" ")[0] : ""} ${((r.max_displacement ?? 0) as number * 1000).toFixed(2)}mm`,
        fapp_analysis: (r) => `${r.solver ? (r.solver as string).split(" ")[0] : ""} ${((r.max_displacement ?? 0) as number * 1000).toFixed(2)}mm`,
        select_critical_element: (r) => `柱#${r.critical_element_id}`,
        apply_demolition_action: (r) => {
          const fe = r.failed_elements as number[] | undefined;
          return fe?.length ? `塌 #${fe.join(",")}` : "";
        },
        high_fidelity_analysis: (r) => `${r.solver ? (r.solver as string).split(" ")[0] : ""} ${((r.max_displacement ?? 0) as number * 1000).toFixed(2)}mm`,
      };
      const fn = briefs[step.name];
      if (!fn) return "";
      let parsed: any;
      try { parsed = typeof step.result === "string" ? JSON.parse(step.result) : step.result; } catch { return ""; }
      if (!parsed || typeof parsed !== "object") return "";
      return fn(parsed);
    }
    return "";
  }

  return (
    <div className="flex h-screen w-full overflow-hidden">
      {/* Sidebar */}
      <Sidebar
        conversations={conversations}
        activeId={activeConvId}
        collapsed={sidebarCollapsed}
        onNew={newConversation}
        onSelect={selectConversation}
        onDelete={deleteConversation}
        onRename={renameConversation}
        onTogglePin={togglePinConversation}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenDemoLibrary={() => setDemoLibraryOpen(true)}
      />

      {/* Panels container */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left Panel: Chat (30%) */}
        <div className="flex w-[30%] min-w-[300px] flex-col border-r border-border">
        {/* Chat header */}
        <div className="flex items-center justify-center border-b border-border px-4 py-2.5">
          <span className="text-sm font-semibold text-foreground">{t("chat.title", lang)}</span>
        </div>

        {/* Messages — min-h-0 ensures flex child can shrink below content height */}
        <div className="min-h-0 flex-1">
          <ScrollArea className="h-full p-4">
            <div className="space-y-4">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full min-h-[200px] text-center text-muted-foreground">
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" className="mb-3 opacity-40">
                  <text x="4" y="20" fill="#22d3ee" fontSize="20" fontWeight="bold" fontFamily="sans-serif">玄</text>
                  <text x="22" y="42" fill="#22d3ee" fontSize="20" fontWeight="bold" fontFamily="sans-serif">武</text>
                </svg>
                <p className="text-sm font-medium">{t("chat.empty_title", lang)}</p>
                <p className="text-xs mt-1">
                  {t("chat.empty_subtitle", lang)}
                </p>
              </div>
            )}
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm overflow-hidden ${
                    msg.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-foreground max-h-[360px] overflow-y-auto"
                  } animate-fade-in-up`}
                >
                  {msg.role === "ai" ? (
                    <div>
                      <div
                        className="prose prose-sm prose-invert max-w-none [&_strong]:text-primary"
                        dangerouslySetInnerHTML={{
                          __html: msg.content
                            .replace(
                              /\*\*(.*?)\*\*/g,
                              '<strong class="text-primary">$1</strong>'
                            )
                            .replace(
                              /`(.*?)`/g,
                              '<code class="text-xs bg-secondary px-1 py-0.5 rounded">$1</code>'
                            )
                            .replace(/\n/g, "<br/>"),
                        }}
                      />
                      {msg.steps && msg.steps.length > 0 && (
                        <details className="mt-2">
                          <summary className="text-[10px] text-muted-foreground cursor-pointer hover:text-foreground transition-colors select-none">
                            {msg.steps.filter((s) => s.type === "tool_call").map((s) => stepBrief(s)).join(" → ")}
                            {" · "}
                            {msg.steps.filter((s) => s.type === "tool_result").map((s) => stepBrief(s)).filter(Boolean).join(", ")}
                          </summary>
                          <div className="mt-1.5 space-y-0.5">
                            {msg.steps.map((step, j) => {
                              const brief = stepBrief(step);
                              return (
                                <div
                                  key={j}
                                  className="text-[10px] font-mono bg-secondary/40 rounded px-2 py-0.5 flex items-center gap-1.5"
                                >
                                  <span className={
                                    step.type === "tool_call"
                                      ? "text-amber-400/80 shrink-0"
                                      : "text-emerald-400/80 shrink-0"
                                  }>
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
                  ) : (
                    msg.content
                  )}
                </div>
              </div>
            ))}
            {status === "loading" && (
              <div className="flex justify-start">
                <div className="flex flex-col gap-1 rounded-xl bg-muted px-4 py-2.5">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t("chat.thinking", lang)}
                  </div>
                  {currentStep && (
                    <div className="flex items-center gap-1.5 text-[11px] text-primary/80 animate-pulse">
                      <ListOrdered className="h-3 w-3" />
                      {currentStep}
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

        {/* Quick actions */}
        {messages.length === 0 && (
          <div className="flex flex-wrap gap-1.5 px-4 pb-2">
            {quickActions.map((action) => (
              <button
                key={action}
                onClick={() => setInput(action)}
                className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary cursor-pointer"
              >
                {action}
              </button>
            ))}
          </div>
        )}

        {/* Demolish button */}
        {demolishReady && (
          <div className="px-4 pb-2">
            <button
              onClick={() => setDemolishDialogOpen(true)}
              className="w-full flex items-center justify-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2.5 text-sm font-medium text-red-400 hover:bg-red-500/20 hover:border-red-500/60 transition-all cursor-pointer animate-pulse"
            >
              <Zap className="h-4 w-4" />
              {t("chat.demolish", lang)}
            </button>
          </div>
        )}

        {/* Input */}
        <div className="border-t border-border p-3">
          <div className="flex gap-2">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t("chat.placeholder", lang)}
              className="flex-1"
              disabled={status === "loading"}
            />
            {status === "loading" ? (
              <Button
                onClick={handleStop}
                size="icon"
                variant="destructive"
                className="shrink-0"
                title={t("chat.stop", lang)}
              >
                <Square className="h-4 w-4" />
              </Button>
            ) : (
              <Button
                onClick={sendMessage}
                disabled={!input.trim()}
                size="icon"
              >
                <Send className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Center Panel: Visualization (50%) */}
      <div className="flex w-[50%] flex-col border-r border-border bg-[#0a0f1a]">
        {/* Visualization mode toggle */}
        <div className="flex items-center justify-between border-b border-border px-4 py-1.5">
          <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
            {vizMode === "svg" ? "SVG 2D View" : "Unity 3D View"}
          </span>
          <div className="flex items-center gap-1 bg-secondary/50 rounded-lg p-0.5">
            <button
              onClick={() => setVizMode("svg")}
              className={`px-3 py-1 text-[11px] font-medium rounded-md transition-colors cursor-pointer ${
                vizMode === "svg"
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              SVG
            </button>
            <button
              onClick={() => setVizMode("unity")}
              className={`px-3 py-1 text-[11px] font-medium rounded-md transition-colors cursor-pointer ${
                vizMode === "unity"
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Unity
            </button>
          </div>
        </div>

        {vizMode === "svg" ? (
          <>
        {/* Structure visualization */}
        <FrameVisualization
          structure={frameStructure}
          displacements={nodeDisplacements}
          criticalElementId={structuralMetrics?.criticalElementId ?? null}
          failedElements={failedElements}
          maxDisplacement={analysisResult?.max_displacement as number | undefined}
          elementForces={analysisResult?.element_forces as Array<{element_id: number; Nmax: number; Nmin: number; Mmax: number; Mmin: number; Qmax: number; Qmin: number}> | undefined}
        />

        {/* Verification panel — centered below visualization */}
        {analysisResult && (
          <div className="flex items-center justify-center px-4 pb-2">
            <VerificationPanel fastResult={analysisResult} structure={frameStructure as Record<string, unknown> | null} lang={lang} analysisSolver={analysisSolver ?? undefined} />
          </div>
        )}
          </>
        ) : (
          <UnityVideoPanel onStreamConnected={() => setVizMode("unity")} />
        )}

        {/* Log Stream at bottom of center panel */}
        <div className="border-t border-border bg-[#060a12]">
          <div className="flex items-center justify-between px-4 py-2 border-b border-border">
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
              <Terminal className="h-3.5 w-3.5" />
              Agent Log Stream
              {logEntries.length > 0 && (
                <Badge variant="outline" className="text-[10px]">
                  {logEntries.length}
                </Badge>
              )}
            </div>
            <button
              onClick={() => setLogPaused(!logPaused)}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer flex items-center gap-1"
            >
              {logPaused ? (
                <>
                  <PlayCircle className="h-3 w-3" /> Resume
                </>
              ) : (
                <>
                  <Pause className="h-3 w-3" /> Pause
                </>
              )}
            </button>
          </div>
          <ScrollArea className="h-32">
            <div className="p-3 font-mono text-[11px] leading-relaxed">
              {logEntries.length === 0 ? (
                <span className="text-muted-foreground">
                  Waiting for agent activity...
                </span>
              ) : (
                logEntries.map((entry, i) => {
                  const formatted = formatLogEntry(entry);
                  return (
                  <div
                    key={i}
                    className="flex items-start gap-1.5 text-muted-foreground hover:text-foreground transition-colors py-0.5"
                  >
                    <span className="mt-0.5 shrink-0">
                      {getLogIcon(entry.type)}
                    </span>
                    <span className="text-[10px] font-semibold text-foreground/70 shrink-0">{formatted.label}</span>
                    {formatted.detail && (
                      <span className="text-[10px] text-muted-foreground/60 break-all">— {formatted.detail}</span>
                    )}
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
            <Activity className="h-3.5 w-3.5" />
            System Status
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span
                className={`h-2 w-2 rounded-full ${
                  status === "idle"
                    ? "bg-emerald-500"
                    : "bg-amber-500 animate-pulse"
                }`}
              />
              <span className="text-sm capitalize">{t(status === "idle" ? "status.idle" : "status.loading", lang)}</span>
            </div>
            <div className="flex items-center gap-2">
              <span
                className={`h-2 w-2 rounded-full ${wsConnected ? "bg-emerald-500" : "bg-red-500"}`}
              />
              <span className="text-xs text-muted-foreground">
                {wsConnected ? t("status.ws_connected", lang) : t("status.ws_disconnected", lang)}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Brain className="h-3.5 w-3.5 text-primary/60" />
              <span className="text-xs text-muted-foreground">
                LLM: {llmModel}
              </span>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {/* Mechanical Summary */}
          <MechanicalSummary metrics={structuralMetrics} />

          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3 mt-4">
            <Wrench className="h-3.5 w-3.5" />
            Available Tools
          </div>
          {tools.length === 0 ? (
            <p className="text-xs text-muted-foreground">Loading tools...</p>
          ) : (
            <div className="space-y-2">
              {tools.map((tool) => (
                <div
                  key={tool.name}
                  className="rounded-lg border border-border bg-card p-3 transition-colors hover:border-primary/30"
                >
                  <div className="flex items-center gap-2">
                    <Calculator className="h-3.5 w-3.5 text-primary" />
                    <span className="text-sm font-medium">{tool.name}</span>
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground leading-relaxed">
                    {tool.description}
                  </p>
                  <Badge variant="outline" className="mt-2 text-[10px]">
                    {tool.server}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Memory snippets */}
        <div className="border-t border-border p-4">
          <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
            Context Memory
          </div>
          {memorySnippets.length === 0 ? (
            <p className="text-[11px] text-muted-foreground/60">
              No memories yet. Start a conversation...
            </p>
          ) : (
            <div className="space-y-1.5">
              {memorySnippets.map((snippet, i) => (
                <div
                  key={i}
                  className="text-[10px] text-muted-foreground bg-secondary/50 rounded px-2 py-1 leading-relaxed"
                >
                  {snippet.replace("## Relevant Context (from past conversations):\n", "")}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      </div>
      {/* End panels container */}

      {/* Settings Dialog */}
      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="border-border max-w-2xl h-[540px] flex flex-col overflow-hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings className="h-4 w-4 text-primary" />
              {t("settings.title", lang)}
            </DialogTitle>
          </DialogHeader>

          {/* Tab bar */}
          <SettingsTabs
            tabs={[
              { key: "llm", label: t("settings.tab_llm", lang) },
              { key: "appearance", label: t("settings.tab_appearance", lang) },
              { key: "storage", label: t("settings.tab_storage", lang) },
            ]}
            activeTab={settingsTab}
            onTabChange={setSettingsTab}
          />

          <div className="flex-1 overflow-y-auto min-h-0">
          {/* LLM Tab */}
          {settingsTab === "llm" && (
            <div className="space-y-4">
              <div>
                <label className="text-sm font-medium text-muted-foreground uppercase tracking-wide">{t("settings.api_key", lang)}</label>
                <input
                  type="password"
                  value={llmApiKey}
                  onChange={(e) => setLlmApiKey(e.target.value)}
                  placeholder="sk-..."
                  className="mt-1 h-9 w-full rounded-lg border border-border bg-transparent px-2.5 py-1 text-base outline-none focus:border-primary/50 transition-colors"
                />
                <p className="text-xs text-muted-foreground mt-0.5">{t("settings.api_key_hint", lang)}</p>
              </div>
              <div>
                <label className="text-sm font-medium text-muted-foreground uppercase tracking-wide">{t("settings.base_url", lang)}</label>
                <input
                  type="text"
                  value={llmBaseUrl}
                  onChange={(e) => setLlmBaseUrl(e.target.value)}
                  placeholder="https://api.openai.com/v1"
                  className="mt-1 h-9 w-full rounded-lg border border-border bg-transparent px-2.5 py-1 text-base outline-none focus:border-primary/50 transition-colors"
                />
                <p className="text-xs text-muted-foreground mt-0.5">{t("settings.base_url_hint", lang)}</p>
              </div>
              <div>
                <label className="text-sm font-medium text-muted-foreground uppercase tracking-wide">{t("settings.model", lang)}</label>
                <input
                  type="text"
                  value={llmModel}
                  onChange={(e) => handleModelChange(e.target.value)}
                  placeholder="gpt-4o"
                  list="llm-model-presets"
                  className="mt-1 h-9 w-full rounded-lg border border-border bg-transparent px-2.5 py-1 text-base outline-none focus:border-primary/50 transition-colors"
                />
                <datalist id="llm-model-presets">
                  {COMMON_MODELS.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
                <p className="text-xs text-muted-foreground mt-0.5">{t("settings.model_hint", lang)}</p>
              </div>
              <DialogFooter className="flex items-center gap-2 pt-2">
                {llmStatus === "saved" && (
                  <span className="text-xs text-emerald-400 mr-auto">{t("settings.saved", lang)}</span>
                )}
                {llmStatus === "error" && (
                  <span className="text-xs text-red-400 mr-auto">{t("settings.failed", lang)}</span>
                )}
                <Button variant="outline" onClick={() => setSettingsOpen(false)}>
                  {t("settings.cancel", lang)}
                </Button>
                <Button onClick={saveLlmSettings} disabled={llmStatus === "saving"}>
                  {llmStatus === "saving" ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                      {t("settings.saving", lang)}
                    </>
                  ) : (
                    t("settings.save", lang)
                  )}
                </Button>
              </DialogFooter>
            </div>
          )}

          {/* Appearance Tab */}
          {settingsTab === "appearance" && (
            <div className="space-y-5">
              {/* Language */}
              <div>
                <label className="text-sm font-medium text-muted-foreground uppercase tracking-wide">{t("settings.language", lang)}</label>
                <div className="mt-2 flex items-center gap-3">
                  <button
                    onClick={() => handleLangChange("en")}
                    className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors cursor-pointer ${
                      lang === "en"
                        ? "bg-primary/20 text-primary border border-primary/50"
                        : "bg-muted text-muted-foreground border border-border hover:bg-muted/80"
                    }`}
                  >
                    English
                  </button>
                  <button
                    onClick={() => handleLangChange("zh")}
                    className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors cursor-pointer ${
                      lang === "zh"
                        ? "bg-primary/20 text-primary border border-primary/50"
                        : "bg-muted text-muted-foreground border border-border hover:bg-muted/80"
                    }`}
                  >
                    中文
                  </button>
                </div>
                <p className="text-xs text-muted-foreground mt-1.5">{t("settings.language_hint", lang)}</p>
              </div>
              {/* Theme */}
              <div>
                <label className="text-sm font-medium text-muted-foreground uppercase tracking-wide">{t("settings.theme", lang)}</label>
                <div className="mt-2 grid grid-cols-3 gap-2">
                  {THEMES.map((t2) => {
                    const active = theme === t2.key;
                    return (
                      <button
                        key={t2.key}
                        onClick={() => setTheme(t2.key)}
                        className={`flex flex-col items-center gap-1.5 rounded-lg p-2 border transition-all cursor-pointer ${
                          active
                            ? "border-primary bg-primary/10 ring-1 ring-primary/30"
                            : "border-border bg-muted/20 hover:border-muted-foreground/40"
                        }`}
                      >
                        <div className="flex gap-0.5">
                          {t2.colors.map((c, i) => (
                            <span
                              key={i}
                              className="w-5 h-5 rounded-full border border-white/10"
                              style={{ backgroundColor: c }}
                            />
                          ))}
                        </div>
                        <span
                          className={`text-xs font-medium ${
                            active ? "text-primary" : "text-foreground"
                          }`}
                        >
                          {lang === "zh" ? t2.nameZh : t2.name}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* Storage Tab */}
          {settingsTab === "storage" && (
            <div className="space-y-3">
              <div className="flex items-center justify-between rounded-lg border border-border bg-muted/20 px-3 py-2">
                <div>
                  <span className="text-sm text-foreground">{t("settings.conv_storage", lang)}</span>
                  <p className="text-xs text-muted-foreground">{t("settings.conv_storage_hint", lang)}</p>
                </div>
                <button
                  onClick={() => {
                    if (confirm(t("settings.clear_conv_confirm", lang))) {
                      localStorage.removeItem(CONV_STORAGE);
                      localStorage.removeItem(CONV_ACTIVE);
                      setConversations([]);
                      setMessages([]);
                      setActiveConvId(null);
                      setFrameStructure(null);
                      setAnalysisResult(null);
                      setAnalysisSolver(null);
                      setFailedElements([]);
                      setDemolishReady(false);
                    }
                  }}
                  className="px-3 py-1 text-xs font-medium text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/10 transition-colors cursor-pointer shrink-0"
                >
                  {t("settings.clear", lang)}
                </button>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-border bg-muted/20 px-3 py-2">
                <div>
                  <span className="text-sm text-foreground">{t("settings.memory_storage", lang)}</span>
                  <p className="text-xs text-muted-foreground">{t("settings.memory_storage_hint", lang)}</p>
                </div>
                <button
                  onClick={async () => {
                    try {
                      await fetchWithTimeout("http://localhost:8000/settings/memory/clear", { method: "POST" });
                      setMemorySnippets([]);
                    } catch {}
                  }}
                  className="px-3 py-1 text-xs font-medium text-amber-400 border border-amber-500/30 rounded-lg hover:bg-amber-500/10 transition-colors cursor-pointer shrink-0"
                >
                  {t("settings.clear", lang)}
                </button>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-border bg-muted/20 px-3 py-2">
                <div>
                  <span className="text-sm text-foreground">{t("settings.export", lang)}</span>
                  <p className="text-xs text-muted-foreground">{t("settings.export_hint", lang)}</p>
                </div>
                <button
                  onClick={() => {
                    const data = localStorage.getItem(CONV_STORAGE) || "[]";
                    const blob = new Blob([data], { type: "application/json" });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = "xuanwu_conversations_backup.json";
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                  className="px-3 py-1 text-xs font-medium text-primary border border-primary/30 rounded-lg hover:bg-primary/10 transition-colors cursor-pointer shrink-0"
                >
                  {t("settings.download", lang)}
                </button>
              </div>
              <div className="pt-3">
                <Button variant="outline" className="w-full" onClick={() => setSettingsOpen(false)}>
                  {t("settings.close", lang)}
                </Button>
              </div>
            </div>
          )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Demolition Confirm Dialog */}
      <Dialog open={demolishDialogOpen} onOpenChange={setDemolishDialogOpen}>
        <DialogContent className="border-red-500/30">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-400">
              <Zap className="h-5 w-5" />
              {t("confirm.title", lang)}
            </DialogTitle>
            <DialogDescription className="text-muted-foreground">
              {t("confirm.desc", lang)}
              {structuralMetrics?.criticalElementId !== null && (
                <span className="block mt-2 text-amber-400">
                  {t("confirm.target", lang)}: Element #{structuralMetrics?.criticalElementId}
                  {structuralMetrics?.criticalAxialForce && (
                    <span> ({(structuralMetrics.criticalAxialForce / 1000).toFixed(1)} kN {t("mech.axial_force", lang)})</span>
                  )}
                </span>
              )}
              <span className="block mt-2 text-muted-foreground/60 text-xs">
                {t("confirm.hint", lang)}
              </span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setDemolishDialogOpen(false)}>
              {t("confirm.cancel", lang)}
            </Button>
            <Button
              onClick={triggerDemolition}
              className="bg-red-600 hover:bg-red-700 text-white"
            >
              <Zap className="h-4 w-4 mr-2" />
              {t("confirm.demolish", lang)}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Demo Library Dialog */}
      <Dialog open={demoLibraryOpen} onOpenChange={setDemoLibraryOpen}>
        <DialogContent className="border-border max-w-xl h-[480px] flex flex-col overflow-hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Library className="h-5 w-5 text-primary" />
              {t("demo.title", lang)}
            </DialogTitle>
            <DialogDescription className="text-muted-foreground">
              {t("demo.title_desc", lang)}
            </DialogDescription>
          </DialogHeader>

          <div className="flex-1 overflow-y-auto min-h-0 space-y-3 py-2">
            {/* Unity Full Flow Demo */}
            <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 hover:border-primary/40 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                    <Play className="h-4 w-4 text-primary" />
                    {t("demo.unity_full_flow", lang)}
                  </h3>
                  <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed">
                    {t("demo.unity_full_flow_desc", lang)}
                  </p>
                  <div className="mt-3 flex items-center gap-3 text-[10px] text-muted-foreground/70">
                    <span className="flex items-center gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                      Launch Unity
                    </span>
                    <span>→</span>
                    <span className="flex items-center gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-blue-400" />
                      Generate
                    </span>
                    <span>→</span>
                    <span className="flex items-center gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                      Analyze
                    </span>
                    <span>→</span>
                    <span className="flex items-center gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
                      Demolish
                    </span>
                  </div>
                </div>
                <Button
                  onClick={runUnityFullFlowDemo}
                  disabled={demoRunning}
                  className="shrink-0"
                  size="sm"
                >
                  {demoRunning ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                      {t("demo.running", lang)}
                    </>
                  ) : (
                    <>
                      <Zap className="h-3.5 w-3.5 mr-1.5" />
                      {t("demo.run", lang)}
                    </>
                  )}
                </Button>
              </div>
            </div>

            {/* Placeholder for future demos */}
            <div className="rounded-xl border border-border border-dashed bg-muted/10 p-4 text-center">
              <p className="text-xs text-muted-foreground/50">
                More demos coming soon...
              </p>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Demo running overlay */}
      {demoRunning && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 rounded-full border border-primary/30 bg-[#0f172a]/95 backdrop-blur-sm px-5 py-2.5 shadow-xl shadow-black/30 animate-in fade-in slide-in-from-bottom-2">
          <Loader2 className="h-4 w-4 text-primary animate-spin" />
          <span className="text-sm text-foreground font-medium">{demoStatus}</span>
        </div>
      )}

      {/* Floating Toolbar */}
      <FloatingToolbar
        wsConnected={wsConnected}
        toolsCount={tools.length}
        onOpenSettings={() => setSettingsOpen(true)}
        onClearChat={handleClearChat}
        quickActions={quickActions}
        onQuickAction={sendQuickAction}
      />
    </div>
  );
}
