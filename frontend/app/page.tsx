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

  // LLM settings — per-model profiles persisted in localStorage
  const LLM_STORAGE_KEY = "xuanwu_llm_profiles";
  const COMMON_MODELS = ["gpt-4o", "gpt-4o-mini", "deepseek-v4-pro", "deepseek-v4-chat", "claude-sonnet-4-6", "claude-opus-4-7"];

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
            const stepLabels: Record<string, string> = {
              generate_simple_frame: "Generating frame...",
              analyze_frame: "Analyzing structure...",
              select_critical_element: "Identifying critical column...",
              apply_demolition_action: "Triggering demolition...",
              high_fidelity_analysis: "Running high-fidelity verification...",
            };
            setCurrentStep(stepLabels[data.name] || `Running ${data.name}...`);
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
                setFailedElements(feList);
                setStructuralMetrics((prev) =>
                  prev
                    ? { ...prev, failedElements: feList }
                    : {
                        maxDisplacement: 0,
                        maxAxialForce: 0,
                        criticalElementId: null,
                        criticalAxialForce: null,
                        columnCount: 0,
                        failedElements: feList,
                      }
                );
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
    "Analyze a 2-story 2-bay frame",
    "Analyze a 3-story 3-bay frame",
    "Analyze a 2-story 4-bay frame",
    "Analyze a 4-story 3-bay frame",
    "Analyze a 1-story 2-bay frame",
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

  const formatLogEntry = (entry: StepEvent) => {
    const time = new Date().toLocaleTimeString();
    switch (entry.type) {
      case "tool_call":
        return `[${time}] Calling: ${entry.name}(${JSON.stringify(entry.arguments)})`;
      case "tool_result":
        return `[${time}] Result: ${JSON.stringify(entry.result)}`;
      case "response":
        return `[${time}] ${entry.content}`;
      case "error":
        return `[${time}] ERROR: ${entry.content}`;
      default:
        return `[${time}] ${JSON.stringify(entry)}`;
    }
  };

  return (
    <div className="flex h-screen w-full overflow-hidden">
      {/* Left Panel: Chat (30%) */}
      <div className="flex w-[30%] min-w-[320px] flex-col border-r border-border">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/20">
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M4 4L16 16M16 4L4 16" stroke="#22d3ee" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="flex-1">
            <h1 className="text-sm font-semibold text-foreground">
              XuanwuAI Console
            </h1>
            <p className="text-[10px] text-muted-foreground">
              Intelligent Demolition Simulator
            </p>
          </div>
          <button
            onClick={() => setSettingsOpen(true)}
            className="flex h-7 w-7 items-center justify-center rounded-md hover:bg-muted transition-colors cursor-pointer"
            title="LLM Settings"
          >
            <Settings className="h-3.5 w-3.5 text-muted-foreground" />
          </button>
        </div>

        {/* Messages */}
        <ScrollArea className="flex-1 p-4">
          <div className="space-y-4">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full min-h-[200px] text-center text-muted-foreground">
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" className="mb-3 opacity-40">
                  <path d="M10 10L38 38M38 10L10 38" stroke="#22d3ee" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <p className="text-sm font-medium">XuanwuAI Ready</p>
                <p className="text-xs mt-1">
                  Ask the AI to analyze a frame structure
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
                    Thinking...
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
              Demolish Critical Column
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
              placeholder="e.g. Analyze a 2-story 2-bay frame"
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
        {/* Main viz area */}
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="flex flex-col items-center gap-6">
            <div className="relative">
              <div className="logo-spin">
                <svg
                  width="120"
                  height="120"
                  viewBox="0 0 120 120"
                  fill="none"
                  className="opacity-60"
                >
                  <circle
                    cx="60"
                    cy="60"
                    r="54"
                    stroke="#22d3ee"
                    strokeWidth="2"
                    strokeDasharray="8 6"
                  />
                  <circle
                    cx="60"
                    cy="60"
                    r="38"
                    stroke="#22d3ee"
                    strokeWidth="1.5"
                    strokeDasharray="4 4"
                    className="opacity-50"
                  />
                  <circle
                    cx="60"
                    cy="60"
                    r="22"
                    stroke="#22d3ee"
                    strokeWidth="1"
                    strokeDasharray="3 3"
                    className="opacity-30"
                  />
                </svg>
              </div>
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="flex flex-col items-center">
                  <div className="h-8 w-1 bg-primary rounded-full" />
                  <div className="h-2 w-6 bg-primary/60 rounded-full mt-1" />
                </div>
              </div>
            </div>

            <div className="text-center">
              <p className="text-lg font-medium text-foreground">
                Visualization Panel
              </p>
              <p className="text-sm text-muted-foreground mt-1">
                Unity simulation stream will appear here
              </p>
            </div>

            {analysisResult ? (
              <div className="mt-4 w-full max-w-md">
                <VerificationPanel fastResult={analysisResult} />
              </div>
            ) : (
              <div className="mt-4 rounded-xl border border-border p-6 bg-[#0f172a]/50">
                <pre className="text-[10px] text-muted-foreground font-mono leading-tight">
                  {"    ┌──────────┐\n    │  ██  ██  │\n    │  ██  ██  │\n    ├──┼──┼──┼──┤\n    │  ██  ██  │\n    │  ██  ██  │\n    └──┴──┴──┴──┘\n  2-Bay Frame (Day 4+)"}
                </pre>
              </div>
            )}
          </div>
        </div>

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
                logEntries.map((entry, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-1.5 text-muted-foreground hover:text-foreground transition-colors py-0.5"
                  >
                    <span className="mt-0.5 shrink-0">
                      {getLogIcon(entry.type)}
                    </span>
                    <span className="break-all">
                      {formatLogEntry(entry)}
                    </span>
                  </div>
                ))
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
              <span className="text-sm capitalize">{status}</span>
            </div>
            <div className="flex items-center gap-2">
              <span
                className={`h-2 w-2 rounded-full ${wsConnected ? "bg-emerald-500" : "bg-red-500"}`}
              />
              <span className="text-xs text-muted-foreground">
                {wsConnected ? "WS Connected" : "WS Disconnected"}
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

      {/* LLM Settings Dialog */}
      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="border-border">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings className="h-4 w-4 text-primary" />
              LLM Configuration
            </DialogTitle>
            <DialogDescription className="text-muted-foreground">
              Configure your LLM provider connection. Settings are saved locally and applied to the Gateway.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">API Key</label>
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
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Base URL</label>
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
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Model</label>
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
          </div>
          <DialogFooter className="flex items-center gap-2">
            {llmStatus === "saved" && (
              <span className="text-xs text-emerald-400 mr-auto">Saved successfully</span>
            )}
            {llmStatus === "error" && (
              <span className="text-xs text-red-400 mr-auto">Failed to save</span>
            )}
            <Button variant="outline" onClick={() => setSettingsOpen(false)}>
              Cancel
            </Button>
            <Button onClick={saveLlmSettings} disabled={llmStatus === "saving"}>
              {llmStatus === "saving" ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                  Saving...
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
              Confirm Demolition
            </DialogTitle>
            <DialogDescription className="text-muted-foreground">
              This will trigger the physics-based collapse simulation in Unity.
              {structuralMetrics?.criticalElementId !== null && (
                <span className="block mt-2 text-amber-400">
                  Target: Element #{structuralMetrics?.criticalElementId}
                  {structuralMetrics?.criticalAxialForce && (
                    <span> ({(structuralMetrics.criticalAxialForce / 1000).toFixed(1)} kN axial)</span>
                  )}
                </span>
              )}
              <span className="block mt-2 text-red-400/80 text-xs">
                Ensure Unity simulation is running and listening on port 5005.
              </span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setDemolishDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={triggerDemolition}
              className="bg-red-600 hover:bg-red-700 text-white"
            >
              <Zap className="h-4 w-4 mr-2" />
              Demolish
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
