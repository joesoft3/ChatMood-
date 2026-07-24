"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, FileAudio, FileText, FileVideo, Image as ImageIcon, Loader2, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import AppShell from "@/components/AppShell";
import { StudioActionButton, StudioActionLink, StudioEmptyState, StudioHero, StudioNotice, StudioStatusPill } from "@/components/StudioChrome";
import { apiFetch } from "@/lib/api";

interface FileRec {
  id: string;
  filename: string;
  mime: string;
  size_bytes: number;
  extracted: boolean;
  created_at: string | null;
}

interface Analysis {
  transcript: string;
  analysis: string;
}

function fmtSize(n: number): string {
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
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

function kindOf(mime: string): { label: string; icon: React.ReactNode } {
  if (mime.startsWith("image/")) return { label: "image", icon: <ImageIcon size={15} /> };
  if (mime.startsWith("audio/")) return { label: "audio", icon: <FileAudio size={15} /> };
  if (mime.startsWith("video/")) return { label: "video", icon: <FileVideo size={15} /> };
  return { label: "document", icon: <FileText size={15} /> };
}

export default function FilesPage() {
  const [files, setFiles] = useState<FileRec[] | null>(null);
  const [msg, setMsg] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<Record<string, Analysis>>({});
  const [openId, setOpenId] = useState<string | null>(null);
  const [lastSyncAt, setLastSyncAt] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [liveRefresh, setLiveRefresh] = useState(true);
  const [syncTick, setSyncTick] = useState(0);

  const load = useCallback(async (options?: { silent?: boolean }) => {
    if (!options?.silent) setRefreshing(true);
    try {
      const j = await apiFetch<FileRec[]>("/files");
      setFiles(j);
      setLastSyncAt(Date.now());
    } catch {
      setFiles(null);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
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
    }, 12000);
    return () => window.clearInterval(id);
  }, [liveRefresh, load]);

  async function download(f: FileRec) {
    try {
      const blob = await apiFetch<Blob>(`/files/${f.id}/download`);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = f.filename;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e: any) {
      setMsg("⚠️ " + (e.message ?? "Download failed"));
    }
  }

  async function remove(f: FileRec) {
    if (!confirm(`Delete ${f.filename}? Its search index is removed too.`)) return;
    await apiFetch(`/files/${f.id}`, { method: "DELETE" }).catch(() => {});
    await load();
  }

  async function reanalyze(f: FileRec) {
    setBusyId(f.id);
    setMsg("");
    setOpenId(f.id);
    try {
      const fd = new FormData();
      const j = await apiFetch<Analysis>(`/files/${f.id}/reanalyze`, { method: "POST", body: fd });
      setAnalysis((a) => ({ ...a, [f.id]: j }));
    } catch (e: any) {
      setMsg("⚠️ " + (e.message ?? "Analysis failed"));
      setOpenId(null);
    } finally {
      setBusyId(null);
    }
  }

  const canAnalyze = (f: FileRec) => f.mime.startsWith("audio/") || f.mime.startsWith("video/");
  const indexedCount = (files ?? []).filter((f) => f.extracted).length;
  const mediaCount = (files ?? []).filter((f) => canAnalyze(f)).length;
  const totalBytes = (files ?? []).reduce((sum, f) => sum + f.size_bytes, 0);
  const lastSyncLabel = sinceLabel(lastSyncAt);
  void syncTick;

  return (
    <AppShell title="Files">
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-3 sm:px-4 py-6 compact-v">
        <div className="max-w-4xl 2xl:max-w-5xl mx-auto space-y-4">
          <StudioHero
            icon={<FileText size={20} />}
            title="Files library"
            subtitle="Every upload is ready for chat context, search indexing and media re-analysis from one live workspace."
            actions={
              <>
                <StudioActionButton onClick={() => void load()} tone="accent">
                  {refreshing ? <span className="inline-flex items-center gap-1"><RefreshCw size={12} className="animate-spin" /> Refreshing…</span> : <span className="inline-flex items-center gap-1"><RefreshCw size={12} /> Refresh now</span>}
                </StudioActionButton>
                <StudioActionLink href="/chat">💬 Chat</StudioActionLink>
                <StudioActionLink href="/voice">🎙 Voice</StudioActionLink>
              </>
            }
            stats={[
              { label: "Files", value: files?.length ?? "…" },
              { label: "Indexed", value: indexedCount },
              { label: "Media", value: mediaCount },
              { label: "Storage", value: files ? fmtSize(totalBytes) : "…" },
            ]}
          />
          <div className="flex flex-wrap items-center gap-2">
            <StudioStatusPill label="Library sync" value={lastSyncLabel} tone="accent" pulse={refreshing || liveRefresh} />
            <StudioStatusPill label="Live refresh" value={liveRefresh ? "every 12s" : "paused"} tone={liveRefresh ? "success" : "default"} pulse={liveRefresh} />
            <StudioStatusPill label="Media queue" value={busyId ? "analysis running" : "idle"} tone={busyId ? "success" : "default"} pulse={Boolean(busyId)} />
            <div className="ml-auto">
              <StudioActionButton onClick={() => setLiveRefresh((v) => !v)} tone={liveRefresh ? "success" : "default"}>
                {liveRefresh ? "⏸ Pause live refresh" : "▶ Resume live refresh"}
              </StudioActionButton>
            </div>
          </div>
          <div className="text-xs text-gray-500 space-y-1">
            <p>
              Everything you&apos;ve uploaded — documents feed the chat context + search index (📚), audio/video
              can be re-analyzed any time with the media pipeline.
            </p>
          </div>
          {msg && <p className="text-xs text-yellow-500">{msg}</p>}
          {!files ? (
            <p className="text-sm text-gray-600">Loading…</p>
          ) : files.length === 0 ? (
            <StudioEmptyState
              emoji="🗂️"
              title="No files yet"
              description="Attach documents in chat, or drop audio and video on the Voice page to analyze them here later."
              actions={
                <>
                  <StudioActionLink href="/chat">Attach in chat</StudioActionLink>
                  <StudioActionLink href="/voice">Analyze on Voice page</StudioActionLink>
                </>
              }
            />
          ) : (
            <ul className="space-y-2">
              {files.map((f) => {
                const k = kindOf(f.mime);
                return (
                  <li key={f.id} className="rounded-xl bg-panel border border-line px-3 py-2.5 space-y-2">
                    <div className="flex items-center gap-2.5 text-sm">
                      <span className="text-accent shrink-0">{k.icon}</span>
                      <span className="flex-1 truncate text-gray-200">{f.filename}</span>
                      {f.extracted && (
                        <span className="text-[10px] text-green-400/90 shrink-0" title="Indexed for document search">
                          📚 indexed
                        </span>
                      )}
                      <span className="text-[11px] text-gray-600 shrink-0">
                        {k.label} · {fmtSize(f.size_bytes)}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[11px] flex-wrap">
                      <button
                        onClick={() => download(f)}
                        className="rounded-lg bg-white/5 border border-line px-2.5 py-1 text-gray-300 hover:bg-white/10 transition flex items-center gap-1"
                      >
                        <Download size={11} /> Download
                      </button>
                      {canAnalyze(f) && (
                        <button
                          onClick={() => setOpenId(openId === f.id ? null : f.id)}
                          className="rounded-lg bg-white/5 border border-line px-2.5 py-1 text-gray-300 hover:bg-white/10 transition"
                        >
                          {openId === f.id ? "Hide" : "Analysis"}
                        </button>
                      )}
                      {canAnalyze(f) && (
                        <button
                          onClick={() => reanalyze(f)}
                          disabled={busyId === f.id}
                          className="rounded-lg bg-white/5 border border-line px-2.5 py-1 text-gray-300 hover:bg-white/10 transition flex items-center gap-1 disabled:opacity-40"
                        >
                          {busyId === f.id ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
                          Re-analyze
                        </button>
                      )}
                      <span className="text-[10px] text-gray-600 ml-auto">{(f.created_at ?? "").slice(0, 10)}</span>
                      <button onClick={() => remove(f)} className="text-gray-600 hover:text-red-400 transition" aria-label="Delete file">
                        <Trash2 size={12} />
                      </button>
                    </div>
                    {openId === f.id && canAnalyze(f) && (
                      <div className="rounded-lg bg-base border border-line p-3 space-y-2">
                        {busyId === f.id ? (
                          <p className="text-xs text-gray-500 flex items-center gap-2">
                            <Loader2 size={12} className="animate-spin" /> Analyzing {f.filename}…
                          </p>
                        ) : analysis[f.id] ? (
                          <>
                            {analysis[f.id].transcript && (
                              <details>
                                <summary className="cursor-pointer text-[11px] text-gray-500 hover:text-gray-300">
                                  Transcript / lyrics ({analysis[f.id].transcript.split(/\s+/).length} words)
                                </summary>
                                <p className="mt-1.5 text-xs text-gray-400 whitespace-pre-wrap max-h-40 overflow-y-auto scrollbar-thin">
                                  {analysis[f.id].transcript}
                                </p>
                              </details>
                            )}
                            <p className="text-sm text-gray-200 whitespace-pre-wrap [overflow-wrap:anywhere]">
                              {analysis[f.id].analysis}
                            </p>
                          </>
                        ) : (
                          <p className="text-xs text-gray-500">
                            Press <Sparkles size={10} className="inline" /> Re-analyze to run the media pipeline on this file.
                          </p>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          <StudioNotice>
            Files refresh automatically every few seconds while you work here, so completed re-analysis and new uploads appear without a hard reload.
          </StudioNotice>
        </div>
      </div>
    </AppShell>
  );
}
