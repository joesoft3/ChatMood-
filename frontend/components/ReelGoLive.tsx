"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Copy, Loader2, Radio, Square, Users, Video } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { copyText } from "@/lib/clipboard";

interface Stream {
  provider: string;
  stream_id: string;
  ingest_url: string;
  stream_key: string;
  playback_url: string;
}

interface LiveReel {
  id: string;
  live_state: string;
  live_viewers: number;
  live_peak_viewers: number;
  caption: string;
}

/**
 * 🔴 Go Live — provision a broadcast, show the creator their ingest details,
 * and track viewers until they end it.
 *
 * The stream key is a WRITE credential (anyone holding it can broadcast as this
 * creator), so it is returned exactly once by `/reels/live/start` and is never
 * re-fetchable. That's why it's masked here by default and the component keeps
 * it only in memory — a refresh loses it, which is the correct trade.
 */
export default function ReelGoLive({
  configured,
  providerLabel,
  onClose,
  onStarted,
}: {
  configured: boolean;
  providerLabel: string;
  onClose: () => void;
  onStarted?: () => void;
}) {
  const [caption, setCaption] = useState("");
  const [stream, setStream] = useState<Stream | null>(null);
  const [reel, setReel] = useState<LiveReel | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [copied, setCopied] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef<number | null>(null);

  // Camera preview: a monitor so the creator can frame themselves. The actual
  // broadcast goes out over RTMP from their encoder (OBS / Streamlabs / phone),
  // which is what every managed provider expects.
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stopPreview = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  // Always release the camera — a page that keeps the light on after you leave
  // reads as spyware.
  useEffect(() => stopPreview, [stopPreview]);

  async function openPreview() {
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1080 } },
        audio: true,
      });
      streamRef.current = s;
      if (videoRef.current) {
        videoRef.current.srcObject = s;
        await videoRef.current.play().catch(() => {});
      }
    } catch {
      setErr("Couldn't open the camera — check the browser permission.");
    }
  }

  async function start() {
    setBusy(true);
    setErr("");
    try {
      const r = await apiFetch<{ reel: LiveReel; stream: Stream }>("/reels/live/start", {
        method: "POST",
        body: (() => {
          const fd = new FormData();
          fd.append("caption", caption.trim());
          return fd;
        })(),
      });
      setStream(r.stream);
      setReel(r.reel);
      startedAt.current = Date.now();
      onStarted?.();
    } catch (e: any) {
      setErr(e.message ?? "Couldn't start the broadcast");
    } finally {
      setBusy(false);
    }
  }

  async function end() {
    if (!reel) return;
    if (!window.confirm("End the broadcast? Your post stays in the feed as a replay.")) return;
    setBusy(true);
    try {
      await apiFetch(`/reels/live/${reel.id}/end`, { method: "POST" });
      stopPreview();
      onClose();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  // Poll viewers + tick the timer while live.
  useEffect(() => {
    if (!reel || reel.live_state !== "live") return;
    const id = window.setInterval(async () => {
      if (startedAt.current) setElapsed(Math.floor((Date.now() - startedAt.current) / 1000));
      try {
        const fd = new FormData();
        fd.append("joining", "false"); // a poll is not a new viewer
        const j = await apiFetch<{ viewers: number; peak: number }>(
          `/reels/live/${reel.id}/heartbeat`,
          { method: "POST", body: fd },
        );
        setReel((r) => (r ? { ...r, live_viewers: j.viewers, live_peak_viewers: j.peak } : r));
      } catch {
        /* a dropped poll must not kill the broadcast UI */
      }
    }, 10000);
    return () => window.clearInterval(id);
  }, [reel]);

  async function copy(text: string, what: string) {
    await copyText(text);
    setCopied(what);
    window.setTimeout(() => setCopied(""), 1800);
  }

  const mmss = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/95 backdrop-blur">
      <header className="flex items-center gap-3 border-b border-line px-4 py-3">
        <Radio size={16} className={stream ? "animate-pulse text-red-500" : "text-gray-400"} />
        <h2 className="text-sm font-semibold text-gray-100">
          {stream ? "You're live" : "Go Live"}
        </h2>
        {stream && (
          <>
            <span className="rounded-full bg-red-600 px-2 py-0.5 text-[10px] font-bold text-white">
              LIVE
            </span>
            <span className="text-[11px] tabular-nums text-gray-400">{mmss}</span>
            <span className="inline-flex items-center gap-1 text-[11px] text-gray-400">
              <Users size={11} /> {reel?.live_viewers ?? 0}
            </span>
          </>
        )}
        <button
          onClick={() => {
            stopPreview();
            onClose();
          }}
          className="ml-auto text-xs text-gray-400 hover:text-white"
        >
          {stream ? "Hide" : "Close"}
        </button>
      </header>

      <div className="flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-lg space-y-4">
          {!configured && (
            <div className="rounded-xl border border-yellow-500/30 bg-yellow-500/10 p-3 text-xs text-yellow-300">
              Live streaming isn&apos;t switched on for this deployment yet. The owner needs to set{" "}
              <code>LIVE_PROVIDER</code> and the matching provider keys.
            </div>
          )}
          {err && (
            <div className="rounded-xl border border-red-400/30 bg-red-400/10 p-3 text-xs text-red-300">
              {err}
            </div>
          )}

          {/* camera monitor */}
          <div className="relative aspect-[9/16] max-h-[46vh] overflow-hidden rounded-2xl border border-line bg-black">
            <video
              ref={videoRef}
              muted
              playsInline
              className="h-full w-full object-cover"
            />
            {!streamRef.current && (
              <button
                onClick={openPreview}
                className="absolute inset-0 grid place-items-center gap-2 text-gray-400 hover:text-white"
              >
                <Video size={26} />
                <span className="text-xs">Tap to preview your camera</span>
              </button>
            )}
          </div>

          {!stream ? (
            <>
              <input
                value={caption}
                onChange={(e) => setCaption(e.target.value)}
                maxLength={200}
                placeholder="What's this stream about?"
                className="w-full rounded-xl border border-line bg-panel px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
              />
              <button
                onClick={start}
                disabled={busy || !configured}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-red-600 px-4 py-3 text-sm font-semibold text-white transition hover:brightness-110 disabled:opacity-40"
              >
                {busy ? <Loader2 size={15} className="animate-spin" /> : <Radio size={15} />}
                Start broadcasting
              </button>
              <p className="text-[11px] leading-relaxed text-gray-500">
                Starting creates a live post at the top of the feed. You&apos;ll get an RTMP address
                and key to paste into OBS, Streamlabs or your phone&apos;s streaming app.
              </p>
            </>
          ) : (
            <>
              <div className="space-y-2 rounded-xl border border-line bg-panel p-3">
                <p className="text-[11px] text-gray-400">
                  Paste these into your streaming app ({providerLabel || stream.provider}):
                </p>
                <div className="space-y-1.5">
                  <label className="text-[10px] uppercase tracking-wide text-gray-600">
                    Server / RTMP URL
                  </label>
                  <div className="flex gap-2">
                    <code className="min-w-0 flex-1 truncate rounded-lg bg-base px-2.5 py-2 text-[11px] text-gray-200">
                      {stream.ingest_url}
                    </code>
                    <button
                      onClick={() => copy(stream.ingest_url, "url")}
                      className="rounded-lg border border-line px-2.5 py-2 text-[10px] text-gray-300 hover:border-accent/40"
                    >
                      <Copy size={11} /> {copied === "url" ? "✓" : ""}
                    </button>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <label className="text-[10px] uppercase tracking-wide text-gray-600">
                    Stream key — keep this secret
                  </label>
                  <div className="flex gap-2">
                    <code className="min-w-0 flex-1 truncate rounded-lg bg-base px-2.5 py-2 text-[11px] text-gray-200">
                      {showKey ? stream.stream_key : "•".repeat(Math.min(28, stream.stream_key.length))}
                    </code>
                    <button
                      onClick={() => setShowKey((v) => !v)}
                      className="rounded-lg border border-line px-2.5 py-2 text-[10px] text-gray-300"
                    >
                      {showKey ? "Hide" : "Show"}
                    </button>
                    <button
                      onClick={() => copy(stream.stream_key, "key")}
                      className="rounded-lg border border-line px-2.5 py-2 text-[10px] text-gray-300 hover:border-accent/40"
                    >
                      <Copy size={11} /> {copied === "key" ? "✓" : ""}
                    </button>
                  </div>
                  <p className="text-[10px] text-gray-600">
                    Shown once — anyone with this key can broadcast as you.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 text-center">
                <div className="rounded-xl border border-line bg-panel px-3 py-3">
                  <p className="text-lg font-semibold text-gray-100">{reel?.live_viewers ?? 0}</p>
                  <p className="text-[10px] text-gray-500">Watching now</p>
                </div>
                <div className="rounded-xl border border-line bg-panel px-3 py-3">
                  <p className="text-lg font-semibold text-gray-100">
                    {reel?.live_peak_viewers ?? 0}
                  </p>
                  <p className="text-[10px] text-gray-500">Peak</p>
                </div>
              </div>

              <button
                onClick={end}
                disabled={busy}
                className="flex w-full items-center justify-center gap-2 rounded-xl border border-red-400/40 bg-red-400/10 px-4 py-3 text-sm font-semibold text-red-300 transition hover:bg-red-400/20 disabled:opacity-50"
              >
                <Square size={14} /> End broadcast
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
