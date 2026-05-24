"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  Plus,
  Search,
  MessageSquare,
  Pin,
  PinOff,
  Trash2,
  Pencil,
  Check,
  X,
  ChevronLeft,
  ChevronRight,
  Settings,
  MoreHorizontal,
  Library,
  Wrench,
  Brain,
} from "lucide-react";

export interface Conversation {
  id: string;
  title: string;
  pinned: boolean;
  createdAt: number;
  messageCount: number;
}

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  collapsed: boolean;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onTogglePin: (id: string) => void;
  onToggleCollapse: () => void;
  onOpenSettings: () => void;
  onOpenDemoLibrary: () => void;
  onOpenTools?: () => void;
  onOpenMemory?: () => void;
  toolsCount?: number;
}

export function Sidebar({
  conversations,
  activeId,
  collapsed,
  onNew,
  onSelect,
  onDelete,
  onRename,
  onTogglePin,
  onToggleCollapse,
  onOpenSettings,
  onOpenDemoLibrary,
  onOpenTools,
  onOpenMemory,
  toolsCount,
}: Props) {
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const editRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (editingId && editRef.current) {
      editRef.current.focus();
      editRef.current.select();
    }
  }, [editingId]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpenId(null);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const startRename = useCallback((conv: Conversation) => {
    setEditingId(conv.id);
    setEditTitle(conv.title);
    setMenuOpenId(null);
  }, []);

  const commitRename = useCallback(() => {
    if (editingId && editTitle.trim()) {
      onRename(editingId, editTitle.trim());
    }
    setEditingId(null);
  }, [editingId, editTitle, onRename]);

  const cancelRename = useCallback(() => {
    setEditingId(null);
  }, []);

  const filtered = search.trim()
    ? conversations.filter(
        (c) =>
          c.title.toLowerCase().includes(search.toLowerCase())
      )
    : conversations;

  const pinnedConvs = filtered.filter((c) => c.pinned);
  const unpinnedConvs = filtered.filter((c) => !c.pinned);

  if (collapsed) {
    return (
      <div className="flex w-14 min-w-[56px] flex-col items-center border-r border-border py-3 gap-3 bg-[#060a12] h-full">
        <button
          onClick={onToggleCollapse}
          className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-muted transition-colors cursor-pointer"
          title="Expand sidebar"
        >
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        </button>
        <button
          onClick={onNew}
          className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/20 hover:bg-primary/30 transition-colors cursor-pointer"
          title="New Chat"
        >
          <Plus className="h-5 w-5 text-primary" />
        </button>
        <div className="flex-1 flex flex-col items-center gap-2 overflow-y-auto">
          {conversations.filter((c) => c.pinned).slice(0, 5).map((conv) => (
            <button
              key={conv.id}
              onClick={() => onSelect(conv.id)}
              className={`flex h-8 w-8 items-center justify-center rounded-lg text-[10px] font-medium transition-colors cursor-pointer ${
                conv.id === activeId
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:bg-muted"
              }`}
              title={conv.title}
            >
              {conv.title.slice(0, 2).toUpperCase()}
            </button>
          ))}
        </div>
        {/* Bottom: Tools + Memory + Demo Library + Settings + 玄武 */}
        <div className="flex flex-col items-center gap-2 pb-2">
          <button
            onClick={onOpenTools}
            className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-muted transition-colors cursor-pointer"
            title={`Available Tools (${toolsCount ?? 0})`}
          >
            <Wrench className="h-4 w-4 text-muted-foreground hover:text-foreground" />
          </button>
          <button
            onClick={onOpenMemory}
            className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-muted transition-colors cursor-pointer"
            title="Context Memory"
          >
            <Brain className="h-4 w-4 text-muted-foreground hover:text-foreground" />
          </button>
          <button
            onClick={onOpenDemoLibrary}
            className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-muted transition-colors cursor-pointer"
            title="Demo Library"
          >
            <Library className="h-4 w-4 text-muted-foreground hover:text-foreground" />
          </button>
          <button
            onClick={onOpenSettings}
            className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-muted transition-colors cursor-pointer"
            title="Settings"
          >
            <Settings className="h-4 w-4 text-muted-foreground hover:text-foreground" />
          </button>
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
            <text x="2" y="13" fill="#22d3ee" fontSize="14" fontWeight="bold" fontFamily="sans-serif" opacity="0.7">玄</text>
            <text x="13" y="26" fill="#22d3ee" fontSize="14" fontWeight="bold" fontFamily="sans-serif" opacity="0.7">武</text>
          </svg>
        </div>
      </div>
    );
  }

  return (
    <div className="flex w-[260px] min-w-[260px] flex-col border-r border-border bg-[#060a12] h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
            <text x="1" y="9" fill="#22d3ee" fontSize="9" fontWeight="bold" fontFamily="sans-serif">玄</text>
            <text x="10" y="19" fill="#22d3ee" fontSize="9" fontWeight="bold" fontFamily="sans-serif">武</text>
          </svg>
          <span className="text-sm font-semibold text-foreground">XuanwuAI <span className="text-primary">玄武</span></span>
        </div>
        <button
          onClick={onToggleCollapse}
          className="flex h-7 w-7 items-center justify-center rounded-md hover:bg-muted transition-colors cursor-pointer"
          title="Collapse sidebar"
        >
          <ChevronLeft className="h-4 w-4 text-muted-foreground" />
        </button>
      </div>

      {/* New Chat Button */}
      <div className="px-3 pt-3 pb-2">
        <button
          onClick={onNew}
          className="flex w-full items-center gap-2 rounded-lg border border-border hover:border-primary/40 bg-transparent px-3 py-2 text-sm text-foreground hover:bg-muted/50 transition-all cursor-pointer"
        >
          <Plus className="h-4 w-4" />
          New Chat
        </button>
      </div>

      {/* Search */}
      <div className="px-3 pb-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search conversations..."
            className="h-8 w-full rounded-lg border border-border bg-transparent pl-8 pr-3 text-xs outline-none focus:border-primary/40 transition-colors"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 cursor-pointer"
            >
              <X className="h-3 w-3 text-muted-foreground hover:text-foreground" />
            </button>
          )}
        </div>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto px-2 py-1">
        {/* Pinned */}
        {pinnedConvs.length > 0 && (
          <div className="mb-2">
            <div className="px-2 py-1 text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              Pinned
            </div>
            {pinnedConvs.map((conv) => (
              <ConversationItem
                key={conv.id}
                conv={conv}
                active={conv.id === activeId}
                editing={editingId === conv.id}
                editTitle={editTitle}
                menuOpen={menuOpenId === conv.id}
                onSelect={() => onSelect(conv.id)}
                onEditChange={setEditTitle}
                onCommitRename={commitRename}
                onCancelRename={cancelRename}
                onStartRename={() => startRename(conv)}
                onTogglePin={() => { onTogglePin(conv.id); setMenuOpenId(null); }}
                onDelete={() => { onDelete(conv.id); setMenuOpenId(null); }}
                onToggleMenu={() => setMenuOpenId(menuOpenId === conv.id ? null : conv.id)}
                editRef={editRef}
                menuRef={menuRef}
              />
            ))}
          </div>
        )}

        {/* Unpinned */}
        {unpinnedConvs.length > 0 && (
          <div>
            {pinnedConvs.length > 0 && (
              <div className="px-2 py-1 text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                Recent
              </div>
            )}
            {unpinnedConvs.map((conv) => (
              <ConversationItem
                key={conv.id}
                conv={conv}
                active={conv.id === activeId}
                editing={editingId === conv.id}
                editTitle={editTitle}
                menuOpen={menuOpenId === conv.id}
                onSelect={() => onSelect(conv.id)}
                onEditChange={setEditTitle}
                onCommitRename={commitRename}
                onCancelRename={cancelRename}
                onStartRename={() => startRename(conv)}
                onTogglePin={() => { onTogglePin(conv.id); setMenuOpenId(null); }}
                onDelete={() => { onDelete(conv.id); setMenuOpenId(null); }}
                onToggleMenu={() => setMenuOpenId(menuOpenId === conv.id ? null : conv.id)}
                editRef={editRef}
                menuRef={menuRef}
              />
            ))}
          </div>
        )}

        {filtered.length === 0 && (
          <div className="px-3 py-8 text-center text-xs text-muted-foreground">
            {search ? "No conversations found" : "No conversations yet"}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-border p-3 space-y-1">
        <button
          onClick={onOpenTools}
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
        >
          <Wrench className="h-3.5 w-3.5" />
          Available Tools ({toolsCount ?? 0})
        </button>
        <button
          onClick={onOpenMemory}
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
        >
          <Brain className="h-3.5 w-3.5" />
          Context Memory
        </button>
        <button
          onClick={onOpenDemoLibrary}
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
        >
          <Library className="h-3.5 w-3.5" />
          Demo Library
        </button>
        <button
          onClick={onOpenSettings}
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
        >
          <Settings className="h-3.5 w-3.5" />
          Settings
        </button>
      </div>
    </div>
  );
}

function ConversationItem({
  conv,
  active,
  editing,
  editTitle,
  menuOpen,
  onSelect,
  onEditChange,
  onCommitRename,
  onCancelRename,
  onStartRename,
  onTogglePin,
  onDelete,
  onToggleMenu,
  editRef,
  menuRef,
}: {
  conv: Conversation;
  active: boolean;
  editing: boolean;
  editTitle: string;
  menuOpen: boolean;
  onSelect: () => void;
  onEditChange: (v: string) => void;
  onCommitRename: () => void;
  onCancelRename: () => void;
  onStartRename: () => void;
  onTogglePin: () => void;
  onDelete: () => void;
  onToggleMenu: () => void;
  editRef: React.RefObject<HTMLInputElement | null>;
  menuRef: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <div
      className={`group relative flex items-center rounded-lg px-2 py-1.5 cursor-pointer transition-colors ${
        active
          ? "bg-primary/15 text-primary"
          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
      }`}
      onClick={editing ? undefined : onSelect}
    >
      <MessageSquare className={`h-3.5 w-3.5 mr-2 shrink-0 ${active ? "text-primary" : ""}`} />

      {editing ? (
        <div className="flex-1 flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <input
            ref={editRef}
            value={editTitle}
            onChange={(e) => onEditChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onCommitRename();
              if (e.key === "Escape") onCancelRename();
            }}
            className="flex-1 h-6 rounded border border-primary/40 bg-transparent px-1.5 text-xs outline-none"
          />
          <button onClick={onCommitRename} className="cursor-pointer">
            <Check className="h-3 w-3 text-emerald-400" />
          </button>
          <button onClick={onCancelRename} className="cursor-pointer">
            <X className="h-3 w-3 text-muted-foreground" />
          </button>
        </div>
      ) : (
        <span className="flex-1 text-xs truncate">{conv.title}</span>
      )}

      {/* More button */}
      {!editing && (
        <button
          onClick={(e) => { e.stopPropagation(); onToggleMenu(); }}
          className={`flex h-6 w-6 items-center justify-center rounded transition-all cursor-pointer ${
            menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100"
          } hover:bg-muted`}
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      )}

      {/* Pin indicator */}
      {conv.pinned && !editing && (
        <Pin className="h-3 w-3 text-amber-400 shrink-0 ml-1" />
      )}

      {/* Dropdown menu */}
      {menuOpen && (
        <div
          ref={menuRef}
          className="absolute right-0 top-full mt-0.5 z-50 w-36 rounded-lg border border-border bg-card shadow-xl py-1"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={onStartRename}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors cursor-pointer"
          >
            <Pencil className="h-3 w-3" />
            Rename
          </button>
          <button
            onClick={onTogglePin}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-foreground hover:bg-muted transition-colors cursor-pointer"
          >
            {conv.pinned ? (
              <>
                <PinOff className="h-3 w-3" />
                Unpin
              </>
            ) : (
              <>
                <Pin className="h-3 w-3" />
                Pin
              </>
            )}
          </button>
          <div className="border-t border-border my-0.5" />
          <button
            onClick={onDelete}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
          >
            <Trash2 className="h-3 w-3" />
            Delete
          </button>
        </div>
      )}
    </div>
  );
}
