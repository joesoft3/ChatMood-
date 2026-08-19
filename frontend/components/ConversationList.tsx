"use client";

import { useEffect, useMemo, useState } from "react";
import { Archive, Pin, PinOff, Search, Trash2 } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { ConvItem, useConversations } from "@/lib/conversations";

const BUCKETS = ["Pinned", "Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"] as const;

function bucketFor(iso?: string | null, pinned?: boolean): (typeof BUCKETS)[number] {
  if (pinned) return "Pinned";
  if (!iso) return "Older";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Older";
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);
  const startOfWeek = new Date(startOfToday);
  startOfWeek.setDate(startOfWeek.getDate() - 7);
  const startOfMonth = new Date(startOfToday);
  startOfMonth.setDate(startOfMonth.getDate() - 30);
  if (d >= startOfToday) return "Today";
  if (d >= startOfYesterday) return "Yesterday";
  if (d >= startOfWeek) return "Previous 7 days";
  if (d >= startOfMonth) return "Previous 30 days";
  return "Older";
}

/** Conversation history — desktop sidebar and mobile drawer. */
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
  const grouped = useMemo(() => {
    const map = new Map<(typeof BUCKETS)[number], typeof visible>();
    for (const key of BUCKETS) map.set(key, []);
    for (const c of visible) {
      const key = hits ? "Today" : bucketFor(c.updated_at, c.pinned);
      map.get(key)!.push(c);
    }
    return map;
  }, [visible, hits]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 px-2 pb-2">
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            id="sidebar-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats"
            className="w-full rounded-lg bg-white/5 py-2 pl-8 pr-3 text-[13px] text-gray-200 outline-none placeholder-gray-600 focus:bg-white/8"
          />
        </div>
      </div>
      <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3 scrollbar-thin">
        {BUCKETS.map((label) => {
          const rows = grouped.get(label) ?? [];
          if (!rows.length || (hits && label !== "Today")) return null;
          return (
            <div key={label} className="mb-2">
              <div className="px-2 pb-1 pt-3 text-[11px] font-medium text-gray-500">
                {hits ? "Search results" : label}
              </div>
              {rows.map((c) => (
                <div
                  key={c.id}
                  onClick={() => editingId !== c.id && go(() => setActiveId(c.id))}
                  onDoubleClick={() => startRename(c)}
                  className={`group flex cursor-pointer items-center gap-1 rounded-lg px-2 py-2 text-[13px] transition ${
                    activeId === c.id ? "bg-white/10 text-gray-100" : "text-gray-300 hover:bg-white/5"
                  }`}
                >
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
                      className="min-w-0 flex-1 rounded-md bg-base px-2 py-0.5 text-sm outline-none"
                    />
                  ) : (
                    <span className="min-w-0 flex-1" title={"snippet" in c && c.snippet ? c.snippet : "Double-click to rename"}>
                      <span className="block truncate">{c.title || "New chat"}</span>
                      {"snippet" in c && c.snippet && (
                        <span className="block truncate text-[11px] text-gray-600">{c.snippet}</span>
                      )}
                    </span>
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      void pin(c.id, !c.pinned);
                    }}
                    className={`rounded-md p-1 transition md:opacity-0 md:group-hover:opacity-100 ${
                      c.pinned ? "opacity-100 text-gray-300" : "text-gray-600 hover:text-white"
                    }`}
                    aria-label={c.pinned ? "Unpin chat" : "Pin chat"}
                    title={c.pinned ? "Unpin" : "Pin to top"}
                  >
                    {c.pinned ? <PinOff size={13} /> : <Pin size={13} />}
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      void archive(c.id, true);
                    }}
                    className="rounded-md p-1 text-gray-600 transition hover:text-white md:opacity-0 md:group-hover:opacity-100"
                    aria-label="Archive chat"
                    title="Archive"
                  >
                    <Archive size={13} />
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      remove(c.id);
                    }}
                    className="rounded-md p-1 text-gray-600 transition hover:text-red-400 md:opacity-0 md:group-hover:opacity-100"
                    aria-label="Delete chat"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </div>
          );
        })}
        {convs.length === 0 && !hits && <p className="px-2 py-6 text-xs text-gray-600">No conversations yet.</p>}
        {convs.length > 0 && visible.length === 0 && (
          <p className="px-2 py-6 text-xs text-gray-600">No chats matched your search.</p>
        )}
        <button
          type="button"
          onClick={() => setShowArchived((v) => !v)}
          className="mt-2 w-full rounded-lg px-2 py-2 text-left text-[12px] text-gray-500 hover:bg-white/5 hover:text-gray-300"
        >
          {showArchived ? "Hide archived" : "Archived"}
        </button>
        {showArchived && (
          <div className="space-y-0.5 pb-2">
            {archived.length === 0 && <p className="px-2 py-2 text-xs text-gray-600">Nothing archived.</p>}
            {archived.map((c) => (
              <div key={c.id} className="flex items-center gap-2 rounded-lg px-2 py-2 text-[13px] text-gray-500 hover:bg-white/5">
                <button type="button" onClick={() => go(() => setActiveId(c.id))} className="min-w-0 flex-1 truncate text-left">
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
                  className="text-[11px] text-gray-400 hover:text-white"
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
