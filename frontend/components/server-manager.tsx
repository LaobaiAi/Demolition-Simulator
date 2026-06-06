"use client";

import { useState, useEffect, useCallback } from "react";
import styles from "./server-manager-styles";
import { t, type Lang } from "@/lib/i18n";
import {
  fetchServerStatus,
  fetchServerMetrics,
  fetchTools,
  fetchOrphanTools,
  callManagerTool,
  pauseServer,
  resumeServer,
  stopServer,
  type ServerStatus,
  type Tool,
  type OrphanTool,
  type OrphanToolsResponse,
} from "@/lib/api";

type TabId = "overview" | "tools" | "orphans" | "create" | "health" | "search" | "orchestrate" | "logs";

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

  // Orphan tools state
  const [orphanData, setOrphanData] = useState<OrphanToolsResponse | null>(null);
  const [orphanLoading, setOrphanLoading] = useState(false);
  const [expandedOrphanServers, setExpandedOrphanServers] = useState<Set<string>>(new Set());
  const [expandedOrphanSchemas, setExpandedOrphanSchemas] = useState<Set<string>>(new Set());

  // Overview search filter
  const [overviewSearch, setOverviewSearch] = useState("");

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

  const loadOrphans = useCallback(async () => {
    setOrphanLoading(true);
    try {
      const data = await fetchOrphanTools();
      setOrphanData(data);
      const serverNames = new Set(data.orphans.map((o) => o.server));
      setExpandedOrphanServers(serverNames);
    } catch {
      setOrphanData(null);
    } finally {
      setOrphanLoading(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => { loadServers(); loadMetrics(); }, 0);
    const interval = setInterval(loadServers, 5000);
    return () => { clearTimeout(t); clearInterval(interval); };
  }, [loadServers, loadMetrics]);

  const toolsPerServer: Record<string, number> = {};
  for (const t of allTools) {
    toolsPerServer[t.server] = (toolsPerServer[t.server] || 0) + 1;
  }

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

  const filteredServers = overviewSearch
    ? servers.filter((s) => s.name.toLowerCase().includes(overviewSearch.toLowerCase()))
    : servers;

  const tabs: { id: TabId; labelKey: string }[] = [
    { id: "overview", labelKey: "srv.tab_overview" },
    { id: "tools", labelKey: "srv.tab_tools" },
    { id: "orphans", labelKey: "srv.tab_orphans" },
    { id: "create", labelKey: "srv.tab_create" },
    { id: "health", labelKey: "srv.tab_health" },
    { id: "search", labelKey: "srv.tab_search" },
    { id: "orchestrate", labelKey: "srv.tab_orchestrate" },
    { id: "logs", labelKey: "srv.tab_logs" },
  ];

  function toggleOrphanServer(name: string) {
    setExpandedOrphanServers((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function toggleOrphanSchema(key: string) {
    setExpandedOrphanSchemas((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

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
              onClick={() => {
                setActiveTab(tab.id);
                if (tab.id === "orchestrate") handleAnalyzeDeps();
                if (tab.id === "health") loadMetrics();
                if (tab.id === "tools") loadTools();
                if (tab.id === "orphans") loadOrphans();
              }}
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
              {/* Marketplace-style search bar */}
              <div style={styles.marketSearchWrap}>
                <span style={styles.marketSearchIcon}>🔍</span>
                <input
                  style={styles.marketSearchInput}
                  value={overviewSearch}
                  onChange={(e) => setOverviewSearch(e.target.value)}
                  placeholder={t("srv.search_placeholder", lang)}
                />
              </div>

              {/* Compact stat pills */}
              <div style={styles.statsBar}>
                <StatPill label={t("srv.total", lang)} value={stats.total} color="#94a3b8" />
                <StatPill label={t("srv.running", lang)} value={stats.running} color={STATE_COLORS.running} />
                <StatPill label={t("srv.hibernating", lang)} value={stats.hibernating} color={STATE_COLORS.hibernating} />
                <StatPill label={t("srv.crashed", lang)} value={stats.crashed} color={STATE_COLORS.crashed} />
                <StatPill label={t("srv.composite", lang)} value={stats.composite} color={STATE_COLORS.composite} />
              </div>

              {error && <p style={styles.error}>{error}</p>}
              {loading ? (
                <p style={styles.loading}>Loading...</p>
              ) : filteredServers.length === 0 ? (
                <p style={styles.hint}>No servers match your search.</p>
              ) : (
                <div style={styles.grid}>
                  {filteredServers.map((s) => (
                    <MarketServerCard
                      key={s.name}
                      server={s}
                      lang={lang}
                      toolCount={toolsPerServer[s.name] || 0}
                      metric={metrics[s.name]}
                      onRefresh={loadServers}
                    />
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

          {activeTab === "orphans" && (
            <OrphansTab
              data={orphanData}
              loading={orphanLoading}
              lang={lang}
              expandedServers={expandedOrphanServers}
              expandedSchemas={expandedOrphanSchemas}
              onToggleServer={toggleOrphanServer}
              onToggleSchema={toggleOrphanSchema}
            />
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

// ══════════════════════════════════════════════════════════════════════════════
// Marketplace-style Server Card
// ══════════════════════════════════════════════════════════════════════════════

function MarketServerCard({ server: s, lang, toolCount, metric, onRefresh }: {
  server: ServerStatus;
  lang: Lang;
  toolCount: number;
  metric: { total_calls?: number; error_count?: number; avg_latency_ms?: number; last_called?: number | null } | undefined;
  onRefresh: () => void;
}) {
  const isComposite = s.state === "composite";
  const isHibernating = s.state === "hibernating";
  const stateColor = STATE_COLORS[s.state] || "#94a3b8";
  const avatar = s.name.charAt(0).toUpperCase();

  return (
    <div style={styles.mktCard}>
      <div style={styles.mktCardTop}>
        {/* Status dot + Avatar */}
        <div style={styles.mktAvatarRow}>
          <span style={{ ...styles.dot, backgroundColor: stateColor }} />
          <div style={{ ...styles.mktAvatar, borderColor: stateColor }}>{avatar}</div>
          <div style={styles.mktNameBlock}>
            <span style={styles.mktCardName}>{s.name}</span>
            <span style={{ ...styles.mktStateBadge, color: stateColor, borderColor: stateColor }}>
              {s.state}
            </span>
          </div>
        </div>

        {/* Stats row */}
        <div style={styles.mktStatsRow}>
          <span style={styles.mktStat}>
            <span style={styles.mktStatValue}>{toolCount}</span>
            <span style={styles.mktStatLabel}>{t("srv.tool_count", lang).replace("{n}", String(toolCount))}</span>
          </span>
          <span style={styles.mktStat}>
            <span style={styles.mktStatValue}>{s.total_calls}</span>
            <span style={styles.mktStatLabel}>calls</span>
          </span>
          <span style={styles.mktStat}>
            <span style={styles.mktStatValue}>{s.avg_latency_ms > 0 ? s.avg_latency_ms : "—"}</span>
            <span style={styles.mktStatLabel}>ms</span>
          </span>
        </div>

        {/* Sub-metrics line */}
        <div style={styles.mktSubMetrics}>
          <span>PID {s.pid || "—"}</span>
          <span>·</span>
          <span>err {s.error_count}</span>
          {metric?.last_called && (
            <>
              <span>·</span>
              <span>last {new Date(metric.last_called * 1000).toLocaleTimeString()}</span>
            </>
          )}
        </div>
      </div>

      {/* Actions row — always visible, compact */}
      <div style={styles.mktActions}>
        <button
          style={styles.mktActionBtn}
          onClick={async () => { await callManagerTool("get_server", { server_name: s.name }); }}
        >
          {t("srv.view", lang)}
        </button>
        {!isComposite && (
          <button
            style={styles.mktActionBtn}
            onClick={async () => { await callManagerTool("restart_server", { server_name: s.name }); onRefresh(); }}
          >
            {t("srv.restart", lang)}
          </button>
        )}
        {!isComposite && (
          <button
            style={{ ...styles.mktActionBtn, color: isHibernating ? "#4ade80" : "#a78bfa" }}
            onClick={async () => {
              if (isHibernating) await resumeServer(s.name);
              else await pauseServer(s.name);
              onRefresh();
            }}
          >
            {isHibernating ? t("srv.resume", lang) : t("srv.pause", lang)}
          </button>
        )}
        {!isComposite && (
          <button
            style={{ ...styles.mktActionBtn, color: "#ef4444" }}
            onClick={async () => { await stopServer(s.name); onRefresh(); }}
          >
            {t("srv.stop", lang)}
          </button>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Orphans Tab
// ══════════════════════════════════════════════════════════════════════════════

function OrphansTab({ data, loading, lang, expandedServers, expandedSchemas, onToggleServer, onToggleSchema }: {
  data: OrphanToolsResponse | null;
  loading: boolean;
  lang: Lang;
  expandedServers: Set<string>;
  expandedSchemas: Set<string>;
  onToggleServer: (name: string) => void;
  onToggleSchema: (key: string) => void;
}) {
  if (loading) return <p style={styles.loading}>{t("srv.orphan_loading", lang)}</p>;
  if (!data) return <p style={styles.hint}>Failed to load orphan data.</p>;

  const { orphans, fragile, robust, summary } = data;

  // Group orphans by server
  const grouped: Record<string, OrphanTool[]> = {};
  for (const o of orphans) {
    if (!grouped[o.server]) grouped[o.server] = [];
    grouped[o.server].push(o);
  }

  const serverNames = Object.keys(grouped).sort();

  return (
    <div>
      {/* Summary bar */}
      <div style={styles.orphanSummaryBar}>
        <span style={styles.orphanSummaryText}>
          {t("srv.orphan_count", lang)
            .replace("{n}", String(summary.orphan_count))
            .replace("{m}", String(serverNames.length))}
        </span>
        <div style={styles.orphanSummaryTags}>
          <span style={styles.orphanTagDanger}>
            {t("srv.orphan_fragile", lang).replace("{n}", String(summary.fragile_count))}
          </span>
          <span style={styles.orphanTagOk}>
            {t("srv.orphan_robust", lang).replace("{n}", String(summary.robust_count))}
          </span>
          <span style={styles.orphanTagMuted}>Total: {summary.total_tools}</span>
        </div>
      </div>

      {orphans.length === 0 ? (
        <p style={styles.ok}>{t("srv.orphan_empty", lang)}</p>
      ) : (
        <div style={styles.orphanServerList}>
          {serverNames.map((serverName) => {
            const serverOrphans = grouped[serverName];
            const isExpanded = expandedServers.has(serverName);
            return (
              <div key={serverName} style={styles.orphanServerGroup}>
                <button
                  style={styles.orphanServerHeader}
                  onClick={() => onToggleServer(serverName)}
                >
                  <span style={styles.orphanChevron}>{isExpanded ? "▾" : "▸"}</span>
                  <span style={styles.orphanServerName}>{serverName}</span>
                  <span style={styles.orphanServerCount}>{serverOrphans.length} tools</span>
                </button>

                {isExpanded && (
                  <div style={styles.orphanToolList}>
                    {serverOrphans.map((tool) => {
                      const schemaKey = `${tool.server}::${tool.name}`;
                      const schemaOpen = expandedSchemas.has(schemaKey);
                      return (
                        <div key={tool.name} style={styles.orphanToolCard}>
                          <div style={styles.orphanToolHeader}>
                            <span style={styles.orphanToolName}>{tool.name}</span>
                            <span style={styles.orphanToolServer}>{tool.server}</span>
                          </div>
                          <p style={styles.orphanToolDesc}>{tool.description}</p>

                          {/* Reachability indicators */}
                          <div style={styles.orphanPaths}>
                            <span style={styles.orphanPathLabel}>{t("srv.orphan_paths", lang)}:</span>
                            <span style={styles.orphanPathChip} title={t("srv.orphan_llm", lang)}>
                              {tool.reachability.llm_path ? "✅" : "❌"} {t("srv.orphan_llm", lang)}
                            </span>
                            <span style={styles.orphanPathChip} title={t("srv.orphan_frontend", lang)}>
                              {tool.reachability.frontend_path ? "✅" : "❌"} {t("srv.orphan_frontend", lang)}
                            </span>
                            <span style={styles.orphanPathChip} title={t("srv.orphan_pipeline", lang)}>
                              {tool.reachability.pipeline_path ? "✅" : "❌"} {t("srv.orphan_pipeline", lang)}
                            </span>
                          </div>

                          {/* Why orphaned hint */}
                          {tool.paths === 0 && (
                            <p style={styles.orphanWhy}>{t("srv.orphan_why", lang)}</p>
                          )}

                          {/* View Schema toggle */}
                          <button
                            style={styles.orphanSchemaToggle}
                            onClick={() => onToggleSchema(schemaKey)}
                          >
                            {schemaOpen ? t("srv.orphan_hide_schema", lang) : t("srv.orphan_view_schema", lang)}
                          </button>
                          {schemaOpen && (
                            <pre style={styles.orphanSchemaPre}>
                              {JSON.stringify(tool.input_schema, null, 2)}
                            </pre>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Shared sub-components
// ══════════════════════════════════════════════════════════════════════════════

function StatPill({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ ...styles.statPill, borderColor: color }}>
      <span style={{ ...styles.statPillValue, color }}>{value}</span>
      <span style={styles.statPillLabel}>{label}</span>
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

function DepsList({ edges = [] }: { edges?: Array<{ from: string; to: string; type: string }> }) {
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

// ══════════════════════════════════════════════════════════════════════════════
// Styles
// ══════════════════════════════════════════════════════════════════════════════
