"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { Settings2, Maximize2, Minimize2 } from "lucide-react";

export type EffectKey = 'cascade' | 'explosion' | 'dust' | 'shake' | 'buckling' | 'fracture' | 'flash' | 'trail' | 'bounce';

interface DebrisParticle {
  x: number; y: number;
  vx: number; vy: number;
  size: number; color: string;
  baseOpacity: number;
  rotation: number; rotSpeed: number;
  groundY: number;
  delay: number; lifetime: number;
  didBounce: boolean;
}

interface DustCloud {
  cx: number; cy: number;
  maxR: number; delay: number;
}
interface ImpactRing {
  cx: number; cy: number;
  maxR: number; delay: number;
  duration: number;
}

export const EFFECT_DEFS: { key: EffectKey; label: string; desc: string; score: number; color: string }[] = [
  { key: 'cascade',  label: 'Cascade',  desc: '由下至上逐层倒塌', score: 25, color: '#22c55e' },
  { key: 'explosion',label: 'Debris',   desc: '爆炸碎片飞散',     score: 15, color: '#f97316' },
  { key: 'dust',     label: 'Dust',     desc: '底部烟尘扩散',     score: 10, color: '#94a3b8' },
  { key: 'shake',    label: 'Shake',    desc: '撞击视口抖动',     score: 10, color: '#eab308' },
  { key: 'buckling', label: 'Buckling', desc: '梁中部弯折',       score: 15, color: '#22d3ee' },
  { key: 'fracture', label: 'Fracture', desc: '长杆断裂多段',     score: 10, color: '#a855f7' },
  { key: 'flash',    label: 'Flash',    desc: '失效前红色闪烁',   score:  5, color: '#ef4444' },
  { key: 'trail',    label: 'Trail',    desc: '碎片尾迹',         score:  5, color: '#78716c' },
  { key: 'bounce',   label: 'Bounce',   desc: '碎片撞击回弹',     score:  5, color: '#3b82f6' },
];

interface FrameNode { id: number; x: number; y: number; }
interface FrameElement { id: number; node_i: number; node_j: number; E?: number; A?: number; I?: number; }
interface FrameLoad { node_id: number; Fx: number; Fy: number; }
interface FrameSupport { node_id: number; type: string; }
interface FrameStructure { nodes: FrameNode[]; elements: FrameElement[]; loads: FrameLoad[]; supports: FrameSupport[]; }

interface Props {
  structure: FrameStructure;
  failedElements: number[];
  animatingElements?: number[];
  animationTrigger?: number;
  onAnimationComplete?: () => void;
}

function seedRand(seed: number): number {
  const s = Math.sin(seed * 9301 + 49297) * 233280;
  return s - Math.floor(s);
}

export function CollapseAnimation({
  structure,
  failedElements,
  animatingElements,
  animationTrigger,
  onAnimationComplete,
}: Props) {
  const { nodes, elements, supports = [] } = structure;
  const [frame, setFrame] = useState(0);
  const rafRef = useRef<number>(0);
  const startRef = useRef<number>(0);
  const lastFrameRef = useRef<number>(0);
  const DURATION = 5000;

  const [effectsOpen, setEffectsOpen] = useState(true);
  const [effects, setEffects] = useState<Record<string, boolean>>(() => {
    const r: Record<string, boolean> = {};
    EFFECT_DEFS.forEach(d => r[d.key] = true);
    return r;
  });
  const toggleEffect = (k: EffectKey) => setEffects(p => ({ ...p, [k]: !p[k] }));
  const e = effects;

  const [animExplore, setAnimExplore] = useState(false);
  const [animScale, setAnimScale] = useState(1);
  const [animPanX, setAnimPanX] = useState(0);
  const [animPanY, setAnimPanY] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef<{active:boolean; startX:number; startY:number; panX:number; panY:number}>({active:false, startX:0, startY:0, panX:0, panY:0});
  const resetAnimExplore = () => { setAnimExplore(false); setAnimScale(1); setAnimPanX(0); setAnimPanY(0); setIsDragging(false); dragRef.current.active = false; };

  const minX = Math.min(...nodes.map(n => n.x));
  const maxX = Math.max(...nodes.map(n => n.x));
  const minY = Math.min(...nodes.map(n => n.y));
  const maxY = Math.max(...nodes.map(n => n.y));
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  const pad = 60;
  const svgW = 600;
  const svgH = 400;
  const sc = Math.min((svgW - pad*2) / rangeX, (svgH - pad*2) / rangeY);

  function toSvg(x: number, y: number) {
    return { x: pad + (x - minX) * sc, y: svgH - pad - (y - minY) * sc };
  }

  const nodeMap = new Map(nodes.map(n => [n.id, n]));
  const failedSet = useMemo(() => new Set(failedElements), [failedElements]);

  const animActiveSet = useMemo(() => {
    if (animatingElements && animatingElements.length > 0) return new Set(animatingElements);
    return failedSet;
  }, [animatingElements, failedSet]);

  const failedNodeIds = useMemo(() => {
    const ids = new Set<number>();
    for (const elem of elements) if (failedSet.has(elem.id)) { ids.add(elem.node_i); ids.add(elem.node_j); }
    return ids;
  }, [elements, failedSet]);

  const animData = useMemo(() => {
    const failedElems = elements.filter(e => animActiveSet.has(e.id));
    const withInfo = failedElems.map(el => {
      const ni = nodeMap.get(el.node_i)!;
      const nj = nodeMap.get(el.node_j)!;
      const minElemY = Math.min(ni.y, nj.y);
      const isColumn = Math.abs(ni.x - nj.x) < 0.01;
      const len = Math.hypot(nj.x - ni.x, nj.y - ni.y);
      const p1 = toSvg(ni.x, ni.y);
      const p2 = toSvg(nj.x, nj.y);
      return { id: el.id, minElemY, isColumn, len, p1, p2, ni, nj };
    });
    withInfo.sort((a, b) => a.minElemY - b.minElemY);
    const total = withInfo.length;
    const cascade = withInfo.map((e, i) => ({
      id: e.id, isColumn: e.isColumn, len: e.len,
      p1: e.p1, p2: e.p2,
      delay: total > 1 ? (i / (total - 1)) * 1500 : 0,
    }));

    const debris: DebrisParticle[] = [];
    for (const item of cascade) {
      const cx = (item.p1.x + item.p2.x) / 2;
      const cy = (item.p1.y + item.p2.y) / 2;
      const count = 6 + Math.floor(seedRand(item.id) * 5);
      for (let i = 0; i < count; i++) {
        const angle = seedRand(item.id * 100 + i * 7) * Math.PI * 2;
        const speed = 2 + seedRand(item.id * 200 + i * 13) * 5;
        const groundY = svgH - pad + 5 + seedRand(item.id * 300 + i * 23) * 20;
        debris.push({
          x: cx + (seedRand(item.id * 400 + i * 31) - 0.5) * 20,
          y: cy,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed - 3,
          size: 1.5 + seedRand(item.id * 500 + i * 37) * 3,
          color: item.isColumn ? '#ef4444' : '#f97316',
          baseOpacity: 0.6 + seedRand(item.id * 600 + i * 41) * 0.4,
          rotation: seedRand(item.id * 700 + i * 47) * 360,
          rotSpeed: (seedRand(item.id * 800 + i * 53) - 0.5) * 8,
          groundY,
          delay: item.delay + 100 + seedRand(item.id * 900 + i * 59) * 200,
          lifetime: 0.8 + seedRand(item.id * 1000 + i * 61) * 0.8,
          didBounce: false,
        });
      }
    }

    const dust: DustCloud[] = [];
    for (const item of cascade) {
      const cx = (item.p1.x + item.p2.x) / 2;
      for (let i = 0; i < 2; i++) {
        dust.push({
          cx: cx + (seedRand(item.id * 1100 + i * 67) - 0.5) * 50,
          cy: svgH - pad + 5 + seedRand(item.id * 1200 + i * 71) * 15,
          maxR: 12 + seedRand(item.id * 1300 + i * 73) * 20,
          delay: item.delay + 400 + seedRand(item.id * 1400 + i * 79) * 400,
        });
      }
    }

    const impactRings: ImpactRing[] = [];
    for (const item of cascade) {
      const cx = (item.p1.x + item.p2.x) / 2;
      impactRings.push({ cx, cy: svgH - pad + 5, maxR: 15 + seedRand(item.id * 1500) * 25, delay: item.delay + 700, duration: 600 + seedRand(item.id * 1600) * 300 });
    }

    return { cascade, debris, dust, impactRings };
  }, [elements, animActiveSet, nodeMap, minX, minY, sc, pad, svgH]);

  useEffect(() => {
    const toAnimate = animatingElements;
    if (!toAnimate || toAnimate.length === 0) return;
    startRef.current = performance.now();
    lastFrameRef.current = 0;
    const animate = (t: number) => {
      const elapsed = t - startRef.current;
      if (elapsed < DURATION) {
        if (elapsed - lastFrameRef.current >= 33) {
          setFrame(elapsed);
          lastFrameRef.current = elapsed;
        }
        rafRef.current = requestAnimationFrame(animate);
      } else {
        setFrame(DURATION);
        onAnimationComplete?.();
      }
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [animationTrigger]);

  const t = frame;
  const hasFailed = failedElements.length > 0;
  const totalProgress = Math.min(t / DURATION, 1);

  function ease(p: number): number {
    return p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
  }

  function elementLocalPos(cascadeItem: typeof animData.cascade[0], localT: number) {
    if (localT <= 0) return { x1: cascadeItem.p1.x, y1: cascadeItem.p1.y, x2: cascadeItem.p2.x, y2: cascadeItem.p2.y, fallProg: 0 };
    const fallDuration = 800;
    const fallProg = Math.min(localT / fallDuration, 1);
    const eProg = ease(fallProg);
    const fallDist = svgH * 0.6 * eProg;
    const cx = (cascadeItem.p1.x + cascadeItem.p2.x) / 2;
    const cy = (cascadeItem.p1.y + cascadeItem.p2.y) / 2;
    if (cascadeItem.isColumn) {
      const angle = eProg * 80;
      const rad = angle * Math.PI / 180;
      const dx1 = cascadeItem.p1.x - cx; const dy1 = cascadeItem.p1.y - cy;
      const dx2 = cascadeItem.p2.x - cx; const dy2 = cascadeItem.p2.y - cy;
      return {
        x1: cx + dx1 * Math.cos(rad) - dy1 * Math.sin(rad),
        y1: cy + fallDist + dx1 * Math.sin(rad) + dy1 * Math.cos(rad),
        x2: cx + dx2 * Math.cos(rad) - dy2 * Math.sin(rad),
        y2: cy + fallDist + dx2 * Math.sin(rad) + dy2 * Math.cos(rad),
        fallProg: eProg,
      };
    } else {
      const angle = eProg * 30 * ((cascadeItem.id % 2 === 0) ? 1 : -1);
      const rad = angle * Math.PI / 180;
      const dx1 = cascadeItem.p1.x - cx; const dy1 = cascadeItem.p1.y - cy;
      const dx2 = cascadeItem.p2.x - cx; const dy2 = cascadeItem.p2.y - cy;
      return {
        x1: cx + fallDist * 0.3 + dx1 * Math.cos(rad) - dy1 * Math.sin(rad),
        y1: cy + fallDist + dx1 * Math.sin(rad) + dy1 * Math.cos(rad),
        x2: cx + fallDist * 0.3 + dx2 * Math.cos(rad) - dy2 * Math.sin(rad),
        y2: cy + fallDist + dx2 * Math.sin(rad) + dy2 * Math.cos(rad),
        fallProg: eProg,
      };
    }
  }

  const shakeOn = e.shake && hasFailed;
  const firstHit = animData.cascade.length > 0 ? animData.cascade[0].delay + 600 : 0;
  const preRumble = shakeOn && hasFailed && t > 80 && t < firstHit && firstHit > 200
    ? Math.sin(t * 0.12) * 1.8 * Math.min(t / firstHit, 1) : 0;
  const shakeElapsed = Math.max(0, t - firstHit);
  const shakeIntensity = shakeOn && shakeElapsed < 1000
    ? Math.sin(shakeElapsed * 0.08) * 4 * (1 - shakeElapsed / 1000) : 0;
  const totalShake = preRumble + shakeIntensity;
  const shakeX = totalShake * Math.sin(t * 0.05 + 1);
  const shakeY = totalShake * Math.sin(t * 0.07 + 2);

  const flashWarning = e.flash && hasFailed && t > 0 && t < 800 ? Math.sin((t / 800) * Math.PI) * 0.7 : 0;
  const tensionPulse = e.flash && hasFailed && t > firstHit - 350 && t < firstHit - 50 ? Math.sin(((t - firstHit + 350) / 300) * Math.PI) * 0.3 : 0;
  const flashImpact = e.flash && hasFailed && t > firstHit - 100 && t < firstHit + 250 ? Math.sin(((t - firstHit + 100) / 350) * Math.PI) * 0.5 : 0;
  const flashOpacity = Math.max(flashWarning, tensionPulse, flashImpact);

  function buckledMidpoint(origP1: {x:number,y:number}, origP2: {x:number,y:number}, prog: number) {
    const mx = (origP1.x + origP2.x) / 2;
    const my = (origP1.y + origP2.y) / 2;
    const deflect = prog * 30;
    const normalX = -(origP2.y - origP1.y);
    const normalY = (origP2.x - origP1.x);
    const nLen = Math.hypot(normalX, normalY) || 1;
    return { bx: mx + (normalX / nLen) * deflect * 0.3, by: my + (normalY / nLen) * deflect + prog * 40 };
  }

  function fractureSegments(p1: {x:number,y:number}, p2: {x:number,y:number}, len: number, id: number) {
    const count = len > 6 ? 3 : 2;
    const segs: {x1:number,y1:number,x2:number,y2:number}[] = [];
    for (let i = 0; i < count; i++) {
      const frac1 = i / count;
      const frac2 = (i + 1) / count;
      const sx1 = p1.x + (p2.x - p1.x) * frac1;
      const sy1 = p1.y + (p2.y - p1.y) * frac1;
      const sx2 = p1.x + (p2.x - p1.x) * frac2;
      const sy2 = p1.y + (p2.y - p1.y) * frac2;
      const rOff = (seedRand(id * 1500 + i * 83) - 0.5) * 6;
      const rOff2 = (seedRand(id * 1600 + i * 89) - 0.5) * 6;
      segs.push({ x1: sx1 + rOff, y1: sy1 + rOff2, x2: sx2 + rOff2, y2: sy2 + rOff });
    }
    return segs;
  }

  const activeScore = EFFECT_DEFS.filter(d => effects[d.key]).reduce((s, d) => s + d.score, 0);

  return (
    <div className="flex-1 flex flex-col relative">
      <div className="border-b border-border shrink-0">
        <button onClick={() => setEffectsOpen(!effectsOpen)}
          className="flex items-center gap-2 px-4 py-1.5 w-full text-left text-xs font-medium text-muted-foreground hover:text-foreground transition-colors cursor-pointer">
          <Settings2 className="h-3 w-3" />Effects ({activeScore}/100)
          <span className="text-[10px] text-muted-foreground/50">{effectsOpen ? '▲' : '▼'}</span>
        </button>
        {effectsOpen && (
          <div className="px-3 pb-2.5 flex flex-wrap gap-1.5 items-center">
            <button onClick={() => {
              const all = EFFECT_DEFS.some(d => !effects[d.key]);
              const v: Record<string, boolean> = {};
              EFFECT_DEFS.forEach(d => v[d.key] = all);
              setEffects(v);
            }}
              className="px-2 py-1 text-[10px] rounded border border-border text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors cursor-pointer">
              {EFFECT_DEFS.every(d => effects[d.key]) ? '全部禁用' : '全部启用'}
            </button>
            {EFFECT_DEFS.map(def => {
              const on = effects[def.key];
              return (
                <button key={def.key} onClick={() => toggleEffect(def.key)}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-medium border transition-all cursor-pointer ${on ? 'bg-primary/15 border-primary/40 text-primary' : 'border-border/60 text-muted-foreground/50 hover:text-muted-foreground'}`}
                  title={`${def.label}: ${def.desc} (${def.score}分)`}>
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: def.color, opacity: on ? 1 : 0.3 }} />{def.label}
                  <span className={`text-[8px] ${on ? 'text-primary/60' : 'text-muted-foreground/30'}`}>{def.score}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="flex-1 flex items-center justify-center p-4 relative" onMouseLeave={resetAnimExplore}>
        <button onClick={() => { if (animExplore) resetAnimExplore(); else setAnimExplore(true); }}
          className={`absolute top-3 right-3 z-10 p-1.5 rounded-md border transition-all cursor-pointer ${animExplore ? 'bg-primary/20 border-primary text-primary' : 'bg-background/80 border-border text-muted-foreground hover:text-foreground hover:border-primary/50'}`}
          title={animExplore ? 'Exit explore mode' : 'Explore mode: zoom & pan'}>
          {animExplore ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
        </button>
        {animExplore && (
          <div className="absolute top-12 right-3 z-10 bg-background/90 border border-border rounded-md px-2 py-1 text-[10px] text-muted-foreground">Scroll to zoom · Drag to pan</div>
        )}

        <svg viewBox={`0 0 ${svgW} ${svgH}`} className="w-full h-full"
          style={{ cursor: animExplore ? (isDragging ? 'grabbing' : 'grab') : 'default' }}
          onWheel={e => { if (!animExplore) return; e.preventDefault(); setAnimScale(p => Math.min(5, Math.max(0.5, p * (e.deltaY > 0 ? 0.9 : 1.1)))); }}
          onMouseDown={e => { if (!animExplore || e.button !== 0) return; setIsDragging(true); dragRef.current = { active: true, startX: e.clientX, startY: e.clientY, panX: animPanX, panY: animPanY }; }}
          onMouseMove={e => { if (!animExplore || !dragRef.current.active) return; setAnimPanX(dragRef.current.panX + e.clientX - dragRef.current.startX); setAnimPanY(dragRef.current.panY + e.clientY - dragRef.current.startY); }}
          onMouseUp={() => { setIsDragging(false); dragRef.current.active = false; }}>
          <g transform={`translate(${animPanX + shakeX}, ${animPanY + shakeY}) scale(${animScale})`}>
            {Array.from({ length: 6 }).map((_, i) => (
              <line key={`gh-${i}`} x1={pad} y1={pad + i * (svgH - pad*2)/5} x2={svgW-pad} y2={pad + i * (svgH - pad*2)/5} stroke="var(--border)" strokeWidth={0.5} />
            ))}
            {Array.from({ length: 8 }).map((_, i) => (
              <line key={`gv-${i}`} x1={pad + i * (svgW - pad*2)/7} y1={pad} x2={pad + i * (svgW - pad*2)/7} y2={svgH-pad} stroke="var(--border)" strokeWidth={0.5} />
            ))}
            {e.trail && hasFailed && animData.cascade.map(item => {
              const localT = t - item.delay;
              if (localT < 50 || localT > 2000) return null;
              return [40, 80, 130].map((offset, idx) => {
                const past = elementLocalPos(item, localT - offset);
                if (localT - offset <= 0) return null;
                const trailOpacity = (1 - idx * 0.3) * (1 - Math.min(localT / 2000, 1) * 0.5);
                return (
                  <g key={`trail-${item.id}-${idx}`}>
                    <circle cx={(past.x1 + past.x2) / 2} cy={(past.y1 + past.y2) / 2} r={2.5 - idx * 0.5} fill="#78716c" opacity={trailOpacity * 0.4} />
                    <circle cx={(past.x1 + past.x2) / 2 + (idx-1)*3} cy={(past.y1 + past.y2) / 2 + 3} r={2 - idx * 0.3} fill="#78716c" opacity={trailOpacity * 0.25} />
                  </g>
                );
              });
            })}
            {supports.map(sup => {
              const n = nodeMap.get(sup.node_id)!;
              const p = toSvg(n.x, n.y);
              const ts = 10;
              if (sup.type === "fixed") {
                return (
                  <g key={`sup-${sup.node_id}`}>
                    <line x1={p.x-ts} y1={p.y} x2={p.x+ts} y2={p.y} stroke="#94a3b8" strokeWidth={2} />
                    {[-ts, 0, ts].map(dx => <line key={dx} x1={p.x+dx} y1={p.y} x2={p.x+dx+5} y2={p.y+8} stroke="#94a3b8" strokeWidth={1.5} />)}
                  </g>
                );
              }
              if (sup.type === "hinged") {
                return (
                  <g key={`sup-${sup.node_id}`}>
                    <line x1={p.x-ts} y1={p.y} x2={p.x+ts} y2={p.y} stroke="#94a3b8" strokeWidth={2} />
                    <circle cx={p.x} cy={p.y} r={4} fill="none" stroke="#94a3b8" strokeWidth={1.5} />
                    {[-ts, ts].map(dx => <line key={dx} x1={p.x+dx} y1={p.y} x2={p.x+dx+5} y2={p.y+8} stroke="#94a3b8" strokeWidth={1.5} />)}
                  </g>
                );
              }
              return null;
            })}
            {elements.map(elem => {
              if (failedSet.has(elem.id)) return null;
              const ni = nodeMap.get(elem.node_i)!;
              const nj = nodeMap.get(elem.node_j)!;
              const p = toSvg(ni.x, ni.y);
              const pj = toSvg(nj.x, nj.y);
              const isCol = Math.abs(ni.x - nj.x) < 0.01;
              const op = hasFailed ? 0.5 + 0.5 * (1 - totalProgress * 0.3) : 1;
              return <line key={elem.id} x1={p.x} y1={p.y} x2={pj.x} y2={pj.y} stroke="#22d3ee" strokeWidth={isCol ? 3 : 2} opacity={op} />;
            })}
            {nodes.map(n => {
              if (failedNodeIds.has(n.id) && hasFailed) return null;
              const p = toSvg(n.x, n.y);
              const isTop = n.y === maxY;
              return <circle key={`node-${n.id}`} cx={p.x} cy={p.y} r={isTop ? 4.5 : 3.5} fill={n.y === 0 ? '#64748b' : '#0f172a'} stroke={isTop ? '#f59e0b' : '#22d3ee'} strokeWidth={1.5} opacity={hasFailed ? 0.5 + 0.5 * (1 - totalProgress * 0.3) : 1} />;
            })}
            {hasFailed && e.cascade ? (
              animData.cascade.map(item => {
                const localT = t - item.delay;
                const globalFlashed = e.flash && t < 500 && t > 0;
                const flashing = globalFlashed || (e.flash && localT >= -200 && localT < 50);
                const falling = localT > 0;
                if (!falling) {
                  return (
                    <line key={item.id} x1={item.p1.x} y1={item.p1.y} x2={item.p2.x} y2={item.p2.y}
                      stroke={flashing ? '#ef4444' : '#ef4444'} strokeWidth={item.isColumn ? 3 : 2}
                      strokeDasharray="6 2" opacity={flashing ? 0.3 + 0.7 * Math.sin(t * 0.02) : 0.6} />
                  );
                }
                const pos = elementLocalPos(item, localT);
                const fallProg = pos.fallProg;
                const fade = 1 - fallProg * 0.4;
                const shouldFracture = e.fracture && !item.isColumn && item.len > 3;
                const shouldBuckle = e.buckling && !item.isColumn && !shouldFracture;
                if (shouldFracture) {
                  const segs = fractureSegments(item.p1, item.p2, item.len, item.id);
                  return (
                    <g key={item.id}>
                      {segs.map((seg, si) => {
                        const segLocalT = localT + si * 60;
                        const segProg = Math.min(segLocalT / 1000, 1);
                        const segEased = ease(segProg);
                        const segFallDist = svgH * 0.5 * segEased;
                        const segAngle2 = segEased * 25 * (si % 2 === 0 ? 1 : -1);
                        const sRad2 = segAngle2 * Math.PI / 180;
                        const scx2 = (seg.x1 + seg.x2) / 2;
                        const scy2 = (seg.y1 + seg.y2) / 2;
                        const sdx1 = seg.x1 - scx2; const sdy1 = seg.y1 - scy2;
                        const sdx2 = seg.x2 - scx2; const sdy2 = seg.y2 - scy2;
                        return (
                          <line key={`${item.id}-f${si}`}
                            x1={scx2 + sdx1*Math.cos(sRad2) - sdy1*Math.sin(sRad2)}
                            y1={scy2 + segFallDist + sdx1*Math.sin(sRad2) + sdy1*Math.cos(sRad2)}
                            x2={scx2 + sdx2*Math.cos(sRad2) - sdy2*Math.sin(sRad2)}
                            y2={scy2 + segFallDist + sdx2*Math.sin(sRad2) + sdy2*Math.cos(sRad2)}
                            stroke={si === 0 ? '#ef4444' : '#f87171'} strokeWidth={2} strokeDasharray="4 2" opacity={1 - segProg * 0.5} />
                        );
                      })}
                    </g>
                  );
                }
                if (shouldBuckle) {
                  const bm = buckledMidpoint({x:pos.x1,y:pos.y1}, {x:pos.x2,y:pos.y2}, fallProg);
                  return <polyline key={item.id} points={`${pos.x1},${pos.y1} ${bm.bx},${bm.by} ${pos.x2},${pos.y2}`} fill="none" stroke="#ef4444" strokeWidth={2} strokeDasharray="6 2" opacity={fade} />;
                }
                return <line key={item.id} x1={pos.x1} y1={pos.y1} x2={pos.x2} y2={pos.y2} stroke="#ef4444" strokeWidth={item.isColumn ? 3 : 2} strokeDasharray="6 2" opacity={fade} />;
              })
            ) : hasFailed ? (
              animData.cascade.map(item => {
                const pos = elementLocalPos(item, t);
                const fallProg = pos.fallProg;
                const fade = 1 - fallProg * 0.4;
                const shouldFracture = e.fracture && !item.isColumn && item.len > 3;
                const shouldBuckle = e.buckling && !item.isColumn && !shouldFracture;
                if (shouldFracture) {
                  const segs = fractureSegments(item.p1, item.p2, item.len, item.id);
                  return (
                    <g key={item.id}>
                      {segs.map((seg, si) => {
                        const segT = t + si * 60;
                        const segP = Math.min(segT / 1000, 1);
                        const segE = ease(segP);
                        const segFD = svgH * 0.5 * segE;
                        const segA = segE * 25 * (si % 2 === 0 ? 1 : -1);
                        const sR = segA * Math.PI / 180;
                        const sCx = (seg.x1 + seg.x2) / 2;
                        const sCy = (seg.y1 + seg.y2) / 2;
                        const sdx1 = seg.x1 - sCx; const sdy1 = seg.y1 - sCy;
                        const sdx2 = seg.x2 - sCx; const sdy2 = seg.y2 - sCy;
                        return (
                          <line key={`${item.id}-f${si}`}
                            x1={sCx + sdx1*Math.cos(sR) - sdy1*Math.sin(sR)}
                            y1={sCy + segFD + sdx1*Math.sin(sR) + sdy1*Math.cos(sR)}
                            x2={sCx + sdx2*Math.cos(sR) - sdy2*Math.sin(sR)}
                            y2={sCy + segFD + sdx2*Math.sin(sR) + sdy2*Math.cos(sR)}
                            stroke={si === 0 ? '#ef4444' : '#f87171'} strokeWidth={2} strokeDasharray="4 2" opacity={1 - segP * 0.5} />
                        );
                      })}
                    </g>
                  );
                }
                if (shouldBuckle) {
                  const bm = buckledMidpoint({x:pos.x1,y:pos.y1}, {x:pos.x2,y:pos.y2}, fallProg);
                  return <polyline key={item.id} points={`${pos.x1},${pos.y1} ${bm.bx},${bm.by} ${pos.x2},${pos.y2}`} fill="none" stroke="#ef4444" strokeWidth={2} strokeDasharray="6 2" opacity={fade} />;
                }
                return <line key={item.id} x1={pos.x1} y1={pos.y1} x2={pos.x2} y2={pos.y2} stroke="#ef4444" strokeWidth={item.isColumn ? 3 : 2} strokeDasharray="6 2" opacity={fade} />;
              })
            ) : null}
            {(e.shake && hasFailed) && animData.impactRings.map((ring, idx) => {
              const localT = t - ring.delay;
              if (localT < 0 || localT > ring.duration) return null;
              const prog = localT / ring.duration;
              const r = ring.maxR * ease(prog);
              const op = 0.25 * (1 - prog);
              return <circle key={`impact-${idx}`} cx={ring.cx} cy={ring.cy} r={r} fill="none" stroke="#ef4444" strokeWidth={1.5} opacity={op} />;
            })}
            {e.dust && hasFailed && animData.dust.map((cloud, idx) => {
              const localT = t - cloud.delay;
              if (localT < 0 || localT > 1500) return null;
              const prog = localT / 800;
              const r = cloud.maxR * Math.min(prog, 1);
              const op = Math.max(0, 0.25 * (1 - Math.min(prog, 1))) * Math.min(prog * 2, 1);
              return (
                <g key={`dust-${idx}`}>
                  <circle cx={cloud.cx} cy={cloud.cy} r={r} fill="#a3a3a3" opacity={op * 0.5} />
                  <circle cx={cloud.cx + r*0.3} cy={cloud.cy - r*0.2} r={r*0.6} fill="#a3a3a3" opacity={op * 0.3} />
                </g>
              );
            })}
            {e.explosion && hasFailed && animData.debris.map((p, idx) => {
              const localT = t - p.delay;
              if (localT < 0) return null;
              const age = localT / 1000;
              if (age > p.lifetime) return null;
              const x = p.x + p.vx * age * 60;
              let y = p.y + p.vy * age * 60 + 0.5 * 980 * age * age * 0.6;
              if (e.bounce) {
                if (y > p.groundY && !p.didBounce) p.didBounce = true;
                if (y > p.groundY) { const overshoot = y - p.groundY; y = p.groundY - overshoot * 0.3; p.vy = -p.vy * 0.4; p.vx *= 0.85; }
              } else {
                if (y > p.groundY) y = p.groundY;
              }
              const op = p.baseOpacity * Math.max(0, 1 - age / p.lifetime);
              return (
                <g key={`debris-${idx}`}>
                  <circle cx={x} cy={y} r={p.size} fill={p.color} opacity={op} />
                  {e.trail && <circle cx={x - p.vx * 0.5} cy={y - p.vy * 0.5} r={p.size * 0.5} fill={p.color} opacity={op * 0.3} />}
                </g>
              );
            })}
            {flashOpacity > 0 && <rect x={0} y={0} width={svgW} height={svgH} fill="#ef4444" opacity={flashOpacity * 0.15} pointerEvents="none" />}
            {elements.length > 0 && (
              <g>
                <rect x={svgW / 2 - 80} y={svgH - 48} width={160} height={6} rx={3} fill="var(--muted)" stroke="var(--border)" strokeWidth={0.5} />
                <rect x={svgW / 2 - 80} y={svgH - 48} width={Math.round(160 * (failedElements.length / elements.length))} height={6} rx={3} fill="#ef4444" opacity={hasFailed ? 0.8 : 0} />
                <text x={svgW / 2} y={svgH - 52} textAnchor="middle" fill="var(--muted-foreground)" fontSize={7}>
                  {elements.length - failedElements.length}/{elements.length} standing
                  {failedElements.length > 0 && ` · ${failedElements.length} collapsed`}
                </text>
              </g>
            )}
            <text x={svgW / 2} y={svgH - 20} textAnchor="middle" fill={hasFailed ? '#ef4444' : '#94a3b8'} fontSize={11}
              className={hasFailed ? 'animate-pulse' : ''} fontWeight="bold">
              {hasFailed && animActiveSet.size > 0 && totalProgress < 1
                ? `⚡ Demolishing: ${[...animActiveSet].map(id => `#${id}`).join(', ')} — ${(totalProgress * 100).toFixed(0)}%`
                : hasFailed && totalProgress >= 1
                ? `✖ Collapsed: ${failedElements.length} element(s) — ${(elements.length - failedElements.length)}/${elements.length} remaining`
                : hasFailed ? `✖ Collapsed: ${failedElements.length} element(s) — ${(totalProgress * 100).toFixed(0)}%`
                : 'Click a round in Demolition Targets to play the collapse animation'}
            </text>
          </g>
        </svg>
      </div>
    </div>
  );
}
