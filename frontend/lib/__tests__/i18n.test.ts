import { describe, it, expect, beforeEach, vi } from "vitest";
import { t, getSavedLang, saveLang } from "@/lib/i18n";

describe("t()", () => {
  it("returns English text when lang is en", () => {
    expect(t("chat.title", "en")).toBe("Demolition Simulator");
  });

  it("returns Chinese text when lang is zh", () => {
    expect(t("chat.title", "zh")).toBe("Demolition Simulator");
    expect(t("sidebar.new_chat", "zh")).toBe("新建对话");
  });

  it("falls back to English when zh translation is missing", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    (window as unknown as Record<string, unknown>).__i18n_warned_missing_test = undefined;
    const result = t("nonexistent_key_12345", "zh");
    expect(result).toBe("nonexistent_key_12345");
    warnSpy.mockRestore();
  });

  it("returns key itself when no translation exists in either language", () => {
    const result = t("completely.unknown.key", "en");
    expect(result).toBe("completely.unknown.key");
  });
});

describe("getSavedLang / saveLang", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns en by default", () => {
    expect(getSavedLang()).toBe("en");
  });

  it("returns saved language", () => {
    saveLang("zh");
    expect(getSavedLang()).toBe("zh");
  });

  it("falls back to en for invalid values", () => {
    localStorage.setItem("xuanwu_language", "fr");
    expect(getSavedLang()).toBe("en");
  });
});
