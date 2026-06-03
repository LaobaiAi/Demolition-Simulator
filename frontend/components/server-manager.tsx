"use client";

import { useState, useEffect, useCallback } from "react";
import { t, type Lang } from "@/lib/i18n";
import {
  fetchServerStatus,
  fetchServerMetrics,
  fetchTools,
  callManagerTool,
  pauseServer,
  resumeServer,
  stopServer,
  type ServerStatus,
  type Tool,
} from "@/lib/api";

type TabId = "overview" | "create" | "health" | "search" | "orchestrate" | "logs" | "tools";

interface Props {
  lang: Lang;
  onClose: () => void;
}

const STATE_COLORS: Record<string, string> = {
  running: "#4ade80",
  registered: "#60a5fa",
  hibernating: "#a78bfa",
  starting: "#fbbf24",
  crashed: "#ef4444",
  degraded: "#f97316",
  stopped: "#6b7280",
  composite: "#22d3ee",
};

const KINDS: { value: string; label: string }[] = [
  { value: "atomic-mcp", label: "Atomic MCP Server" },
  { value: "atomic-class", label: "Atomic Class Server" },
  { value: "merged", label: "Merged Server" },
  { value: "composite", label: "Composite Pipeline" },
  { value: "bridge", label: "Bridge Server" },
];

export default function ServerManager({ lang, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [servers, setServers] = useState<ServerStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create form state
  const [createForm, setCreateForm] = useState({
    name: "",
    kind: "atomic-mcp",
    description: "",
    start_mode: "lazy",
    tools: [{ name: "", description: "" }],
  });
  const [createResult, setCreateResult] = useState<Record<string, unknown> | null>(null);

  // Search state
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Record<string, unknown>[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);

  // Orchestrate state
  const [depGraph, setDepGraph] = useState<Record<string, unknown> | null>(null);
  const [mergeCandidates, setMergeCandidates] = useState<Record<string, unknown>[]>([]);

  // Health state
  const [metrics, setMetrics] = useState<Record<string, {total_calls: number; error_count: number; avg_latency_ms: number; last_called: number | null}>>({});

  // Tools state
  const [allTools, setAllTools] = useState<Tool[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);

  const loadServers = useCallback(async () => {
    try {
      setError(null);
      const data = await fetchServerStatus();
      setServers(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMetrics = useCallback(async () => {
    try {
      const data = await fetchServerMetrics();
      setMetrics(data || {});
    } catch {}
  }, []);

  const loadTools = useCallback(async () => {
    setToolsLoading(true);
    try {
      const data = await fetchTools();
      setAllTools(data);
    } catch {
      setAllTools([]);
    } finally {
      setToolsLoading(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => { loadServers(); loadMetrics(); }, 0);
    const interval = setInterval(loadServers, 5000);
    return () => { clearTimeout(t); clearInterval(interval); };
  }, [loadServers, loadMetrics]);

  const stats = {
    total: servers.length,
    running: servers.filter((s) => s.state === "running").length,
    hibernating: servers.filter((s) => s.state === "hibernating").length,
    crashed: servers.filter((s) => s.state === "crashed").length,
    composite: servers.filter((s) => s.state === "composite").length,
  };

  async function handleCreate() {
    setCreateResult(null);
    const tools = createForm.tools.filter((t) => t.name.trim());
    const result = await callManagerTool("create_server", {
      server_name: createForm.name,
      kind: createForm.kind,
      description: createForm.description,
      start_mode: createForm.start_mode,
      tools,
    });
    setCreateResult(result);
    loadServers();
  }

  async function handleSearch() {
    if (!searchQuery.trim()) return;
    setSearchLoading(true);
    try {
      const result = await callManagerTool("search_capabilities", {
        query: searchQuery,
        threshold: 0.1,
        top_k: 15,
      });
      setSearchResults((result.results as Record<string, unknown>[]) || []);
    } catch {
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  }

  async function handleAnalyzeDeps() {
    const result = await callManagerTool("analyze_dependency_graph", {});
    setDepGraph(result);
    const merge = await callManagerTool("detect_merge_opportunities", {});
    setMergeCandidates((merge.merge_candidates as Record<string, unknown>[]) || []);
  }

  const tabs: { id: TabId; labelKey: string }[] = [
    { id: "overview", labelKey: "srv.tab_overview" },
    { id: "tools", labelKey: "srv.tab_tools" },
    { id: "create", labelKey: "srv.tab_create" },
    { id: "health", labelKey: "srv.tab_health" },
    { id: "search", labelKey: "srv.tab_search" },
    { id: "orchestrate", labelKey: "srv.tab_orchestrate" },
    { id: "logs", labelKey: "srv.tab_logs" },
  ];

  return (
    <div style={styles.overlay}>
      <div style={styles.modal}>
        <div style={styles.header}>
          <h2 style={styles.title}>{t("srv.title", lang)}</h2>
          <button onClick={onClose} style={styles.closeBtn}>✕</button>
        </div>

        <div style={styles.tabBar}>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => { setActiveTab(tab.id); if (tab.id === "orchestrate") handleAnalyzeDeps(); if (tab.id === "health") loadMetrics(); if (tab.id === "tools") loadTools(); }}
              style={{
                ...styles.tab,
                ...(activeTab === tab.id ? styles.tabActive : {}),
              }}
            >
              {t(tab.labelKey, lang).replace("{n}", String(allTools.length))}
            </button>
          ))}
        </div>

        <div style={styles.content}>
          {activeTab === "overview" && (
            <div>
              <div style={styles.statsBar}>
                <StatBadge label={t("srv.total", lang)} value={stats.total} color="#94a3b8" />
                <StatBadge label={t("srv.running", lang)} value={stats.running} color={STATE_COLORS.running} />
                <StatBadge label={t("srv.hibernating", lang)} value={stats.hibernating} color={STATE_COLORS.hibernating} />
                <StatBadge label={t("srv.crashed", lang)} value={stats.crashed} color={STATE_COLORS.crashed} />
                <StatBadge label={t("srv.composite", lang)} value={stats.composite} color={STATE_COLORS.composite} />
              </div>
              {error && <p style={styles.error}>{error}</p>}
              {loading ? (
                <p style={styles.loading}>Loading...</p>
              ) : (
                <div style={styles.grid}>
                  {servers.map((s) => (
                    <ServerCard key={s.name} server={s} lang={lang} onRefresh={loadServers} />
                  ))}
                </div>
              )}
            </div>
          )}

          {activeTab === "tools" && (
            <div>
              {toolsLoading ? (
                <p style={styles.loading}>Loading tools...</p>
              ) : allTools.length === 0 ? (
                <p style={styles.hint}>No tools loaded.</p>
              ) : (
                <div style={styles.toolsGrid}>
                  {allTools.map((tool, i) => (
                    <div key={`${tool.server}-${tool.name}-${i}`} style={styles.toolCard}>
                      <div style={styles.toolCardHeader}>
                        <span style={styles.toolName}>{tool.name}</span>
                        <span style={styles.toolServer}>{tool.server}</span>
                      </div>
                      <p style={styles.toolDesc}>{tool.description}</p>
                      {tool.input_schema && Object.keys(tool.input_schema).length > 0 && (
                        <details style={styles.toolSchema}>
                          <summary style={styles.toolSchemaSummary}>Schema</summary>
                          <pre style={styles.toolSchemaPre}>{JSON.stringify(tool.input_schema, null, 2)}</pre>
                        </details>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeTab === "create" && (
            <div style={styles.form}>
              <div style={styles.formGroup}>
                <label style={styles.label}>{t("srv.create_name", lang)}</label>
                <input
                  style={styles.input}
                  value={createForm.name}
                  onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
                  placeholder="my_new_server"
                />
              </div>
              <div style={styles.formRow}>
                <div style={styles.formGroup}>
                  <label style={styles.label}>{t("srv.create_kind", lang)}</label>
                  <select
                    style={styles.select}
                    value={createForm.kind}
                    onChange={(e) => setCreateForm({ ...createForm, kind: e.target.value })}
                  >
                    {KINDS.map((k) => (
                      <option key={k.value} value={k.value}>{k.label}</option>
                    ))}
                  </select>
                </div>
                <div style={styles.formGroup}>
                  <label style={styles.label}>{t("srv.create_start", lang)}</label>
                  <select
                    style={styles.select}
                    value={createForm.start_mode}
                    onChange={(e) => setCreateForm({ ...createForm, start_mode: e.target.value })}
                  >
                    <option value="lazy">Lazy</option>
                    <option value="eager">Eager</option>
                  </select>
                </div>
              </div>
              <div style={styles.formGroup}>
                <label style={styles.label}>{t("srv.create_desc", lang)}</label>
                <input
                  style={styles.input}
                  value={createForm.description}
                  onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
                  placeholder="One-line description"
                />
              </div>
              <div style={styles.formGroup}>
                <label style={styles.label}>{t("srv.create_tools_hint", lang)}</label>
                {createForm.tools.map((tool, i) => (
                  <div key={i} style={styles.toolRow}>
                    <input
                      style={{ ...styles.input, flex: 1 }}
                      value={tool.name}
                      onChange={(e) => {
                        const tools = [...createForm.tools];
                        tools[i].name = e.target.value;
                        setCreateForm({ ...createForm, tools });
                      }}
                      placeholder="tool_name"
                    />
                    <input
                      style={{ ...styles.input, flex: 2 }}
                      value={tool.description}
                      onChange={(e) => {
                        const tools = [...createForm.tools];
                        tools[i].description = e.target.value;
                        setCreateForm({ ...createForm, tools });
                      }}
                      placeholder="Tool description"
                    />
                    <button
                      style={styles.smallBtn}
                      onClick={() => setCreateForm({ ...createForm, tools: createForm.tools.filter((_, j) => j !== i) })}
                    >
                      ✕
                    </button>
                  </div>
                ))}
                <button
                  style={styles.addBtn}
                  onClick={() => setCreateForm({ ...createForm, tools: [...createForm.tools, { name: "", description: "" }] })}
                >
                  + Add Tool
                </button>
              </div>
              <div style={styles.formActions}>
                <button style={styles.cancelBtn} onClick={() => setCreateForm({ name: "", kind: "atomic-mcp", description: "", start_mode: "lazy", tools: [{ name: "", description: "" }] })}>
                  {t("srv.create_cancel", lang)}
                </button>
                <button style={styles.primaryBtn} onClick={handleCreate} disabled={!createForm.name.trim()}>
                  {t("srv.create_button", lang)}
                </button>
              </div>
              {createResult && (
                <pre style={styles.resultPre}>{JSON.stringify(createResult, null, 2)}</pre>
              )}
            </div>
          )}

          {activeTab === "health" && (
            <div>
              <div style={styles.healthGrid}>
                {servers.map((s) => {
                  const m = metrics[s.name] || {};
                  return (
                    <div key={s.name} style={styles.healthCard}>
                      <div style={styles.healthCardHeader}>
                        <span style={{ ...styles.dot, backgroundColor: STATE_COLORS[s.state] || "#94a3b8" }} />
                        <strong>{s.name}</strong>
                        <span style={styles.stateTag}>{s.state}</span>
                      </div>
                      <div style={styles.healthStats}>
                        <HealthRow label={t("srv.health_pid", lang)} value={s.pid ? String(s.pid) : "—"} />
                        <HealthRow label={t("srv.health_calls", lang)} value={String(m.total_calls || 0)} />
                        <HealthRow label={t("srv.health_errors", lang)} value={String(m.error_count || 0)} />
                        <HealthRow label={t("srv.health_latency", lang)} value={`${m.avg_latency_ms || 0}ms`} />
                      </div>
                      <div style={styles.healthActions}>
                        <button style={styles.smallBtn} onClick={async () => { await callManagerTool("restart_server", { server_name: s.name }); loadServers(); }}>
                          {t("srv.restart", lang)}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {activeTab === "search" && (
            <div>
              <div style={styles.searchBar}>
                <input
                  style={styles.input}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                  placeholder={t("srv.search_placeholder", lang)}
                />
                <button style={styles.primaryBtn} onClick={handleSearch} disabled={searchLoading}>
                  Search
                </button>
              </div>
              {searchLoading && <p style={styles.loading}>Searching...</p>}
              {searchResults.length === 0 && !searchLoading ? (
                <p style={styles.hint}>{t("srv.search_no_results", lang)}</p>
              ) : (
                <div style={styles.searchList}>
                  {searchResults.map((r, i) => (
                    <div key={i} style={styles.searchItem}>
                      <div style={styles.searchItemHeader}>
                        <strong>{r.tool_name as string}</strong>
                        <span style={styles.serverTag}>{r.server_name as string}</span>
                        <span style={styles.scoreTag}>{(r.score as number)?.toFixed(2)}</span>
                      </div>
                      <p style={styles.searchDesc}>{r.tool_description as string || (r.server_description as string)}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeTab === "orchestrate" && (
            <div>
              {depGraph && (
                <div style={styles.graphCard}>
                  <h4>{t("srv.deps_title", lang)}</h4>
                  <p style={styles.hint}>
                    {(depGraph.nodes as unknown[])?.length || 0} {t("srv.deps_nodes", lang)},{" "}
                    {(depGraph.edges as unknown[])?.length || 0} {t("srv.deps_edges", lang)},{" "}
                    {(depGraph.isolated as unknown[])?.length || 0} {t("srv.deps_isolated", lang)}
                  </p>
                  <p style={styles.hint}>{depGraph.summary as string}</p>
                  {(depGraph.cycles as unknown[])?.length > 0 ? (
                    <p style={styles.error}>⚠ Cycles detected: {JSON.stringify(depGraph.cycles)}</p>
                  ) : (
                    <p style={styles.ok}>✓ No dependency cycles</p>
                  )}
                  <DepsList edges={depGraph.edges as Array<{ from: string; to: string; type: string }>} />
                </div>
              )}
              {mergeCandidates.length > 0 && (
                <div style={styles.graphCard}>
                  <h4>{t("srv.merge_suggestions", lang)}</h4>
                  {mergeCandidates.map((c, i) => (
                    <div key={i} style={styles.mergeItem}>
                      <strong>{(c.type as string) || "merge"}</strong>
                      <p style={styles.hint}>{c.rationale as string}</p>
                      <p style={styles.code}>
                        servers: {(c.servers as string[])?.join(" → ")}
                      </p>
                    </div>
                  ))}
                </div>
              )}
              {!depGraph && (
                <p style={styles.hint}>Loading dependency graph...</p>
              )}
            </div>
          )}

          {activeTab === "logs" && (
            <div>
              <p style={styles.hint}>{t("srv.log_empty", lang)}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ServerCard({ server: s, lang, onRefresh }: { server: ServerStatus; lang: Lang; onRefresh: () => void }) {
  const isComposite = s.state === "composite";
  const isHibernating = s.state === "hibernating";
  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <span style={{ ...styles.dot, backgroundColor: STATE_COLORS[s.state] || "#94a3b8" }} />
        <strong style={styles.cardName}>{s.name}</strong>
      </div>
      <div style={styles.cardBody}>
        <p style={styles.cardInfo}>State: {s.state}</p>
        <p style={styles.cardInfo}>{t("srv.tools", lang)}: {s.total_calls}</p>
        {s.avg_latency_ms > 0 && <p style={styles.cardInfo}>Latency: {s.avg_latency_ms}ms</p>}
      </div>
      <div style={styles.cardActions}>
        <button style={styles.smallBtn} onClick={async () => { await callManagerTool("get_server", { server_name: s.name }); }}>
          {t("srv.view", lang)}
        </button>
        {!isComposite && (
          <button style={styles.smallBtn} onClick={async () => { await callManagerTool("restart_server", { server_name: s.name }); onRefresh(); }}>
            {t("srv.restart", lang)}
          </button>
        )}
      </div>
      {!isComposite && (
        <div style={styles.cardActions}>
          <button
            style={{ ...styles.actionBtn, ...(isHibernating ? styles.resumeBtn : styles.pauseBtn) }}
            onClick={async () => {
              if (isHibernating) {
                await resumeServer(s.name);
              } else {
                await pauseServer(s.name);
              }
              onRefresh();
            }}
          >
            {isHibernating ? t("srv.resume", lang) : t("srv.pause", lang)}
          </button>
          <button
            style={{ ...styles.actionBtn, ...styles.stopBtn }}
            onClick={async () => {
              await stopServer(s.name);
              onRefresh();
            }}
          >
            {t("srv.stop", lang)}
          </button>
        </div>
      )}
    </div>
  );
}

function StatBadge({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ ...styles.statBadge, borderColor: color }}>
      <span style={{ ...styles.statValue, color }}>{value}</span>
      <span style={styles.statLabel}>{label}</span>
    </div>
  );
}

function HealthRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={styles.healthRow}>
      <span style={styles.healthLabel}>{label}</span>
      <span style={styles.healthValue}>{value}</span>
    </div>
  );
}

function DepsList({ edges }: { edges: Array<{ from: string; to: string; type: string }> }) {
  if (edges.length === 0) return <p style={{ color: "#94a3b8", fontSize: 13 }}>No dependencies</p>;
  return (
    <div style={{ marginTop: 8 }}>
      {edges.map((e, i) => (
        <div key={i} style={styles.depItem}>
          <span style={{ fontWeight: 600 }}>{e.from}</span>
          <span style={{ color: "#94a3b8", margin: "0 6px" }}>→</span>
          <span style={{ fontWeight: 600 }}>{e.to}</span>
          <span style={styles.depType}>{e.type}</span>
        </div>
      ))}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  overlay: {
    position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: "rgba(0,0,0,0.6)", zIndex: 1000,
    display: "flex", alignItems: "center", justifyContent: "center",
  },
  modal: {
    width: "90vw", maxWidth: 1100, height: "85vh",
    backgroundColor: "#1e293b", borderRadius: 12,
    display: "flex", flexDirection: "column", overflow: "hidden",
    boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
  },
  header: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    padding: "16px 24px", borderBottom: "1px solid #334155",
  },
  title: { color: "#f1f5f9", fontSize: 18, fontWeight: 700, margin: 0 },
  closeBtn: { background: "none", border: "none", color: "#94a3b8", fontSize: 20, cursor: "pointer" },
  tabBar: { display: "flex", borderBottom: "1px solid #334155", padding: "0 16px" },
  tab: {
    padding: "10px 16px", background: "none", border: "none",
    color: "#94a3b8", cursor: "pointer", fontSize: 13, fontWeight: 500,
    borderBottom: "2px solid transparent",
  },
  tabActive: { color: "#60a5fa", borderBottom: "2px solid #60a5fa" },
  content: { flex: 1, overflow: "auto", padding: 20 },
  statsBar: { display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" as const },
  statBadge: {
    display: "flex", alignItems: "center", gap: 6,
    padding: "6px 12px", borderRadius: 8, border: "1px solid",
    backgroundColor: "rgba(30,41,59,0.8)",
  },
  statValue: { fontSize: 20, fontWeight: 700 },
  statLabel: { fontSize: 11, color: "#94a3b8", textTransform: "uppercase" as const },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12 },
  card: {
    backgroundColor: "#0f172a", borderRadius: 8, padding: 14,
    border: "1px solid #334155",
  },
  cardHeader: { display: "flex", alignItems: "center", gap: 8, marginBottom: 8 },
  dot: { width: 8, height: 8, borderRadius: "50%", flexShrink: 0 },
  cardName: { color: "#e2e8f0", fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const },
  cardBody: { marginBottom: 8 },
  cardInfo: { color: "#94a3b8", fontSize: 11, margin: "2px 0" },
  cardActions: { display: "flex", gap: 6 },
  smallBtn: {
    padding: "3px 8px", fontSize: 11, borderRadius: 4,
    backgroundColor: "#334155", color: "#cbd5e1", border: "none", cursor: "pointer",
  },
  actionBtn: {
    flex: 1, padding: "4px 8px", fontSize: 11, borderRadius: 4,
    border: "none", cursor: "pointer", fontWeight: 600,
  },
  pauseBtn: { backgroundColor: "#a78bfa", color: "#1e1b4b" },
  resumeBtn: { backgroundColor: "#4ade80", color: "#052e16" },
  stopBtn: { backgroundColor: "#ef4444", color: "white" },
  form: { maxWidth: 600 },
  formGroup: { marginBottom: 12 },
  formRow: { display: "flex", gap: 12 },
  label: { color: "#94a3b8", fontSize: 12, display: "block", marginBottom: 4 },
  input: {
    width: "100%", padding: "8px 10px", borderRadius: 6,
    border: "1px solid #334155", backgroundColor: "#0f172a",
    color: "#e2e8f0", fontSize: 13, boxSizing: "border-box" as const,
  },
  select: {
    padding: "8px 10px", borderRadius: 6,
    border: "1px solid #334155", backgroundColor: "#0f172a",
    color: "#e2e8f0", fontSize: 13, minWidth: 160,
  },
  toolRow: { display: "flex", gap: 8, marginBottom: 6, alignItems: "center" },
  addBtn: {
    padding: "6px 12px", fontSize: 12, borderRadius: 6,
    backgroundColor: "transparent", color: "#60a5fa", border: "1px dashed #334155", cursor: "pointer",
  },
  formActions: { display: "flex", gap: 10, marginTop: 16 },
  cancelBtn: {
    padding: "8px 16px", borderRadius: 6, fontSize: 13,
    backgroundColor: "#334155", color: "#cbd5e1", border: "none", cursor: "pointer",
  },
  primaryBtn: {
    padding: "8px 20px", borderRadius: 6, fontSize: 13, fontWeight: 600,
    backgroundColor: "#3b82f6", color: "white", border: "none", cursor: "pointer",
  },
  resultPre: {
    marginTop: 12, padding: 12, borderRadius: 6,
    backgroundColor: "#0f172a", color: "#a5f3fc", fontSize: 11,
    maxHeight: 300, overflow: "auto", whiteSpace: "pre-wrap",
  },
  healthGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 },
  healthCard: {
    backgroundColor: "#0f172a", borderRadius: 8, padding: 14,
    border: "1px solid #334155",
  },
  healthCardHeader: { display: "flex", alignItems: "center", gap: 8, marginBottom: 10 },
  stateTag: {
    marginLeft: "auto", fontSize: 10, padding: "2px 6px", borderRadius: 4,
    backgroundColor: "#1e293b", color: "#94a3b8", textTransform: "uppercase" as const,
  },
  healthStats: { marginBottom: 10 },
  healthRow: { display: "flex", justifyContent: "space-between", padding: "2px 0" },
  healthLabel: { color: "#64748b", fontSize: 11 },
  healthValue: { color: "#e2e8f0", fontSize: 12, fontWeight: 600, fontFamily: "monospace" },
  healthActions: { display: "flex", gap: 6 },
  searchBar: { display: "flex", gap: 10, marginBottom: 16 },
  searchList: { display: "flex", flexDirection: "column", gap: 8 },
  searchItem: {
    backgroundColor: "#0f172a", borderRadius: 8, padding: 12,
    border: "1px solid #334155",
  },
  searchItemHeader: { display: "flex", alignItems: "center", gap: 8, marginBottom: 4 },
  serverTag: {
    fontSize: 10, padding: "1px 6px", borderRadius: 4,
    backgroundColor: "#1e3a5f", color: "#60a5fa",
  },
  scoreTag: {
    fontSize: 10, padding: "1px 6px", borderRadius: 4,
    backgroundColor: "#1e293b", color: "#fbbf24", marginLeft: "auto", fontFamily: "monospace",
  },
  searchDesc: { color: "#94a3b8", fontSize: 12, margin: 0 },
  graphCard: {
    backgroundColor: "#0f172a", borderRadius: 8, padding: 14,
    border: "1px solid #334155", marginBottom: 12,
  },
  mergeItem: {
    padding: "8px 0", borderBottom: "1px solid #1e293b",
  },
  depItem: { display: "flex", alignItems: "center", fontSize: 12, padding: "2px 0" },
  depType: {
    marginLeft: "auto", fontSize: 10, padding: "1px 5px",
    borderRadius: 3, backgroundColor: "#1e293b", color: "#64748b",
  },
  error: { color: "#ef4444", fontSize: 12 },
  ok: { color: "#4ade80", fontSize: 12 },
  hint: { color: "#64748b", fontSize: 12, margin: "4px 0" },
  code: { color: "#a5f3fc", fontSize: 11, fontFamily: "monospace", margin: "2px 0" },
  loading: { color: "#94a3b8", fontSize: 13 },
  toolsGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 10 },
  toolCard: {
    backgroundColor: "#0f172a", borderRadius: 8, padding: 12,
    border: "1px solid #334155",
  },
  toolCardHeader: { display: "flex", alignItems: "center", gap: 8, marginBottom: 6 },
  toolName: {
    color: "#e2e8f0", fontSize: 13, fontWeight: 600,
    fontFamily: "monospace",
  },
  toolServer: {
    fontSize: 10, padding: "1px 6px", borderRadius: 4,
    backgroundColor: "#1e3a5f", color: "#60a5fa", marginLeft: "auto",
  },
  toolDesc: { color: "#94a3b8", fontSize: 11, margin: 0, lineHeight: 1.4 },
  toolSchema: { marginTop: 8 },
  toolSchemaSummary: { fontSize: 10, color: "#64748b", cursor: "pointer" },
  toolSchemaPre: {
    marginTop: 4, padding: 8, borderRadius: 4,
    backgroundColor: "#0a0f1a", color: "#a5f3fc", fontSize: 10,
    maxHeight: 150, overflow: "auto", whiteSpace: "pre-wrap",
  },
};
