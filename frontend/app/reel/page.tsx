"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bookmark,
  Clapperboard,
  Copy,
  Link2,
  Repeat2,
  Sparkles,
  Users,
  Wand2,
  Eye,
  EyeOff,
  Heart,
  Loader2,
  Play,
  Plus,
  Send,
  Trash2,
  Upload,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import AppShell from "@/components/AppShell";
import { SHARE_TARGETS } from "@/components/SocialIcons";
import { StudioEmptyState } from "@/components/StudioChrome";
import { apiFetch } from "@/lib/api";
import { copyText } from "@/lib/clipboard";

/* ---------------------------------------------------------------- types */
interface Reel {
  id: string;
  author: string;
  caption: string;
  source: "upload" | "film" | "chat" | "duet" | "repost";
  url: string;
  poster: string;
  views: number;
  likes: number;
  shares: number;
  saves: number;
  reposts: number;
  parent_id: string;
  parent_author: string;
  effect: string;
  captioned: boolean;
  liked: boolean;
  saved: boolean;
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

interface EffectDef {
  id: string;
  label: string;
  emoji: string;
  css: string;
}

interface Catalog {
  effects: EffectDef[];
  speeds: Record<string, number>;
  caption_styles: string[];
  duet_layouts: string[];
}

interface Stats {
  posts: number;
  live: number;
  views: number;
  likes: number;
  shares: number;
  saves: number;
}

type Tab = "foryou" | "saved" | "mine";

const MAX_MB = 100;

/** 1200 → "1.2K", 3_400_000 → "3.4M" — counters must stay one glanceable line. */
function compact(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0).replace(/\.0$/, "")}K`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

/** "3h ago" / "2d ago" — relative time reads better than a raw date on a feed. */
function ago(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`).getTime();
  const s = Math.max(0, (Date.now() - then) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 604_800) return `${Math.floor(s / 86_400)}d ago`;
  return new Date(then).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const SOURCE_BADGE: Record<Reel["source"], string> = {
  upload: "🎥 Uploaded",
  film: "🎬 Mood film",
  chat: "✨ Made in Mood",
  duet: "🎭 Duet",
  repost: "🔁 Repost",
};

/* --------------------------------------------------------- action button */
function RailButton({
  icon,
  count,
  label,
  active,
  activeClass = "bg-red-500 text-white",
  onClick,
}: {
  icon: React.ReactNode;
  count?: number;
  label: string;
  active?: boolean;
  activeClass?: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      className="group flex flex-col items-center gap-1 outline-none"
    >
      <span
        className={`grid h-11 w-11 place-items-center rounded-full backdrop-blur transition
          active:scale-90 group-focus-visible:ring-2 group-focus-visible:ring-white/70
          ${active ? activeClass : "bg-black/45 text-white hover:bg-black/65"}`}
      >
        {icon}
      </span>
      {count !== undefined && (
        <span className="text-[11px] font-semibold text-white drop-shadow">{compact(count)}</span>
      )}
    </button>
  );
}

/* -------------------------------------------------- social share sheet */
function ShareSheet({
  reel,
  onClose,
  onShared,
}: {
  reel: Reel;
  onClose: () => void;
  onShared: (platform: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const link = reel.url;
  const text = reel.caption ? `${reel.caption} — @${reel.author} on Mood Reel` : `@${reel.author} on Mood Reel`;

  async function copy() {
    const ok = await copyText(link);
    setCopied(ok);
    if (ok) {
      onShared("copy");
      window.setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <div className="fixed inset-0 z-[60] grid place-items-end bg-black/70 backdrop-blur-sm sm:place-items-center" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-full overflow-hidden rounded-t-2xl border border-line bg-panel p-4 sm:max-w-md sm:rounded-2xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-100">Share this reel</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-200">
            <X size={18} />
          </button>
        </div>

        <div className="grid grid-cols-5 gap-1">
          {SHARE_TARGETS.map((t) => (
            <button
              key={t.id}
              onClick={async () => {
                if (t.href) {
                  window.open(t.href(link, text), "_blank", "noopener,noreferrer");
                  onShared(t.id);
                } else {
                  // TikTok/Instagram have no web share intent — copy & paste.
                  const ok = await copyText(link);
                  if (ok) onShared(t.id);
                }
                onClose();
              }}
              className="flex min-w-0 flex-col items-center gap-1.5 rounded-xl px-0.5 py-2.5 transition hover:bg-white/5"
            >
              <span
                className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-white/10"
                style={{ color: t.color, backgroundColor: `${t.color}1A` }}
              >
                {t.icon}
              </span>
              <span className="w-full truncate text-center text-[9.5px] text-gray-400">{t.label}</span>
            </button>
          ))}
        </div>

        <p className="mt-2 text-center text-[10px] text-gray-600">
          TikTok &amp; Instagram don&apos;t allow prefilled web posts — we copy the link for you to paste.
        </p>

        <div className="mt-3 flex items-center gap-2 rounded-xl border border-line bg-white/5 p-2">
          <Link2 size={14} className="shrink-0 text-gray-500" />
          <span className="flex-1 truncate text-[11px] text-gray-400">{link}</span>
          <button
            onClick={copy}
            className="flex shrink-0 items-center gap-1 rounded-lg bg-accent px-2.5 py-1.5 text-[11px] font-semibold text-[#0b0f14] hover:brightness-110"
          >
            <Copy size={12} /> {copied ? "Copied" : "Copy"}
          </button>
        </div>

        {typeof navigator !== "undefined" && "share" in navigator && (
          <button
            onClick={async () => {
              try {
                await navigator.share({ title: `@${reel.author} on Mood Reel`, text, url: link });
                onShared("native");
              } catch {
                /* dismissed — not a share */
              }
              onClose();
            }}
            className="mt-2 w-full rounded-xl border border-line py-2.5 text-xs text-gray-200 hover:border-accent/50"
          >
            More sharing options…
          </button>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- one card */
function ReelCard({
  reel,
  muted,
  toggleMute,
  onLike,
  onSave,
  onShare,
  onDuet,
  onRepost,
  onDelete,
  onVisibility,
  onView,
}: {
  reel: Reel;
  muted: boolean;
  toggleMute: () => void;
  onLike: (id: string) => void;
  onSave: (id: string) => void;
  onShare: (r: Reel) => void;
  onDuet: (r: Reel) => void;
  onRepost: (r: Reel) => void;
  onDelete: (id: string) => void;
  onVisibility: (r: Reel) => void;
  onView: (id: string) => void;
}) {
  const vidRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [failed, setFailed] = useState(false);
  const counted = useRef(false);

  // Autoplay only while the card actually fills the screen — an off-screen
  // <video> that keeps decoding is the fastest way to melt a phone battery.
  useEffect(() => {
    const el = vidRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        const visible = entry.intersectionRatio > 0.6;
        if (visible) {
          el.play().catch(() => {});
          if (!counted.current) {
            counted.current = true;
            onView(reel.id);
          }
        } else {
          el.pause();
          el.currentTime = 0;
        }
      },
      { threshold: [0, 0.6, 1] },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [reel.id, onView]);

  return (
    <section className="relative mx-auto h-full w-full max-w-[calc(100vh*9/16)] snap-start snap-always overflow-hidden bg-black">
      {reel.url && !failed ? (
        <video
          ref={vidRef}
          src={reel.url}
          poster={reel.poster || undefined}
          loop
          muted={muted}
          playsInline
          preload="metadata"
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onError={() => setFailed(true)}
          onTimeUpdate={(e) => {
            const v = e.currentTarget;
            if (v.duration) setProgress((v.currentTime / v.duration) * 100);
          }}
          onClick={() => {
            const el = vidRef.current;
            if (!el) return;
            if (el.paused) el.play().catch(() => {});
            else el.pause();
          }}
          className="h-full w-full object-contain"
        />
      ) : (
        <div className="grid h-full w-full place-items-center px-6 text-center text-sm text-gray-500">
          {failed ? "This video couldn't be loaded." : "This reel is no longer available."}
        </div>
      )}

      {/* tap-to-play affordance */}
      {!playing && reel.url && !failed && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <span className="grid h-16 w-16 place-items-center rounded-full bg-black/45 backdrop-blur">
            <Play size={30} className="ml-1 text-white/90" />
          </span>
        </div>
      )}

      {/* unposted ribbon — only the author ever sees this card */}
      {reel.status === "hidden" && (
        <div className="absolute left-3 top-3 rounded-full bg-amber-500/90 px-2.5 py-1 text-[10px] font-bold text-black">
          UNPOSTED — only you can see this
        </div>
      )}

      {/* scrub progress */}
      <div className="absolute inset-x-0 bottom-0 h-0.5 bg-white/15">
        <div className="h-full bg-white/85 transition-[width] duration-150" style={{ width: `${progress}%` }} />
      </div>

      {/* caption + author */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/45 to-transparent p-4 pb-6 pr-[4.75rem]">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-full bg-accent/85 text-[11px] font-bold uppercase text-black">
            {reel.author.slice(0, 1)}
          </span>
          <p className="text-sm font-semibold text-white">@{reel.author}</p>
          <span className="text-[11px] text-gray-400">· {ago(reel.created_at)}</span>
        </div>
        {reel.parent_author && (
          <p className="mt-1 flex items-center gap-1 text-[11px] font-medium text-accent">
            {reel.source === "duet" ? <Users size={11} /> : <Repeat2 size={11} />}
            {reel.source === "duet" ? "Duet with" : "Reposted from"} @{reel.parent_author}
          </p>
        )}
        {reel.caption && (
          <p className="mt-1.5 line-clamp-3 text-[13px] leading-snug text-gray-100">{reel.caption}</p>
        )}
        <p className="mt-1.5 flex items-center gap-2 text-[11px] text-gray-400">
          <span>{SOURCE_BADGE[reel.source]}</span>
          <span>·</span>
          <span className="flex items-center gap-1">
            <Eye size={11} /> {compact(reel.views)}
          </span>
          {reel.effect && (
            <>
              <span>·</span>
              <span className="flex items-center gap-1 text-accent">
                <Wand2 size={11} /> {reel.effect}
              </span>
            </>
          )}
          {reel.captioned && (
            <>
              <span>·</span>
              <span className="text-accent">CC</span>
            </>
          )}
        </p>
      </div>

      {/* right rail */}
      <div className="absolute bottom-24 right-3 flex flex-col items-center gap-3.5">
        <RailButton
          icon={<Heart size={20} className={reel.liked ? "fill-white" : ""} />}
          count={reel.likes}
          label={reel.liked ? "Unlike" : "Like"}
          active={reel.liked}
          onClick={() => onLike(reel.id)}
        />
        <RailButton
          icon={<Bookmark size={19} className={reel.saved ? "fill-white" : ""} />}
          count={reel.saves}
          label={reel.saved ? "Remove from saved" : "Save"}
          active={reel.saved}
          activeClass="bg-accent text-black"
          onClick={() => onSave(reel.id)}
        />
        <RailButton
          icon={<Repeat2 size={19} />}
          count={reel.reposts}
          label={reel.mine ? "You can't repost your own reel" : "Repost to your profile"}
          onClick={() => onRepost(reel)}
        />
        <RailButton
          icon={<Send size={18} />}
          count={reel.shares}
          label="Share to WhatsApp, X, Facebook and more"
          onClick={() => onShare(reel)}
        />
        {!reel.mine && (
          <RailButton icon={<Users size={19} />} label="Duet with this reel" onClick={() => onDuet(reel)} />
        )}
        <RailButton icon={muted ? <VolumeX size={19} /> : <Volume2 size={19} />} label={muted ? "Unmute" : "Mute"} onClick={toggleMute} />

        {reel.mine && (
          <>
            <RailButton
              icon={reel.status === "live" ? <EyeOff size={18} /> : <Eye size={18} />}
              label={reel.status === "live" ? "Unpost (hide from the feed)" : "Post again"}
              onClick={() => onVisibility(reel)}
            />
            <RailButton icon={<Trash2 size={18} />} label="Delete this reel" onClick={() => onDelete(reel.id)} />
          </>
        )}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ page */
export default function ReelPage() {
  const [reels, setReels] = useState<Reel[] | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [films, setFilms] = useState<Film[]>([]);
  const [muted, setMuted] = useState(true);
  const [composerOpen, setComposerOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("foryou");
  const [composerTab, setComposerTab] = useState<"upload" | "share">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [caption, setCaption] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [shareFor, setShareFor] = useState<Reel | null>(null);
  const [duetFor, setDuetFor] = useState<Reel | null>(null);
  const [duetFile, setDuetFile] = useState<File | null>(null);
  const [duetLayout, setDuetLayout] = useState("side");
  const [duetAudio, setDuetAudio] = useState("both");
  // studio options for a new upload
  const [effect, setEffect] = useState("none");
  const [speed, setSpeed] = useState(1);
  const [autoCaptions, setAutoCaptions] = useState(false);

  const flash = useCallback((t: string) => {
    setMsg(t);
    window.setTimeout(() => setMsg(""), 4000);
  }, []);

  const query = useMemo(
    () => (tab === "saved" ? "?saved=true" : tab === "mine" ? "?mine=true" : ""),
    [tab],
  );

  const load = useCallback(async () => {
    try {
      const j = await apiFetch<{ reels: Reel[] }>(`/reels${query}`);
      setReels(j.reels);
    } catch {
      setReels((r) => r ?? []);
    }
  }, [query]);

  const loadStats = useCallback(() => {
    apiFetch<Stats>("/reels/stats").then(setStats).catch(() => {});
  }, []);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    loadStats();
  }, [loadStats]);

  // Effect catalog drives both the chips and the live CSS preview.
  useEffect(() => {
    apiFetch<Catalog>("/reels/effects").then(setCatalog).catch(() => {});
  }, []);

  // Films are only fetched once the creator actually opens the Share tab.
  useEffect(() => {
    if (!composerOpen || composerTab !== "share" || films.length) return;
    apiFetch<{ films: Film[] }>("/media/films")
      .then((j) => setFilms(j.films.filter((f) => f.status === "done")))
      .catch(() => {});
  }, [composerOpen, composerTab, films.length]);

  const patch = useCallback((id: string, next: Partial<Reel>) => {
    setReels((rs) => (rs ?? []).map((r) => (r.id === id ? { ...r, ...next } : r)));
  }, []);

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
      fd.append("effect", effect);
      fd.append("speed", String(speed));
      fd.append("captions", String(autoCaptions));
      const j = await apiFetch<{ reel: Reel }>("/reels/upload", { method: "POST", body: fd });
      if (tab !== "saved") setReels((r) => [j.reel, ...(r ?? [])]);
      setComposerOpen(false);
      setFile(null);
      setCaption("");
      loadStats();
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
      if (tab !== "saved") setReels((r) => [j.reel, ...(r ?? [])]);
      setComposerOpen(false);
      setCaption("");
      loadStats();
      flash("🎉 Shared to the reel");
    } catch (e) {
      flash(e instanceof Error ? e.message : "Share failed");
    } finally {
      setBusy(false);
    }
  }

  // Optimistic like/save — counters must feel instant, then reconcile against
  // the server's authoritative number (or roll back if the call failed).
  const like = useCallback(
    async (id: string) => {
      const before = (reels ?? []).find((r) => r.id === id);
      if (!before) return;
      patch(id, { liked: !before.liked, likes: before.likes + (before.liked ? -1 : 1) });
      try {
        const j = await apiFetch<{ liked: boolean; likes: number }>(`/reels/${id}/like`, { method: "POST" });
        patch(id, { liked: j.liked, likes: j.likes });
      } catch {
        patch(id, { liked: before.liked, likes: before.likes });
      }
    },
    [reels, patch],
  );

  const save = useCallback(
    async (id: string) => {
      const before = (reels ?? []).find((r) => r.id === id);
      if (!before) return;
      patch(id, { saved: !before.saved, saves: before.saves + (before.saved ? -1 : 1) });
      try {
        const j = await apiFetch<{ saved: boolean; saves: number }>(`/reels/${id}/save`, { method: "POST" });
        patch(id, { saved: j.saved, saves: j.saves });
        flash(j.saved ? "🔖 Saved to your collection" : "Removed from saved");
        // Un-saving from inside the Saved tab should drop the card immediately.
        if (!j.saved && tab === "saved") setReels((rs) => (rs ?? []).filter((r) => r.id !== id));
      } catch {
        patch(id, { saved: before.saved, saves: before.saves });
        flash("Couldn't update your saves");
      }
    },
    [reels, patch, flash, tab],
  );

  // The sheet does the actual sharing; this only records that it happened, so
  // a dismissed share sheet never inflates the counter.
  const countShare = useCallback(
    async (reel: Reel, platform: string) => {
      patch(reel.id, { shares: reel.shares + 1 });
      try {
        const j = await apiFetch<{ shares: number }>(`/reels/${reel.id}/share`, { method: "POST" });
        patch(reel.id, { shares: j.shares });
      } catch {
        patch(reel.id, { shares: reel.shares });
      }
      flash(platform === "copy" ? "🔗 Link copied" : `Shared to ${platform}`);
    },
    [patch, flash],
  );

  const repost = useCallback(
    async (r: Reel) => {
      if (r.mine) {
        flash("That's already your reel");
        return;
      }
      try {
        const j = await apiFetch<{ reel: Reel; reposts: number }>(`/reels/${r.id}/repost`, {
          method: "POST",
          body: JSON.stringify({}),
        });
        patch(r.id, { reposts: j.reposts });
        flash("🔁 Reposted to your profile");
        if (tab === "mine") setReels((rs) => [j.reel, ...(rs ?? [])]);
      } catch (e) {
        flash(e instanceof Error ? e.message : "Repost failed");
      }
    },
    [patch, flash, tab],
  );

  async function submitDuet() {
    if (!duetFor || !duetFile || busy) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", duetFile);
      fd.append("caption", caption.trim());
      fd.append("layout", duetLayout);
      fd.append("audio", duetAudio);
      fd.append("effect", effect);
      const j = await apiFetch<{ reel: Reel }>(`/reels/${duetFor.id}/duet`, {
        method: "POST",
        body: fd,
      });
      setReels((rs) => [j.reel, ...(rs ?? [])]);
      setDuetFor(null);
      setDuetFile(null);
      setCaption("");
      loadStats();
      flash("🎭 Duet posted");
    } catch (e) {
      flash(e instanceof Error ? e.message : "Duet failed");
    } finally {
      setBusy(false);
    }
  }

  const view = useCallback((id: string) => {
    apiFetch(`/reels/${id}/view`, { method: "POST" }).catch(() => {});
  }, []);

  const visibility = useCallback(
    async (r: Reel) => {
      const live = r.status !== "live";
      try {
        await apiFetch(`/reels/${r.id}/visibility`, {
          method: "POST",
          body: JSON.stringify({ live }),
        });
        patch(r.id, { status: live ? "live" : "hidden" });
        loadStats();
        flash(live ? "✅ Back on the feed" : "🚫 Unposted — hidden from the feed");
        if (!live && tab === "foryou") setReels((rs) => (rs ?? []).filter((x) => x.id !== r.id));
      } catch (e) {
        flash(e instanceof Error ? e.message : "Couldn't change visibility");
      }
    },
    [patch, flash, loadStats, tab],
  );

  const remove = useCallback(
    async (id: string) => {
      if (!window.confirm("Delete this reel permanently? Its views, likes and saves go with it.")) return;
      try {
        await apiFetch(`/reels/${id}`, { method: "DELETE" });
        setReels((rs) => (rs ?? []).filter((r) => r.id !== id));
        loadStats();
        flash("🗑 Reel deleted");
      } catch (e) {
        flash(e instanceof Error ? e.message : "Delete failed");
      }
    },
    [flash, loadStats],
  );

  const postButton = (
    <button
      onClick={() => setComposerOpen(true)}
      className="flex items-center gap-1.5 rounded-xl bg-accent px-3.5 py-2 text-xs font-semibold text-[#0b0f14] transition hover:brightness-110"
    >
      <Plus size={14} /> Post
    </button>
  );

  const TABS: [Tab, string][] = [
    ["foryou", "For you"],
    ["saved", "Saved"],
    ["mine", "My reels"],
  ];

  const empty = {
    foryou: ["📺", "The reel is quiet", "Post a clip from your camera roll, or share a film you made in Mood — it lands here for every creator to watch."],
    saved: ["🔖", "Nothing saved yet", "Tap the bookmark on any reel and it'll wait for you here."],
    mine: ["🎬", "You haven't posted yet", "Your posts — live and unposted — collect here with their views, likes, shares and saves."],
  }[tab];

  return (
    <AppShell title="Reel" headerRight={postButton}>
      {msg && (
        <div className="shrink-0 border-b border-line bg-accent/10 px-4 py-2 text-center text-xs text-accent">
          {msg}
        </div>
      )}

      {/* feed tabs */}
      <div className="flex shrink-0 items-center justify-center gap-1 border-b border-line bg-base/80 px-4 py-2 backdrop-blur">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            onClick={() => {
              if (id === tab) return;
              setTab(id);
              setReels(null);
            }}
            className={`rounded-full px-4 py-1.5 text-xs transition ${
              tab === id ? "bg-white font-semibold text-black" : "text-gray-400 hover:text-gray-200"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* 📊 creator totals — the profile strip, shown on your own tab */}
      {tab === "mine" && stats && (
        <div className="grid shrink-0 grid-cols-5 gap-px border-b border-line bg-line text-center">
          {([
            ["Posts", stats.posts],
            ["Live", stats.live],
            ["Views", stats.views],
            ["Likes", stats.likes],
            ["Shares", stats.shares],
          ] as [string, number][]).map(([label, value]) => (
            <div key={label} className="bg-base px-1 py-2.5">
              <p className="text-sm font-semibold text-gray-100">{compact(value)}</p>
              <p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p>
            </div>
          ))}
        </div>
      )}

      {reels === null ? (
        <div className="grid flex-1 place-items-center">
          <Loader2 className="animate-spin text-gray-600" />
        </div>
      ) : reels.length === 0 ? (
        <div className="p-4">
          <StudioEmptyState
            emoji={empty[0]}
            title={empty[1]}
            description={empty[2]}
            actions={
              tab === "saved" ? (
                <button
                  onClick={() => setTab("foryou")}
                  className="rounded-xl border border-line px-4 py-2 text-xs text-gray-200 hover:border-accent/50"
                >
                  Browse the feed
                </button>
              ) : (
                <button
                  onClick={() => setComposerOpen(true)}
                  className="rounded-xl bg-accent px-4 py-2 text-xs font-semibold text-[#0b0f14] hover:brightness-110"
                >
                  <Plus size={13} className="mr-1 inline" /> Post to the reel
                </button>
              )
            }
          />
        </div>
      ) : (
        // full-bleed vertical snap feed — one reel per screen
        <div className="flex-1 snap-y snap-mandatory overflow-y-auto overscroll-contain scrollbar-thin">
          {reels.map((r) => (
            <div key={r.id} className="h-full w-full bg-black">
              <ReelCard
                reel={r}
                muted={muted}
                toggleMute={() => setMuted((m) => !m)}
                onLike={like}
                onSave={save}
                onShare={setShareFor}
                onDuet={(r) => {
                  setDuetFor(r);
                  setCaption("");
                }}
                onRepost={repost}
                onDelete={remove}
                onVisibility={visibility}
                onView={view}
              />
            </div>
          ))}
        </div>
      )}

      {/* ------------------------------------------------ share sheet */}
      {shareFor && (
        <ShareSheet
          reel={shareFor}
          onClose={() => setShareFor(null)}
          onShared={(platform) => countShare(shareFor, platform)}
        />
      )}

      {/* ------------------------------------------------ duet studio */}
      {duetFor && (
        <div
          className="fixed inset-0 z-[60] grid place-items-end bg-black/70 backdrop-blur-sm sm:place-items-center"
          onClick={() => setDuetFor(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="max-h-[88vh] w-full overflow-y-auto rounded-t-2xl border border-line bg-panel p-4 sm:max-w-lg sm:rounded-2xl"
          >
            <div className="mb-1 flex items-center justify-between">
              <h2 className="flex items-center gap-1.5 text-sm font-semibold text-gray-100">
                <Users size={15} className="text-accent" /> Duet with @{duetFor.author}
              </h2>
              <button onClick={() => setDuetFor(null)} className="text-gray-500 hover:text-gray-200">
                <X size={18} />
              </button>
            </div>
            <p className="mb-3 text-[11px] text-gray-500">
              Their reel stays untouched — your duet is posted as a new reel that credits them.
            </p>

            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Layout</p>
            <div className="mb-3 grid grid-cols-3 gap-2">
              {([["side", "Side by side", "▌▐"], ["top", "Top & bottom", "▀▄"], ["green", "Inset", "▣"]] as const).map(
                ([id, label, glyph]) => (
                  <button
                    key={id}
                    onClick={() => setDuetLayout(id)}
                    className={`rounded-xl border px-2 py-3 text-center transition ${
                      duetLayout === id ? "border-accent bg-accent/10" : "border-line hover:border-accent/40"
                    }`}
                  >
                    <span className="block text-lg leading-none text-gray-200">{glyph}</span>
                    <span className="mt-1 block text-[10px] text-gray-400">{label}</span>
                  </button>
                ),
              )}
            </div>

            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Audio</p>
            <div className="mb-3 flex gap-1">
              {([["both", "Both"], ["mine", "Mine only"], ["theirs", "Theirs only"]] as const).map(([id, label]) => (
                <button
                  key={id}
                  onClick={() => setDuetAudio(id)}
                  className={`flex-1 rounded-lg px-2 py-1.5 text-[11px] transition ${
                    duetAudio === id ? "bg-accent font-semibold text-[#0b0f14]" : "border border-line text-gray-400"
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
              placeholder={`Duet with @${duetFor.author}…`}
              className="mb-3 w-full resize-none rounded-xl border border-line bg-white/5 p-3 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-accent"
            />

            <label className="mb-3 flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed border-line px-4 py-6 text-center transition hover:border-accent/50">
              <Upload size={20} className="text-accent" />
              <span className="text-xs text-gray-300">{duetFile ? duetFile.name : "Choose your side of the duet"}</span>
              <span className="text-[10px] text-gray-600">MP4, MOV or WebM · up to {MAX_MB} MB</span>
              <input
                type="file"
                accept="video/mp4,video/quicktime,video/webm"
                className="hidden"
                onChange={(e) => setDuetFile(e.target.files?.[0] ?? null)}
              />
            </label>

            <button
              onClick={submitDuet}
              disabled={!duetFile || busy}
              className="w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-[#0b0f14] transition hover:brightness-110 disabled:opacity-40"
            >
              {busy ? <Loader2 size={15} className="mx-auto animate-spin" /> : "Post the duet"}
            </button>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------- composer */}
      {composerOpen && (
        <div
          className="fixed inset-0 z-50 grid place-items-end bg-black/70 backdrop-blur-sm sm:place-items-center"
          onClick={() => setComposerOpen(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="max-h-[86vh] w-full overflow-y-auto rounded-t-2xl border border-line bg-panel p-4 sm:max-w-lg sm:rounded-2xl"
          >
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
                  onClick={() => setComposerTab(id)}
                  className={`flex-1 rounded-lg px-3 py-2 text-xs transition ${
                    composerTab === id
                      ? "bg-accent font-semibold text-[#0b0f14]"
                      : "text-gray-400 hover:text-gray-200"
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
              className="w-full resize-none rounded-xl border border-line bg-white/5 p-3 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-accent"
            />
            <p className="mb-3 mt-1 text-right text-[10px] text-gray-600">{caption.length}/300</p>

            {composerTab === "upload" ? (
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
                {/* 🎨 effects — the chip preview uses the SAME css the server
                    burns in, so what you pick is what you get */}
                <div>
                  <p className="mb-1.5 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                    <Sparkles size={11} className="text-accent" /> Effect
                  </p>
                  <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
                    {(catalog?.effects ?? []).map((e) => (
                      <button
                        key={e.id}
                        onClick={() => setEffect(e.id)}
                        className={`shrink-0 rounded-xl border px-3 py-2 text-center transition ${
                          effect === e.id ? "border-accent bg-accent/10" : "border-line hover:border-accent/40"
                        }`}
                      >
                        <span
                          className="mb-0.5 block text-lg leading-none"
                          style={{ filter: e.css === "none" ? undefined : e.css }}
                        >
                          {e.emoji}
                        </span>
                        <span className="block text-[10px] text-gray-300">{e.label}</span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">Speed</span>
                  <div className="flex gap-1">
                    {Object.entries(catalog?.speeds ?? { "1x": 1 }).map(([label, v]) => (
                      <button
                        key={label}
                        onClick={() => setSpeed(v)}
                        className={`rounded-lg px-2.5 py-1 text-[11px] transition ${
                          speed === v ? "bg-accent font-semibold text-[#0b0f14]" : "border border-line text-gray-400"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                <label className="flex cursor-pointer items-center gap-2 text-xs text-gray-300">
                  <input
                    type="checkbox"
                    checked={autoCaptions}
                    onChange={(e) => setAutoCaptions(e.target.checked)}
                    className="accent-[rgb(var(--mood-accent))]"
                  />
                  <span className="flex items-center gap-1">
                    Auto-captions <span className="text-[10px] text-gray-600">— transcribed and burned in</span>
                  </span>
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
                    No finished films yet — make one in the Films studio and it&apos;ll show up here.
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
