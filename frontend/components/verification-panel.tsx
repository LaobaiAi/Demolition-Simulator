"use client";

import { useState } from "react";
import {
  ShieldCheck,
  AlertTriangle,
  Loader2,
  BarChart3,
  Table2,
  TrendingUp,
  Layers,
  Zap,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { verifyAnalysis, verifyMulti, type VerificationResult, type MultiSolverResult } from "@/lib/api";
import { t, type Lang } from "@/lib/i18n";

interface VerificationPanelProps {
  fastResult: Record<string, unknown> | null;
  structure: Record<string, unknown> | null;
  lang: Lang;
  analysisSolver?: string;
}

type TabKey = "displacements" | "forces" | "comparison" | "deviation" | "multi";

function fmtDisp(v: number): string {
  return (v * 1000).toFixed(4) + " mm";
}

function fmtForce(v: number): string {
  if (Math.abs(v) >= 1000) return (v / 1000).toFixed(2) + " kN";
  return v.toFixed(1) + " N";
}

interface NodeDisp { node_id: number; ux: number; uy: number; }
interface ElemForce { element_id: number; Nmax: number; Nmin: number; Mmax: number; Mmin: number; Qmax: number; Qmin: number; }

export function VerificationPanel({ fastResult, structure, lang, analysisSolver }: VerificationPanelProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<VerificationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("displacements");
  const [multiResult, setMultiResult] = useState<MultiSolverResult | null>(null);
  const [multiLoading, setMultiLoading] = useState(false);

  const nodeDisps: NodeDisp[] = (fastResult?.node_displacements as NodeDisp[]) || [];
  const elemForces: ElemForce[] = (fastResult?.element_forces as ElemForce[]) || [];

  const handleVerify = async () => {
    if (!fastResult) return;
    setLoading(true);
    setError(null);
    setMultiResult(null);
    try {
      const res = await verifyAnalysis(fastResult, structure || undefined);
      setResult(res);
      setTab("displacements");
      setOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Verification failed");
    } finally {
      setLoading(false);
    }
  };

  const handleDeepVerify = async () => {
    if (!fastResult || !structure) return;
    setMultiLoading(true);
    try {
      const res = await verifyMulti(fastResult, structure);
      setMultiResult(res);
      setTab("multi");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Deep verification failed");
    } finally {
      setMultiLoading(false);
    }
  };

  const getChartData = () => {
    if (!result) return [];
    return [
      {
        name: "Max Displacement",
        Fast: result.comparison.max_displacement.fast,
        "High-Fidelity": result.comparison.max_displacement.high_fidelity,
      },
      {
        name: "Max Axial Force",
        Fast: result.comparison.max_axial_force.fast,
        "High-Fidelity": result.comparison.max_axial_force.high_fidelity,
      },
    ];
  };

  const getDiffData = () => {
    if (!result) return [];
    return [
      {
        name: "Max Displacement",
        "Difference %": result.comparison.max_displacement.diff_percent,
      },
      {
        name: "Max Axial Force",
        "Difference %": result.comparison.max_axial_force.diff_percent,
      },
    ];
  };

  const tabs: { key: TabKey; icon: React.ReactNode; label: string }[] = [
    { key: "displacements", icon: <Table2 className="h-3.5 w-3.5" />, label: t("verify.tab_displacements", lang) },
    { key: "forces", icon: <Table2 className="h-3.5 w-3.5" />, label: t("verify.tab_forces", lang) },
    { key: "comparison", icon: <BarChart3 className="h-3.5 w-3.5" />, label: t("verify.tab_compare", lang) },
    { key: "deviation", icon: <TrendingUp className="h-3.5 w-3.5" />, label: t("verify.tab_deviation", lang) },
    ...(multiResult ? [{ key: "multi" as TabKey, icon: <Layers className="h-3.5 w-3.5" />, label: t("verify.tab_multi", lang) }] : []),
  ];

  const hasHiFi = result?.status !== "unavailable";

  return (
    <>
      {/* Verification Button + Engine label */}
      <div className="flex flex-col items-center gap-3">
        <div className="flex items-center justify-between w-full">
          <button
            onClick={handleVerify}
            disabled={!fastResult || loading}
            className={`relative px-6 py-3 rounded-xl font-semibold text-sm transition-all duration-300 cursor-pointer
              ${
                fastResult && !loading
                  ? "bg-red-500/20 text-red-400 border border-red-500/50 glow-pulse hover:bg-red-500/30"
                  : "bg-muted text-muted-foreground border border-border cursor-not-allowed"
              }`}
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("verify.verifying", lang)}
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4" />
                {t("verify.button", lang)}
              </span>
            )}
          </button>
          {analysisSolver && (
            <span className="text-[11px] text-muted-foreground font-mono">
              {t("verify.engine", lang)}: <span className="text-cyan-400/80">{analysisSolver}</span>
            </span>
          )}
        </div>
        {fastResult && !loading && (
          <p className="text-[10px] text-muted-foreground">
            {t("verify.hint", lang)}
          </p>
        )}
        {error && (
          <p className="text-xs text-red-400">{error}</p>
        )}
      </div>

      {/* Dialog with tabs */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="!max-w-[58vw] max-h-[92vh] w-[58vw] overflow-hidden flex flex-col bg-[#0f172a] border-border text-foreground">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3 text-lg">
              {result?.status === "verified" ? (
                <>
                  <ShieldCheck className="h-6 w-6 text-emerald-400" />
                  <span className="text-emerald-400">{t("verify.verified", lang)}</span>
                </>
              ) : result?.status === "unavailable" ? (
                <>
                  <AlertTriangle className="h-6 w-6 text-muted-foreground" />
                  <span className="text-muted-foreground">{t("verify.unavailable", lang)}</span>
                </>
              ) : (
                <>
                  <AlertTriangle className="h-6 w-6 text-amber-400" />
                  <span className="text-amber-400">{t("verify.warning", lang)}</span>
                </>
              )}
            </DialogTitle>
          </DialogHeader>

          <div className="flex-1 overflow-y-auto">
            {/* Tabs */}
            <div className="flex border-b border-border">
              {tabs.map((tb) => (
                <button
                  key={tb.key}
                  onClick={() => setTab(tb.key)}
                  className={`flex items-center gap-1.5 px-5 py-2.5 text-sm font-medium border-b-2 transition-colors cursor-pointer ${
                    tab === tb.key
                      ? "border-primary text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {tb.icon}
                  {tb.label}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="p-5 space-y-5">
              {/* Status Banner */}
              {result?.status === "unavailable" ? (
                <div className="rounded-lg border border-muted-foreground/20 bg-muted/30 px-8 py-4 text-base text-muted-foreground">
                  {result?.message || "High-fidelity analysis is not available on this platform."}
                </div>
              ) : (
                <div
                  className={`rounded-lg border px-4 py-3 text-sm ${
                    result?.status === "verified"
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                      : "border-amber-500/30 bg-amber-500/10 text-amber-300"
                  }`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <span>
                        {result?.status === "verified"
                          ? t("verify.agree", lang)
                          : t("verify.deviate", lang)}
                      </span>
                      {result?.solver && (
                        <span className="ml-2 text-[10px] text-muted-foreground">
                          via {result.solver}
                        </span>
                      )}
                    </div>
                    {result?.status === "warning" && structure && (
                      <button
                        onClick={handleDeepVerify}
                        disabled={multiLoading}
                        className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-500/20 border border-amber-500/40 text-amber-300 hover:bg-amber-500/30 transition-colors cursor-pointer"
                      >
                        {multiLoading ? (
                          <>
                            <Loader2 className="h-3 w-3 animate-spin" />
                            {t("verify.deep_verifying", lang)}
                          </>
                        ) : (
                          <>
                            <Zap className="h-3 w-3" />
                            {t("verify.deep_verify", lang)}
                          </>
                        )}
                      </button>
                    )}
                  </div>
                  {result?.message && (
                    <p className="mt-2 text-[11px] text-amber-300/60 leading-relaxed">{result.message}</p>
                  )}
                </div>
              )}

              {tab === "displacements" && (
                <div className="space-y-6">
                  {/* Displacement card */}
                  <div className="rounded-xl border border-border bg-[#0a0f1a] p-5">
                    <div className="text-xs text-muted-foreground uppercase tracking-wide mb-3">{t("verify.disp", lang)}</div>
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-muted-foreground">{t("verify.fast", lang)}</span>
                        <span className="text-xl font-bold text-cyan-400 font-mono tabular-nums">
                          {fmtDisp(result?.comparison.max_displacement.fast ?? 0)}
                        </span>
                      </div>
                      {hasHiFi && (
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">{t("verify.hifi", lang)}</span>
                          <span className="text-xl font-bold text-purple-400 font-mono tabular-nums">
                            {fmtDisp(result?.comparison.max_displacement.high_fidelity ?? 0)}
                          </span>
                        </div>
                      )}
                      <div className="border-t border-border pt-2 flex items-center justify-between">
                        <span className="text-sm text-muted-foreground">{t("verify.diff", lang)}</span>
                        <span className={`text-lg font-bold font-mono ${
                          (result?.comparison.max_displacement.diff_percent ?? 0) < 5 ? "text-emerald-400" : "text-amber-400"
                        }`}>
                          {result?.comparison.max_displacement.diff_percent ?? 0}%
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Node Displacements table */}
                  {nodeDisps.length > 0 && (
                    <div>
                      <h4 className="text-sm font-semibold text-foreground mb-3">Node Displacements</h4>
                      <div className="rounded-lg border border-border overflow-hidden max-h-[400px] overflow-y-auto">
                        <table className="w-full text-sm">
                          <thead className="sticky top-0 bg-[#0f172a]">
                            <tr className="border-b border-border bg-muted/50">
                              <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted-foreground">Node ID</th>
                              <th className="text-right px-4 py-2.5 text-xs font-semibold text-muted-foreground">Ux (mm)</th>
                              <th className="text-right px-4 py-2.5 text-xs font-semibold text-muted-foreground">Uy (mm)</th>
                              <th className="text-right px-4 py-2.5 text-xs font-semibold text-muted-foreground">|U| (mm)</th>
                            </tr>
                          </thead>
                          <tbody>
                            {nodeDisps.map((nd) => {
                              const absU = Math.abs(nd.ux) + Math.abs(nd.uy);
                              const isMax = absU >= (fastResult?.max_displacement as number || 0) * 0.99;
                              return (
                                <tr key={nd.node_id} className={`border-b border-border/50 ${isMax ? "bg-cyan-500/5" : ""}`}>
                                  <td className="px-4 py-2 font-mono text-sm text-foreground">{nd.node_id}</td>
                                  <td className="px-4 py-2 text-right font-mono text-sm text-cyan-300/80">{(nd.ux * 1000).toFixed(6)}</td>
                                  <td className="px-4 py-2 text-right font-mono text-sm text-cyan-300/80">{(nd.uy * 1000).toFixed(6)}</td>
                                  <td className={`px-4 py-2 text-right font-mono text-sm font-semibold ${isMax ? "text-cyan-400" : "text-foreground/60"}`}>
                                    {(absU * 1000).toFixed(6)}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {tab === "forces" && (
                <div className="space-y-6">
                  {/* Axial force card */}
                  <div className="rounded-xl border border-border bg-[#0a0f1a] p-5">
                    <div className="text-xs text-muted-foreground uppercase tracking-wide mb-3">{t("verify.axial", lang)}</div>
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-muted-foreground">{t("verify.fast", lang)}</span>
                        <span className="text-xl font-bold text-cyan-400 font-mono tabular-nums">
                          {fmtForce(result?.comparison.max_axial_force.fast ?? 0)}
                        </span>
                      </div>
                      {hasHiFi && (
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">{t("verify.hifi", lang)}</span>
                          <span className="text-xl font-bold text-purple-400 font-mono tabular-nums">
                            {fmtForce(result?.comparison.max_axial_force.high_fidelity ?? 0)}
                          </span>
                        </div>
                      )}
                      <div className="border-t border-border pt-2 flex items-center justify-between">
                        <span className="text-sm text-muted-foreground">{t("verify.diff", lang)}</span>
                        <span className={`text-lg font-bold font-mono ${
                          (result?.comparison.max_axial_force.diff_percent ?? 0) < 5 ? "text-emerald-400" : "text-amber-400"
                        }`}>
                          {result?.comparison.max_axial_force.diff_percent ?? 0}%
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Element Forces table */}
                  {elemForces.length > 0 && (
                    <div>
                      <h4 className="text-sm font-semibold text-foreground mb-3">Element Forces</h4>
                      <div className="rounded-lg border border-border overflow-hidden max-h-[400px] overflow-y-auto">
                        <table className="w-full text-sm">
                          <thead className="sticky top-0 bg-[#0f172a]">
                            <tr className="border-b border-border bg-muted/50">
                              <th className="text-left px-3 py-2.5 text-xs font-semibold text-muted-foreground">Elem</th>
                              <th className="text-right px-3 py-2.5 text-xs font-semibold text-muted-foreground">N (kN)</th>
                              <th className="text-right px-3 py-2.5 text-xs font-semibold text-muted-foreground">Mmax</th>
                              <th className="text-right px-3 py-2.5 text-xs font-semibold text-muted-foreground">Mmin</th>
                              <th className="text-right px-3 py-2.5 text-xs font-semibold text-muted-foreground">Qmax</th>
                              <th className="text-right px-3 py-2.5 text-xs font-semibold text-muted-foreground">Qmin</th>
                            </tr>
                          </thead>
                          <tbody>
                            {elemForces.map((ef) => {
                              const maxAxial = Math.abs(ef.Nmax) > Math.abs(ef.Nmin) ? ef.Nmax : ef.Nmin;
                              const isMax = Math.abs(maxAxial) >= ((fastResult?.max_axial_force as number) || 0) * 0.99;
                              return (
                                <tr key={ef.element_id} className={`border-b border-border/50 ${isMax ? "bg-cyan-500/5" : ""}`}>
                                  <td className="px-3 py-2 font-mono text-sm text-foreground">#{ef.element_id}</td>
                                  <td className={`px-3 py-2 text-right font-mono text-sm font-semibold ${isMax ? "text-cyan-400" : "text-foreground/80"}`}>
                                    {(maxAxial / 1000).toFixed(2)}
                                  </td>
                                  <td className="px-3 py-2 text-right font-mono text-sm text-foreground/60">{ef.Mmax.toExponential(2)}</td>
                                  <td className="px-3 py-2 text-right font-mono text-sm text-foreground/60">{ef.Mmin.toExponential(2)}</td>
                                  <td className="px-3 py-2 text-right font-mono text-sm text-foreground/60">{ef.Qmax.toExponential(2)}</td>
                                  <td className="px-3 py-2 text-right font-mono text-sm text-foreground/60">{ef.Qmin.toExponential(2)}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {tab === "comparison" && (
                <div>
                  <h4 className="text-sm font-semibold text-foreground mb-3">{t("verify.visual_comparison", lang)}</h4>
                  <div className="rounded-lg border border-border p-5 bg-[#0a0f1a]">
                    <ResponsiveContainer width="100%" height={320}>
                      <BarChart data={getChartData()}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#94a3b8" }} />
                        <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} />
                        <Tooltip contentStyle={{
                          backgroundColor: "#1e293b",
                          border: "1px solid #334155",
                          borderRadius: "8px",
                          fontSize: "13px",
                        }} />
                        <Legend wrapperStyle={{ fontSize: "12px" }} />
                        <Bar dataKey="Fast" fill="#22d3ee" radius={[6, 6, 0, 0]} />
                        <Bar dataKey="High-Fidelity" fill="#a78bfa" radius={[6, 6, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  {result?.message && (
                    <p className="mt-2 text-[11px] text-amber-300/60 leading-relaxed">{result.message}</p>
                  )}
                </div>
              )}

              {tab === "deviation" && (
                <div>
                  <h4 className="text-sm font-semibold text-foreground mb-3">{t("verify.deviation_analysis", lang)}</h4>
                  <div className="rounded-lg border border-border p-5 bg-[#0a0f1a]">
                    <ResponsiveContainer width="100%" height={280}>
                      <BarChart data={getDiffData()}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#94a3b8" }} />
                        <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} domain={[0, 10]} />
                        <Tooltip contentStyle={{
                          backgroundColor: "#1e293b",
                          border: "1px solid #334155",
                          borderRadius: "8px",
                          fontSize: "13px",
                        }} />
                        <Bar
                          dataKey="Difference %"
                          fill={result?.status === "verified" ? "#10b981" : "#f59e0b"}
                          radius={[6, 6, 0, 0]}
                        />
                      </BarChart>
                    </ResponsiveContainer>
                    <div className="flex items-center gap-2 mt-3">
                      <div className="h-px flex-1 bg-red-500/30 border-t border-dashed border-red-500/50" />
                      <span className="text-xs text-red-400/60">{t("verify.threshold", lang)}</span>
                    </div>
                  </div>
                  {result?.message && (
                    <p className="mt-2 text-[11px] text-amber-300/60 leading-relaxed">{result.message}</p>
                  )}
                </div>
              )}

              {tab === "multi" && (
                <div className="space-y-6">
                  {!multiResult ? (
                    <div className="flex flex-col items-center gap-3 py-8">
                      <Layers className="h-10 w-10 text-muted-foreground/40" />
                      <p className="text-sm text-muted-foreground">
                        {multiLoading ? t("verify.deep_verifying", lang) : "Run Deep Verify to compare all 4 solvers"}
                      </p>
                      {!multiLoading && structure && (
                        <button
                          onClick={handleDeepVerify}
                          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-amber-500/20 border border-amber-500/40 text-amber-300 hover:bg-amber-500/30 transition-colors cursor-pointer"
                        >
                          <Zap className="h-4 w-4" />
                          {t("verify.deep_verify", lang)}
                        </button>
                      )}
                    </div>
                  ) : (
                    <>
                      <div className="rounded-xl border border-border bg-[#0a0f1a] p-5">
                        <h4 className="text-xs text-muted-foreground uppercase tracking-wide mb-4">{t("verify.all_solvers_table", lang)}</h4>
                        <div className="space-y-5">
                          {/* Max Displacement row */}
                          <div>
                            <div className="text-sm font-medium text-foreground mb-2">{t("verify.disp", lang)}</div>
                            <div className="rounded-lg border border-border overflow-hidden">
                              <table className="w-full text-sm">
                                <thead>
                                  <tr className="border-b border-border bg-muted/30">
                                    <th className="text-left px-3 py-2 text-xs font-semibold text-muted-foreground">{t("verify.metric", lang)}</th>
                                    <th className="text-right px-3 py-2 text-xs font-semibold text-cyan-400">{t("verify.solver_anastruct", lang)}</th>
                                    <th className="text-right px-3 py-2 text-xs font-semibold text-purple-400">{t("verify.solver_opensees", lang)}</th>
                                    <th className="text-right px-3 py-2 text-xs font-semibold text-emerald-400">{t("verify.solver_pynite", lang)}</th>
                                    <th className="text-right px-3 py-2 text-xs font-semibold text-amber-400">{t("verify.solver_fapp", lang)}</th>
                                    <th className="text-right px-3 py-2 text-xs font-semibold text-foreground">{t("verify.consensus", lang)}</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  <tr className="border-b border-border/50">
                                    <td className="px-3 py-2.5 text-muted-foreground">{t("verify.disp", lang)}</td>
                                    {["anastruct", "opensees", "pynite", "fapp"].map((key) => {
                                      const r = multiResult.solvers[key];
                                      const dev = multiResult.deviations[key];
                                      const isOutlier = dev?.is_outlier;
                                      return (
                                        <td key={key} className={`px-3 py-2.5 text-right font-mono tabular-nums ${
                                          !r || r.error ? "text-muted-foreground/40" :
                                          isOutlier ? "text-red-400" : "text-foreground/80"
                                        }`}>
                                          {r && !r.error ? fmtDisp(r.max_displacement ?? 0) : "N/A"}
                                        </td>
                                      );
                                    })}
                                    <td className="px-3 py-2.5 text-right font-mono font-semibold text-foreground tabular-nums">
                                      {fmtDisp(multiResult.consensus.max_displacement)}
                                    </td>
                                  </tr>
                                </tbody>
                              </table>
                            </div>
                          </div>

                          {/* Max Axial Force row */}
                          <div>
                            <div className="text-sm font-medium text-foreground mb-2">{t("verify.axial", lang)}</div>
                            <div className="rounded-lg border border-border overflow-hidden">
                              <table className="w-full text-sm">
                                <thead>
                                  <tr className="border-b border-border bg-muted/30">
                                    <th className="text-left px-3 py-2 text-xs font-semibold text-muted-foreground">{t("verify.metric", lang)}</th>
                                    <th className="text-right px-3 py-2 text-xs font-semibold text-cyan-400">{t("verify.solver_anastruct", lang)}</th>
                                    <th className="text-right px-3 py-2 text-xs font-semibold text-purple-400">{t("verify.solver_opensees", lang)}</th>
                                    <th className="text-right px-3 py-2 text-xs font-semibold text-emerald-400">{t("verify.solver_pynite", lang)}</th>
                                    <th className="text-right px-3 py-2 text-xs font-semibold text-amber-400">{t("verify.solver_fapp", lang)}</th>
                                    <th className="text-right px-3 py-2 text-xs font-semibold text-foreground">{t("verify.consensus", lang)}</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  <tr className="border-b border-border/50">
                                    <td className="px-3 py-2.5 text-muted-foreground">{t("verify.axial", lang)}</td>
                                    {["anastruct", "opensees", "pynite", "fapp"].map((key) => {
                                      const r = multiResult.solvers[key];
                                      const dev = multiResult.deviations[key];
                                      const isOutlier = dev?.is_outlier;
                                      return (
                                        <td key={key} className={`px-3 py-2.5 text-right font-mono tabular-nums ${
                                          !r || r.error ? "text-muted-foreground/40" :
                                          isOutlier ? "text-red-400" : "text-foreground/80"
                                        }`}>
                                          {r && !r.error ? fmtForce(r.max_axial_force ?? 0) : "N/A"}
                                        </td>
                                      );
                                    })}
                                    <td className="px-3 py-2.5 text-right font-mono font-semibold text-foreground tabular-nums">
                                      {fmtForce(multiResult.consensus.max_axial_force)}
                                    </td>
                                  </tr>
                                </tbody>
                              </table>
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Deviation summary */}
                      <div className="rounded-xl border border-border bg-[#0a0f1a] p-5">
                        <h4 className="text-xs text-muted-foreground uppercase tracking-wide mb-3">{t("verify.deviation_analysis", lang)}</h4>
                        <div className="space-y-2">
                          {Object.entries(multiResult.deviations).map(([key, dev]) => {
                            const nameMap: Record<string, string> = {
                              anastruct: t("verify.solver_anastruct", lang),
                              opensees: t("verify.solver_opensees", lang),
                              pynite: t("verify.solver_pynite", lang),
                              fapp: t("verify.solver_fapp", lang),
                            };
                            return (
                              <div key={key} className={`flex items-center justify-between rounded-lg px-3 py-2 ${
                                dev.is_outlier ? "bg-red-500/5 border border-red-500/20" : "bg-muted/10"
                              }`}>
                                <div className="flex items-center gap-2">
                                  <span className="text-sm text-foreground">{nameMap[key] || key}</span>
                                  {dev.is_outlier && (
                                    <span className="text-[10px] font-medium text-red-400 bg-red-500/10 px-1.5 py-0.5 rounded">{t("verify.outlier", lang)}</span>
                                  )}
                                </div>
                                <div className="flex gap-4 text-xs font-mono">
                                  <span className={dev.displacement_diff_pct > 5 ? "text-red-400" : "text-emerald-400"}>
                                    Disp: {dev.displacement_diff_pct}%
                                  </span>
                                  <span className={dev.axial_diff_pct > 5 ? "text-red-400" : "text-emerald-400"}>
                                    Axial: {dev.axial_diff_pct}%
                                  </span>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                        <div className="flex items-center gap-2 mt-3">
                          <div className="h-px flex-1 bg-red-500/30 border-t border-dashed border-red-500/50" />
                          <span className="text-xs text-red-400/60">{t("verify.threshold", lang)}</span>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
