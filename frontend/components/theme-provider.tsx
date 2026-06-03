"use client";

import { createContext, useContext, useState, useCallback, useLayoutEffect, type ReactNode } from "react";

export interface Theme {
  key: string;
  name: string;
  nameZh: string;
  colors: string[]; // 4 swatch colors for preview
}

export const THEMES: Theme[] = [
  {
    key: "theme-xuanwu-dark",
    name: "Xuanwu Dark",
    nameZh: "玄武暗",
    colors: ["#0f172a", "#22d3ee", "#1e293b", "#e2e8f0"],
  },
  {
    key: "theme-light",
    name: "Light",
    nameZh: "亮色",
    colors: ["#ffffff", "#0284c7", "#f1f5f9", "#1e293b"],
  },
  {
    key: "theme-forest",
    name: "Forest",
    nameZh: "森林绿",
    colors: ["#0a1a0f", "#10b981", "#122618", "#d4e8d0"],
  },
  {
    key: "theme-sunset",
    name: "Sunset",
    nameZh: "日落橙",
    colors: ["#1a1214", "#f97316", "#24181a", "#f0dfd8"],
  },
  {
    key: "theme-midnight",
    name: "Midnight",
    nameZh: "午夜紫",
    colors: ["#0b0d1e", "#8b5cf6", "#131636", "#d3d5f0"],
  },
  {
    key: "theme-steel",
    name: "Steel",
    nameZh: "钢铁灰",
    colors: ["#111318", "#6b8ca3", "#191c22", "#d8dce3"],
  },
];

const DEFAULT_THEME = THEMES[0].key;
const STORAGE_KEY = "xuanwu_theme";

interface ThemeContextValue {
  theme: string;
  setTheme: (key: string) => void;
  themes: Theme[];
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: DEFAULT_THEME,
  setTheme: () => {},
  themes: THEMES,
});

export function useTheme() {
  return useContext(ThemeContext);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState(DEFAULT_THEME);

  // Initialize theme from localStorage before first paint
  useLayoutEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      const themeKey = saved && THEMES.some((t) => t.key === saved) ? saved : DEFAULT_THEME;
      setThemeState(themeKey);
      const root = document.documentElement;
      // Add theme classes (swap from SSR default theme-xuanwu-dark)
      for (const t of THEMES) root.classList.remove(t.key);
      if (themeKey !== "theme-light") root.classList.add("dark");
      else root.classList.remove("dark");
      root.classList.add(themeKey);
    } catch {}
  }, []);

  const setTheme = useCallback((key: string) => {
    setThemeState(key);
    const root = document.documentElement;
    for (const t of THEMES) {
      root.classList.remove(t.key);
    }
    root.classList.remove("dark");
    root.classList.add(key);
    if (key !== "theme-light") {
      root.classList.add("dark");
    }
    try {
      localStorage.setItem(STORAGE_KEY, key);
    } catch {}
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, themes: THEMES }}>
      {children}
    </ThemeContext.Provider>
  );
}
