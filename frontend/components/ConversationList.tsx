"use client";

import { useEffect, useMemo, useState } from "react";
import { Archive, MessageSquare, Pin, PinOff, Plus, Search, Trash2 } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { ConvItem, useConversations } from "@/lib/conversations";

/** Conversation history list — used by both the desktop sidebar and mobile/tablet drawer.
 *  Double-click (or long-press) a title to rename it inline. */
export default function ConversationList({ onNavigate }: { onNavigate?: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const { convs, activeId, setActiveId, remove, refresh, pin, archive } = useConversations();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<(ConvItem & { snippet?: string })[] | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [archived, setArchived] = useState<ConvItem[]>([]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return convs;
    return convs.filter((c) => (c.title || "New chat").toLowerCase().includes(q));
  }, [convs, query]);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setHits(null);
      return;
    }
    const t = window.setTimeout(() => {
      apiFetch<{ results: (ConvItem & { snippet?: string })[] }>(`/conversations/search?q=${encodeURIComponent(q)}`)
        .then((r) => setHits(r.results))
        .catch(() => setHits(null));
    }, 280);
    return () => window.clearTimeout(t);
  }, [query]);

  useEffect(() => {
    if (!showArchived) return;
    apiFetch<ConvItem[]>("/conversations?archived=true")
      .then(setArchived)
      .catch(() => setArchived([]));
  }, [showArchived, convs.length]);

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

  const visible: (ConvItem & { snippet?: string })[] = hits ?? filtered;

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
            placeholder="Search titles & messages"
            className="w-full rounded-xl border border-white/8 bg-[#141415] pl-8 pr-3 py-2 text-xs text-gray-300 outline-none focus:border-accent/40 placeholder-gray-600"
          />
        </div>
        <div className="flex items-center justify-between px-1">
          <div className="text-[11px] uppercase tracking-[0.18em] text-gray-600">{hits ? "Matches" : "Recent"}</div>
          <button
            type="button"
            onClick={() => setShowArchived((v) => !v)}
            className="text-[11px] text-gray-500 hover:text-white"
          >
            {showArchived ? "Hide archive" : "Archived"}
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin px-2 pb-3 space-y-1">
        {visible.map((c) => (
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
              <span className="flex-1 min-w-0" title={"snippet" in c && c.snippet ? c.snippet : "Double-click to rename"}>
                <span className="block truncate">
                  {c.pinned ? "📌 " : ""}
                  {c.title || "New chat"}
                </span>
                {"snippet" in c && c.snippet && (
                  <span className="block truncate text-[10px] text-gray-600">{c.snippet}</span>
                )}
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
                void archive(c.id, true);
              }}
              className="md:opacity-0 md:group-hover:opacity-100 text-gray-500 hover:text-white transition"
              aria-label="Archive chat"
              title="Archive"
            >
              <Archive size={14} />
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
        {convs.length === 0 && !hits && <p className="text-xs text-gray-600 px-3 py-4">No conversations yet.</p>}
        {convs.length > 0 && visible.length === 0 && <p className="text-xs text-gray-600 px-3 py-4">No chats matched your search.</p>}
        {showArchived && (
          <div className="pt-2 space-y-1">
            <div className="px-2 text-[11px] uppercase tracking-[0.18em] text-gray-600">Archived</div>
            {archived.length === 0 && <p className="text-xs text-gray-600 px-3 py-2">Nothing archived.</p>}
            {archived.map((c) => (
              <div
                key={c.id}
                className="group flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-gray-500 border border-transparent hover:bg-white/5"
              >
                <button
                  type="button"
                  onClick={() => go(() => setActiveId(c.id))}
                  className="flex-1 truncate text-left"
                >
                  {c.title || "New chat"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    void apiFetch(`/conversations/${c.id}`, {
                      method: "PATCH",
                      body: JSON.stringify({ archived: false }),
                    }).then(() => {
                      setArchived((rows) => rows.filter((x) => x.id !== c.id));
                      void refresh();
                    });
                  }}
                  className="text-[11px] text-accent hover:underline"
                >
                  Restore
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
