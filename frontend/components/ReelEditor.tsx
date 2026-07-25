"use client";

/**
 * 🎞 Reel Editor — record or add clips, arrange them on a timeline, then publish.
 *
 * Everything here is a *draft*: clips are staged on the server as `_ra` assets
 * (never in the feed) and only become a reel when Publish renders the timeline
 * in one ffmpeg pass. Discarding cleans the staged files up.
 *
 * Effect previews use the same CSS the server's ffmpeg chain approximates, so
 * what you see while editing is what gets burned in.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Circle,
  Copy,
  Loader2,
  Mic,
  Music,
  Plus,
  Repeat,
  Scissors,
  Send,
  Square,
  Trash2,
  Video,
  Volume2,
  X,
} from "lucide-react";
import { apiFetch } from "@/lib/api";

export interface Asset {
  id: string;
  name: string;
  kind: "video" | "audio";
  url: string;
  duration: number;
  has_audio: boolean;
}

export interface TimelineClip {
  key: string;
  asset: Asset;
  start: number;
  end: number | null;
  effect: string;
  speed: number;
  volume: number;
}

interface EffectDef {
  id: string;
  label: string;
  emoji: string;
  css: string;
}

const MAX_CLIPS = 10;
const CORNERS: [string, string][] = [
  ["tl", "Top left"],
  ["tr", "Top right"],
  ["bl", "Bottom left"],
  ["br", "Bottom right"],
];

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export default function ReelEditor({
  effects,
  speeds,
  onClose,
  onPublished,
  flash,
}: {
  effects: EffectDef[];
  speeds: Record<string, number>;
  onClose: () => void;
  onPublished: (reel: unknown) => void;
  flash: (m: string) => void;
}) {
  const [clips, setClips] = useState<TimelineClip[]>([]);
  const [selected, setSelected] = useState(0);
  const [bed, setBed] = useState<Asset | null>(null);
  const [bedVolume, setBedVolume] = useState(0.8);
  const [overlay, setOverlay] = useState<Asset | null>(null);
  const [overlayCorner, setOverlayCorner] = useState("tr");
  const [overlayScale, setOverlayScale] = useState(0.3);
  const [caption, setCaption] = useState("");
  const [autoCaptions, setAutoCaptions] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [publishing, setPublishing] = useState(false);

  // camera
  const [recording, setRecording] = useState(false);
  const [camOpen, setCamOpen] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const camRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const previewRef = useRef<HTMLVideoElement>(null);
  const current = clips[selected];

  // Always release the camera: a page that keeps the light on after you leave
  // is the fastest way to lose a user's trust.
  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (timer.current) clearInterval(timer.current);
  }, []);

  useEffect(() => stopStream, [stopStream]);

  async function stage(file: File | Blob, kind: "video" | "audio", filename: string) {
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file, filename);
      fd.append("kind", kind);
      const { asset } = await apiFetch<{ asset: Asset }>("/reels/assets", {
        method: "POST",
        body: fd,
      });
      return asset;
    } catch (e) {
      flash(e instanceof Error ? e.message : "Upload failed");
      return null;
    } finally {
      setUploading(false);
    }
  }

  function addClip(asset: Asset) {
    setClips((cs) => {
      if (cs.length >= MAX_CLIPS) {
        flash(`A reel can hold ${MAX_CLIPS} clips`);
        return cs;
      }
      const next: TimelineClip = {
        key: `${asset.id}-${Date.now()}`,
        asset,
        start: 0,
        end: asset.duration > 0 ? Number(asset.duration.toFixed(2)) : null,
        effect: "none",
        speed: 1,
        volume: 1,
      };
      setSelected(cs.length);
      return [...cs, next];
    });
  }

  async function pickVideo(f: File | null) {
    if (!f) return;
    const a = await stage(f, "video", f.name);
    if (a) addClip(a);
  }

  async function pickAudio(f: File | null) {
    if (!f) return;
    const a = await stage(f, "audio", f.name);
    if (a) {
      setBed(a);
      flash("🎵 Audio track added");
    }
  }

  async function pickOverlay(f: File | null) {
    if (!f) return;
    const a = await stage(f, "video", f.name);
    if (a) {
      setOverlay(a);
      flash("🖼 Overlay added");
    }
  }

  /* ------------------------------------------------------------ camera */
  async function openCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1080 }, height: { ideal: 1920 } },
        audio: true,
      });
      streamRef.current = stream;
      setCamOpen(true);
      // the <video> mounts with the modal, so attach on the next tick
      window.setTimeout(() => {
        if (camRef.current) {
          camRef.current.srcObject = stream;
          camRef.current.play().catch(() => {});
        }
      }, 60);
    } catch {
      flash("Couldn't open the camera — check the browser permission");
    }
  }

  function startRecording() {
    const stream = streamRef.current;
    if (!stream) return;
    chunks.current = [];
    // Codec support differs per browser; let the UA pick when our preference
    // isn't available rather than throwing NotSupportedError.
    const pref = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4"];
    const mime = pref.find((m) => MediaRecorder.isTypeSupported?.(m));
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    rec.onstop = async () => {
      const blob = new Blob(chunks.current, { type: chunks.current[0]?.type || "video/webm" });
      const a = await stage(blob, "video", "capture.webm");
      if (a) addClip(a);
    };
    rec.start();
    recRef.current = rec;
    setRecording(true);
    setElapsed(0);
    timer.current = setInterval(() => setElapsed((s) => s + 1), 1000);
  }

  function stopRecording() {
    recRef.current?.stop();
    setRecording(false);
    if (timer.current) clearInterval(timer.current);
  }

  function closeCamera() {
    if (recording) stopRecording();
    stopStream();
    setCamOpen(false);
  }

  /* --------------------------------------------------------- timeline ops */
  const patchClip = (i: number, next: Partial<TimelineClip>) =>
    setClips((cs) => cs.map((c, n) => (n === i ? { ...c, ...next } : c)));

  function duplicate(i: number) {
    setClips((cs) => {
      if (cs.length >= MAX_CLIPS) {
        flash(`A reel can hold ${MAX_CLIPS} clips`);
        return cs;
      }
      const copy = { ...cs[i], key: `${cs[i].asset.id}-${Date.now()}` };
      const out = [...cs];
      out.splice(i + 1, 0, copy);
      return out;
    });
    flash("Clip duplicated");
  }

  /** Split at the preview playhead — the classic "cut here" gesture. */
  function splitAt(i: number) {
    const c = clips[i];
    const at = previewRef.current?.currentTime ?? 0;
    const from = c.start;
    const to = c.end ?? c.asset.duration;
    const cut = from + at;
    if (cut <= from + 0.25 || cut >= to - 0.25) {
      flash("Move the playhead into the clip to split it");
      return;
    }
    setClips((cs) => {
      if (cs.length >= MAX_CLIPS) {
        flash(`A reel can hold ${MAX_CLIPS} clips`);
        return cs;
      }
      const left = { ...c, end: Number(cut.toFixed(2)) };
      const right = { ...c, key: `${c.asset.id}-${Date.now()}`, start: Number(cut.toFixed(2)), end: to };
      const out = [...cs];
      out.splice(i, 1, left, right);
      return out;
    });
    flash("✂️ Clip split");
  }

  async function removeClip(i: number) {
    const c = clips[i];
    setClips((cs) => cs.filter((_, n) => n !== i));
    setSelected((s) => Math.max(0, Math.min(s, clips.length - 2)));
    // Only unstage when no other clip still points at that asset (a duplicate
    // or a split half would otherwise lose its source file).
    if (!clips.some((x, n) => n !== i && x.asset.name === c.asset.name)) {
      apiFetch(`/reels/assets/${c.asset.name}`, { method: "DELETE" }).catch(() => {});
    }
  }

  const totalSeconds = clips.reduce((sum, c) => {
    const len = (c.end ?? c.asset.duration) - c.start;
    return sum + Math.max(0, len) / (c.speed || 1);
  }, 0);

  async function publish() {
    if (!clips.length || publishing) return;
    setPublishing(true);
    try {
      const { reel } = await apiFetch<{ reel: unknown }>("/reels/publish", {
        method: "POST",
        body: JSON.stringify({
          clips: clips.map((c) => ({
            name: c.asset.name,
            start: c.start,
            end: c.end,
            effect: c.effect,
            speed: c.speed,
            volume: c.volume,
          })),
          audio: bed ? { name: bed.name, volume: bedVolume } : null,
          overlay: overlay
            ? { name: overlay.name, corner: overlayCorner, scale: overlayScale }
            : null,
          caption: caption.trim(),
          captions: autoCaptions,
        }),
      });
      onPublished(reel);
    } catch (e) {
      flash(e instanceof Error ? e.message : "Publish failed");
    } finally {
      setPublishing(false);
    }
  }

  const effectCss = effects.find((e) => e.id === current?.effect)?.css;

  return (
    <div className="fixed inset-0 z-[70] flex flex-col bg-[#0b0b0d]">
      {/* header */}
      <div className="flex shrink-0 items-center justify-between border-b border-line px-4 py-3">
        <button onClick={onClose} className="text-gray-400 hover:text-gray-100">
          <X size={20} />
        </button>
        <div className="text-center">
          <p className="text-sm font-semibold text-gray-100">Edit reel</p>
          <p className="text-[10px] text-gray-500">
            {clips.length} clip{clips.length === 1 ? "" : "s"} · {fmt(totalSeconds)}
          </p>
        </div>
        <button
          onClick={publish}
          disabled={!clips.length || publishing || uploading}
          className="flex items-center gap-1.5 rounded-xl bg-accent px-4 py-2 text-xs font-bold text-[#0b0f14] transition hover:brightness-110 disabled:opacity-40"
        >
          {publishing ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          Publish
        </button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {/* preview */}
        <div className="relative mx-auto aspect-[9/16] max-h-[46vh] w-full max-w-[calc(46vh*9/16)] bg-black">
          {current ? (
            <video
              ref={previewRef}
              key={current.key}
              src={current.asset.url}
              controls
              playsInline
              className="h-full w-full object-contain"
              style={{ filter: effectCss && effectCss !== "none" ? effectCss : undefined }}
            />
          ) : (
            <div className="grid h-full place-items-center px-6 text-center text-xs text-gray-500">
              Record a clip or add one to get started
            </div>
          )}
          {overlay && (
            <div
              className={`pointer-events-none absolute ${
                overlayCorner.startsWith("t") ? "top-3" : "bottom-3"
              } ${overlayCorner.endsWith("l") ? "left-3" : "right-3"} overflow-hidden rounded-lg border border-white/25`}
              style={{ width: `${overlayScale * 100}%` }}
            >
              {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
              <video src={overlay.url} muted className="h-full w-full object-cover" />
            </div>
          )}
        </div>

        {/* add row */}
        <div className="flex flex-wrap items-center justify-center gap-2 border-y border-line bg-white/[0.02] px-3 py-3">
          <button
            onClick={openCamera}
            className="flex items-center gap-1.5 rounded-xl bg-red-500/90 px-3.5 py-2 text-xs font-semibold text-white hover:brightness-110"
          >
            <Circle size={13} className="fill-white" /> Record
          </button>
          <label className="flex cursor-pointer items-center gap-1.5 rounded-xl border border-line px-3.5 py-2 text-xs text-gray-200 hover:border-accent/50">
            <Plus size={13} className="text-accent" /> <Video size={13} /> Video
            <input type="file" accept="video/*" className="hidden"
                   onChange={(e) => pickVideo(e.target.files?.[0] ?? null)} />
          </label>
          <label className="flex cursor-pointer items-center gap-1.5 rounded-xl border border-line px-3.5 py-2 text-xs text-gray-200 hover:border-accent/50">
            <Plus size={13} className="text-accent" /> <Music size={13} /> Audio
            <input type="file" accept="audio/*" className="hidden"
                   onChange={(e) => pickAudio(e.target.files?.[0] ?? null)} />
          </label>
          <label className="flex cursor-pointer items-center gap-1.5 rounded-xl border border-line px-3.5 py-2 text-xs text-gray-200 hover:border-accent/50">
            <Plus size={13} className="text-accent" /> Overlay
            <input type="file" accept="video/*" className="hidden"
                   onChange={(e) => pickOverlay(e.target.files?.[0] ?? null)} />
          </label>
          {uploading && <Loader2 size={15} className="animate-spin text-accent" />}
        </div>

        {/* timeline */}
        {clips.length > 0 && (
          <div className="border-b border-line px-3 py-3">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-gray-500">Timeline</p>
            <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
              {clips.map((c, i) => (
                <button
                  key={c.key}
                  onClick={() => setSelected(i)}
                  className={`relative shrink-0 overflow-hidden rounded-lg border-2 transition ${
                    i === selected ? "border-accent" : "border-transparent opacity-70"
                  }`}
                >
                  {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                  <video
                    src={c.asset.url}
                    muted
                    preload="metadata"
                    className="h-20 w-12 bg-black object-cover"
                    style={{
                      filter: (() => {
                        const css = effects.find((e) => e.id === c.effect)?.css;
                        return css && css !== "none" ? css : undefined;
                      })(),
                    }}
                  />
                  <span className="absolute bottom-0 left-0 right-0 bg-black/70 text-center text-[9px] text-white">
                    {i + 1}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* selected-clip controls */}
        {current && (
          <div className="space-y-4 px-4 py-4">
            <div className="flex flex-wrap gap-2">
              <button onClick={() => splitAt(selected)}
                className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-[11px] text-gray-200 hover:border-accent/50">
                <Scissors size={12} /> Split
              </button>
              <button onClick={() => duplicate(selected)}
                className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-[11px] text-gray-200 hover:border-accent/50">
                <Copy size={12} /> Duplicate
              </button>
              <button onClick={() => removeClip(selected)}
                className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-[11px] text-gray-400 hover:border-red-400/50 hover:text-red-400">
                <Trash2 size={12} /> Remove
              </button>
            </div>

            {/* trim */}
            {current.asset.duration > 0 && (
              <div>
                <p className="mb-1 flex items-center justify-between text-[11px] text-gray-400">
                  <span className="font-semibold uppercase tracking-wide">Trim</span>
                  <span>
                    {current.start.toFixed(1)}s – {(current.end ?? current.asset.duration).toFixed(1)}s
                  </span>
                </p>
                <input
                  type="range" min={0} max={current.asset.duration} step={0.1}
                  value={current.start}
                  onChange={(e) => {
                    const v = Math.min(Number(e.target.value), (current.end ?? current.asset.duration) - 0.3);
                    patchClip(selected, { start: v });
                  }}
                  className="w-full accent-[rgb(var(--mood-accent))]"
                />
                <input
                  type="range" min={0} max={current.asset.duration} step={0.1}
                  value={current.end ?? current.asset.duration}
                  onChange={(e) => {
                    const v = Math.max(Number(e.target.value), current.start + 0.3);
                    patchClip(selected, { end: v });
                  }}
                  className="w-full accent-[rgb(var(--mood-accent))]"
                />
              </div>
            )}

            {/* per-clip volume — the "volume split" */}
            <div>
              <p className="mb-1 flex items-center justify-between text-[11px] text-gray-400">
                <span className="flex items-center gap-1 font-semibold uppercase tracking-wide">
                  <Volume2 size={11} /> Clip volume
                </span>
                <span>{Math.round(current.volume * 100)}%</span>
              </p>
              <input
                type="range" min={0} max={1.5} step={0.05} value={current.volume}
                onChange={(e) => patchClip(selected, { volume: Number(e.target.value) })}
                className="w-full accent-[rgb(var(--mood-accent))]"
              />
            </div>

            {/* effects */}
            <div>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Effect</p>
              <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
                {effects.map((e) => (
                  <button
                    key={e.id}
                    onClick={() => patchClip(selected, { effect: e.id })}
                    className={`shrink-0 rounded-xl border px-3 py-2 text-center transition ${
                      current.effect === e.id ? "border-accent bg-accent/10" : "border-line hover:border-accent/40"
                    }`}
                  >
                    <span className="mb-0.5 block text-lg leading-none"
                          style={{ filter: e.css === "none" ? undefined : e.css }}>
                      {e.emoji}
                    </span>
                    <span className="block text-[10px] text-gray-300">{e.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* speed */}
            <div className="flex items-center gap-3">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">Speed</span>
              <div className="flex gap-1">
                {Object.entries(speeds).map(([label, v]) => (
                  <button
                    key={label}
                    onClick={() => patchClip(selected, { speed: v })}
                    className={`rounded-lg px-2.5 py-1 text-[11px] transition ${
                      current.speed === v
                        ? "bg-accent font-semibold text-[#0b0f14]"
                        : "border border-line text-gray-400"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* audio bed */}
        {bed && (
          <div className="mx-4 mb-3 rounded-xl border border-line bg-white/[0.03] p-3">
            <div className="mb-1.5 flex items-center justify-between">
              <p className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-200">
                <Music size={12} className="text-accent" /> Audio track
              </p>
              <button onClick={() => {
                apiFetch(`/reels/assets/${bed.name}`, { method: "DELETE" }).catch(() => {});
                setBed(null);
              }} className="text-gray-500 hover:text-red-400">
                <Trash2 size={13} />
              </button>
            </div>
            <p className="mb-1 flex justify-between text-[10px] text-gray-500">
              <span>Track volume</span>
              <span>{Math.round(bedVolume * 100)}%</span>
            </p>
            <input type="range" min={0} max={1.5} step={0.05} value={bedVolume}
                   onChange={(e) => setBedVolume(Number(e.target.value))}
                   className="w-full accent-[rgb(var(--mood-accent))]" />
          </div>
        )}

        {/* overlay controls */}
        {overlay && (
          <div className="mx-4 mb-3 rounded-xl border border-line bg-white/[0.03] p-3">
            <div className="mb-2 flex items-center justify-between">
              <p className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-200">
                <Repeat size={12} className="text-accent" /> Overlay
              </p>
              <button onClick={() => {
                apiFetch(`/reels/assets/${overlay.name}`, { method: "DELETE" }).catch(() => {});
                setOverlay(null);
              }} className="text-gray-500 hover:text-red-400">
                <Trash2 size={13} />
              </button>
            </div>
            <div className="mb-2 grid grid-cols-4 gap-1">
              {CORNERS.map(([id, label]) => (
                <button key={id} onClick={() => setOverlayCorner(id)}
                  className={`rounded-lg px-1 py-1.5 text-[9.5px] transition ${
                    overlayCorner === id ? "bg-accent font-semibold text-[#0b0f14]" : "border border-line text-gray-400"
                  }`}>{label}</button>
              ))}
            </div>
            <p className="mb-1 flex justify-between text-[10px] text-gray-500">
              <span>Size</span><span>{Math.round(overlayScale * 100)}%</span>
            </p>
            <input type="range" min={0.15} max={0.6} step={0.05} value={overlayScale}
                   onChange={(e) => setOverlayScale(Number(e.target.value))}
                   className="w-full accent-[rgb(var(--mood-accent))]" />
          </div>
        )}

        {/* caption + publish */}
        <div className="space-y-2 px-4 pb-8">
          <textarea
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            rows={2}
            maxLength={300}
            placeholder="Write a caption…"
            className="w-full resize-none rounded-xl border border-line bg-white/5 p-3 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-accent"
          />
          <label className="flex cursor-pointer items-center gap-2 text-xs text-gray-300">
            <input type="checkbox" checked={autoCaptions}
                   onChange={(e) => setAutoCaptions(e.target.checked)}
                   className="accent-[rgb(var(--mood-accent))]" />
            Auto-captions <span className="text-[10px] text-gray-600">— transcribed and burned in</span>
          </label>
          <button
            onClick={publish}
            disabled={!clips.length || publishing || uploading}
            className="w-full rounded-xl bg-accent py-3 text-sm font-bold text-[#0b0f14] transition hover:brightness-110 disabled:opacity-40"
          >
            {publishing ? (
              <span className="flex items-center justify-center gap-2">
                <Loader2 size={15} className="animate-spin" /> Rendering your reel…
              </span>
            ) : (
              "🚀 Publish reel"
            )}
          </button>
        </div>
      </div>

      {/* ------------------------------------------------------- camera */}
      {camOpen && (
        <div className="fixed inset-0 z-[80] flex flex-col bg-black">
          <div className="relative flex-1">
            {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
            <video ref={camRef} autoPlay muted playsInline className="h-full w-full object-cover" />
            {recording && (
              <div className="absolute left-1/2 top-6 flex -translate-x-1/2 items-center gap-2 rounded-full bg-red-600/90 px-3 py-1.5">
                <span className="h-2 w-2 animate-pulse rounded-full bg-white" />
                <span className="text-xs font-semibold text-white">{fmt(elapsed)}</span>
              </div>
            )}
          </div>
          <div className="flex items-center justify-around bg-black px-6 py-6">
            <button onClick={closeCamera} className="text-sm text-gray-400 hover:text-white">
              Cancel
            </button>
            <button
              onClick={recording ? stopRecording : startRecording}
              aria-label={recording ? "Stop recording" : "Start recording"}
              className="grid h-[74px] w-[74px] place-items-center rounded-full border-4 border-white/80 transition active:scale-95"
            >
              {recording ? (
                <Square size={26} className="fill-red-500 text-red-500" />
              ) : (
                <span className="h-14 w-14 rounded-full bg-red-500" />
              )}
            </button>
            <button
              onClick={closeCamera}
              disabled={recording}
              className="text-sm font-semibold text-accent disabled:opacity-40"
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
