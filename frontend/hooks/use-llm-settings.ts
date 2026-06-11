"use client";

import { useState, useEffect, useCallback } from "react";
import { getSavedLang, saveLang, type Lang } from "@/lib/i18n";

const LLM_STORAGE_KEY = "xuanwu_llm_profiles";

async function fetchWithTimeout(url: string, options: RequestInit = {}, timeoutMs = 8000): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function loadProfiles(): Record<string, { api_key: string; base_url: string }> {
  try {
    const saved = localStorage.getItem(LLM_STORAGE_KEY);
    if (saved) return JSON.parse(saved);
  } catch {}
  return {};
}

function saveProfiles(profiles: Record<string, { api_key: string; base_url: string }>) {
  localStorage.setItem(LLM_STORAGE_KEY, JSON.stringify(profiles));
}

export function useLlmSettings() {
  const [lang, setLang] = useState<Lang>(() => getSavedLang());

  useEffect(() => {
    document.documentElement.setAttribute("data-lang", lang);
  }, [lang]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState("llm");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [llmModel, setLlmModel] = useState("gpt-4o");
  const [llmStatus, setLlmStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [llmTestStatus, setLlmTestStatus] = useState<"idle" | "testing" | "success" | "error">("idle");
  const [llmTestMsg, setLlmTestMsg] = useState("");
  const [thinkingEnabled, setThinkingEnabled] = useState(false);

  const handleLangChange = useCallback((newLang: Lang) => {
    setLang(newLang);
    saveLang(newLang);
    document.documentElement.setAttribute("data-lang", newLang);
  }, []);

  useEffect(() => {
    const initFromBackend = async () => {
      try {
        const res = await fetchWithTimeout("http://localhost:8000/settings/llm");
        if (res.ok) {
          const backend = await res.json();
          if (backend.has_api_key && backend.model) {
            setLlmModel(backend.model);
            setLlmApiKey("••••••••");
            setLlmBaseUrl(backend.base_url || "");
            localStorage.setItem("xuanwu_last_model", backend.model);
            if (backend.thinking_enabled !== undefined) {
              setThinkingEnabled(backend.thinking_enabled);
            }
            return;
          }
        }
      } catch {}

      const profiles = loadProfiles();
      const saved = localStorage.getItem("xuanwu_llm_settings");
      if (saved && Object.keys(profiles).length === 0) {
        try {
          const parsed = JSON.parse(saved);
          const model = parsed.model || "gpt-4o";
          profiles[model] = { api_key: parsed.api_key || "", base_url: parsed.base_url || "" };
          saveProfiles(profiles);
          localStorage.removeItem("xuanwu_llm_settings");
        } catch {}
      }
      const lastModel = localStorage.getItem("xuanwu_last_model") || "gpt-4o";
      setLlmModel(lastModel);
      const profile = profiles[lastModel];
      if (profile) {
        setLlmApiKey(profile.api_key || "");
        setLlmBaseUrl(profile.base_url || "");
        fetchWithTimeout("http://localhost:8000/settings/llm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: lastModel, api_key: profile.api_key, base_url: profile.base_url }),
        }).catch(() => {});
      }
    };
    initFromBackend();
  }, []);

  const handleModelChange = useCallback((newModel: string) => {
    setLlmModel(newModel);
    const profiles = loadProfiles();
    const profile = profiles[newModel];
    if (profile) {
      setLlmApiKey(profile.api_key || "");
      setLlmBaseUrl(profile.base_url || "");
    } else {
      setLlmApiKey("");
      setLlmBaseUrl("");
    }
  }, []);

  const saveLlmSettings = useCallback(async () => {
    setLlmStatus("saving");
    const config: Record<string, string | boolean | undefined> = {
      model: llmModel || undefined,
      thinking_enabled: thinkingEnabled,
    };
    if (llmBaseUrl) config.base_url = llmBaseUrl;
    if (llmApiKey && llmApiKey !== "••••••••") {
      config.api_key = llmApiKey;
    }
    try {
      const res = await fetchWithTimeout("http://localhost:8000/settings/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      if (!res.ok) throw new Error("Failed");
      const profiles = loadProfiles();
      const existingKey = llmApiKey !== "••••••••" ? llmApiKey : (profiles[llmModel]?.api_key || "");
      profiles[llmModel] = { api_key: existingKey, base_url: llmBaseUrl };
      saveProfiles(profiles);
      localStorage.setItem("xuanwu_last_model", llmModel);
      setLlmStatus("saved");
      setTimeout(() => setLlmStatus("idle"), 2000);
    } catch {
      setLlmStatus("error");
      setTimeout(() => setLlmStatus("idle"), 3000);
    }
  }, [llmModel, llmApiKey, llmBaseUrl]);

  const testLlmConnection = useCallback(async () => {
    setLlmTestStatus("testing");
    setLlmTestMsg("");
    try {
      const key = llmApiKey && llmApiKey !== "••••••••" ? llmApiKey : "";
      const res = await fetch("http://localhost:8000/settings/llm/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          api_key: key || undefined,
          base_url: llmBaseUrl || undefined,
          model: llmModel || undefined,
        }),
      });
      const data = await res.json();
      if (data.status === "ok") {
        setLlmTestStatus("success");
        setLlmTestMsg(data.message || "Connection successful");
      } else {
        throw new Error(data.message || "Connection failed");
      }
    } catch (err) {
      setLlmTestStatus("error");
      setLlmTestMsg(err instanceof Error ? err.message : "Connection failed");
    }
  }, [llmModel, llmApiKey, llmBaseUrl]);

  return {
    lang, setLang,
    handleLangChange,
    settingsOpen, setSettingsOpen,
    settingsTab, setSettingsTab,
    llmApiKey, setLlmApiKey,
    llmBaseUrl, setLlmBaseUrl,
    llmModel, setLlmModel,
    llmStatus,
    llmTestStatus,
    llmTestMsg,
    handleModelChange,
    saveLlmSettings,
    testLlmConnection,
    thinkingEnabled, setThinkingEnabled,
  };
}
