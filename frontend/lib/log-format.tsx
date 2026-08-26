import { Play, CheckCircle, Brain, AlertCircle, Terminal } from "lucide-react";
import { t, type Lang } from "@/lib/i18n";
import type { StepEvent } from "@/lib/state-restore";

export function getLogIcon(type: string) {
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
}

export function fmtVal(v: unknown): string {
  if (typeof v === "number") {
    if (Math.abs(v) >= 1000) return (v / 1000).toFixed(2) + "k";
    return v.toFixed(4);
  }
  return String(v);
}

export function formatLogEntry(entry: StepEvent): { label: string; detail: string } {
  switch (entry.type) {
    case "tool_call": {
      const args = ((entry as unknown) as Record<string, unknown>).arguments as Record<string, unknown> || {};
      let detail = "";
      if (entry.name === "generate_simple_frame") {
        detail = `${args.stories || "?"} stories x ${args.bays || "?"} bays`;
      } else if (entry.name === "generate_frame" || entry.name === "generate_from_text") {
        detail = `${args.num_stories || "?"} stories x ${args.num_bays_x || "?"} bays, ${args.span_x_m || "?"}m span`;
      } else if (entry.name === "analyze_frame") {
        detail = "Running anaStruct linear analysis...";
      } else if (entry.name === "select_critical_element") {
        detail = "Identifying column with highest axial load";
      } else if (entry.name === "apply_demolition_action") {
        detail = `Removing element #${args.element_id || "?"}`;
      } else if (entry.name === "high_fidelity_analysis") {
        detail = "Running OpenSees verification...";
      } else {
        detail = JSON.stringify(args).slice(0, 80);
      }
      return { label: entry.name || "?", detail };
    }
    case "tool_result": {
      let parsed: Record<string, unknown> | null = null;
      try {
        parsed = typeof entry.result === "string" ? JSON.parse(entry.result) : (entry.result as Record<string, unknown>);
      } catch { /* not JSON */ }
      if (!parsed) return { label: "Result", detail: String(entry.result).slice(0, 80) };

      if (entry.name === "generate_simple_frame" || entry.name === "generate_frame" || entry.name === "generate_from_text") {
        const n = (parsed.nodes as unknown[] | undefined)?.length ?? 0;
        const e = (parsed.elements as unknown[] | undefined)?.length ?? 0;
        return { label: "Frame ready", detail: `${n} nodes, ${e} elements` };
      } else if (entry.name === "analyze_frame") {
        const disp = parsed.max_displacement;
        const axial = parsed.max_axial_force;
        return { label: "Analysis done", detail: `Max disp: ${fmtVal(disp)} m, Max axial: ${fmtVal(axial)} N` };
      } else if (entry.name === "select_critical_element") {
        return { label: "Critical element", detail: `Element #${parsed.critical_element_id}, axial: ${fmtVal(parsed.critical_axial_force_N)} N` };
      } else if (entry.name === "apply_demolition_action") {
        const fe = parsed.failed_elements as number[] | undefined;
        return { label: "Demolished!", detail: fe ? `${fe.length} element(s) collapsed: [${fe.join(", ")}]` : "Done" };
      } else if (entry.name === "high_fidelity_analysis") {
        return { label: "Hi-Fi result", detail: `Max disp: ${fmtVal(parsed.max_displacement)} m` };
      }
      return { label: entry.name || "Result", detail: JSON.stringify(parsed).slice(0, 80) };
    }
    case "response":
      return { label: "AI", detail: (entry.content || "").slice(0, 100) };
    case "error":
      return { label: "ERROR", detail: entry.content || "" };
    default:
      return { label: entry.type, detail: "" };
  }
}

export function stepBrief(step: StepEvent, lang: Lang): string {
  const toolNames: Record<string, string> = {
    generate_simple_frame: t("step.generating_brief", lang),
    analyze_frame: t("step.analyzing_brief", lang),
    select_critical_element: t("step.critical_brief", lang),
    apply_demolition_action: t("step.demolishing_brief", lang),
    high_fidelity_analysis: "OpenSees",
    pynite_analysis: "PyNite",
    fapp_analysis: "FAPP",
    full_analysis_3d_gb: "3D GB50017",
  };
  if (step.type === "tool_call") {
    return toolNames[step.name || ""] || step.name || "?";
  }
  if (step.type === "tool_result" && step.name) {
    const briefs: Record<string, (r: Record<string, unknown>) => string> = {
      generate_simple_frame: (r) => {
        const n = (r.nodes as unknown[] | undefined)?.length ?? 0;
        const e = (r.elements as unknown[] | undefined)?.length ?? 0;
        return `${n}点${e}杆`;
      },
      analyze_frame: (r) => `max ${((r.max_displacement ?? 0) as number * 1000).toFixed(2)}mm`,
      pynite_analysis: (r) => `${r.solver ? (r.solver as string).split(" ")[0] : ""} ${((r.max_displacement ?? 0) as number * 1000).toFixed(2)}mm`,
      fapp_analysis: (r) => `${r.solver ? (r.solver as string).split(" ")[0] : ""} ${((r.max_displacement ?? 0) as number * 1000).toFixed(2)}mm`,
      select_critical_element: (r) => `柱#${r.critical_element_id}`,
      apply_demolition_action: (r) => {
        const fe = r.failed_elements as number[] | undefined;
        return fe?.length ? `塌 #${fe.join(",")}` : "";
      },
      high_fidelity_analysis: (r) => `${r.solver ? (r.solver as string).split(" ")[0] : ""} ${((r.max_displacement ?? 0) as number * 1000).toFixed(2)}mm`,
      full_analysis_3d_gb: (r) => {
        const a = r.analysis as Record<string, unknown> | undefined;
        return `${a?.solver ? (a.solver as string).split(" ")[0] : ""} ${(((a?.max_displacement ?? 0) as number) * 1000).toFixed(2)}mm`;
      },
    };
    const fn = briefs[step.name];
    if (!fn) return "";
    let parsed: Record<string, unknown>;
    try { parsed = typeof step.result === "string" ? JSON.parse(step.result) : step.result as Record<string, unknown>; } catch { return ""; }
    if (!parsed || typeof parsed !== "object") return "";
    return fn(parsed);
  }
  return "";
}
