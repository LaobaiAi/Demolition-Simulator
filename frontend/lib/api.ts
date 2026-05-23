const API_BASE = "http://localhost:8000";

export interface Tool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  server: string;
}

export async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

export async function fetchTools(): Promise<Tool[]> {
  const res = await fetch(`${API_BASE}/tools`);
  if (!res.ok) throw new Error(`Failed to fetch tools: ${res.status}`);
  const data = await res.json();
  return data.tools;
}

export async function callTool(
  toolName: string,
  arguments_: Record<string, unknown>
): Promise<{ result: string; error?: string }> {
  const res = await fetch(`${API_BASE}/tools/call`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool_name: toolName, arguments: arguments_ }),
  });
  if (!res.ok) throw new Error(`Tool call failed: ${res.status}`);
  return res.json();
}

export function createChatWebSocket(): WebSocket {
  return new WebSocket("ws://localhost:8000/ws/chat");
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
  const res = await fetch(`${API_BASE}/verify`, {
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
  solver_count: number;
  deviations: Record<string, {
    displacement_diff_pct: number;
    axial_diff_pct: number;
    is_outlier: boolean;
  }>;
}

export async function verifyMulti(
  fastResult: Record<string, unknown>,
  structure: Record<string, unknown>
): Promise<MultiSolverResult> {
  const res = await fetch(`${API_BASE}/verify/multi`, {
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
}

export async function saveLLMSettings(config: LLMConfig): Promise<void> {
  const res = await fetch(`${API_BASE}/settings/llm`, {
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
}> {
  const res = await fetch(`${API_BASE}/settings/llm`);
  if (!res.ok) throw new Error(`Failed to get config: ${res.status}`);
  return res.json();
}
