// Pure functions and types for structural analysis state restoration.
// Extracted from page.tsx to keep the main component at a manageable size.
// No React dependencies — all functions are pure data transforms.

import type { StructuralMetrics, DemolitionRound } from "@/components/mechanical-summary";

// ── Structural data types ────────────────────────────────────────────────────

export interface FrameNode { id: number; x: number; y: number; z?: number; }
export interface FrameElement { id: number; node_i: number; node_j: number; E?: number; A?: number; I?: number; Iy?: number; Iz?: number; J?: number; }
export interface FrameLoad { node_id: number; Fx: number; Fy: number; Fz?: number; }
export interface FrameSupport { node_id: number; type: string; }
export interface FrameStructure { nodes: FrameNode[]; elements: FrameElement[]; loads: FrameLoad[]; supports: FrameSupport[]; }
export interface NodeDisp { node_id: number; ux: number; uy: number; }

// ── Chat message types ───────────────────────────────────────────────────────

export interface StepEvent {
  type: string;
  name?: string;
  arguments?: Record<string, unknown>;
  result?: unknown;
  content?: string;
  pipeline?: string;
  total_steps?: number;
  progress?: number;
  phase?: string;
  timeline_steps?: unknown[];
  error?: string;
  tool?: string;
  step_index?: number;
  step_count?: number;
  data?: { result?: string; [key: string]: unknown };
  strategy?: string;
}

export interface ChatMessage {
  role: "user" | "ai";
  content: string;
  steps?: StepEvent[];
}

// ── Analysis tools set ───────────────────────────────────────────────────────

export const ANALYSIS_TOOLS = new Set(["analyze_frame", "pynite_analysis", "fapp_analysis", "high_fidelity_analysis"]);

// ── Axial force extraction ───────────────────────────────────────────────────

export function extractMaxAxialForce(elemForces: Record<string, unknown>[] | undefined): { elementId: number; absMaxAxial: number } | null {
  if (!elemForces || elemForces.length === 0) return null;
  let maxForce = 0;
  let bestId = 0;
  for (const ef of elemForces) {
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

// ── Analysis result extraction by round ──────────────────────────────────────

export function extractRoundAnalysisResults(messages: ChatMessage[]): Record<number, Record<string, unknown>> {
  const results: Record<number, Record<string, unknown>> = {};
  let currentRound = -1;

  for (const msg of messages) {
    if (msg.role !== "ai" || !msg.steps) continue;
    for (const step of msg.steps) {
      if (step.type !== "tool_result" || !step.name) continue;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let parsed: any;
      try {
        parsed = typeof step.result === "string" ? JSON.parse(step.result) : step.result;
      } catch { continue; }
      if (!parsed) continue;

      if (step.name === "apply_demolition_action") {
        const fe = parsed.failed_elements;
        if (fe && Array.isArray(fe) && fe.length > 0) {
          currentRound++;
        }
      } else if (step.name === "analyze_frame") {
        if (parsed.max_displacement !== undefined && !("error" in parsed)) {
          results[currentRound] = parsed;
        }
      }
    }
  }
  return results;
}

// ── Demolition round timeline ────────────────────────────────────────────────

export function extractDemolitionRounds(messages: ChatMessage[]): DemolitionRound[] {
  const rounds: DemolitionRound[] = [];
  const cumulative = new Set<number>();
  for (const msg of messages) {
    if (msg.role !== "ai" || !msg.steps) continue;
    for (const step of msg.steps) {
      if (step.type !== "tool_result" || step.name !== "apply_demolition_action") continue;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let parsed: any;
      try {
        parsed = typeof step.result === "string" ? JSON.parse(step.result) : step.result;
      } catch { continue; }
      if (!parsed?.failed_elements?.length) continue;
      for (const id of (parsed.failed_elements as number[])) cumulative.add(id);
      rounds.push({
        round: rounds.length,
        elementIds: [...parsed.failed_elements as number[]],
        cumulativeIds: Array.from(cumulative),
      });
    }
  }
  return rounds;
}

// ── Full state restoration from conversation ─────────────────────────────────

export interface RestoredState {
  frameStructure: FrameStructure | null;
  analysisResult: Record<string, unknown> | null;
  nodeDisplacements: NodeDisp[] | null;
  structuralMetrics: StructuralMetrics | null;
  failedElements: number[];
  demolishReady: boolean;
}

export function restoreStateFromMessages(msgs: ChatMessage[]): RestoredState {
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
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let parsed: any;
      try {
        parsed = typeof step.result === "string" ? JSON.parse(step.result) : step.result;
      } catch { continue; }
      if (!parsed) continue;

      if (step.name === "generate_simple_frame" || step.name === "generate_frame" || step.name === "generate_from_text") {
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
