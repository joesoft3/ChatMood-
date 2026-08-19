import type { Metadata } from "next";
import Link from "next/link";
import ErrorBoundary from "@/components/ErrorBoundary";
import HeroVideo from "@/components/HeroVideo";
import LandingNav from "@/components/LandingNav";

export const metadata: Metadata = {
  title: "ChatMood — Grok-class chat, arena, research and AI films",
  description:
    "ChatMood is a Grok-class assistant for streaming chat, live-cited research, blind model debates, and AI films with voice and sound.",
  alternates: { canonical: "/" },
};

const badges = ["S1 ChatMood-4", "⚔️ Arena v2", "🔭 Deep Research", "🎙 Cinema Sound"];

const features: [string, string, string][] = [
  ["💬", "Streaming chat", "Frontier-grade models with a sharp, witty personality — Grok-class answers, your rules."],
  ["🎬", "Video with pure sound & voice", "Text-to-video with an AI voiceover and a cinematic ambient mix, polished by the built-in studio."],
  ["⚔️", "Arena v2", "S1 ChatMood-4, GPT and Gemini debate blind. Ballots, judge verdicts and score cards with one-tap rematch."],
  ["🔭", "Deep research", "Multi-source investigations with live citations and a saved research library."],
  ["🧠", "Long-term memory", "ChatMood remembers what matters between conversations. You stay in control."],
  ["🎤", "Voice mode", "Speak naturally and hear answers back — full duplex voice conversations."],
];

const steps: [string, string][] = [
  ["1", "Create your account — free, 30 seconds, no card."],
  ["2", "Chat, search, generate — images and sound-tracked video included."],
  ["3", "Take it anywhere — web app, Android app, your own custom domain."],
];

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col">
      <ErrorBoundary>
        <LandingNav />
      </ErrorBoundary>

      {/* --------------------------------------------------- hero: video backdrop */}
      <section className="relative flex min-h-[100svh] flex-col items-center justify-center overflow-hidden px-4 sm:px-6 pb-16 pt-24">
        <ErrorBoundary fallback={null}>
          <HeroVideo />
        </ErrorBoundary>
        {/* overlay: dim the loop + melt the hero into the page background below */}
        <div aria-hidden className="absolute inset-0 bg-[#121210]/50" />
        <div
          aria-hidden
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(180deg, rgba(18,18,16,0.35) 0%, rgba(18,18,16,0.15) 40%, rgb(var(--mood-base)) 100%)",
          }}
        />

        <div className="relative max-w-3xl text-center space-y-6">
          <p className="text-xs uppercase tracking-[0.35em] text-accent">ChatMood</p>
          <h1 className="text-[clamp(2.3rem,7vw,4rem)] font-bold leading-[1.06] [text-shadow:0_2px_24px_rgb(0_0_0/0.45)]">
            A Grok-class AI that <span className="text-accent">talks back —</span>
            <br className="hidden sm:block" /> in voice, video and sound.
          </h1>
          <p className="mx-auto max-w-xl text-base sm:text-lg leading-relaxed text-gray-300 [text-shadow:0_1px_16px_rgb(0_0_0/0.5)]">
            Chat, search, see, hear and remember — one calm workspace for research, images, films and real action.
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            {badges.map((b) => (
              <span
                key={b}
                className="rounded-full border border-white/15 bg-black/30 px-3 py-1 text-[11px] text-gray-300 backdrop-blur-sm"
              >
                {b}
              </span>
            ))}
          </div>
          <div className="flex flex-wrap justify-center gap-3 pt-2">
            <Link
              href="/signup"
              className="rounded-2xl bg-accent px-6 py-3 font-semibold text-black transition hover:brightness-110 shadow-[0_12px_28px_rgb(var(--mood-accent)/0.3)]"
            >
              Sign up — free
            </Link>
            <Link
              href="/login"
              className="rounded-2xl border border-white/20 bg-black/25 px-6 py-3 backdrop-blur-sm transition hover:bg-white/10"
            >
              Sign in
            </Link>
          </div>
        </div>

        <p aria-hidden className="absolute bottom-5 text-[10px] uppercase tracking-[0.3em] text-gray-500">
          scroll ↓
        </p>
      </section>

      <section className="border-t border-line px-4 sm:px-6 py-10">
        <div className="mx-auto max-w-2xl space-y-4">
          <h3 className="text-center text-lg font-semibold">ChatMood Home Interface</h3>
          <div className="rounded-2xl border border-line bg-panel p-5 shadow-lg">
            <div className="text-sm text-gray-400 mb-3">Ask ChatMood</div>
            <div className="flex flex-wrap gap-2">
              {/* This is a server-rendered marketing page, so these are real
                  destinations—not client-only alert handlers. Besides being
                  useful, that keeps this route prerenderable for a production
                  deploy. */}
              <Link href="/images" className="rounded-xl bg-accent/20 px-3 py-2 text-sm transition hover:bg-accent/30">
                📷 Create with camera
              </Link>
              <Link href="/voice" className="rounded-xl bg-accent/20 px-3 py-2 text-sm transition hover:bg-accent/30">
                🎤 Talk with voice
              </Link>
              <Link href="/chat" className="rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-black transition hover:brightness-110">
                ✈️ Start a chat
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* --------------------------------------------------- feature grid */}
      <section className="px-4 sm:px-6 py-16 sm:py-20">
        <div className="mx-auto max-w-4xl 2xl:max-w-6xl">
          <h2 className="text-center text-xl font-semibold">One workspace, every mode</h2>
          <p className="mt-2 text-center text-sm text-gray-500">
            Everything talks to everything — no tab hopping, no context lost.
          </p>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 md:grid-cols-3">
            {features.map(([icon, title, desc]) => (
              <div
                key={title}
                className="space-y-2 rounded-2xl border border-line bg-panel p-5 shadow-[0_12px_28px_rgb(0_0_0/0.12)] transition hover:border-accent/40 hover:bg-white/[0.03]"
              >
                <div className="text-2xl">{icon}</div>
                <h3 className="font-semibold">{title}</h3>
                <p className="text-sm leading-relaxed text-gray-500">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* --------------------------------------------------- three steps */}
      <section className="border-t border-line px-4 sm:px-6 py-14">
        <div className="mx-auto max-w-4xl 2xl:max-w-6xl">
          <h2 className="mb-8 text-center text-xl font-semibold">Up and running in three steps</h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {steps.map(([n, text]) => (
              <div key={n} className="flex items-start gap-3 rounded-2xl border border-line bg-panel p-5">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/15 text-sm font-bold text-accent">
                  {n}
                </span>
                <p className="text-sm text-gray-400">{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* --------------------------------------------------- apps */}
      <section className="border-t border-line px-4 sm:px-6 py-14">
        <div className="mx-auto max-w-4xl 2xl:max-w-6xl space-y-5 rounded-3xl border border-line bg-panel p-8 text-center sm:p-10">
          <h2 className="text-xl font-semibold sm:text-2xl">Take ChatMood everywhere</h2>
          <p className="mx-auto max-w-lg text-sm leading-relaxed text-gray-400">
            The Android app brings push notifications for Arena verdicts and approvals, voice mode on the go, and the full
            studio in your pocket.
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            <a
              href="https://github.com/joesoft3/moodai/releases/latest"
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2 rounded-xl bg-accent px-5 py-3 text-sm font-semibold text-black transition hover:brightness-110"
            >
              ⬇️ Android APK — latest release
            </a>
            <span className="flex items-center gap-2 rounded-xl border border-line px-5 py-3 text-sm text-gray-500">
              ▶️ Google Play — in review
            </span>
            <a
              href="https://github.com/joesoft3/moodai"
              target="_blank"
              rel="noreferrer"
              className="rounded-xl border border-line px-5 py-3 text-sm text-gray-300 transition hover:bg-white/5"
            >
              ⭐ Star on GitHub
            </a>
          </div>
          <p className="text-[11px] text-gray-600">
            Free plan included. Add your own AI keys in Settings to unlock higher limits.
          </p>
        </div>
      </section>

      {/* --------------------------------------------------- footer */}
      <footer className="border-t border-line px-4 sm:px-6 py-8">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center gap-x-6 gap-y-3 text-xs text-gray-500 2xl:max-w-6xl">
          <span className="font-semibold text-gray-300">ChatMood</span>
          <span>© 2026 · Built with ❤️ in Accra</span>
          {/* -my-2/py-2 keeps the visual rhythm while giving each link a
              44px-tall tap target (they were 16px — well under the 44px
              minimum and easy to miss on a phone). */}
          <span className="ml-auto -my-2 flex flex-wrap items-center gap-x-5">
            <Link href="/terms" className="inline-flex min-h-[44px] items-center transition hover:text-gray-300">
              Terms of Service
            </Link>
            <Link href="/privacy" className="inline-flex min-h-[44px] items-center transition hover:text-gray-300">
              Privacy Policy
            </Link>
            <Link href="/login" className="inline-flex min-h-[44px] items-center transition hover:text-gray-300">
              Sign in
            </Link>
            <Link href="/signup" className="inline-flex min-h-[44px] items-center transition hover:text-gray-300">
              Sign up
            </Link>
          </span>
        </div>
      </footer>
    </main>
  );
}
