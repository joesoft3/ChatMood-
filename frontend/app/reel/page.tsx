"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Clapperboard,
  Heart,
  Loader2,
  Play,
  Plus,
  Trash2,
  Upload,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import AppShell from "@/components/AppShell";
import { StudioEmptyState } from "@/components/StudioChrome";
import { apiFetch } from "@/lib/api";

/* ---------------------------------------------------------------- types */
interface Reel {
  id: string;
  author: string;
  caption: string;
  source: "upload" | "film" | "chat";
  url: string;
  poster: string;
  views: number;
  likes: number;
  liked: boolean;
  mine: boolean;
  status: "live" | "hidden";
  created_at: string | null;
}

interface Film {
  id: string;
  prompt: string;
  status: string;
  poster: string;
}

const MAX_MB = 100;

/* ------------------------------------------------------------- one card */
function ReelCard({
  reel,
  muted,
  toggleMute,
  onLike,
  onDelete,
  onView,
}: {
  reel: Reel;
  muted: boolean;
  toggleMute: () => void;
  onLike: (id: string) => void;
  onDelete: (id: string) => void;
  onView: (id: string) => void;
}) {
  const vidRef = useRef<HTMLVideoElement>(null);
  const [active, setActive] = useState(false);
  const counted = useRef(false);

  // Autoplay only while the card actually fills the screen — an off-screen
  // <video> that keeps decoding is the fastest way to melt a phone battery.
  useEffect(() => {
    const el = vidRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        const visible = entry.intersectionRatio > 0.6;
        setActive(visible);
        if (visible) {
          el.play().catch(() => {});
          if (!counted.current) {
            counted.current = true;
            onView(reel.id);
          }
        } else {
          el.pause();
        }
      },
      { threshold: [0, 0.6, 1] },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [reel.id, onView]);

  return (
    <section className="relative h-full w-full snap-start snap-always overflow-hidden bg-black">
      {reel.url ? (
        <video
          ref={vidRef}
          src={reel.url}
          poster={reel.poster || undefined}
          loop
          muted={muted}
          playsInline
          preload="metadata"
          onClick={() => {
            const el = vidRef.current;
            if (!el) return;
            el.paused ? el.play().catch(() => {}) : el.pause();
          }}
          className="h-full w-full object-contain"
        />
      ) : (
        <div className="grid h-full w-full place-items-center text-sm text-gray-500">
          This reel is no longer available
        </div>
      )}

      {!active && reel.url && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <Play size={44} className="text-white/40" />
        </div>
      )}

      {/* caption + author */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent p-4 pb-6 pr-20">
        <p className="text-sm font-semibold text-white">@{reel.author}</p>
        {reel.caption && <p className="mt-1 line-clamp-3 text-[13px] text-gray-200">{reel.caption}</p>}
        <p className="mt-1.5 text-[11px] text-gray-400">
          {reel.source === "upload" ? "🎥 uploaded" : reel.source === "film" ? "🎬 Mood film" : "✨ made in Mood"}
          {" · "}
          {reel.views} {reel.views === 1 ? "view" : "views"}
          {reel.status === "hidden" && " · 🚫 unposted"}
        </p>
      </div>

      {/* right rail */}
      <div className="absolute bottom-24 right-3 flex flex-col items-center gap-4">
        <button
          onClick={() => onLike(reel.id)}
          aria-label={reel.liked ? "Unlike" : "Like"}
          className="flex flex-col items-center gap-1 text-white transition active:scale-90"
        >
          <span className={`grid h-11 w-11 place-items-center rounded-full backdrop-blur ${reel.liked ? "bg-red-500/90" : "bg-black/40"}`}>
            <Heart size={20} className={reel.liked ? "fill-white text-white" : ""} />
          </span>
          <span className="text-[11px] font-medium">{reel.likes}</span>
        </button>

        <button
          onClick={toggleMute}
          aria-label={muted ? "Unmute" : "Mute"}
          className="grid h-11 w-11 place-items-center rounded-full bg-black/40 text-white backdrop-blur transition active:scale-90"
        >
          {muted ? <VolumeX size={19} /> : <Volume2 size={19} />}
        </button>

        {reel.mine && (
          <button
            onClick={() => onDelete(reel.id)}
            aria-label="Delete reel"
            className="grid h-11 w-11 place-items-center rounded-full bg-black/40 text-gray-300 backdrop-blur transition hover:text-red-400 active:scale-90"
          >
            <Trash2 size={18} />
          </button>
        )}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ page */
export default function ReelPage() {
  const [reels, setReels] = useState<Reel[] | null>(null);
  const [films, setFilms] = useState<Film[]>([]);
  const [muted, setMuted] = useState(true);
  const [composerOpen, setComposerOpen] = useState(false);
  const [tab, setTab] = useState<"upload" | "share">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [caption, setCaption] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [mineOnly, setMineOnly] = useState(false);

  const flash = (t: string) => {
    setMsg(t);
    window.setTimeout(() => setMsg(""), 4500);
  };

  const load = useCallback(async () => {
    try {
      const j = await apiFetch<{ reels: Reel[] }>(`/reels${mineOnly ? "?mine=true" : ""}`);
      setReels(j.reels);
    } catch {
      setReels((r) => r ?? []);
    }
  }, [mineOnly]);

  useEffect(() => {
    load();
  }, [load]);

  // Films are only needed once the creator opens the Share tab.
  useEffect(() => {
    if (!composerOpen || tab !== "share" || films.length) return;
    apiFetch<{ films: Film[] }>("/media/films")
      .then((j) => setFilms(j.films.filter((f) => f.status === "done")))
      .catch(() => {});
  }, [composerOpen, tab, films.length]);

  async function upload() {
    if (!file || busy) return;
    if (file.size > MAX_MB * 1024 * 1024) {
      flash(`That clip is over ${MAX_MB} MB — trim it and try again.`);
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("caption", caption.trim());
      const j = await apiFetch<{ reel: Reel }>("/reels/upload", { method: "POST", body: fd });
      setReels((r) => [j.reel, ...(r ?? [])]);
      setComposerOpen(false);
      setFile(null);
      setCaption("");
      flash("🎉 Posted to the reel");
    } catch (e) {
      flash(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function shareFilm(filmId: string) {
    if (busy) return;
    setBusy(true);
    try {
      const j = await apiFetch<{ reel: Reel }>("/reels/share", {
        method: "POST",
        body: JSON.stringify({ film_id: filmId, caption: caption.trim() }),
      });
      setReels((r) => [j.reel, ...(r ?? [])]);
      setComposerOpen(false);
      setCaption("");
      flash("🎉 Shared to the reel");
    } catch (e) {
      flash(e instanceof Error ? e.message : "Share failed");
    } finally {
      setBusy(false);
    }
  }

  // Optimistic like — the counter must feel instant, and we reconcile with the
  // server's authoritative count (or roll back) as soon as it answers.
  const like = useCallback(async (id: string) => {
    setReels((rs) =>
      (rs ?? []).map((r) =>
        r.id === id ? { ...r, liked: !r.liked, likes: r.likes + (r.liked ? -1 : 1) } : r,
      ),
    );
    try {
      const j = await apiFetch<{ liked: boolean; likes: number }>(`/reels/${id}/like`, { method: "POST" });
      setReels((rs) => (rs ?? []).map((r) => (r.id === id ? { ...r, liked: j.liked, likes: j.likes } : r)));
    } catch {
      setReels((rs) =>
        (rs ?? []).map((r) =>
          r.id === id ? { ...r, liked: !r.liked, likes: r.likes + (r.liked ? -1 : 1) } : r,
        ),
      );
    }
  }, []);

  const view = useCallback((id: string) => {
    apiFetch(`/reels/${id}/view`, { method: "POST" }).catch(() => {});
  }, []);

  const remove = useCallback(async (id: string) => {
    if (!window.confirm("Delete this reel? This can't be undone.")) return;
    try {
      await apiFetch(`/reels/${id}`, { method: "DELETE" });
      setReels((rs) => (rs ?? []).filter((r) => r.id !== id));
    } catch (e) {
      flash(e instanceof Error ? e.message : "Delete failed");
    }
  }, []);

  const postButton = (
    <button
      onClick={() => setComposerOpen(true)}
      className="flex items-center gap-1.5 rounded-xl bg-accent px-3.5 py-2 text-xs font-semibold text-[#0b0f14] transition hover:brightness-110"
    >
      <Plus size={14} /> Post
    </button>
  );

  return (
    <AppShell title="Reel" headerRight={postButton}>
      {msg && (
        <div className="border-b border-line bg-accent/10 px-4 py-2 text-center text-xs text-accent">{msg}</div>
      )}

      {/* feed switch */}
      <div className="flex items-center justify-center gap-1 border-b border-line bg-base/80 px-4 py-2 backdrop-blur">
        {([["For you", false], ["My reels", true]] as const).map(([label, val]) => (
          <button
            key={label}
            onClick={() => {
              setMineOnly(val);
              setReels(null);
            }}
            className={`rounded-full px-4 py-1.5 text-xs transition ${
              mineOnly === val ? "bg-white text-black font-semibold" : "text-gray-400 hover:text-gray-200"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {reels === null ? (
        <div className="grid flex-1 place-items-center">
          <Loader2 className="animate-spin text-gray-600" />
        </div>
      ) : reels.length === 0 ? (
        <div className="p-4">
          <StudioEmptyState
            emoji="📺"
            title={mineOnly ? "You haven't posted yet" : "The reel is quiet"}
            description="Post a clip from your camera roll, or share a film you made in Mood — it lands here for every creator to watch."
            actions={
              <button
                onClick={() => setComposerOpen(true)}
                className="rounded-xl bg-accent px-4 py-2 text-xs font-semibold text-[#0b0f14] hover:brightness-110"
              >
                <Plus size={13} className="mr-1 inline" /> Post to the reel
              </button>
            }
          />
        </div>
      ) : (
        // full-bleed vertical snap feed — one reel per screen
        <div className="flex-1 snap-y snap-mandatory overflow-y-auto overscroll-contain scrollbar-thin">
          {reels.map((r) => (
            <div key={r.id} className="h-full w-full">
              <ReelCard
                reel={r}
                muted={muted}
                toggleMute={() => setMuted((m) => !m)}
                onLike={like}
                onDelete={remove}
                onView={view}
              />
            </div>
          ))}
        </div>
      )}

      {/* ---------------------------------------------------- composer */}
      {composerOpen && (
        <div className="fixed inset-0 z-50 grid place-items-end bg-black/70 backdrop-blur-sm sm:place-items-center">
          <div className="max-h-[86vh] w-full overflow-y-auto rounded-t-2xl border border-line bg-panel p-4 sm:max-w-lg sm:rounded-2xl">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-100">Post to the reel</h2>
              <button onClick={() => setComposerOpen(false)} className="text-gray-500 hover:text-gray-200">
                <X size={18} />
              </button>
            </div>

            <div className="mb-3 flex gap-1 rounded-xl border border-line bg-white/5 p-1">
              {([["upload", "🎥 Upload"], ["share", "🎬 Share a film"]] as const).map(([id, label]) => (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={`flex-1 rounded-lg px-3 py-2 text-xs transition ${
                    tab === id ? "bg-accent text-[#0b0f14] font-semibold" : "text-gray-400 hover:text-gray-200"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            <textarea
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              rows={2}
              maxLength={300}
              placeholder="Say something about this reel…"
              className="mb-3 w-full resize-none rounded-xl border border-line bg-white/5 p-3 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-accent"
            />

            {tab === "upload" ? (
              <div className="space-y-3">
                <label className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed border-line px-4 py-7 text-center transition hover:border-accent/50">
                  <Upload size={22} className="text-accent" />
                  <span className="text-xs text-gray-300">{file ? file.name : "Choose a video"}</span>
                  <span className="text-[10px] text-gray-600">MP4, MOV or WebM · up to {MAX_MB} MB</span>
                  <input
                    type="file"
                    accept="video/mp4,video/quicktime,video/webm"
                    className="hidden"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  />
                </label>
                <button
                  onClick={upload}
                  disabled={!file || busy}
                  className="w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-[#0b0f14] transition hover:brightness-110 disabled:opacity-40"
                >
                  {busy ? <Loader2 size={15} className="mx-auto animate-spin" /> : "Post to the reel"}
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                {films.length === 0 ? (
                  <p className="py-6 text-center text-xs text-gray-500">
                    No finished films yet — make one in the Films studio and it'll show up here.
                  </p>
                ) : (
                  films.map((f) => (
                    <button
                      key={f.id}
                      onClick={() => shareFilm(f.id)}
                      disabled={busy}
                      className="flex w-full items-center gap-3 rounded-xl border border-line px-3 py-2.5 text-left transition hover:border-accent/50 disabled:opacity-40"
                    >
                      <span className="grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-lg bg-black">
                        {f.poster ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={f.poster} alt="" className="h-full w-full object-cover" />
                        ) : (
                          <Clapperboard size={15} className="text-gray-600" />
                        )}
                      </span>
                      <span className="line-clamp-2 flex-1 text-xs text-gray-300">{f.prompt}</span>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </AppShell>
  );
}
