import type { Metadata } from "next";
import Link from "next/link";
import { API_IS_RELATIVE, apiOrigin, serverApiBase } from "@/lib/apiBase";

// 🎬 Public film share page — beautiful OG previews (video + hero poster),
// no login wall. Server-rendered from the API's public film endpoint.


// This page is server-rendered, but the URLs it emits are followed by the
// *browser*: resolve them against the public API base (a same-origin "/api/v1"
// path when the app proxies), never against the server's internal origin.
function resolvePublicMediaUrl(u: string): string {
  if (!u) return "";
  const idx = u.indexOf("/api/v1/");
  const path = idx >= 0 ? u.slice(idx) : u.startsWith("/api/") ? u : null;
  if (path === null) return u;
  return API_IS_RELATIVE ? path : `${apiOrigin()}${path}`;
}

interface ShareFilm {
  id: string;
  title: string;
  brand_name?: string | null;
  url: string;
  poster: string;
  scenes: number;
  duration_seconds: number;
  aspect_ratio: string;
  audio: string;
  style: string;
  created_at: string | null;
}

async function loadFilm(id: string): Promise<ShareFilm | null> {
  try {
    // SSR fetch: must be absolute, so use the internal/server-side base.
    const res = await fetch(`${serverApiBase()}/media/public/films/${id}`, {
      next: { revalidate: 300 },
    });
    if (!res.ok) return null;
    return (await res.json()) as ShareFilm;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const film = await loadFilm(id);
  if (!film) {
    return { title: "Film not found · ChatMood", robots: { index: false } };
  }
  const description = `${film.scenes}-scene AI film directed with ChatMood — ${
    film.audio === "voice+ambience" ? "AI voiceover + cinematic ambience" : film.audio === "voice" ? "AI voiceover" : "direction"
  }.`;
  return {
    title: `${film.title} — a ChatMood film`,
    description,
    openGraph: {
      type: "video.other",
      title: film.title,
      description,
      videos: film.url ? [{ url: resolvePublicMediaUrl(film.url), type: "video/mp4" }] : undefined,
      images: film.poster ? [{ url: resolvePublicMediaUrl(film.poster), alt: film.title }] : undefined,
    },
    twitter: { card: "summary_large_image", title: film.title, description, images: film.poster ? [resolvePublicMediaUrl(film.poster)] : undefined },
  };
}

export default async function FilmSharePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const film = await loadFilm(id);

  return (
    <main className="min-h-screen flex flex-col items-center px-4 sm:px-6 py-10 sm:py-14">
      <div className="w-full max-w-3xl space-y-6">
        <div className="text-center space-y-1">
          <Link href="/" className="text-xs uppercase tracking-[0.3em] text-accent hover:brightness-125 transition">
            ChatMood · Films
          </Link>
        </div>

        {!film ? (
          <div className="rounded-2xl border border-line bg-panel p-10 text-center space-y-3">
            <div className="text-4xl">🥀</div>
            <h1 className="font-semibold">This film link has expired</h1>
            <p className="text-sm text-gray-500">
              Films stream from a rotating 24-hour media cache. Ask the director for a fresh link — or make your own.
            </p>
          </div>
        ) : (
          <>
            <h1 className="text-center text-[clamp(1.3rem,4.5vw,2rem)] font-bold leading-tight">{film.title}</h1>

            <div className="rounded-3xl overflow-hidden border border-line bg-panel shadow-2xl shadow-black/40">
              {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
              <video
                src={resolvePublicMediaUrl(film.url)}
                poster={film.poster ? resolvePublicMediaUrl(film.poster) : undefined}
                preload="metadata"
                controls
                playsInline
                autoPlay={false}
                className={`w-full bg-black ${film.aspect_ratio === "9:16" ? "aspect-[9/16] max-h-[70vh] mx-auto" : film.aspect_ratio === "1:1" ? "aspect-square" : "aspect-video"}`}
              />
              <div className="flex flex-wrap items-center gap-1.5 px-4 py-3">
                <span className="text-[11px] rounded-full bg-white/5 border border-line px-2 py-0.5 text-gray-400">🎬 {film.scenes}-scene film</span>
                <span className="text-[11px] rounded-full bg-white/5 border border-line px-2 py-0.5 text-gray-400">{film.duration_seconds}s</span>
                <span className="text-[11px] rounded-full bg-white/5 border border-line px-2 py-0.5 text-gray-400">{film.aspect_ratio}</span>
                <span className="text-[11px] rounded-full bg-white/5 border border-line px-2 py-0.5 text-gray-400">{film.style.replace("_", " ")}</span>
                {film.audio !== "none" && (
                  <span className="text-[11px] rounded-full bg-accent/10 border border-accent/30 px-2 py-0.5 text-accent">
                    {film.audio === "voice+ambience" ? "🎼 AI voice + ambience" : "🎙 AI voiceover"}
                  </span>
                )}
              </div>
            </div>

            {/* Professional CTA band */}
            <div className="rounded-2xl border border-line bg-panel p-5 sm:p-6 flex flex-col sm:flex-row items-center gap-4">
              <p className="text-sm text-gray-400 text-center sm:text-left flex-1">
                {film.brand_name ? (
                  <span className="text-amber-300 font-semibold">by {film.brand_name} · </span>
                ) : null}
                <span className="text-gray-200 font-semibold">Directed with ChatMood</span> — one prompt, four model
                brains, a film with studio voice and sound. Make yours free in 30 seconds.
              </p>
              <Link
                href="/signup"
                className="rounded-xl bg-accent text-black font-semibold px-5 py-3 text-sm hover:brightness-110 transition shrink-0"
              >
                🎬 Direct your own film
              </Link>
            </div>
          </>
        )}

        <footer className="flex justify-center gap-5 text-[11px] text-gray-600 pt-2">
          <Link href="/terms" className="hover:text-gray-400 transition">Terms</Link>
          <Link href="/privacy" className="hover:text-gray-400 transition">Privacy</Link>
          <span>© 2026 ChatMood · Accra</span>
        </footer>
      </div>
    </main>
  );
}
