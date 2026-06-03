/**
 * Progressive collapse chain reaction animation driver.
 * Manages the propagation of collapse events with timing and visual effects.
 */

import { ParticleEffectManager } from "./particle-effects";

// ── Types ───────────────────────────────────────────────────────────────────────
export interface CollapseEvent {
  timeMs: number;
  round: number;
  type: "initial" | "propagation" | "chain_collapse";
  elementIds: number[];
  description: string;
}

export interface CollapseChain {
  events: CollapseEvent[];
  totalDurationMs: number;
}

export interface ChainAnimationState {
  currentEventIndex: number;
  elapsedMs: number;
  isPlaying: boolean;
  completedEvents: Set<number>; // round indices that have been triggered
  revealedElements: Set<number>; // all element IDs that have collapsed
}

// ── Default Effects Config ─────────────────────────────────────────────────────
export const CHAIN_EFFECTS = {
  initial: {
    flashDuration: 200,
    fallDuration: 800,
    shakeIntensity: 5,
    dustIntensity: 1.0,
  },
  propagation: {
    flashDuration: 150,
    fallDuration: 600,
    shakeIntensity: 3,
    dustIntensity: 0.7,
  },
  chain_collapse: {
    flashDuration: 100,
    fallDuration: 500,
    shakeIntensity: 2,
    dustIntensity: 0.5,
  },
};

// ── Chain Builder ───────────────────────────────────────────────────────────────

/** Parse collapse chain data from API into animation events */
export function buildCollapseChain(
  chainRounds: Record<string, unknown>[],
  baseDelayMs: number = 600
): CollapseChain {
  const events: CollapseEvent[] = [];
  let currentTime = 0;

  for (const round of chainRounds) {
    const roundNum = (round.round as number) ?? 0;
    const newRemovals = (round.new_removals as number[]) ?? [];
    const type = (round.type as CollapseEvent["type"]) ?? "propagation";

    if (roundNum > 0) {
      currentTime += baseDelayMs;
    }

    events.push({
      timeMs: currentTime,
      round: roundNum,
      type,
      elementIds: newRemovals,
      description: (round.description as string) ?? "",
    });
  }

  return {
    events,
    totalDurationMs: events.length > 0
      ? events[events.length - 1].timeMs + 2000
      : 0,
  };
}

/** Create a simple chain from demolition rounds (for integration with existing system) */
export function createChainFromRounds(
  demolitionRounds: { round: number; elementIds: number[] }[]
): CollapseChain {
  const events: CollapseEvent[] = [];

  for (const r of demolitionRounds) {
    events.push({
      timeMs: r.round * 600,
      round: r.round,
      type: r.round === 0 ? "initial" : "chain_collapse",
      elementIds: r.elementIds,
      description: `Round ${r.round}: ${r.elementIds.length} element(s)`,
    });
  }

  return {
    events,
    totalDurationMs: events.length * 600 + 2000,
  };
}

// ── State Management ────────────────────────────────────────────────────────────

export function createChainState(): ChainAnimationState {
  return {
    currentEventIndex: 0,
    elapsedMs: 0,
    isPlaying: false,
    completedEvents: new Set(),
    revealedElements: new Set(),
  };
}

/** Advance the chain animation by dtMs and return newly triggered events */
export function advanceChain(
  state: ChainAnimationState,
  chain: CollapseChain,
  dtMs: number
): CollapseEvent[] {
  if (!state.isPlaying) return [];

  state.elapsedMs += dtMs;
  const triggered: CollapseEvent[] = [];

  while (
    state.currentEventIndex < chain.events.length &&
    chain.events[state.currentEventIndex].timeMs <= state.elapsedMs
  ) {
    const event = chain.events[state.currentEventIndex];
    if (!state.completedEvents.has(state.currentEventIndex)) {
      state.completedEvents.add(state.currentEventIndex);
      for (const eid of event.elementIds) {
        state.revealedElements.add(eid);
      }
      triggered.push(event);
    }
    state.currentEventIndex++;
  }

  // Check if animation is complete
  if (state.currentEventIndex >= chain.events.length) {
    state.isPlaying = false;
  }

  return triggered;
}

// ── SVG Rendering Helpers ──────────────────────────────────────────────────────

/** Get the visual effect parameters for a given event type */
export function getEffectParams(eventType: CollapseEvent["type"]) {
  return CHAIN_EFFECTS[eventType] ?? CHAIN_EFFECTS.chain_collapse;
}

/** Update particle effects for chain reaction events */
export function applyChainParticles(
  event: CollapseEvent,
  structure: { nodes: { id: number; x: number; y: number }[]; elements: { id: number; node_i: number; node_j: number }[] } | null,
  particleManager: ParticleEffectManager
) {
  if (!structure) return;

  const nodeMap = new Map(structure.nodes.map(n => [n.id, { x: n.x, y: n.y, z: 0 }]));

  for (const eid of event.elementIds) {
    const el = structure.elements.find(e => e.id === eid);
    if (!el) continue;

    const ni = nodeMap.get(el.node_i);
    const nj = nodeMap.get(el.node_j);
    if (!ni || !nj) continue;

    const cx = (ni.x + nj.x) / 2;
    const cy = (ni.y + nj.y) / 2;
    const cz = ((ni.z ?? 0) + (nj.z ?? 0)) / 2;
    const length = Math.sqrt(
      (nj.x - ni.x) ** 2 + (nj.y - ni.y) ** 2 + ((nj.z ?? 0) - (ni.z ?? 0)) ** 2
    );

    particleManager.createFracture(`chain_${event.round}_${eid}`, {
      elementId: eid,
      x: cx, y: cy, z: cz,
      width: 0.3,
      height: 0.3,
      depth: Math.max(length, 0.5),
      material: "concrete",
    });
  }
}
