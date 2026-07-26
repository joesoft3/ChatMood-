"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlarmClock,
  Bot,
  CheckCircle2,
  Clock,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Telescope,
  Trash2,
  XCircle,
  Zap,
} from "lucide-react";
import AppShell from "@/components/AppShell";
import {
  StudioActionButton,
  StudioActionLink,
  StudioEmptyState,
  StudioHero,
  StudioNotice,
  StudioStatusPill,
} from "@/components/StudioChrome";
import { apiFetch } from "@/lib/api";

interface TaskRun {
  id: string;
  status: string;
  summary: string;
  error: string;
  tokens_in: number;
  tokens_out: number;
  duration_ms: number;
  created_at: string | null;
}

interface Task {
  id: string;
  title: string;
  prompt: string;
  mode: string;
  search: boolean;
  schedule_kind: string;
  hour_utc: number;
  minute_utc: number;
  weekdays: number[];
  schedule_label: string;
  enabled: boolean;
  notify: boolean;
  project_id: string | null;
  conversation_id: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string;
  last_error: string;
  run_count: number;
}

interface TaskList {
  tasks: Task[];
  limit: number;
  used: number;
  plan: string;
  scheduler: boolean;
}

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const MODES = [
  { id: "chat", label: "Chat", icon: <Zap size={13} />, hint: "a normal grounded answer" },
  { id: "deepsearch", label: "Research", icon: <Telescope size={13} />, hint: "multi-round web research" },
  { id: "agent", label: "Agents", icon: <Bot size={13} />, hint: "a research team writes it" },
];

const PRESETS = [
  { title: "Morning AI brief", prompt: "Summarize the most important AI news from the last 24 hours, with sources.", hour: 7 },
  { title: "Daily market open", prompt: "Give me a market open briefing: indices, notable movers and the day's key events.", hour: 13 },
  { title: "Weekly competitor scan", prompt: "What did my competitors ship or announce this week? Cite every claim.", hour: 9 },
];

/** Format a UTC hour/minute in the viewer's own timezone — the API speaks UTC,
 *  people do not. */
function localTime(hourUtc: number, minuteUtc: number): string {
  const d = new Date();
  d.setUTCHours(hourUtc, minuteUtc, 0, 0);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function whenLabel(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`).getTime();
  const diff = then - Date.now();
  const mins = Math.round(Math.abs(diff) / 60000);
  const rel =
    mins < 60 ? `${mins}m` : mins < 1440 ? `${Math.round(mins / 60)}h` : `${Math.round(mins / 1440)}d`;
  return diff >= 0 ? `in ${rel}` : `${rel} ago`;
}

export default function TasksPage() {
  const [data, setData] = useState<TaskList | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [runs, setRuns] = useState<Record<string, TaskRun[]>>({});
  const [refreshing, setRefreshing] = useState(false);
  const [showForm, setShowForm] = useState(false);

  // create form
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [mode, setMode] = useState("chat");
  const [kind, setKind] = useState("daily");
  const [hour, setHour] = useState(7);
  const [minute, setMinute] = useState(0);
  const [days, setDays] = useState<number[]>([0, 1, 2, 3, 4]);
  const [search, setSearch] = useState(true);
  const [notify, setNotify] = useState(true);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    if (!opts?.silent) setRefreshing(true);
    try {
      setData(await apiFetch<TaskList>("/tasks"));
      setErr("");
    } catch (e: any) {
      setErr(e.message || "Couldn't load tasks");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // A task that is mid-run updates itself without the user hunting for refresh.
  useEffect(() => {
    if (!data?.tasks.some((t) => t.last_status === "running")) return;
    const id = window.setInterval(() => load({ silent: true }), 5000);
    return () => window.clearInterval(id);
  }, [data, load]);

  async function create() {
    if (!title.trim() || !prompt.trim()) {
      setErr("Give the task a title and a prompt.");
      return;
    }
    setCreating(true);
    setErr("");
    try {
      await apiFetch("/tasks", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          prompt: prompt.trim(),
          mode,
          search,
          notify,
          schedule_kind: kind,
          hour_utc: hour,
          minute_utc: minute,
          weekdays: kind === "weekly" ? days : [],
        }),
      });
      setTitle("");
      setPrompt("");
      setShowForm(false);
      setMsg("⏰ Task scheduled — ChatMood will run it for you.");
      await load({ silent: true });
    } catch (e: any) {
      setErr(e.message || "Couldn't create the task");
    } finally {
      setCreating(false);
    }
  }

  async function toggle(t: Task) {
    setBusyId(t.id);
    try {
      await apiFetch(`/tasks/${t.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !t.enabled }) });
      await load({ silent: true });
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusyId(null);
    }
  }

  async function runNow(t: Task) {
    setBusyId(t.id);
    setErr("");
    setMsg(`Running “${t.title}”…`);
    try {
      const r = await apiFetch<{ conversation_id: string }>(`/tasks/${t.id}/run`, { method: "POST" });
      setMsg(`✅ “${t.title}” finished — the answer is in its thread.`);
      await load({ silent: true });
      if (openId === t.id) await openDetail(t.id, true);
      return r;
    } catch (e: any) {
      setMsg("");
      setErr(e.message || "The run failed");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(t: Task) {
    if (!window.confirm(`Delete “${t.title}”? Its past answers stay in the chat thread.`)) return;
    setBusyId(t.id);
    try {
      await apiFetch(`/tasks/${t.id}`, { method: "DELETE" });
      await load({ silent: true });
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusyId(null);
    }
  }

  async function openDetail(id: string, force = false) {
    if (openId === id && !force) {
      setOpenId(null);
      return;
    }
    setOpenId(id);
    try {
      const d = await apiFetch<Task & { runs: TaskRun[] }>(`/tasks/${id}`);
      setRuns((prev) => ({ ...prev, [id]: d.runs }));
    } catch {
      /* history is a nicety — never block the page on it */
    }
  }

  const tasks = data?.tasks ?? [];
  const active = tasks.filter((t) => t.enabled).length;
  const atLimit = data ? data.used >= data.limit : false;

  return (
    <AppShell
      title="Tasks"
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
      <div className="mx-auto max-w-4xl space-y-4 p-3 sm:p-4">
        <StudioHero
          icon={<AlarmClock size={20} />}
          title="⏰ Scheduled tasks"
          subtitle="Save a prompt once and ChatMood runs it on a schedule — unattended. Every result lands in its own chat thread and pings your phone."
          actions={
            <>
              <StudioActionButton onClick={() => setShowForm((v) => !v)} tone="accent">
                <span className="inline-flex items-center gap-1.5">
                  <Plus size={13} /> {showForm ? "Close" : "New task"}
                </span>
              </StudioActionButton>
              <StudioActionLink href="/chat">Back to chat</StudioActionLink>
            </>
          }
          stats={[
            { label: "Scheduled", value: tasks.length },
            { label: "Active", value: active },
            { label: "Plan limit", value: data ? `${data.used}/${data.limit}` : "—" },
            { label: "Total runs", value: tasks.reduce((n, t) => n + t.run_count, 0) },
          ]}
        />

        {data && !data.scheduler && (
          <StudioNotice tone="warn">
            The background scheduler is turned off on this deployment — tasks won&apos;t fire automatically,
            but <strong>Run now</strong> still works.
          </StudioNotice>
        )}
        {msg && <StudioNotice tone="success">{msg}</StudioNotice>}
        {err && <StudioNotice tone="warn">{err}</StudioNotice>}

        {showForm && (
          <section className="space-y-3 rounded-2xl border border-line bg-panel p-4">
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((p) => (
                <button
                  key={p.title}
                  onClick={() => {
                    setTitle(p.title);
                    setPrompt(p.prompt);
                    setHour(p.hour);
                  }}
                  className="rounded-full border border-line bg-white/5 px-3 py-1 text-[11px] text-gray-400 transition hover:border-accent/40 hover:text-gray-100"
                >
                  {p.title}
                </button>
              ))}
            </div>

            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Task name — e.g. Morning AI brief"
              maxLength={160}
              className="w-full rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
            />
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="What should ChatMood do each time? e.g. Summarize the most important AI news from the last 24 hours, with sources."
              rows={3}
              maxLength={4000}
              className="w-full resize-y rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
            />

            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-gray-500">Mode</span>
              {MODES.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setMode(m.id)}
                  title={m.hint}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] transition ${
                    mode === m.id
                      ? "border-accent/40 bg-accent/15 text-accent"
                      : "border-line bg-white/5 text-gray-400 hover:text-gray-200"
                  }`}
                >
                  {m.icon} {m.label}
                </button>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-gray-500">Repeat</span>
              {["once", "hourly", "daily", "weekly"].map((k) => (
                <button
                  key={k}
                  onClick={() => setKind(k)}
                  className={`rounded-full border px-3 py-1.5 text-[11px] capitalize transition ${
                    kind === k
                      ? "border-accent/40 bg-accent/15 text-accent"
                      : "border-line bg-white/5 text-gray-400 hover:text-gray-200"
                  }`}
                >
                  {k}
                </button>
              ))}
            </div>

            {kind === "weekly" && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] text-gray-500">On</span>
                {DAY_LABELS.map((d, i) => (
                  <button
                    key={d}
                    onClick={() =>
                      setDays((prev) => (prev.includes(i) ? prev.filter((x) => x !== i) : [...prev, i].sort()))
                    }
                    className={`rounded-lg border px-2.5 py-1 text-[11px] transition ${
                      days.includes(i)
                        ? "border-accent/40 bg-accent/15 text-accent"
                        : "border-line bg-white/5 text-gray-500 hover:text-gray-300"
                    }`}
                  >
                    {d}
                  </button>
                ))}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3">
              {kind !== "hourly" && (
                <label className="flex items-center gap-2 text-[11px] text-gray-500">
                  Hour (UTC)
                  <select
                    value={hour}
                    onChange={(e) => setHour(Number(e.target.value))}
                    className="rounded-lg border border-line bg-base px-2 py-1 text-xs text-gray-100"
                  >
                    {Array.from({ length: 24 }, (_, i) => (
                      <option key={i} value={i}>
                        {String(i).padStart(2, "0")}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="flex items-center gap-2 text-[11px] text-gray-500">
                Minute
                <select
                  value={minute}
                  onChange={(e) => setMinute(Number(e.target.value))}
                  className="rounded-lg border border-line bg-base px-2 py-1 text-xs text-gray-100"
                >
                  {[0, 15, 30, 45].map((m) => (
                    <option key={m} value={m}>
                      {String(m).padStart(2, "0")}
                    </option>
                  ))}
                </select>
              </label>
              <span className="text-[11px] text-gray-500">
                = {localTime(hour, minute)} your time
              </span>
              <label className="flex items-center gap-1.5 text-[11px] text-gray-400">
                <input type="checkbox" checked={search} onChange={(e) => setSearch(e.target.checked)} />
                Live web
              </label>
              <label className="flex items-center gap-1.5 text-[11px] text-gray-400">
                <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} />
                Notify me
              </label>
            </div>

            {atLimit && (
              <StudioNotice tone="warn">
                You&apos;ve used all {data?.limit} tasks on the {data?.plan} plan.
                {data?.plan !== "pro" && " Upgrade to Pro for more."}
              </StudioNotice>
            )}

            <button
              onClick={create}
              disabled={creating || atLimit}
              className="inline-flex items-center gap-2 rounded-xl border border-accent/30 bg-accent/15 px-4 py-2 text-xs text-accent transition hover:bg-accent/25 disabled:opacity-50"
            >
              {creating ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
              Schedule task
            </button>
          </section>
        )}

        {data === null ? (
          <div className="pt-20 text-center text-gray-600">
            <Loader2 className="mx-auto animate-spin" />
          </div>
        ) : tasks.length === 0 ? (
          <StudioEmptyState
            emoji="⏰"
            title="No scheduled tasks yet"
            description="Tasks turn ChatMood from something you ask into something that shows up. Schedule a morning briefing, a weekly competitor scan, or any prompt you'd otherwise retype."
            actions={<StudioActionButton onClick={() => setShowForm(true)} tone="accent">Create your first task</StudioActionButton>}
          />
        ) : (
          <div className="space-y-2">
            {tasks.map((t) => (
              <article
                key={t.id}
                className={`rounded-2xl border bg-panel p-3.5 transition ${
                  t.enabled ? "border-line" : "border-line/50 opacity-60"
                }`}
              >
                <div className="flex flex-wrap items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="truncate text-sm font-semibold text-gray-100">{t.title}</h2>
                      <span className="rounded-full border border-line bg-white/5 px-2 py-0.5 text-[10px] capitalize text-gray-400">
                        {t.mode}
                      </span>
                      {t.last_status === "running" && (
                        <span className="inline-flex items-center gap-1 rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-[10px] text-accent">
                          <Loader2 size={9} className="animate-spin" /> running
                        </span>
                      )}
                      {t.last_status === "ok" && (
                        <span className="inline-flex items-center gap-1 text-[10px] text-emerald-400">
                          <CheckCircle2 size={10} /> ok
                        </span>
                      )}
                      {t.last_status === "failed" && (
                        <span className="inline-flex items-center gap-1 text-[10px] text-red-400" title={t.last_error}>
                          <XCircle size={10} /> failed
                        </span>
                      )}
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs text-gray-500">{t.prompt}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-500">
                      <span className="inline-flex items-center gap-1">
                        <Clock size={11} /> {t.schedule_label}
                      </span>
                      {t.enabled && t.next_run_at && <span>next {whenLabel(t.next_run_at)}</span>}
                      {t.run_count > 0 && <span>{t.run_count} run{t.run_count === 1 ? "" : "s"}</span>}
                      {t.conversation_id && (
                        <Link href={`/chat?c=${t.conversation_id}`} className="text-accent hover:underline">
                          open thread →
                        </Link>
                      )}
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-wrap gap-1.5">
                    <button
                      onClick={() => runNow(t)}
                      disabled={busyId === t.id}
                      title="Run now (doesn't affect the schedule)"
                      className="rounded-lg border border-line bg-white/5 p-2 text-gray-400 transition hover:border-accent/40 hover:text-accent disabled:opacity-50"
                    >
                      {busyId === t.id ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                    </button>
                    <button
                      onClick={() => toggle(t)}
                      disabled={busyId === t.id}
                      title={t.enabled ? "Pause" : "Resume"}
                      className="rounded-lg border border-line bg-white/5 p-2 text-gray-400 transition hover:text-gray-100 disabled:opacity-50"
                    >
                      {t.enabled ? <Pause size={14} /> : <Play size={14} />}
                    </button>
                    <button
                      onClick={() => remove(t)}
                      disabled={busyId === t.id}
                      title="Delete"
                      className="rounded-lg border border-line bg-white/5 p-2 text-gray-500 transition hover:border-red-400/40 hover:text-red-300 disabled:opacity-50"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>

                <button
                  onClick={() => openDetail(t.id)}
                  className="mt-2 text-[11px] text-gray-500 transition hover:text-gray-300"
                >
                  {openId === t.id ? "Hide history" : "History"}
                </button>

                {openId === t.id && (
                  <div className="mt-2 space-y-1.5 border-t border-line pt-2">
                    {(runs[t.id] ?? []).length === 0 ? (
                      <p className="text-[11px] text-gray-600">No runs yet.</p>
                    ) : (
                      (runs[t.id] ?? []).map((r) => (
                        <div key={r.id} className="rounded-lg bg-base px-2.5 py-2 text-[11px]">
                          <div className="flex flex-wrap items-center gap-2 text-gray-500">
                            <span className={r.status === "ok" ? "text-emerald-400" : "text-red-400"}>
                              {r.status}
                            </span>
                            <span>{whenLabel(r.created_at)}</span>
                            <span>{(r.duration_ms / 1000).toFixed(1)}s</span>
                            {(r.tokens_in > 0 || r.tokens_out > 0) && (
                              <span>
                                {r.tokens_in}↑ {r.tokens_out}↓ tokens
                              </span>
                            )}
                          </div>
                          <p className="mt-1 line-clamp-3 text-gray-400">{r.error || r.summary}</p>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </article>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <StudioStatusPill label="Timezone" value="schedules are stored in UTC" />
          <StudioStatusPill label="Plan" value={data?.plan ?? "—"} tone="accent" />
        </div>
      </div>
    </AppShell>
  );
}
