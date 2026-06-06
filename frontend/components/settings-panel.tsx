"use client";

import { Settings, Brain, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { t, type Lang } from "@/lib/i18n";
import { THEMES } from "@/components/theme-provider";

const COMMON_MODELS = ["gpt-4o", "gpt-4o-mini", "deepseek-v4-pro", "deepseek-v4-chat", "claude-sonnet-4-6", "claude-opus-4-7"];

function SettingsTabs({
  tabs,
  activeTab,
  onTabChange,
}: {
  tabs: { key: string; label: string }[];
  activeTab: string;
  onTabChange: (key: string) => void;
}) {
  return (
    <div className="flex border-b border-border mb-1">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onTabChange(tab.key)}
          className={`flex-1 px-3 py-2 text-sm font-medium transition-colors cursor-pointer border-b-2 -mb-[1px] ${
            activeTab === tab.key
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

interface Props {
  lang: Lang;
  open: boolean;
  onClose: () => void;
  tab: string;
  onTabChange: (tab: string) => void;
  llmApiKey: string;
  setLlmApiKey: (v: string) => void;
  llmBaseUrl: string;
  setLlmBaseUrl: (v: string) => void;
  llmModel: string;
  onModelChange: (v: string) => void;
  llmStatus: "idle" | "saving" | "saved" | "error";
  llmTestStatus: "idle" | "testing" | "success" | "error";
  llmTestMsg: string;
  onSaveLlm: () => Promise<void>;
  onTestLlm: () => Promise<void>;
  thinkingEnabled: boolean;
  setThinkingEnabled: (v: boolean) => void;
  theme: string;
  setTheme: (t: string) => void;
  onLangChange: (l: Lang) => void;
  onClearConversations: () => void;
  onClearMemory: () => Promise<void>;
  onExportBackup: () => void;
  memoryOpen: boolean;
  setMemoryOpen: (v: boolean) => void;
  memorySnippets: string[];
}

export default function SettingsPanel({
  lang,
  open,
  onClose,
  tab,
  onTabChange,
  llmApiKey,
  setLlmApiKey,
  llmBaseUrl,
  setLlmBaseUrl,
  llmModel,
  onModelChange,
  llmStatus,
  llmTestStatus,
  llmTestMsg,
  onSaveLlm,
  onTestLlm,
  thinkingEnabled,
  setThinkingEnabled,
  theme,
  setTheme,
  onLangChange,
  onClearConversations,
  onClearMemory,
  onExportBackup,
  memoryOpen,
  setMemoryOpen,
  memorySnippets,
}: Props) {
  return (
    <>
      <Dialog open={open} onOpenChange={onClose}>
        <DialogContent className="border-border max-w-2xl h-[540px] flex flex-col overflow-hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings className="h-4 w-4 text-primary" />
              {t("settings.title", lang)}
            </DialogTitle>
          </DialogHeader>

          <SettingsTabs
            tabs={[
              { key: "llm", label: t("settings.tab_llm", lang) },
              { key: "appearance", label: t("settings.tab_appearance", lang) },
              { key: "storage", label: t("settings.tab_storage", lang) },
            ]}
            activeTab={tab}
            onTabChange={onTabChange}
          />

          <div className="flex-1 overflow-y-auto min-h-0">
            {tab === "llm" && (
              <div className="space-y-4">
                <div>
                  <label className="text-sm font-medium text-muted-foreground uppercase tracking-wide">{t("settings.api_key", lang)}</label>
                  <input
                    type="password"
                    value={llmApiKey}
                    onChange={(e) => setLlmApiKey(e.target.value)}
                    placeholder="sk-..."
                    className="mt-1 h-9 w-full rounded-lg border border-border bg-transparent px-2.5 py-1 text-base outline-none focus:border-primary/50 transition-colors"
                  />
                  <p className="text-xs text-muted-foreground mt-0.5">{t("settings.api_key_hint", lang)}</p>
                </div>
                <div>
                  <label className="text-sm font-medium text-muted-foreground uppercase tracking-wide">{t("settings.base_url", lang)}</label>
                  <input
                    type="text"
                    value={llmBaseUrl}
                    onChange={(e) => setLlmBaseUrl(e.target.value)}
                    placeholder="https://api.openai.com/v1"
                    className="mt-1 h-9 w-full rounded-lg border border-border bg-transparent px-2.5 py-1 text-base outline-none focus:border-primary/50 transition-colors"
                  />
                  <p className="text-xs text-muted-foreground mt-0.5">{t("settings.base_url_hint", lang)}</p>
                </div>
                <div>
                  <label className="text-sm font-medium text-muted-foreground uppercase tracking-wide">{t("settings.model", lang)}</label>
                  <input
                    type="text"
                    value={llmModel}
                    onChange={(e) => onModelChange(e.target.value)}
                    placeholder="gpt-4o"
                    list="llm-model-presets"
                    className="mt-1 h-9 w-full rounded-lg border border-border bg-transparent px-2.5 py-1 text-base outline-none focus:border-primary/50 transition-colors"
                  />
                  <datalist id="llm-model-presets">
                    {COMMON_MODELS.map((m) => (
                      <option key={m} value={m} />
                    ))}
                  </datalist>
                  <p className="text-xs text-muted-foreground mt-0.5">{t("settings.model_hint", lang)}</p>
                </div>
                <div>
                  <label className="text-sm font-medium text-muted-foreground uppercase tracking-wide">{t("settings.thinking_mode", lang)}</label>
                  <div className="mt-2 flex items-center gap-3">
                    <button
                      onClick={() => setThinkingEnabled(!thinkingEnabled)}
                      className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors cursor-pointer ${
                        thinkingEnabled ? "bg-primary/40" : "bg-muted-foreground/20"
                      }`}
                    >
                      <span
                        className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${
                          thinkingEnabled ? "translate-x-6" : "translate-x-1"
                        }`}
                      />
                    </button>
                    <span className="text-sm text-muted-foreground">
                      {thinkingEnabled ? t("settings.thinking_on", lang) : t("settings.thinking_off", lang)}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">{t("settings.thinking_hint", lang)}</p>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={onTestLlm}
                    disabled={llmTestStatus === "testing"}
                    className="h-9 px-4 rounded-lg border border-border text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors disabled:opacity-50 cursor-pointer"
                  >
                    {llmTestStatus === "testing" ? (
                      <span className="flex items-center gap-1.5">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        Testing...
                      </span>
                    ) : (
                      "Test Connection"
                    )}
                  </button>
                  {llmTestStatus !== "idle" && (
                    <span className={`text-xs ${
                      llmTestStatus === "success" ? "text-emerald-400" :
                      llmTestStatus === "error" ? "text-red-400" : "text-muted-foreground"
                    }`}>
                      {llmTestStatus === "testing" ? "Testing..." :
                       llmTestStatus === "success" ? "✓ " + llmTestMsg :
                       "✗ " + llmTestMsg}
                    </span>
                  )}
                </div>
                <DialogFooter className="flex items-center gap-2 pt-2">
                  {llmStatus === "saved" && (
                    <span className="text-xs text-emerald-400 mr-auto">{t("settings.saved", lang)}</span>
                  )}
                  {llmStatus === "error" && (
                    <span className="text-xs text-red-400 mr-auto">{t("settings.failed", lang)}</span>
                  )}
                  <Button variant="outline" onClick={onClose}>
                    {t("settings.cancel", lang)}
                  </Button>
                  <Button onClick={onSaveLlm} disabled={llmStatus === "saving"}>
                    {llmStatus === "saving" ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                        {t("settings.saving", lang)}
                      </>
                    ) : (
                      t("settings.save", lang)
                    )}
                  </Button>
                </DialogFooter>
              </div>
            )}

            {tab === "appearance" && (
              <div className="space-y-5">
                <div>
                  <label className="text-sm font-medium text-muted-foreground uppercase tracking-wide">{t("settings.language", lang)}</label>
                  <div className="mt-2 flex items-center gap-3">
                    <button
                      onClick={() => onLangChange("en")}
                      className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors cursor-pointer ${
                        lang === "en"
                          ? "bg-primary/20 text-primary border border-primary/50"
                          : "bg-muted text-muted-foreground border border-border hover:bg-muted/80"
                      }`}
                    >
                      English
                    </button>
                    <button
                      onClick={() => onLangChange("zh")}
                      className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors cursor-pointer ${
                        lang === "zh"
                          ? "bg-primary/20 text-primary border border-primary/50"
                          : "bg-muted text-muted-foreground border border-border hover:bg-muted/80"
                      }`}
                    >
                      中文
                    </button>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1.5">{t("settings.language_hint", lang)}</p>
                </div>
                <div>
                  <label className="text-sm font-medium text-muted-foreground uppercase tracking-wide">{t("settings.theme", lang)}</label>
                  <div className="mt-2 grid grid-cols-3 gap-2">
                    {THEMES.map((th) => {
                      const active = theme === th.key;
                      return (
                        <button
                          key={th.key}
                          onClick={() => setTheme(th.key)}
                          className={`flex flex-col items-center gap-1.5 rounded-lg p-2 border transition-all cursor-pointer ${
                            active
                              ? "border-primary bg-primary/10 ring-1 ring-primary/30"
                              : "border-border bg-muted/20 hover:border-muted-foreground/40"
                          }`}
                        >
                          <div className="flex gap-0.5">
                            {th.colors.map((c, i) => (
                              <span
                                key={i}
                                className="w-5 h-5 rounded-full border border-white/10"
                                style={{ backgroundColor: c }}
                              />
                            ))}
                          </div>
                          <span className={`text-xs font-medium ${active ? "text-primary" : "text-foreground"}`}>
                            {lang === "zh" ? th.nameZh : th.name}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {tab === "storage" && (
              <div className="space-y-3">
                <div className="flex items-center justify-between rounded-lg border border-border bg-muted/20 px-3 py-2">
                  <div>
                    <span className="text-sm text-foreground">{t("settings.conv_storage", lang)}</span>
                    <p className="text-xs text-muted-foreground">{t("settings.conv_storage_hint", lang)}</p>
                  </div>
                  <button
                    onClick={onClearConversations}
                    className="px-3 py-1 text-xs font-medium text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/10 transition-colors cursor-pointer shrink-0"
                  >
                    {t("settings.clear", lang)}
                  </button>
                </div>
                <div className="flex items-center justify-between rounded-lg border border-border bg-muted/20 px-3 py-2">
                  <div>
                    <span className="text-sm text-foreground">{t("settings.memory_storage", lang)}</span>
                    <p className="text-xs text-muted-foreground">{t("settings.memory_storage_hint", lang)}</p>
                  </div>
                  <button
                    onClick={onClearMemory}
                    className="px-3 py-1 text-xs font-medium text-amber-400 border border-amber-500/30 rounded-lg hover:bg-amber-500/10 transition-colors cursor-pointer shrink-0"
                  >
                    {t("settings.clear", lang)}
                  </button>
                </div>
                <div className="flex items-center justify-between rounded-lg border border-border bg-muted/20 px-3 py-2">
                  <div>
                    <span className="text-sm text-foreground">{t("settings.export", lang)}</span>
                    <p className="text-xs text-muted-foreground">{t("settings.export_hint", lang)}</p>
                  </div>
                  <button
                    onClick={onExportBackup}
                    className="px-3 py-1 text-xs font-medium text-primary border border-primary/30 rounded-lg hover:bg-primary/10 transition-colors cursor-pointer shrink-0"
                  >
                    {t("settings.download", lang)}
                  </button>
                </div>
                <DialogFooter>
                  <Button variant="outline" className="w-full" onClick={onClose}>
                    {t("settings.close", lang)}
                  </Button>
                </DialogFooter>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={memoryOpen} onOpenChange={setMemoryOpen}>
        <DialogContent className="border-border max-w-lg max-h-[60vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Brain className="h-4 w-4 text-primary" />
              {t("memory.title", lang)}
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-y-auto space-y-2 px-1">
            {memorySnippets.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">{t("memory.empty", lang)}</p>
            ) : (
              memorySnippets.map((snippet, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-border bg-card p-3 text-[12px] text-muted-foreground leading-relaxed"
                >
                  {snippet.replace("## Relevant Context (from past conversations):\n", "")}
                </div>
              ))
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
