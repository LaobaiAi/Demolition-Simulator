"use client";

import { useState, useCallback } from "react";
import { safeGetItem, safeSetItem, safeParseJson } from "@/lib/safe-storage";
import type { Conversation } from "@/components/sidebar";
import type { ChatMessage } from "@/lib/state-restore";

const CONV_STORAGE = "xuanwu_conversations";
const CONV_ACTIVE = "xuanwu_active_conv";

interface StoredConv {
  id: string;
  title: string;
  pinned: boolean;
  createdAt: number;
  messages: ChatMessage[];
}

function genId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [convLoaded, setConvLoaded] = useState(false);

  const saveConvs = useCallback((convs: Conversation[], msgs: ChatMessage[], activeId: string | null) => {
    localStorage.setItem(CONV_ACTIVE, activeId || "");
    try {
      const existing = JSON.parse(localStorage.getItem(CONV_STORAGE) || "[]") as StoredConv[];
      const stored: StoredConv[] = convs.map((c) => {
        const prev = existing.find((e) => e.id === c.id);
        if (c.id === activeId) {
          return { ...c, messages: msgs };
        }
        return { ...c, messages: prev?.messages || [] };
      });
      safeSetItem(CONV_STORAGE, JSON.stringify(stored));
    } catch {}
  }, []);

  const loadConversationsFromStorage = useCallback((): StoredConv[] => {
    const saved = safeGetItem(CONV_STORAGE);
    return safeParseJson<StoredConv[]>(saved, []);
  }, []);

  const newConversation = useCallback(() => {
    const id = genId();
    const now = Date.now();
    const conv: Conversation = { id, title: "New conversation", pinned: false, createdAt: now, messageCount: 0 };
    const updated = [conv, ...conversations];
    setConversations(updated);
    setActiveConvId(id);
    saveConvs(updated, [], id);
    return id;
  }, [conversations, saveConvs]);

  const selectConversation = useCallback((id: string, currentMessages?: ChatMessage[]) => {
    if (id === activeConvId) return null;
    const stored = loadConversationsFromStorage();
    const updated = stored.map((c) => {
      if (c.id === activeConvId && currentMessages) return { ...c, messages: currentMessages };
      return c;
    });
    localStorage.setItem(CONV_STORAGE, JSON.stringify(updated));

    setActiveConvId(id);
    const target = updated.find((c) => c.id === id);
    return target?.messages || null;
  }, [activeConvId, loadConversationsFromStorage]);

  const deleteConversation = useCallback((id: string) => {
    const updated = conversations.filter((c) => c.id !== id);
    setConversations(updated);
    if (id === activeConvId) setActiveConvId(null);
    const stored = loadConversationsFromStorage().filter((c) => c.id !== id);
    safeSetItem(CONV_STORAGE, JSON.stringify(stored));
    if (id === activeConvId) localStorage.setItem(CONV_ACTIVE, "");
  }, [conversations, activeConvId, loadConversationsFromStorage]);

  const renameConversation = useCallback((id: string, title: string) => {
    setConversations((prev) => prev.map((c) => c.id === id ? { ...c, title } : c));
    const stored = loadConversationsFromStorage();
    localStorage.setItem(CONV_STORAGE, JSON.stringify(stored.map((c) => c.id === id ? { ...c, title } : c)));
  }, [loadConversationsFromStorage]);

  const togglePinConversation = useCallback((id: string) => {
    setConversations((prev) => prev.map((c) => c.id === id ? { ...c, pinned: !c.pinned } : c));
    const stored = loadConversationsFromStorage();
    localStorage.setItem(CONV_STORAGE, JSON.stringify(stored.map((c) => c.id === id ? { ...c, pinned: !c.pinned } : c)));
  }, [loadConversationsFromStorage]);

  const updateMessageCount = useCallback((id: string, count: number) => {
    setConversations((prev) => {
      const found = prev.find((c) => c.id === id);
      if (found && found.messageCount !== count) {
        return prev.map((c) => c.id === id ? { ...c, messageCount: count } : c);
      }
      return prev;
    });
  }, []);

  const autoTitle = useCallback((id: string, firstUserMessage: string) => {
    setConversations((prev) => {
      const found = prev.find((c) => c.id === id);
      if (found && found.title === "New conversation") {
        const title = firstUserMessage.slice(0, 40) + (firstUserMessage.length > 40 ? "..." : "");
        const stored = loadConversationsFromStorage();
        const si = stored.findIndex((c) => c.id === id);
        if (si >= 0) stored[si].title = title;
        safeSetItem(CONV_STORAGE, JSON.stringify(stored));
        return prev.map((c) => c.id === id ? { ...c, title } : c);
      }
      return prev;
    });
  }, [loadConversationsFromStorage]);

  const syncMessagesToStorage = useCallback((id: string, messages: ChatMessage[]) => {
    const stored = loadConversationsFromStorage();
    const idx = stored.findIndex((c) => c.id === id);
    if (idx >= 0) {
      stored[idx].messages = messages;
      safeSetItem(CONV_STORAGE, JSON.stringify(stored));
    }
    updateMessageCount(id, messages.length);
    const firstUser = messages.find((m) => m.role === "user");
    if (firstUser) autoTitle(id, firstUser.content);
  }, [loadConversationsFromStorage, updateMessageCount, autoTitle]);

  return {
    conversations, setConversations,
    activeConvId, setActiveConvId,
    convLoaded, setConvLoaded,
    saveConvs,
    newConversation,
    selectConversation,
    deleteConversation,
    renameConversation,
    togglePinConversation,
    syncMessagesToStorage,
  };
}
