const CORRUPTION_PREFIX = "_corrupted_";

export function safeGetItem(key: string): string | null {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return null;
    JSON.parse(raw);
    return raw;
  } catch {
    try {
      const raw = localStorage.getItem(key);
      if (raw) {
        const ts = Date.now();
        localStorage.setItem(`${CORRUPTION_PREFIX}${key}_${ts}`, raw);
        console.warn(`[storage] Corrupted data for "${key}" backed up to "${CORRUPTION_PREFIX}${key}_${ts}"`);
      }
    } catch { /* can't even backup */ }
    localStorage.removeItem(key);
    return null;
  }
}

export function safeSetItem(key: string, value: string): boolean {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch {
    console.warn(`[storage] Failed to write "${key}" — storage may be full`);
    return false;
  }
}

export function safeParseJson<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}
