"use client";

import { useState } from "react";
import {
  ShieldCheck,
  AlertTriangle,
  Loader2,
  X,
  BarChart3,
} from "lucide-react";
import { Button } from "@/components/ui/button";
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
import { verifyAnalysis, type VerificationResult } from "@/lib/api";

interface VerificationPanelProps {
  fastResult: Record<string, unknown> | null;
}

export function VerificationPanel({ fastResult }: VerificationPanelProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<VerificationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleVerify = async () => {
    if (!fastResult) return;
    setLoading(true);
    setError(null);
    try {
      const res = await verifyAnalysis(fastResult);
      setResult(res);
      setOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Verification failed");
    } finally {
      setLoading(false);
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

  return (
    <>
      {/* Verification Button */}
      <div className="flex flex-col items-center gap-3">
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
              High-Precision Verification...
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4" />
              Verify Results (High-Precision)
            </span>
          )}
        </button>
        {error && (
          <p className="text-xs text-red-400">{error}</p>
        )}
      </div>

      {/* Comparison Dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl bg-[#0f172a] border-border text-foreground">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3 text-lg">
              {result?.status === "verified" ? (
                <>
                  <ShieldCheck className="h-6 w-6 text-emerald-400" />
                  <span className="text-emerald-400">Dual-Track Verified</span>
                </>
              ) : result?.status === "unavailable" ? (
                <>
                  <AlertTriangle className="h-6 w-6 text-muted-foreground" />
                  <span className="text-muted-foreground">High-Fidelity Unavailable</span>
                </>
              ) : (
                <>
                  <AlertTriangle className="h-6 w-6 text-amber-400" />
                  <span className="text-amber-400">Deviation Detected — Manual Review Recommended</span>
                </>
              )}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-6">
            {/* Status Banner */}
            {result?.status === "unavailable" ? (
              <div className="rounded-lg border border-muted-foreground/20 bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
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
                {result?.status === "verified"
                  ? "Fast analysis and high-fidelity analysis agree within 5% tolerance. Results are engineering-reliable."
                  : "Deviation exceeds 5% threshold. Confidence reduced — consider refining the model or consulting a senior engineer."}
                {result?.demo_mode && (
                  <span className="block mt-1 text-[10px] opacity-60">
                    (Demo mode — simulated high-fidelity data for UI verification)
                  </span>
                )}
              </div>
            )}

            {/* Comparison Table */}
            <div>
              <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Metric Comparison
              </h4>
              <div className="rounded-lg border border-border overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/50">
                      <th className="text-left px-4 py-2 text-xs font-medium text-muted-foreground">Metric</th>
                      <th className="text-right px-4 py-2 text-xs font-medium text-muted-foreground">Fast</th>
                      <th className="text-right px-4 py-2 text-xs font-medium text-muted-foreground">High-Fidelity</th>
                      <th className="text-right px-4 py-2 text-xs font-medium text-muted-foreground">Diff %</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-border">
                      <td className="px-4 py-2 text-xs">Max Displacement</td>
                      <td className="px-4 py-2 text-right font-mono text-xs">
                        {result?.comparison.max_displacement.fast.toExponential(4)}
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-xs">
                        {result?.comparison.max_displacement.high_fidelity.toExponential(4)}
                      </td>
                      <td className={`px-4 py-2 text-right font-mono text-xs ${
                        (result?.comparison.max_displacement.diff_percent ?? 0) < 5
                          ? "text-emerald-400"
                          : "text-amber-400"
                      }`}>
                        {result?.comparison.max_displacement.diff_percent}%
                      </td>
                    </tr>
                    <tr>
                      <td className="px-4 py-2 text-xs">Max Axial Force</td>
                      <td className="px-4 py-2 text-right font-mono text-xs">
                        {result?.comparison.max_axial_force.fast.toFixed(2)} N
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-xs">
                        {result?.comparison.max_axial_force.high_fidelity.toFixed(2)} N
                      </td>
                      <td className={`px-4 py-2 text-right font-mono text-xs ${
                        (result?.comparison.max_axial_force.diff_percent ?? 0) < 5
                          ? "text-emerald-400"
                          : "text-amber-400"
                      }`}>
                        {result?.comparison.max_axial_force.diff_percent}%
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* Bar Chart */}
            <div>
              <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Visual Comparison
              </h4>
              <div className="rounded-lg border border-border p-4 bg-[#0a0f1a]">
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={getChartData()}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#94a3b8" }} />
                    <YAxis tick={{ fontSize: 10, fill: "#94a3b8" }} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1e293b",
                        border: "1px solid #334155",
                        borderRadius: "8px",
                        fontSize: "12px",
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: "11px" }} />
                    <Bar dataKey="Fast" fill="#22d3ee" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="High-Fidelity" fill="#a78bfa" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Diff Chart */}
            <div>
              <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Deviation Analysis
              </h4>
              <div className="rounded-lg border border-border p-4 bg-[#0a0f1a]">
                <ResponsiveContainer width="100%" height={150}>
                  <BarChart data={getDiffData()}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#94a3b8" }} />
                    <YAxis
                      tick={{ fontSize: 10, fill: "#94a3b8" }}
                      domain={[0, 10]}
                      label={{ value: "%", position: "top", fill: "#94a3b8", fontSize: 10 }}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1e293b",
                        border: "1px solid #334155",
                        borderRadius: "8px",
                        fontSize: "12px",
                      }}
                    />
                    <Bar
                      dataKey="Difference %"
                      fill={(result?.status === "verified" ? "#10b981" : "#f59e0b")}
                      radius={[4, 4, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
                {/* 5% threshold line */}
                <div className="flex items-center gap-2 mt-1">
                  <div className="h-px flex-1 bg-red-500/30 border-t border-dashed border-red-500/50" />
                  <span className="text-[9px] text-red-400/60">5% threshold</span>
                </div>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
