export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// ── Resilient fetch wrapper ─────────────────────────────────────────────────

async function fetchWithTimeout(url: string, options: RequestInit = {}, timeoutMs = 10000): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchWithRetry(url: string, options: RequestInit = {}, retries = 3, baseDelay = 1000): Promise<Response> {
  let lastError: Error | null = null;
  for (let i = 0; i < retries; i++) {
    try {
      return await fetchWithTimeout(url, options);
    } catch (e) {
      lastError = e as Error;
      if (i < retries - 1) {
        await new Promise(r => setTimeout(r, baseDelay * Math.pow(2, i)));
      }
    }
  }
  throw lastError ?? new Error("fetch failed after retries");
}

export interface Tool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  server: string;
}

export async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetchWithTimeout(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

export async function fetchTools(): Promise<Tool[]> {
  const res = await fetchWithRetry(`${API_BASE}/tools`);
  if (!res.ok) throw new Error(`Failed to fetch tools: ${res.status}`);
  const data = await res.json();
  return data.tools;
}

export interface ScenarioSummary {
  name: string;
  title: { en: string; zh: string };
  description: { en: string; zh: string };
  category: "topology" | "mechanics";
  needs_analysis: boolean;
  tags: string[];
  viz_mode: string;
}

export interface ScenarioFull extends ScenarioSummary {
  structure_params: Record<string, unknown>;
  strategy: string;
  effects_preset: string;
  effects: Record<string, boolean>;
  speed: number;
}

export async function fetchScenarios(category?: string, tag?: string): Promise<ScenarioSummary[]> {
  const params = new URLSearchParams();
  if (category) params.set("category", category);
  if (tag) params.set("tag", tag);
  const url = `${API_BASE}/scenarios${params.toString() ? "?" + params.toString() : ""}`;
  const res = await fetchWithRetry(url);
  if (!res.ok) throw new Error(`Failed to fetch scenarios: ${res.status}`);
  const data = await res.json();
  const raw = data.result || data;
  if (typeof raw === "string") {
    const parsed = JSON.parse(raw);
    return parsed.scenarios || [];
  }
  return raw.scenarios || [];
}

export async function fetchScenario(name: string): Promise<ScenarioFull | null> {
  const res = await fetchWithTimeout(`${API_BASE}/scenarios/${name}`);
  if (!res.ok) return null;
  const data = await res.json();
  const raw = data.result || data;
  if (typeof raw === "string") return JSON.parse(raw);
  return raw as ScenarioFull;
}

export async function fetchScenarioPrompt(name: string): Promise<string | null> {
  try {
    const res = await fetchWithTimeout(`${API_BASE}/prompts/${name}`);
    if (!res.ok) return null;
    const data = await res.json();
    return (data.content as string) || null;
  } catch {
    return null;
  }
}

export async function callTool(
  toolName: string,
  arguments_: Record<string, unknown>
): Promise<{ result: string; error?: string }> {
  const res = await fetchWithTimeout(`${API_BASE}/tools/call`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool_name: toolName, arguments: arguments_ }),
  });
  if (!res.ok) throw new Error(`Tool call failed: ${res.status}`);
  return res.json();
}

export const WS_BASE = API_BASE.replace("http://", "ws://");

export function createChatWebSocket(): WebSocket {
  return new WebSocket(`${WS_BASE}/ws/chat`);
}

export interface MetricComparison {
  fast: number;
  high_fidelity: number;
  diff_percent: number;
}

export interface VerificationResult {
  status: "verified" | "warning" | "error" | "unavailable";
  demo_mode?: boolean;
  message?: string;
  solver?: string;
  comparison: {
    max_displacement: MetricComparison;
    max_axial_force: MetricComparison;
  };
}

export async function verifyAnalysis(
  fastResult: Record<string, unknown>,
  structure?: Record<string, unknown>
): Promise<VerificationResult> {
  const res = await fetchWithTimeout(`${API_BASE}/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fast_result: fastResult, structure: structure || null }),
  });
  if (!res.ok) throw new Error(`Verification failed: ${res.status}`);
  return res.json();
}

export interface SolverResult {
  max_displacement?: number;
  max_axial_force?: number;
  error?: string;
}

export interface MultiSolverResult {
  solvers: Record<string, SolverResult>;
  consensus: {
    max_displacement: number;
    max_axial_force: number;
  };
  consensus_by_dimension?: Record<string, {
    solver_count: number;
    solvers: string[];
    max_displacement: number;
    max_axial_force: number;
  }>;
  dimension_discrepancy?: {
    detected: boolean;
    displacement_diff_pct: number;
    axial_diff_pct: number;
  };
  solver_count: number;
  deviations: Record<string, {
    displacement_diff_pct: number;
    axial_diff_pct: number;
    is_outlier: boolean;
    group?: string;
  }>;
}

export async function verifyMulti(
  fastResult: Record<string, unknown>,
  structure: Record<string, unknown>
): Promise<MultiSolverResult> {
  const res = await fetchWithTimeout(`${API_BASE}/verify/multi`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fast_result: fastResult, structure }),
  });
  if (!res.ok) throw new Error(`Multi-verification failed: ${res.status}`);
  return res.json();
}

export interface LLMConfig {
  model: string;
  base_url?: string;
  api_key?: string;
  thinking_enabled?: boolean;
}

export async function saveLLMSettings(config: LLMConfig): Promise<void> {
  const res = await fetchWithTimeout(`${API_BASE}/settings/llm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error(`Failed to save settings: ${res.status}`);
}

export async function getLLMConfig(): Promise<{
  model: string;
  base_url: string;
  has_api_key: boolean;
  thinking_enabled: boolean;
}> {
  const res = await fetchWithTimeout(`${API_BASE}/settings/llm`);
  if (!res.ok) throw new Error(`Failed to get config: ${res.status}`);
  return res.json();
}

// ── Server management APIs ──────────────────────────────────────────────────

export interface ServerStatus {
  name: string;
  state: string;
  pid: number | null;
  started_at: number | null;
  crash_count: number;
  restart_count: number;
  total_calls: number;
  error_count: number;
  avg_latency_ms: number;
}

export interface ServerHealth {
  [serverName: string]: {
    state: string;
    pid: number | null;
    started_at: number | null;
    crash_count: number;
    last_error: string | null;
  };
}

export interface ServerMetrics {
  [serverName: string]: {
    total_calls: number;
    error_count: number;
    avg_latency_ms: number;
    last_called: number | null;
  };
}

export async function fetchServerStatus(): Promise<ServerStatus[]> {
  const res = await fetchWithTimeout(`${API_BASE}/servers`);
  if (!res.ok) throw new Error(`Failed to fetch servers: ${res.status}`);
  const data = await res.json();
  return data.servers;
}

export async function fetchServerHealth(): Promise<ServerHealth> {
  const res = await fetchWithTimeout(`${API_BASE}/servers/health`);
  if (!res.ok) throw new Error(`Failed to fetch health: ${res.status}`);
  const data = await res.json();
  return data.health;
}

export async function fetchServerMetrics(): Promise<ServerMetrics> {
  const res = await fetchWithTimeout(`${API_BASE}/servers/metrics`);
  if (!res.ok) throw new Error(`Failed to fetch metrics: ${res.status}`);
  const data = await res.json();
  return data.metrics;
}

export async function pauseServer(serverName: string): Promise<void> {
  const res = await fetchWithTimeout(`${API_BASE}/servers/${serverName}/pause`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to pause: ${res.status}`);
}

export async function resumeServer(serverName: string): Promise<void> {
  const res = await fetchWithTimeout(`${API_BASE}/servers/${serverName}/resume`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to resume: ${res.status}`);
}

export async function restartServer(serverName: string): Promise<void> {
  const res = await fetchWithTimeout(`${API_BASE}/servers/${serverName}/restart`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to restart: ${res.status}`);
}

export async function stopServer(serverName: string): Promise<void> {
  const res = await fetchWithTimeout(`${API_BASE}/servers/${serverName}/stop`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to stop: ${res.status}`);
}

export async function callManagerTool(
  toolName: string,
  args: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const res = await fetchWithTimeout(`${API_BASE}/tools/call`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool_name: toolName, arguments: args }),
  });
  if (!res.ok) throw new Error(`Manager tool call failed: ${res.status}`);
  const data = await res.json();
  if (data.error) return data;
  try {
    return JSON.parse(data.result);
  } catch {
    return data;
  }
}

// ── Orphan Tools API ────────────────────────────────────────────────────────

export interface OrphanTool {
  name: string
  server: string
  description: string
  input_schema: Record<string, unknown>
  reachability: {
    llm_path: boolean
    frontend_path: boolean
    pipeline_path: boolean
  }
  paths: number
}

export interface OrphanToolsResponse {
  orphans: OrphanTool[]
  fragile: OrphanTool[]
  robust: OrphanTool[]
  summary: {
    total_tools: number
    orphan_count: number
    fragile_count: number
    robust_count: number
  }
}

export async function fetchOrphanTools(): Promise<OrphanToolsResponse> {
  const res = await fetchWithTimeout(`${API_BASE}/tools/orphans`)
  if (!res.ok) throw new Error(`Failed to fetch orphan tools: ${res.status}`)
  return res.json()
}
