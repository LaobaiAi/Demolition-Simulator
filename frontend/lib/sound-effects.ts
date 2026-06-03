/**
 * Procedural sound effects using Web Audio API.
 * No external dependencies — synthesizes all sounds at runtime.
 */

let audioCtx: AudioContext | null = null;
const activeNodes: Set<AudioScheduledSourceNode | OscillatorNode> = new Set();

function getAudioContext(): AudioContext | null {
  if (audioCtx) return audioCtx;
  try {
    audioCtx = new AudioContext();
    return audioCtx;
  } catch {
    return null;
  }
}

function safeConnect(
  source: AudioNode,
  dest: AudioNode
): void {
  try {
    source.connect(dest);
  } catch {
    // AudioContext may be closed or in an invalid state
  }
}

function safeDisconnect(node: AudioNode): void {
  try {
    node.disconnect();
  } catch {
    // ignore
  }
}

function createGain(ctx: AudioContext, value: number, rampTarget?: number, rampTime?: number): GainNode {
  const g = ctx.createGain();
  g.gain.setValueAtTime(value, ctx.currentTime);
  if (rampTarget !== undefined && rampTime !== undefined) {
    g.gain.exponentialRampToValueAtTime(Math.max(rampTarget, 0.0001), ctx.currentTime + rampTime);
  }
  return g;
}

function createNoiseBuffer(ctx: AudioContext, duration: number): AudioBuffer {
  const sampleRate = ctx.sampleRate;
  const length = Math.max(1, Math.floor(sampleRate * duration));
  const buffer = ctx.createBuffer(1, length, sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < length; i++) {
    data[i] = Math.random() * 2 - 1;
  }
  return buffer;
}

function trackNode(node: AudioScheduledSourceNode | OscillatorNode): void {
  activeNodes.add(node);
  node.onended = () => {
    activeNodes.delete(node);
    safeDisconnect(node);
  };
}

export function playCollapseSound(
  type: "steel" | "concrete",
  intensity: number = 1
): void {
  const ctx = getAudioContext();
  if (!ctx) return;

  const clampedIntensity = Math.max(0, Math.min(1, intensity));
  const duration = 0.3 + clampedIntensity * 0.5;

  if (type === "steel") {
    const osc = ctx.createOscillator();
    osc.type = "sawtooth";
    osc.frequency.setValueAtTime(200, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(50, ctx.currentTime + duration);

    const gain = createGain(ctx, 0.3 * clampedIntensity, 0.001, duration);
    const filter = ctx.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.setValueAtTime(800, ctx.currentTime);

    safeConnect(osc, filter);
    safeConnect(filter, gain);
    safeConnect(gain, ctx.destination);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + duration + 0.05);
    trackNode(osc);
  } else {
    const noise = ctx.createBufferSource();
    noise.buffer = createNoiseBuffer(ctx, duration + 0.1);

    const gain = createGain(ctx, 0.4 * clampedIntensity, 0.001, duration);
    const filter = ctx.createBiquadFilter();
    filter.type = "bandpass";
    filter.frequency.setValueAtTime(2500 + clampedIntensity * 1500, ctx.currentTime);
    filter.Q.setValueAtTime(1.5, ctx.currentTime);

    safeConnect(noise, filter);
    safeConnect(filter, gain);
    safeConnect(gain, ctx.destination);
    noise.start(ctx.currentTime);
    noise.stop(ctx.currentTime + duration + 0.1);
    trackNode(noise);
  }
}

export function playImpactSound(velocity: number): void {
  const ctx = getAudioContext();
  if (!ctx) return;

  const vol = Math.min(1, Math.max(0.05, Math.abs(velocity) / 15));
  const duration = 0.05 + vol * 0.15;

  const osc = ctx.createOscillator();
  osc.type = "sine";
  osc.frequency.setValueAtTime(120 + vol * 180, ctx.currentTime);
  osc.frequency.exponentialRampToValueAtTime(40, ctx.currentTime + duration);

  const gain = createGain(ctx, vol * 0.5, 0.001, duration);
  safeConnect(osc, gain);
  safeConnect(gain, ctx.destination);
  osc.start(ctx.currentTime);
  osc.stop(ctx.currentTime + duration + 0.05);
  trackNode(osc);
}

export function playCrackSound(): void {
  const ctx = getAudioContext();
  if (!ctx) return;

  const duration = 0.08;

  const noise = ctx.createBufferSource();
  noise.buffer = createNoiseBuffer(ctx, duration + 0.02);

  const gain = createGain(ctx, 0.6, 0.001, duration);
  const filter = ctx.createBiquadFilter();
  filter.type = "highpass";
  filter.frequency.setValueAtTime(3000, ctx.currentTime);

  safeConnect(noise, filter);
  safeConnect(filter, gain);
  safeConnect(gain, ctx.destination);
  noise.start(ctx.currentTime);
  noise.stop(ctx.currentTime + duration + 0.02);
  trackNode(noise);
}

export function playRumbleSound(
  intensity: number = 1,
  duration: number = 2
): void {
  const ctx = getAudioContext();
  if (!ctx) return;

  const clampedIntensity = Math.max(0, Math.min(1, intensity));

  const osc = ctx.createOscillator();
  osc.type = "sine";
  osc.frequency.setValueAtTime(30 + clampedIntensity * 30, ctx.currentTime);
  osc.frequency.linearRampToValueAtTime(15, ctx.currentTime + duration);

  const gain = createGain(ctx, 0.15 * clampedIntensity, 0.001, duration);
  safeConnect(osc, gain);
  safeConnect(gain, ctx.destination);
  osc.start(ctx.currentTime);
  osc.stop(ctx.currentTime + duration + 0.05);
  trackNode(osc);
}

export function stopAll(): void {
  for (const node of activeNodes) {
    try {
      node.stop();
    } catch {
      // already stopped
    }
    safeDisconnect(node);
  }
  activeNodes.clear();
}
