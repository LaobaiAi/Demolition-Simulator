import { describe, it, expect } from "vitest";
import {
  extractMaxAxialForce,
  extractRoundAnalysisResults,
  extractDemolitionRounds,
  restoreStateFromMessages,
  type ChatMessage,
} from "@/lib/state-restore";

describe("extractMaxAxialForce", () => {
  it("returns null for undefined input", () => {
    expect(extractMaxAxialForce(undefined)).toBeNull();
  });

  it("returns null for empty array", () => {
    expect(extractMaxAxialForce([])).toBeNull();
  });

  it("finds the element with highest absolute axial force (Nmax/Nmin)", () => {
    const forces = [
      { element_id: 1, Nmax: 5000, Nmin: -3000 },
      { element_id: 2, Nmax: 2000, Nmin: -12000 },
      { element_id: 3, Nmax: 8000, Nmin: 0 },
    ];
    const result = extractMaxAxialForce(forces);
    expect(result).not.toBeNull();
    expect(result!.elementId).toBe(2);
    expect(result!.absMaxAxial).toBe(12000);
  });

  it("falls back to N field when Nmax/Nmin are zero", () => {
    const forces = [
      { element_id: 1, Nmax: 0, Nmin: 0, N: 5000 },
    ];
    const result = extractMaxAxialForce(forces);
    expect(result).not.toBeNull();
    expect(result!.elementId).toBe(1);
    expect(result!.absMaxAxial).toBe(5000);
  });

  it("uses elem_id as fallback for element_id", () => {
    const forces = [
      { elem_id: 5, Nmax: 3000, Nmin: -1000 },
    ];
    const result = extractMaxAxialForce(forces);
    expect(result!.elementId).toBe(5);
  });
});

describe("extractRoundAnalysisResults", () => {
  it("extracts analysis results per demolition round", () => {
    const messages: ChatMessage[] = [
      {
        role: "ai",
        content: "analyzing",
        steps: [
          { type: "tool_result", name: "analyze_frame", result: JSON.stringify({ max_displacement: 5.2, max_axial_force: 45000 }) },
        ],
      },
      {
        role: "ai",
        content: "demolishing",
        steps: [
          { type: "tool_result", name: "apply_demolition_action", result: JSON.stringify({ failed_elements: [3] }) },
          { type: "tool_result", name: "analyze_frame", result: JSON.stringify({ max_displacement: 12.8, max_axial_force: 38000 }) },
        ],
      },
    ];
    const results = extractRoundAnalysisResults(messages);
    expect(results[-1]).toBeDefined();
    expect(results[-1].max_displacement).toBe(5.2);
    expect(results[0].max_displacement).toBe(12.8);
  });

  it("skips analysis results with errors", () => {
    const messages: ChatMessage[] = [
      {
        role: "ai",
        content: "error",
        steps: [
          { type: "tool_result", name: "analyze_frame", result: JSON.stringify({ error: "convergence failed" }) },
        ],
      },
    ];
    const results = extractRoundAnalysisResults(messages);
    expect(results[-1]).toBeUndefined();
  });
});

describe("extractDemolitionRounds", () => {
  it("builds cumulative round data from messages", () => {
    const messages: ChatMessage[] = [
      {
        role: "ai",
        content: "r1",
        steps: [
          { type: "tool_result", name: "apply_demolition_action", result: JSON.stringify({ failed_elements: [1, 2] }) },
        ],
      },
      {
        role: "ai",
        content: "r2",
        steps: [
          { type: "tool_result", name: "apply_demolition_action", result: JSON.stringify({ failed_elements: [3] }) },
        ],
      },
    ];
    const rounds = extractDemolitionRounds(messages);
    expect(rounds).toHaveLength(2);
    expect(rounds[0].round).toBe(0);
    expect(rounds[0].elementIds).toEqual([1, 2]);
    expect(rounds[0].cumulativeIds).toEqual([1, 2]);
    expect(rounds[1].round).toBe(1);
    expect(rounds[1].elementIds).toEqual([3]);
    expect(rounds[1].cumulativeIds).toEqual([1, 2, 3]);
  });

  it("returns empty array for no demolition actions", () => {
    expect(extractDemolitionRounds([])).toEqual([]);
  });
});

describe("restoreStateFromMessages", () => {
  it("restores full state from a complete workflow", () => {
    const messages: ChatMessage[] = [
      {
        role: "ai",
        content: "frame",
        steps: [
          {
            type: "tool_result",
            name: "generate_frame",
            result: JSON.stringify({
              nodes: [{ id: 1, x: 0, y: 0 }],
              elements: [{ id: 1, node_i: 1, node_j: 2 }],
              loads: [{ node_id: 2, Fx: 0, Fy: -10000 }],
              supports: [{ node_id: 1, type: "fixed" }],
            }),
          },
        ],
      },
      {
        role: "ai",
        content: "analysis",
        steps: [
          {
            type: "tool_result",
            name: "analyze_frame",
            result: JSON.stringify({
              max_displacement: 3.5,
              max_axial_force: 55000,
              node_displacements: [{ node_id: 2, ux: 0.001, uy: 0.0035 }],
              element_forces: [{ element_id: 1, Nmax: 55000, Nmin: 0 }],
            }),
          },
        ],
      },
      {
        role: "ai",
        content: "critical",
        steps: [
          {
            type: "tool_result",
            name: "select_critical_element",
            result: JSON.stringify({
              critical_element_id: 1,
              critical_axial_force_N: 55000,
              column_count: 4,
            }),
          },
        ],
      },
      {
        role: "ai",
        content: "demolish",
        steps: [
          {
            type: "tool_result",
            name: "apply_demolition_action",
            result: JSON.stringify({ failed_elements: [1] }),
          },
        ],
      },
    ];

    const state = restoreStateFromMessages(messages);
    expect(state.frameStructure).not.toBeNull();
    expect(state.frameStructure!.nodes).toHaveLength(1);
    expect(state.analysisResult).not.toBeNull();
    expect(state.analysisResult!.max_displacement).toBe(3.5);
    expect(state.structuralMetrics).not.toBeNull();
    expect(state.structuralMetrics!.criticalElementId).toBe(1);
    expect(state.structuralMetrics!.columnCount).toBe(4);
    expect(state.failedElements).toEqual([1]);
    expect(state.demolishReady).toBe(true);
  });

  it("returns empty defaults for no messages", () => {
    const state = restoreStateFromMessages([]);
    expect(state.frameStructure).toBeNull();
    expect(state.analysisResult).toBeNull();
    expect(state.structuralMetrics).toBeNull();
    expect(state.failedElements).toEqual([]);
    expect(state.demolishReady).toBe(false);
  });
});
