"use client";

import { useMemo, useState } from "react";
import { MessageSquare, Pin, PinOff, Plus, Search, Trash2 } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { useConversations } from "@/lib/conversations";

/** Conversation history list — used by both the desktop sidebar and mobile/tablet drawer.
 *  Double-click (or long-press) a title to rename it inline. */
export default function ConversationList({ onNavigate }: { onNavigate?: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const { convs, activeId, setActiveId, remove, refresh, pin } = useConversations();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return convs;
    return convs.filter((c) => (c.title || "New chat").toLowerCase().includes(q));
  }, [convs, query]);

  function go(fn: () => void) {
    fn();
    onNavigate?.();
    if (pathname !== "/chat") router.push("/chat");
  }

  function startRename(c: { id: string; title: string }) {
    setEditingId(c.id);
    setEditText(c.title);
  }

  async function commitRename(id: string) {
    const title = editText.trim();
    setEditingId(null);
    if (!title) return;
    try {
      await apiFetch(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify({ title }) });
      await refresh();
    } catch (e) {
      console.error(e);
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 basis-auto">
      {/* shrink-0: the New chat button + search must never be squeezed out of
          their own container (they used to overflow and sit under the nav). */}
      <div className="p-3 space-y-3 shrink-0">
        <div className="flex items-center justify-between px-1 text-[11px] text-gray-600">
          <span className="uppercase tracking-[0.18em]">Live history</span>
          <span className="inline-flex items-center gap-1 rounded-full border border-white/8 bg-white/5 px-2 py-0.5 text-[10px] text-gray-400">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
            {convs.length} chats
          </span>
        </div>
        <button
          onClick={() => go(() => setActiveId(null))}
          className="w-full flex items-center justify-center gap-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-line px-4 py-3 text-sm font-medium text-gray-100 transition shadow-[0_8px_24px_rgb(0_0_0/0.22)]"
        >
          <Plus size={16} className="text-accent" /> New chat
        </button>
        <div className="relative">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats"
            className="w-full rounded-xl border border-white/8 bg-[#141415] pl-8 pr-3 py-2 text-xs text-gray-300 outline-none focus:border-accent/40 placeholder-gray-600"
          />
        </div>
        <div className="px-1 text-[11px] uppercase tracking-[0.18em] text-gray-600">Recent</div>
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin px-2 pb-3 space-y-1">
        {filtered.map((c) => (
          <div
            key={c.id}
            onClick={() => editingId !== c.id && go(() => setActiveId(c.id))}
            onDoubleClick={() => startRename(c)}
            className={`group flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm cursor-pointer border transition ${
              activeId === c.id
                ? "bg-white/10 border-white/10 text-white shadow-[0_8px_24px_rgb(0_0_0/0.18)]"
                : "border-transparent text-gray-400 hover:bg-white/5 hover:border-white/5"
            }`}
          >
            <MessageSquare size={14} className="shrink-0 opacity-60" />
            {editingId === c.id ? (
              <input
                autoFocus
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                onBlur={() => commitRename(c.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitRename(c.id);
                  if (e.key === "Escape") setEditingId(null);
                }}
                onClick={(e) => e.stopPropagation()}
                className="flex-1 min-w-0 bg-base border border-accent/40 rounded-md px-2 py-0.5 text-sm outline-none"
              />
            ) : (
              <span className="flex-1 truncate" title="Double-click to rename">
                {c.pinned ? "📌 " : ""}
                {c.title || "New chat"}
              </span>
            )}
            <button
              onClick={(e) => {
                e.stopPropagation();
                void pin(c.id, !c.pinned);
              }}
              className={`md:opacity-0 md:group-hover:opacity-100 transition ${
                c.pinned ? "opacity-100 text-accent" : "text-gray-500 hover:text-white"
              }`}
              aria-label={c.pinned ? "Unpin chat" : "Pin chat"}
              title={c.pinned ? "Unpin" : "Pin to top"}
            >
              {c.pinned ? <PinOff size={14} /> : <Pin size={14} />}
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                remove(c.id);
              }}
              className="md:opacity-0 md:group-hover:opacity-100 text-gray-500 hover:text-red-400 transition"
              aria-label="Delete chat"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        {convs.length === 0 && <p className="text-xs text-gray-600 px-3 py-4">No conversations yet.</p>}
        {convs.length > 0 && filtered.length === 0 && <p className="text-xs text-gray-600 px-3 py-4">No chats matched your search.</p>}
      </div>
    </div>
  );
}
