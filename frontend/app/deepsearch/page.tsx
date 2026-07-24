"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { StudioActionButton, StudioActionLink, StudioEmptyState, StudioHero, StudioNotice, StudioStatusPill } from "@/components/StudioChrome";
import { apiFetch, token } from "@/lib/api";
import { LAST_CONV_KEY } from "@/lib/conversations";

type ResearchItem = { id: string; title: string; updated_at: string | null };

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
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

export default function ResearchPage() {
  const router = useRouter();
  const [items, setItems] = useState<ResearchItem[] | null>(null);
  const [error, setError] = useState("");
  const [lastSyncAt, setLastSyncAt] = useState<number | null>(null);
  const [liveRefresh, setLiveRefresh] = useState(true);
  const [syncTick, setSyncTick] = useState(0);

  async function refreshNow() {
    try {
      const d = await apiFetch<{ items: ResearchItem[] }>("/deepsearch/research");
      setItems(d.items);
      setLastSyncAt(Date.now());
      setError("");
    } catch (e: any) {
      setError(e?.message || "Could not load research");
    }
  }

  useEffect(() => {
    if (!token.get()) {
      router.replace("/login");
      return;
    }
    let dead = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const loop = async () => {
      await refreshNow();
      if (!dead && liveRefresh) timer = setTimeout(loop, 15000);
    };
    void loop();
    return () => {
      dead = true;
      if (timer) clearTimeout(timer);
    };
  }, [liveRefresh, router]);

  useEffect(() => {
    const id = window.setInterval(() => setSyncTick(Date.now()), 15000);
    return () => window.clearInterval(id);
  }, []);

  function openReport(id: string) {
    localStorage.setItem(LAST_CONV_KEY, id);
    router.push("/chat");
  }

  function fresh() {
    localStorage.removeItem(LAST_CONV_KEY);
    router.push("/chat");
  }

  const lastSyncLabel = sinceLabel(lastSyncAt);
  void syncTick;

  return (
    <AppShell title="Research">
      <div className="mx-auto w-full max-w-3xl p-6 space-y-6">
        <StudioHero
          title="Research library"
          subtitle="Every DeepSearch run lands here — re-open a report any time with sources included."
          actions={
            <>
              <StudioActionButton onClick={() => void refreshNow()} tone="accent">↻ Refresh now</StudioActionButton>
              <StudioActionButton onClick={() => setLiveRefresh((v) => !v)} tone={liveRefresh ? "success" : "default"}>
                {liveRefresh ? "⏸ Pause live refresh" : "▶ Resume live refresh"}
              </StudioActionButton>
              <StudioActionButton onClick={fresh}>＋ New research</StudioActionButton>
              <StudioActionLink href="/chat">💬 Open chat</StudioActionLink>
            </>
          }
          stats={[
            { label: "Reports", value: items?.length ?? 0 },
            { label: "Latest ready", value: items?.[0]?.updated_at ? fmtDate(items[0].updated_at) : "—" },
          ]}
        />
        <div className="flex flex-wrap items-center gap-2">
          <StudioStatusPill label="Library sync" value={lastSyncLabel} tone="accent" pulse={liveRefresh} />
          <StudioStatusPill label="Live refresh" value={liveRefresh ? "every 15s" : "paused"} tone={liveRefresh ? "success" : "default"} pulse={liveRefresh} />
          <StudioStatusPill label="Reports" value={items?.length ?? "…"} tone={items && items.length > 0 ? "success" : "default"} pulse={Boolean(items && items.length > 0)} />
        </div>
        <StudioNotice>
          Opens a fresh chat — switch on <span className="text-accent">🔭 Deep</span> before sending.
        </StudioNotice>

        {error && <p className="text-sm text-red-400">{error}</p>}

        {items === null && !error && (
          <div className="grid gap-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-20 animate-pulse rounded-2xl border border-line bg-surface" />
            ))}
          </div>
        )}

        {items && items.length === 0 && (
          <div className="rounded-2xl border border-line bg-surface p-8 text-center">
            <p className="text-3xl">🔭</p>
            <p className="mt-3 text-sm text-gray-400">
              No saved research yet. Ask a big question in chat with <span className="text-accent">🔭 Deep</span> on —
              the multi-round report (with 📚 sources) will appear here automatically.
            </p>
          </div>
        )}

        {items && items.length > 0 && (
          <div className="grid gap-3">
            {items.map((it) => (
              <button
                key={it.id}
                onClick={() => openReport(it.id)}
                className="group flex items-center justify-between gap-4 rounded-2xl border border-line bg-surface p-4 text-left transition hover:border-accent/50"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-gray-200">{it.title}</p>
                  <p className="mt-0.5 text-xs text-gray-600">🔭 DeepSearch report · {fmtDate(it.updated_at)}</p>
                </div>
                <span className="shrink-0 text-xs text-accent opacity-0 transition group-hover:opacity-100">
                  Open →
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
