"use client";

import { useCallback, useEffect, useState } from "react";
import { safeGetItem, safeSetItem, safeParseJson } from "@/lib/safe-storage";

const FAV_KEY = "xuanwu_demo_favorites";

export function loadDemoFavorites(): string[] {
  if (typeof window === "undefined") return [];
  const raw = safeGetItem(FAV_KEY);
  if (!raw) return [];
  const parsed = safeParseJson<unknown>(raw, []);
  return Array.isArray(parsed)
    ? parsed.filter((x): x is string => typeof x === "string")
    : [];
}

export function useDemoFavorites() {
  const [favorites, setFavorites] = useState<string[]>(loadDemoFavorites);

  useEffect(() => {
    if (typeof window === "undefined") return;
    safeSetItem(FAV_KEY, JSON.stringify(favorites));
  }, [favorites]);

  const isFavorite = useCallback(
    (key: string) => favorites.includes(key),
    [favorites]
  );

  const toggleFavorite = useCallback((key: string) => {
    setFavorites((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  }, []);

  return { favorites, isFavorite, toggleFavorite };
}
