"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Bot, Loader2, Plus, RefreshCw, Save, Sparkles, Trash2 } from "lucide-react";
import AppShell from "@/components/AppShell";
import {
  StudioActionButton,
  StudioActionLink,
  StudioEmptyState,
  StudioHero,
  StudioNotice,
} from "@/components/StudioChrome";
import { apiFetch } from "@/lib/api";

interface GptCard {
  id: string;
  name: string;
  description: string;
  instructions: string;
  emoji: string;
  starters: string[];
  file_ids: string[];
  catalog: boolean;
  mine: boolean;
  pulse: boolean;
}

interface FileRec {
  id: string;
  filename: string;
}

const EMOJI_CHOICES = ["🤖", "✍️", "🧑‍💻", "📊", "📚", "✉️", "🎯", "🌅"];

export default function GptsPage() {
  const router = useRouter();
  const [catalog, setCatalog] = useState<GptCard[]>([]);
  const [mine, setMine] = useState<GptCard[]>([]);
  const [detail, setDetail] = useState<GptCard | null>(null);
  const [files, setFiles] = useState<FileRec[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("🤖");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [starters, setStarters] = useState("");

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await apiFetch<{ catalog: GptCard[]; mine: GptCard[] }>("/gpts");
      setCatalog(data.catalog);
      setMine(data.mine);
      setErr("");
    } catch (e: any) {
      setErr(e.message || "Couldn't load GPTs");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
    apiFetch<FileRec[]>("/files")
      .then(setFiles)
      .catch(() => {});
  }, [load]);

  function chatWith(g: GptCard) {
    router.push(`/chat?gpt=${encodeURIComponent(g.id)}`);
  }

  async function create() {
    if (!name.trim()) {
      setErr("Give the GPT a name.");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const g = await apiFetch<GptCard>("/gpts", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          emoji,
          description: description.trim(),
          instructions: instructions.trim(),
          starters: starters.split("\n").map((s) => s.trim()).filter(Boolean).slice(0, 4),
        }),
      });
      setName("");
      setDescription("");
      setInstructions("");
      setStarters("");
      setShowForm(false);
      setMsg(`🤖 “${g.name}” is ready — start a chat and it keeps that brief.`);
      await load();
      setDetail(g);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!detail || detail.catalog) return;
    setBusy(true);
    setErr("");
    try {
      const g = await apiFetch<GptCard>(`/gpts/${detail.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: detail.name.trim(),
          description: detail.description,
          instructions: detail.instructions,
          emoji: detail.emoji,
          starters: detail.starters,
        }),
      });
      setDetail(g);
      setMsg("Saved — the next chat with this GPT picks up the new brief.");
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(g: GptCard) {
    if (g.catalog) return;
    if (!window.confirm(`Delete “${g.name}”? Chats that used it are kept.`)) return;
    setBusy(true);
    try {
      await apiFetch(`/gpts/${g.id}`, { method: "DELETE" });
      if (detail?.id === g.id) setDetail(null);
      setMsg("GPT deleted — your chats were kept.");
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function schedulePulse() {
    setBusy(true);
    setErr("");
    try {
      await apiFetch("/tasks", {
        method: "POST",
        body: JSON.stringify({
          title: "Daily Pulse",
          prompt:
            "Give me this morning's Pulse briefing: the 5 most important developments I should know, each with a source if you have one, then one recommended action.",
          mode: "chat",
          search: true,
          schedule_kind: "daily",
          hour_utc: 8,
          minute_utc: 0,
          enabled: true,
          notify: true,
        }),
      });
      setMsg("🌅 Daily Pulse is scheduled for 08:00 UTC. Manage it under Tasks.");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function pinFile(fid: string) {
    if (!detail || detail.catalog) return;
    setBusy(true);
    try {
      await apiFetch(`/gpts/${detail.id}/files/${fid}`, { method: "POST" });
      const g = await apiFetch<GptCard>(`/gpts/${detail.id}`);
      setDetail(g);
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const all = [...mine, ...catalog];

  return (
    <AppShell
      title="GPTs"
      headerRight={
        <button
          onClick={() => void load()}
          className="rounded-lg border border-line bg-white/5 p-2 text-gray-400 hover:text-gray-100"
          title="Refresh"
        >
          <RefreshCw size={15} className={refreshing ? "animate-spin" : ""} />
        </button>
      }
    >
      <div className="mx-auto max-w-5xl space-y-4 p-3 sm:p-4">
        <StudioHero
          icon={<Bot size={20} />}
          title="🤖 GPTs"
          subtitle="Reusable assistants with their own instructions, starters and knowledge files — the ChatGPT Custom GPT store, built into ChatMood. Catalog GPTs ship with the app; yours stay private."
          actions={
            <>
              <StudioActionButton onClick={() => setShowForm((v) => !v)} tone="accent">
                <span className="inline-flex items-center gap-1.5">
                  <Plus size={13} /> {showForm ? "Close" : "New GPT"}
                </span>
              </StudioActionButton>
              <StudioActionLink href="/tasks">⏰ Tasks / Pulse</StudioActionLink>
            </>
          }
          stats={[
            { label: "Your GPTs", value: mine.length },
            { label: "Catalog", value: catalog.length },
            { label: "Knowledge files", value: mine.reduce((n, g) => n + (g.file_ids?.length ?? 0), 0) },
          ]}
        />

        {msg && <StudioNotice tone="success">{msg}</StudioNotice>}
        {err && <StudioNotice tone="warn">{err}</StudioNotice>}

        {showForm && (
          <section className="space-y-3 rounded-2xl border border-line bg-panel p-4">
            <div className="flex flex-wrap items-center gap-2">
              {EMOJI_CHOICES.map((e) => (
                <button
                  key={e}
                  type="button"
                  onClick={() => setEmoji(e)}
                  className={`rounded-lg border px-2.5 py-1.5 text-base transition ${
                    emoji === e ? "border-accent/40 bg-accent/15" : "border-line bg-white/5"
                  }`}
                >
                  {e}
                </button>
              ))}
            </div>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="GPT name — e.g. Launch copywriter"
              maxLength={80}
              className="w-full rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
            />
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="One line about what it does"
              maxLength={400}
              className="w-full rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
            />
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={4}
              maxLength={8000}
              placeholder="Standing instructions — tone, format, what it must never do…"
              className="w-full resize-y rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
            />
            <textarea
              value={starters}
              onChange={(e) => setStarters(e.target.value)}
              rows={3}
              placeholder="Conversation starters — one per line, up to 4"
              className="w-full resize-y rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
            />
            <button
              type="button"
              onClick={() => void create()}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-xl border border-accent/30 bg-accent/15 px-4 py-2 text-xs text-accent transition hover:bg-accent/25 disabled:opacity-50"
            >
              {busy ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
              Create GPT
            </button>
          </section>
        )}

        {all.length === 0 && !refreshing ? (
          <StudioEmptyState
            emoji="🤖"
            title="No GPTs yet"
            description="Build a reusable assistant once — every chat you start with it already knows the brief."
            actions={
              <StudioActionButton onClick={() => setShowForm(true)} tone="accent">
                Create your first GPT
              </StudioActionButton>
            }
          />
        ) : (
          <>
            {mine.length > 0 && (
              <section className="space-y-2">
                <h2 className="text-xs uppercase tracking-[0.16em] text-gray-500">Yours</h2>
                <div className="grid gap-2 sm:grid-cols-2">
                  {mine.map((g) => (
                    <GptTile key={g.id} g={g} active={detail?.id === g.id} onOpen={setDetail} onChat={chatWith} />
                  ))}
                </div>
              </section>
            )}
            <section className="space-y-2">
              <h2 className="text-xs uppercase tracking-[0.16em] text-gray-500">Catalog</h2>
              <div className="grid gap-2 sm:grid-cols-2">
                {catalog.map((g) => (
                  <GptTile key={g.id} g={g} active={detail?.id === g.id} onOpen={setDetail} onChat={chatWith} />
                ))}
              </div>
            </section>
          </>
        )}

        {detail && (
          <section className="space-y-4 rounded-2xl border border-accent/30 bg-panel p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className="text-2xl">{detail.emoji}</span>
                {detail.catalog ? (
                  <h2 className="text-base font-semibold text-gray-100">{detail.name}</h2>
                ) : (
                  <input
                    value={detail.name}
                    onChange={(e) => setDetail({ ...detail, name: e.target.value })}
                    className="min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-2 py-1 text-base font-semibold text-gray-100 outline-none hover:border-line focus:border-accent/50"
                  />
                )}
              </div>
              <div className="flex flex-wrap gap-1.5">
                <StudioActionButton onClick={() => chatWith(detail)} tone="accent">
                  Start chat →
                </StudioActionButton>
                {detail.pulse && (
                  <StudioActionButton onClick={() => void schedulePulse()}>
                    <span className="inline-flex items-center gap-1.5">
                      <Sparkles size={12} /> Schedule daily Pulse
                    </span>
                  </StudioActionButton>
                )}
                {!detail.catalog && (
                  <button
                    type="button"
                    onClick={() => void remove(detail)}
                    className="rounded-lg border border-line bg-white/5 p-2 text-gray-500 hover:border-red-400/40 hover:text-red-300"
                    title="Delete GPT"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </div>
            <p className="text-sm text-gray-400">{detail.description}</p>
            <div>
              <label className="text-[11px] text-gray-500">Instructions</label>
              <textarea
                value={detail.instructions}
                onChange={(e) => setDetail({ ...detail, instructions: e.target.value })}
                readOnly={detail.catalog}
                rows={5}
                className="mt-1 w-full resize-y rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50 read-only:opacity-80"
              />
            </div>
            {detail.starters.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {detail.starters.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => router.push(`/chat?gpt=${encodeURIComponent(detail.id)}`)}
                    className="rounded-full border border-white/8 bg-[#141415] px-3 py-1.5 text-xs text-gray-300 hover:text-white"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
            {!detail.catalog && (
              <>
                <div>
                  <h3 className="mb-1.5 text-xs font-medium text-gray-300">
                    📎 Knowledge files ({detail.file_ids.length}/12)
                  </h3>
                  {files.length > 0 ? (
                    <select
                      onChange={(e) => e.target.value && void pinFile(e.target.value)}
                      value=""
                      className="w-full rounded-lg border border-line bg-base px-2 py-1.5 text-[11px] text-gray-300"
                    >
                      <option value="">+ Pin a file from your library…</option>
                      {files
                        .filter((f) => !detail.file_ids.includes(f.id))
                        .map((f) => (
                          <option key={f.id} value={f.id}>
                            {f.filename}
                          </option>
                        ))}
                    </select>
                  ) : (
                    <p className="text-[11px] text-gray-600">Upload files in the Files library first, then pin them here.</p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => void save()}
                  disabled={busy}
                  className="inline-flex items-center gap-2 rounded-xl border border-accent/30 bg-accent/15 px-3 py-1.5 text-xs text-accent transition hover:bg-accent/25 disabled:opacity-50"
                >
                  {busy ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Save GPT
                </button>
              </>
            )}
          </section>
        )}
      </div>
    </AppShell>
  );
}

function GptTile({
  g,
  active,
  onOpen,
  onChat,
}: {
  g: GptCard;
  active: boolean;
  onOpen: (g: GptCard) => void;
  onChat: (g: GptCard) => void;
}) {
  return (
    <div
      className={`rounded-2xl border bg-panel p-3.5 text-left transition hover:border-accent/40 ${
        active ? "border-accent/50" : "border-line"
      }`}
    >
      <button type="button" onClick={() => onOpen(g)} className="flex w-full items-start gap-2.5 text-left">
        <span className="text-xl">{g.emoji}</span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold text-gray-100">
            {g.name}
            {g.catalog && <span className="ml-2 text-[10px] text-gray-500">catalog</span>}
          </h2>
          <p className="mt-0.5 line-clamp-2 text-xs text-gray-500">{g.description}</p>
        </div>
      </button>
      <div className="mt-2 flex justify-end">
        <button
          type="button"
          onClick={() => onChat(g)}
          className="rounded-lg border border-accent/30 bg-accent/10 px-2.5 py-1 text-[11px] text-accent hover:bg-accent/20"
        >
          Chat
        </button>
      </div>
    </div>
  );
}
