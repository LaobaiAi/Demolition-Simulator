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
import { Sidebar, type Conversation } from "@/components/sidebar";
import { t, getSavedLang, saveLang, type Lang } from "@/lib/i18n";

interface FrameNode { id: number; x: number; y: number; }
interface FrameElement { id: number; node_i: number; node_j: number; E?: number; A?: number; I?: number; }
interface FrameLoad { node_id: number; Fx: number; Fy: number; }
interface FrameSupport { node_id: number; type: string; }
interface FrameStructure { nodes: FrameNode[]; elements: FrameElement[]; loads: FrameLoad[]; supports: FrameSupport[]; }
interface NodeDisp { node_id: number; ux: number; uy: number; }

function genId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
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
      } else if (step.name === "analyze_frame") {
        if (parsed.max_displacement !== undefined) {
          analysisResult = parsed;
          if (parsed.node_displacements) {
            nodeDisplacements = parsed.node_displacements as NodeDisp[];
          }
          maxDisp = parsed.max_displacement ?? 0;
          maxAxial = parsed.max_axial_force ?? 0;
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
  const [demolishDialogOpen, setDemolishDialogOpen] = useState(false);
  const [demolishReady, setDemolishReady] = useState(false);
  const [frameStructure, setFrameStructure] = useState<FrameStructure | null>(null);
  const [nodeDisplacements, setNodeDisplacements] = useState<NodeDisp[] | null>(null);

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
    // Load last-used model
    const lastModel = localStorage.getItem("xuanwu_last_model") || "gpt-4o";
    setLlmModel(lastModel);
    const profile = profiles[lastModel];
    if (profile) {
      setLlmApiKey(profile.api_key || "");
      setLlmBaseUrl(profile.base_url || "");
      // Apply to backend
      fetch("http://localhost:8000/settings/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: lastModel, api_key: profile.api_key, base_url: profile.base_url }),
      }).catch(() => {});
    }
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
    const config = {
      api_key: llmApiKey || undefined,
      base_url: llmBaseUrl || undefined,
      model: llmModel || undefined,
    };
    try {
      const res = await fetch("http://localhost:8000/settings/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      if (!res.ok) throw new Error("Failed");
      // Save per-model profile
      const profiles = loadProfiles();
      profiles[llmModel] = { api_key: llmApiKey, base_url: llmBaseUrl };
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
          // Final response - commit to messages
          setMessages((prev) => [
            ...prev,
            {
              role: "ai",
              content: data.content || "",
              steps: [...pendingStepsRef.current],
            },
          ]);
          // Also add as a log entry
          setLogEntries((prev) => [
            ...prev,
            { type: "response", content: data.content },
          ]);
          pendingStepsRef.current = [];
          setStatus("idle");
        } else if (data.type === "error") {
          setMessages((prev) => [
            ...prev,
            { role: "ai", content: `Error: ${data.content}` },
          ]);
          setLogEntries((prev) => [...prev, data]);
          pendingStepsRef.current = [];
          setStatus("idle");
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
              select_critical_element: t("step.critical", L),
              apply_demolition_action: t("step.demolishing", L),
              high_fidelity_analysis: t("step.verifying", L),
            };
            setCurrentStep(stepLabels[data.name] || `Running ${data.name}...`);
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

          // Capture structural analysis results for verification
          if (
            data.type === "tool_result" &&
            data.name === "analyze_frame" &&
            data.result
          ) {
            try {
              const parsed =
                typeof data.result === "string"
                  ? JSON.parse(data.result)
                  : data.result;
              if (parsed.max_displacement !== undefined) {
                setAnalysisResult(parsed);
                if (parsed.node_displacements) {
                  setNodeDisplacements(parsed.node_displacements);
                }
                // Update mechanical summary with analysis values
                setStructuralMetrics((prev) => ({
                  maxDisplacement: parsed.max_displacement ?? 0,
                  maxAxialForce: parsed.max_axial_force ?? 0,
                  criticalElementId: prev?.criticalElementId ?? null,
                  criticalAxialForce: prev?.criticalAxialForce ?? null,
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
    setStructuralMetrics(null);
    setFailedElements([]);
    setMemorySnippets([]);
    setCurrentStep("");
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
                          <summary className="text-[10px] text-muted-foreground cursor-pointer hover:text-foreground transition-colors">
                            {msg.steps.length} tool call(s)
                          </summary>
                          <div className="mt-1 space-y-1">
                            {msg.steps.map((step, j) => (
                              <div
                                key={j}
                                className="text-[10px] text-muted-foreground font-mono bg-secondary/50 rounded px-2 py-1"
                              >
                                {step.type === "tool_call"
                                  ? `${step.name}(${JSON.stringify(step.arguments).slice(0, 120)})`
                                  : step.type === "tool_result"
                                    ? `→ ${JSON.stringify(step.result).slice(0, 200)}`
                                    : ""}
                              </div>
                            ))}
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
            <Button
              onClick={sendMessage}
              disabled={!input.trim() || status === "loading"}
              size="icon"
            >
              {status === "loading" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
      </div>

      {/* Center Panel: Visualization (50%) */}
      <div className="flex w-[50%] flex-col border-r border-border bg-[#0a0f1a]">
        {/* Structure visualization */}
        <FrameVisualization
          structure={frameStructure}
          displacements={nodeDisplacements}
          criticalElementId={structuralMetrics?.criticalElementId ?? null}
          failedElements={failedElements}
          maxDisplacement={analysisResult?.max_displacement as number | undefined}
          elementForces={analysisResult?.element_forces as Array<{element_id: number; Nmax: number; Nmin: number; Mmax: number; Mmin: number; Qmax: number; Qmin: number}> | undefined}
        />

        {/* Verification panel */}
        {analysisResult && (
          <div className="px-4 pb-2">
            <VerificationPanel fastResult={analysisResult} structure={frameStructure as Record<string, unknown> | null} lang={lang} />
          </div>
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

      {/* LLM Settings Dialog */}
      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="border-border">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings className="h-4 w-4 text-primary" />
              {t("settings.title", lang)}
            </DialogTitle>
            <DialogDescription className="text-muted-foreground">
              {t("settings.desc", lang)}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("settings.api_key", lang)}</label>
              <input
                type="password"
                value={llmApiKey}
                onChange={(e) => setLlmApiKey(e.target.value)}
                placeholder="sk-..."
                className="mt-1 h-8 w-full rounded-lg border border-border bg-transparent px-2.5 py-1 text-sm outline-none focus:border-primary/50 transition-colors"
              />
              <p className="text-[10px] text-muted-foreground mt-0.5">Required for most providers (OpenAI, DeepSeek, etc.)</p>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("settings.base_url", lang)}</label>
              <input
                type="text"
                value={llmBaseUrl}
                onChange={(e) => setLlmBaseUrl(e.target.value)}
                placeholder="https://api.openai.com/v1"
                className="mt-1 h-8 w-full rounded-lg border border-border bg-transparent px-2.5 py-1 text-sm outline-none focus:border-primary/50 transition-colors"
              />
              <p className="text-[10px] text-muted-foreground mt-0.5">Leave empty for OpenAI default. Set custom endpoint for other providers.</p>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("settings.model", lang)}</label>
              <input
                type="text"
                value={llmModel}
                onChange={(e) => handleModelChange(e.target.value)}
                placeholder="gpt-4o"
                list="llm-model-presets"
                className="mt-1 h-8 w-full rounded-lg border border-border bg-transparent px-2.5 py-1 text-sm outline-none focus:border-primary/50 transition-colors"
              />
              <datalist id="llm-model-presets">
                {COMMON_MODELS.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
              <p className="text-[10px] text-muted-foreground mt-0.5">URL &amp; Key are remembered per model when you save</p>
            </div>
            {/* Language Switch */}
            <div className="border-t border-border pt-4">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("settings.language", lang)}</label>
              <div className="mt-2 flex items-center gap-3">
                <button
                  onClick={() => handleLangChange("en")}
                  className={`px-4 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                    lang === "en"
                      ? "bg-primary/20 text-primary border border-primary/50"
                      : "bg-muted text-muted-foreground border border-border hover:bg-muted/80"
                  }`}
                >
                  English
                </button>
                <button
                  onClick={() => handleLangChange("zh")}
                  className={`px-4 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                    lang === "zh"
                      ? "bg-primary/20 text-primary border border-primary/50"
                      : "bg-muted text-muted-foreground border border-border hover:bg-muted/80"
                  }`}
                >
                  中文
                </button>
              </div>
              <p className="text-[10px] text-muted-foreground mt-1.5">{t("settings.language_hint", lang)}</p>
            </div>
            {/* Storage & Memory Management */}
            <div className="border-t border-border pt-4">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("settings.storage", lang)}</label>
              <div className="mt-2 space-y-3">
                {/* Conversations */}
                <div className="flex items-center justify-between rounded-lg border border-border bg-muted/20 px-3 py-2">
                  <div>
                    <span className="text-xs text-foreground">{t("settings.conv_storage", lang)}</span>
                    <p className="text-[10px] text-muted-foreground">{t("settings.conv_storage_hint", lang)}</p>
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
                        setFailedElements([]);
                        setDemolishReady(false);
                      }
                    }}
                    className="px-3 py-1 text-[10px] font-medium text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/10 transition-colors cursor-pointer shrink-0"
                  >
                    {t("settings.clear", lang)}
                  </button>
                </div>
                {/* Agent Memory */}
                <div className="flex items-center justify-between rounded-lg border border-border bg-muted/20 px-3 py-2">
                  <div>
                    <span className="text-xs text-foreground">{t("settings.memory_storage", lang)}</span>
                    <p className="text-[10px] text-muted-foreground">{t("settings.memory_storage_hint", lang)}</p>
                  </div>
                  <button
                    onClick={async () => {
                      try {
                        await fetch("http://localhost:8000/settings/memory/clear", { method: "POST" });
                        setMemorySnippets([]);
                      } catch {}
                    }}
                    className="px-3 py-1 text-[10px] font-medium text-amber-400 border border-amber-500/30 rounded-lg hover:bg-amber-500/10 transition-colors cursor-pointer shrink-0"
                  >
                    {t("settings.clear", lang)}
                  </button>
                </div>
                {/* Export conversations */}
                <div className="flex items-center justify-between rounded-lg border border-border bg-muted/20 px-3 py-2">
                  <div>
                    <span className="text-xs text-foreground">{t("settings.export", lang)}</span>
                    <p className="text-[10px] text-muted-foreground">{t("settings.export_hint", lang)}</p>
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
                    className="px-3 py-1 text-[10px] font-medium text-primary border border-primary/30 rounded-lg hover:bg-primary/10 transition-colors cursor-pointer shrink-0"
                  >
                    {t("settings.download", lang)}
                  </button>
                </div>
              </div>
            </div>
          </div>
          <DialogFooter className="flex items-center gap-2">
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
                "Save"
              )}
            </Button>
          </DialogFooter>
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
