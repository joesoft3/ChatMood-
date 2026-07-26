"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Archive,
  ArchiveRestore,
  FileText,
  FolderKanban,
  Loader2,
  MessageSquare,
  Paperclip,
  Plus,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";
import AppShell from "@/components/AppShell";
import {
  StudioActionButton,
  StudioActionLink,
  StudioEmptyState,
  StudioHero,
  StudioNotice,
} from "@/components/StudioChrome";
import { apiFetch } from "@/lib/api";

interface Project {
  id: string;
  name: string;
  description: string;
  instructions: string;
  emoji: string;
  accent: string | null;
  archived: boolean;
  chats: number;
  files: number;
  tasks: number;
  updated_at: string | null;
}

interface ProjectDetail extends Project {
  conversations: { id: string; title: string; updated_at: string | null }[];
  pinned_files: { id: string; filename: string; mime: string; size_bytes: number; indexed: boolean }[];
  tasks_list?: { id: string; title: string; enabled: boolean; mode: string }[];
}

interface FileRec {
  id: string;
  filename: string;
  mime: string;
}

const EMOJI_CHOICES = ["🗂", "🚀", "📚", "🔬", "💼", "🎬", "🧪", "📈"];

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [files, setFiles] = useState<FileRec[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [showForm, setShowForm] = useState(false);

  // create form
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("🗂");
  const [description, setDescription] = useState("");

  // detail editor
  const [draftInstructions, setDraftInstructions] = useState("");
  const [draftName, setDraftName] = useState("");

  const load = useCallback(
    async (opts?: { silent?: boolean }) => {
      if (!opts?.silent) setRefreshing(true);
      try {
        const list = await apiFetch<Project[]>(`/projects?include_archived=${showArchived}`);
        setProjects(list);
        setErr("");
      } catch (e: any) {
        setErr(e.message || "Couldn't load projects");
      } finally {
        setRefreshing(false);
      }
    },
    [showArchived],
  );

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    apiFetch<FileRec[]>("/files")
      .then(setFiles)
      .catch(() => {});
  }, []);

  async function open(id: string) {
    setErr("");
    try {
      const d = await apiFetch<ProjectDetail>(`/projects/${id}`);
      setDetail(d);
      setDraftInstructions(d.instructions);
      setDraftName(d.name);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function create() {
    if (!name.trim()) {
      setErr("Give the project a name.");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const p = await apiFetch<Project>("/projects", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), description: description.trim(), emoji }),
      });
      setName("");
      setDescription("");
      setShowForm(false);
      setMsg(`🗂 “${p.name}” created — every chat inside it will follow its brief.`);
      await load({ silent: true });
      await open(p.id);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveBrief() {
    if (!detail) return;
    setBusy(true);
    setErr("");
    try {
      await apiFetch(`/projects/${detail.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: draftName.trim(), instructions: draftInstructions }),
      });
      setMsg("✅ Brief saved — it applies to every chat in this project from the next message.");
      await load({ silent: true });
      await open(detail.id);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleArchive(p: Project) {
    setBusy(true);
    try {
      await apiFetch(`/projects/${p.id}`, {
        method: "PATCH",
        body: JSON.stringify({ archived: !p.archived }),
      });
      await load({ silent: true });
      if (detail?.id === p.id) setDetail(null);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(p: Project) {
    if (
      !window.confirm(
        `Delete “${p.name}”?\n\nIts ${p.chats} chat(s) and uploaded files are NOT deleted — they just stop being filed here.`,
      )
    )
      return;
    setBusy(true);
    try {
      await apiFetch(`/projects/${p.id}`, { method: "DELETE" });
      if (detail?.id === p.id) setDetail(null);
      setMsg("Project deleted — your chats and files were kept.");
      await load({ silent: true });
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function pin(fileId: string) {
    if (!detail) return;
    setBusy(true);
    setErr("");
    try {
      await apiFetch(`/projects/${detail.id}/files/${fileId}`, { method: "POST" });
      await open(detail.id);
      await load({ silent: true });
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function unpin(fileId: string) {
    if (!detail) return;
    setBusy(true);
    try {
      await apiFetch(`/projects/${detail.id}/files/${fileId}`, { method: "DELETE" });
      await open(detail.id);
      await load({ silent: true });
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const unpinned = files.filter((f) => !detail?.pinned_files.some((p) => p.id === f.id));

  return (
    <AppShell
      title="Projects"
      headerRight={
        <button
          onClick={() => load()}
          className="rounded-lg border border-line bg-white/5 p-2 text-gray-400 hover:text-gray-100"
          title="Refresh"
        >
          <RefreshCw size={15} className={refreshing ? "animate-spin" : ""} />
        </button>
      }
    >
      <div className="mx-auto max-w-5xl space-y-4 p-3 sm:p-4">
        <StudioHero
          icon={<FolderKanban size={20} />}
          title="🗂 Projects"
          subtitle="A project keeps a brief, a document set and its chats together — so every conversation inside it already knows the context, without you re-explaining or re-attaching anything."
          actions={
            <>
              <StudioActionButton onClick={() => setShowForm((v) => !v)} tone="accent">
                <span className="inline-flex items-center gap-1.5">
                  <Plus size={13} /> {showForm ? "Close" : "New project"}
                </span>
              </StudioActionButton>
              <StudioActionButton onClick={() => setShowArchived((v) => !v)}>
                {showArchived ? "Hide archived" : "Show archived"}
              </StudioActionButton>
            </>
          }
          stats={[
            { label: "Projects", value: projects?.length ?? "—" },
            { label: "Filed chats", value: projects?.reduce((n, p) => n + p.chats, 0) ?? "—" },
            { label: "Pinned files", value: projects?.reduce((n, p) => n + p.files, 0) ?? "—" },
            { label: "Project tasks", value: projects?.reduce((n, p) => n + p.tasks, 0) ?? "—" },
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
              placeholder="Project name — e.g. Q4 Launch"
              maxLength={120}
              className="w-full rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
            />
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="One line about what this project is (optional)"
              maxLength={2000}
              className="w-full rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
            />
            <button
              onClick={create}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-xl border border-accent/30 bg-accent/15 px-4 py-2 text-xs text-accent transition hover:bg-accent/25 disabled:opacity-50"
            >
              {busy ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
              Create project
            </button>
          </section>
        )}

        {projects === null ? (
          <div className="pt-20 text-center text-gray-600">
            <Loader2 className="mx-auto animate-spin" />
          </div>
        ) : projects.length === 0 ? (
          <StudioEmptyState
            emoji="🗂"
            title="No projects yet"
            description="Projects are for work that spans many chats — a launch, a thesis, a client. Set the brief once and every conversation inside inherits it."
            actions={
              <StudioActionButton onClick={() => setShowForm(true)} tone="accent">
                Create your first project
              </StudioActionButton>
            }
          />
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {projects.map((p) => (
              <button
                key={p.id}
                onClick={() => open(p.id)}
                className={`rounded-2xl border bg-panel p-3.5 text-left transition hover:border-accent/40 ${
                  detail?.id === p.id ? "border-accent/50" : "border-line"
                } ${p.archived ? "opacity-60" : ""}`}
              >
                <div className="flex items-start gap-2.5">
                  <span className="text-xl">{p.emoji}</span>
                  <div className="min-w-0 flex-1">
                    <h2 className="truncate text-sm font-semibold text-gray-100">
                      {p.name}
                      {p.archived && <span className="ml-2 text-[10px] text-gray-500">archived</span>}
                    </h2>
                    {p.description && <p className="mt-0.5 line-clamp-1 text-xs text-gray-500">{p.description}</p>}
                    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-500">
                      <span className="inline-flex items-center gap-1">
                        <MessageSquare size={11} /> {p.chats}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <Paperclip size={11} /> {p.files}
                      </span>
                      {p.tasks > 0 && <span>⏰ {p.tasks}</span>}
                      {p.instructions && <span className="text-accent">has a brief</span>}
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        {detail && (
          <section className="space-y-4 rounded-2xl border border-accent/30 bg-panel p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className="text-2xl">{detail.emoji}</span>
                <input
                  value={draftName}
                  onChange={(e) => setDraftName(e.target.value)}
                  className="min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-2 py-1 text-base font-semibold text-gray-100 outline-none hover:border-line focus:border-accent/50"
                />
              </div>
              <div className="flex flex-wrap gap-1.5">
                <StudioActionLink href={`/chat?project=${detail.id}`}>Start a chat here →</StudioActionLink>
                <button
                  onClick={() => toggleArchive(detail)}
                  className="rounded-lg border border-line bg-white/5 p-2 text-gray-400 hover:text-gray-100"
                  title={detail.archived ? "Restore" : "Archive"}
                >
                  {detail.archived ? <ArchiveRestore size={14} /> : <Archive size={14} />}
                </button>
                <button
                  onClick={() => remove(detail)}
                  className="rounded-lg border border-line bg-white/5 p-2 text-gray-500 hover:border-red-400/40 hover:text-red-300"
                  title="Delete project"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>

            <div>
              <label className="text-[11px] text-gray-500">
                Standing instructions — prepended to every chat in this project
              </label>
              <textarea
                value={draftInstructions}
                onChange={(e) => setDraftInstructions(e.target.value)}
                rows={4}
                maxLength={8000}
                placeholder="e.g. Always answer in British English. Assume the reader is a non-technical executive. Prefer tables over prose."
                className="mt-1 w-full resize-y rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
              />
              <button
                onClick={saveBrief}
                disabled={busy}
                className="mt-2 inline-flex items-center gap-2 rounded-xl border border-accent/30 bg-accent/15 px-3 py-1.5 text-xs text-accent transition hover:bg-accent/25 disabled:opacity-50"
              >
                {busy ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Save brief
              </button>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <h3 className="mb-1.5 text-xs font-medium text-gray-300">
                  📎 Pinned documents ({detail.pinned_files.length})
                </h3>
                {detail.pinned_files.length === 0 ? (
                  <p className="text-[11px] text-gray-600">
                    Nothing pinned. Pinned files are searchable from every chat in this project.
                  </p>
                ) : (
                  <ul className="space-y-1">
                    {detail.pinned_files.map((f) => (
                      <li
                        key={f.id}
                        className="flex items-center gap-2 rounded-lg bg-base px-2.5 py-1.5 text-[11px] text-gray-300"
                      >
                        <FileText size={12} className="shrink-0 text-gray-500" />
                        <span className="min-w-0 flex-1 truncate">{f.filename}</span>
                        {!f.indexed && <span className="text-[10px] text-yellow-500">no text</span>}
                        <button onClick={() => unpin(f.id)} className="text-gray-600 hover:text-red-300">
                          <Trash2 size={11} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {unpinned.length > 0 && (
                  <select
                    onChange={(e) => e.target.value && pin(e.target.value)}
                    value=""
                    className="mt-2 w-full rounded-lg border border-line bg-base px-2 py-1.5 text-[11px] text-gray-300"
                  >
                    <option value="">+ Pin a file from your library…</option>
                    {unpinned.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.filename}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <div>
                <h3 className="mb-1.5 text-xs font-medium text-gray-300">
                  💬 Chats in this project ({detail.conversations.length})
                </h3>
                {detail.conversations.length === 0 ? (
                  <p className="text-[11px] text-gray-600">
                    No chats yet — start one and it inherits the brief above.
                  </p>
                ) : (
                  <ul className="space-y-1">
                    {detail.conversations.slice(0, 10).map((c) => (
                      <li key={c.id}>
                        <Link
                          href={`/chat?c=${c.id}`}
                          className="block truncate rounded-lg bg-base px-2.5 py-1.5 text-[11px] text-gray-300 hover:text-accent"
                        >
                          {c.title}
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </section>
        )}
      </div>
    </AppShell>
  );
}
