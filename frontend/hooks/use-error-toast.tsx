"use client";

import { useEffect, useState, useCallback } from "react";

interface Toast {
  id: number;
  message: string;
  timestamp: number;
}

let _nextId = 1;
const MAX_TOASTS = 3;

export function useErrorToast() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((message: string) => {
    const toast: Toast = { id: _nextId++, message, timestamp: Date.now() };
    setToasts((prev) => [toast, ...prev].slice(0, MAX_TOASTS));
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== toast.id));
    }, 5000);
  }, []);

  useEffect(() => {
    const onError = (e: ErrorEvent) => {
      addToast(e.message || "An unexpected error occurred");
    };
    const onUnhandledRejection = (e: PromiseRejectionEvent) => {
      const msg = e.reason?.message || String(e.reason || "Promise rejected");
      addToast(msg.slice(0, 120));
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onUnhandledRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onUnhandledRejection);
    };
  }, [addToast]);

  const ToastContainer = toasts.length === 0 ? null : (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="pointer-events-auto rounded-lg border border-red-500/30 bg-[#0f172a]/95 backdrop-blur-sm px-4 py-2.5 shadow-xl shadow-black/30 text-xs text-red-300 max-w-sm animate-in fade-in slide-in-from-bottom-2"
        >
          {t.message}
        </div>
      ))}
    </div>
  );

  return { toasts, addToast, ToastContainer };
}
