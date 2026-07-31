"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Hand, Link2, Loader2, Puzzle, RefreshCw, ShieldCheck, Trash2, XCircle } from "lucide-react";
import AppShell from "@/components/AppShell";
import { StudioActionButton, StudioActionLink, StudioEmptyState, StudioHero, StudioNotice, StudioStatusPill } from "@/components/StudioChrome";
import { apiFetch } from "@/lib/api";

interface PluginStatus {
  provider: string;
  name: string;
  icon: string;
  description: string;
  configured: boolean; // server has OAuth client id/secret
  connected: boolean;
  account: string | null;
  connected_at: string | null;
}

interface PendingAction {
  id: string;
  tool: string;
  icon: string;
  label: string;
  args: Record<string, any>;
  conversation_id: string | null;
  created_at: string | null;
}

/** What each plugin unlocks in chat (shown on the store card). */
const SUPERPOWERS: Record<string, string[]> = {
  gmail: [
    "\"Summarize today's unread inbox\"",
    "\"Draft a reply to Kojo about the invoice\"",
    "\"Email the team the arena results\" (asks first ✋)",
  ],
  google_calendar: [
    "\"What's on my calendar this week?\"",
    "\"Book a 30-min sync with Ama on Friday 10:00\"",
    "\"Move my dentist appointment to next month\" (asks first ✋)",
  ],
  github: [
    "\"List my open repos and their issues\"",
    "\"File a bug report on ChatMood for the login bug\" (asks first ✋)",
    "\"Summarize recent commits across my projects\"",
  ],
};

function argPreview(args: Record<string, any>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(args)) {
    const val = typeof v === "string" ? v : JSON.stringify(v);
    if (val) parts.push(`${k}: ${val.slice(0, 60)}${val.length > 60 ? "…" : ""}`);
  }
  return parts.slice(0, 3).join(" · ");
}

function sinceLabel(ts: number | null): string {
  if (!ts) return "waiting for first sync";
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 10) return "synced just now";
  if (seconds < 60) return `synced ${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `synced ${minutes}m ago`;
  return `synced ${Math.floor(minutes / 60)}h ago`;
}

export default function PluginsPage() {
  const router = useRouter();
  const [plugins, setPlugins] = useState<PluginStatus[] | null>(null);
  const [pending, setPending] = useState<PendingAction[] | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState<string | null>(null); // provider or action id being acted on
  const [lastSyncAt, setLastSyncAt] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [liveRefresh, setLiveRefresh] = useState(true);
  const [syncTick, setSyncTick] = useState(0);

  const load = useCallback(async (options?: { silent?: boolean }) => {
    if (!options?.silent) setRefreshing(true);
    try {
      const [p, a] = await Promise.all([
        apiFetch<{ plugins: PluginStatus[] }>("/plugins"),
        apiFetch<{ actions: PendingAction[] }>("/plugins/actions/pending"),
      ]);
      setPlugins(p.plugins);
      setPending(a.actions);
      setLastSyncAt(Date.now());
    } catch (e: any) {
      if ((e.message ?? "").includes("401")) router.push("/login");
    } finally {
      setRefreshing(false);
    }
  }, [router]);

  useEffect(() => {
    void load();
    // OAuth round trips land back here with ?plugin=connected|error
    const qp = new URLSearchParams(window.location.search).get("plugin");
    if (qp === "connected") setMsg("✅ Connected — turn on 🧩 in chat to let ChatMood use it.");
    if (qp === "error") setMsg("⚠️ Connection failed — please try again.");
  }, [load]);

  useEffect(() => {
    const id = window.setInterval(() => setSyncTick(Date.now()), 15000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!liveRefresh) return;
    const id = window.setInterval(() => {
      if (document.hidden) return;
      void load({ silent: true });
    }, 15000);
    return () => window.clearInterval(id);
  }, [liveRefresh, load]);

  async function connect(provider: string) {
    setMsg("");
    setBusy(provider);
    try {
      const j = await apiFetch<{ authorize_url: string }>(`/plugins/${provider}/connect`);
      window.location.href = j.authorize_url; // OAuth round trip → back here
    } catch (e: any) {
      setMsg("⚠️ " + (e.message ?? "Connection failed"));
      setBusy(null);
    }
  }

  async function disconnect(p: PluginStatus) {
    if (!window.confirm(`Disconnect ${p.name}? ChatMood will lose access until you reconnect.`)) return;
    setMsg("");
    setBusy(p.provider);
    try {
      await apiFetch(`/plugins/${p.provider}`, { method: "DELETE" });
      setMsg(`🔌 ${p.name} disconnected.`);
      await load();
    } catch (e: any) {
      setMsg("⚠️ " + (e.message ?? "Disconnect failed"));
    } finally {
      setBusy(null);
    }
  }

  async function decide(action: PendingAction, approve: boolean) {
    setBusy(action.id);
    setMsg("");
    try {
      const j = await apiFetch<{ status: string; result?: { error?: string } }>(
        `/plugins/actions/${action.id}/${approve ? "approve" : "reject"}`,
        { method: "POST" }
      );
      if (approve && j.status === "failed") setMsg(`⚠️ ${action.label} failed: ${j.result?.error ?? "unknown"}`);
      else setMsg(approve ? `✅ ${action.label} executed.` : `🚫 ${action.label} rejected.`);
      await load();
    } catch (e: any) {
      setMsg("⚠️ " + (e.message ?? "Action failed"));
    } finally {
      setBusy(null);
    }
  }

  const connectedCount = (plugins ?? []).filter((p) => p.connected).length;
  const configuredCount = (plugins ?? []).filter((p) => p.configured).length;
  const pendingCount = pending?.length ?? 0;
  const lastSyncLabel = sinceLabel(lastSyncAt);
  void syncTick;

  return (
    <AppShell title="Plugin Store">
      {/* min-h-0 is required: without it the flex item refuses to shrink below
          its content, so the store grows the shell instead of scrolling. */}
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
          <StudioHero
            icon={<Puzzle size={20} />}
            title="Plugin Store"
            subtitle="Connect your accounts so ChatMood can read on demand and always ask before writing. Turn on 🧩 in chat to use them."
            actions={
              <>
                <StudioActionButton onClick={() => void load()} tone="accent">
                  {refreshing ? <span className="inline-flex items-center gap-1"><RefreshCw size={12} className="animate-spin" /> Refreshing…</span> : <span className="inline-flex items-center gap-1"><RefreshCw size={12} /> Refresh now</span>}
                </StudioActionButton>
                <StudioActionLink href="/chat">💬 Back to chat</StudioActionLink>
                <StudioActionLink href="/settings">⚙️ Settings</StudioActionLink>
              </>
            }
            stats={[
              { label: "Connected", value: connectedCount },
              { label: "Available", value: configuredCount },
              { label: "Waiting approval", value: pendingCount },
              { label: "All plugins", value: plugins?.length ?? 0 },
            ]}
          />

          <div className="flex flex-wrap items-center gap-2">
            <StudioStatusPill label="Store sync" value={lastSyncLabel} tone="accent" pulse={refreshing || liveRefresh} />
            <StudioStatusPill label="Connected" value={connectedCount} tone={connectedCount > 0 ? "success" : "default"} pulse={connectedCount > 0} />
            <StudioStatusPill label="Approval queue" value={pendingCount > 0 ? `${pendingCount} waiting` : "clear"} tone={pendingCount > 0 ? "warn" : "success"} pulse={pendingCount > 0} />
            <StudioStatusPill label="Live refresh" value={liveRefresh ? "every 15s" : "paused"} tone={liveRefresh ? "success" : "default"} pulse={liveRefresh} />
            <div className="ml-auto">
              <StudioActionButton onClick={() => setLiveRefresh((v) => !v)} tone={liveRefresh ? "success" : "default"}>
                {liveRefresh ? "⏸ Pause live refresh" : "▶ Resume live refresh"}
              </StudioActionButton>
            </div>
          </div>

          {msg && <StudioNotice tone="accent">{msg}</StudioNotice>}

          {/* ✋ Approval inbox — staged write actions from chat */}
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500 flex items-center gap-1.5">
              <Hand size={12} /> Waiting for your approval
              {pending && pending.length > 0 && (
                <span className="rounded-full bg-amber-400/15 border border-amber-400/40 text-amber-300 px-2 py-0.5 text-[10px] font-bold">
                  {pending.length}
                </span>
              )}
            </h2>
            {!pending ? (
              <p className="text-xs text-gray-600">Loading…</p>
            ) : pending.length === 0 ? (
              <StudioEmptyState
                emoji="✋"
                title="Nothing pending"
                description="Write actions staged in chat — like sending email, creating events or filing issues — will land here for approval."
              />
            ) : (
              <div className="space-y-2">
                {pending.map((a) => (
                  <div key={a.id} className="rounded-xl bg-amber-400/5 border border-amber-400/25 p-3 space-y-2">
                    <p className="text-sm font-medium text-amber-200">
                      {a.icon} {a.label}
                    </p>
                    <p className="text-[11px] text-gray-400 break-all">{argPreview(a.args) || "(no details)"}</p>
                    <div className="flex items-center gap-2">
                      <button
                        disabled={busy === a.id}
                        onClick={() => decide(a, true)}
                        className="inline-flex items-center gap-1 rounded-lg bg-emerald-500/90 text-black text-xs font-semibold px-3 py-1.5 hover:brightness-110 transition disabled:opacity-40"
                      >
                        {busy === a.id ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />} Approve & run
                      </button>
                      <button
                        disabled={busy === a.id}
                        onClick={() => decide(a, false)}
                        className="inline-flex items-center gap-1 rounded-lg bg-white/5 border border-line text-xs px-3 py-1.5 hover:bg-white/10 transition disabled:opacity-40"
                      >
                        <XCircle size={12} /> Reject
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* 🧩 Store grid */}
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">All plugins</h2>
            <div className="grid sm:grid-cols-2 gap-3">
              {(plugins ?? []).map((p) => (
                <div
                  key={p.provider}
                  className={`rounded-2xl border p-4 space-y-3 transition ${
                    p.connected ? "bg-accent/5 border-accent/30" : "bg-panel border-line"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2.5">
                      <span className="text-2xl">{p.icon}</span>
                      <div>
                        <p className="text-sm font-semibold flex items-center gap-1.5">
                          {p.name}
                          {p.connected && <ShieldCheck size={13} className="text-emerald-400" />}
                        </p>
                        <p className="text-[11px] text-gray-500">{p.description}</p>
                      </div>
                    </div>
                  </div>
                  {(SUPERPOWERS[p.provider] ?? []).length > 0 && (
                    <ul className="text-[11px] text-gray-400 space-y-1">
                      {(SUPERPOWERS[p.provider] ?? []).map((s) => (
                        <li key={s} className="italic">· {s}</li>
                      ))}
                    </ul>
                  )}
                  <div className="flex items-center gap-2 flex-wrap">
                    {p.connected ? (
                      <>
                        <span className="text-[11px] text-emerald-400 truncate">
                          ● {p.account ?? "connected"}
                        </span>
                        <button
                          disabled={busy === p.provider}
                          onClick={() => disconnect(p)}
                          className="ml-auto inline-flex items-center gap-1 rounded-lg bg-white/5 border border-line text-[11px] px-2.5 py-1.5 hover:bg-red-400/10 hover:border-red-400/40 hover:text-red-300 transition disabled:opacity-40"
                        >
                          {busy === p.provider ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />} Disconnect
                        </button>
                      </>
                    ) : p.configured ? (
                      <button
                        disabled={busy === p.provider}
                        onClick={() => connect(p.provider)}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-accent text-black text-xs font-semibold px-3.5 py-2 hover:brightness-110 transition disabled:opacity-40"
                      >
                        {busy === p.provider ? <Loader2 size={12} className="animate-spin" /> : <Link2 size={12} />} Connect
                      </button>
                    ) : (
                      <span className="text-[11px] text-gray-600 border border-line rounded-lg px-2.5 py-1.5">
                        Not available on this server (OAuth keys not set)
                      </span>
                    )}
                  </div>
                </div>
              ))}
              {plugins === null && <p className="text-xs text-gray-600 sm:col-span-2">Loading plugins…</p>}
            </div>
          </section>

          <p className="text-[11px] text-gray-600">
            🔒 OAuth tokens are encrypted at rest. Reads happen only when you ask in chat; every write (email, event,
            issue) is staged for your explicit approval — here or inline in the conversation.
          </p>
        </div>
      </div>
    </AppShell>
  );
}
