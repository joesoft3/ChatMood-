import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, BrainCircuit, Clapperboard, Globe2, Mic2, Play, Search, ShieldCheck, Sparkles, Swords, WandSparkles } from "lucide-react";
import ErrorBoundary from "@/components/ErrorBoundary";
import HeroVideo from "@/components/HeroVideo";
import LandingNav from "@/components/LandingNav";

export const metadata: Metadata = {
  title: "Mood AI — the AI workspace for chat, research, voice and films",
  description:
    "Mood AI is a polished AI workspace for streaming chat, live-cited research, model arena debates, voice conversations, images and AI films with sound.",
  alternates: { canonical: "/" },
};

const proof = ["S1 Mood-4", "Arena v2", "Live research", "Voice + sound", "Private memory"];

const modes = [
  {
    icon: Sparkles,
    label: "Ask",
    title: "A calmer command center for everyday AI.",
    text: "Chat with fast models, attach files, compare answers, and keep the thread moving without losing context.",
  },
  {
    icon: Search,
    label: "Research",
    title: "Grounded reports with sources you can revisit.",
    text: "DeepSearch plans, checks, cites and stores the report so the next question starts where the last one ended.",
  },
  {
    icon: Clapperboard,
    label: "Create",
    title: "Images, reels and films in the same flow.",
    text: "Go from prompt to storyboard to voiceover and cinematic sound without stitching tools together.",
  },
] as const;

const features = [
  [BrainCircuit, "Streaming chat", "Frontier-grade models with memory, file context and polished markdown answers."],
  [Swords, "Blind arena", "S1 Mood-4, GPT and Gemini debate blind, score each other, and explain the verdict."],
  [Mic2, "Voice mode", "Speak naturally and hear responses back for hands-free brainstorming and follow-up."],
  [WandSparkles, "Media studio", "Generate images and sound-tracked videos, then refine them inside the studio."],
  [Globe2, "Live citations", "Multi-source investigations keep claims tied to the pages they came from."],
  [ShieldCheck, "Workspace control", "Bring your keys, teams, domains, plugins, files and approvals into one secure place."],
] as const;

const stats = [
  ["4", "Core creation modes"],
  ["1", "Unified workspace"],
  ["24/7", "Research + studio flow"],
] as const;

export default function Home() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-base text-gray-100">
      <div aria-hidden className="mood-aurora fixed inset-0 -z-10" />
      <ErrorBoundary>
        <LandingNav />
      </ErrorBoundary>

      <section className="relative isolate flex min-h-[100svh] items-center overflow-hidden px-4 pb-16 pt-24 sm:px-6 lg:pt-28">
        <ErrorBoundary fallback={null}>
          <HeroVideo />
        </ErrorBoundary>
        <div aria-hidden className="absolute inset-0 bg-[linear-gradient(90deg,rgb(var(--mood-base))_0%,rgb(var(--mood-base)_/_0.86)_35%,rgb(var(--mood-base)_/_0.42)_100%)]" />
        <div aria-hidden className="absolute inset-0 bg-[radial-gradient(circle_at_72%_38%,rgb(var(--mood-accent)_/_0.28),transparent_30%),linear-gradient(180deg,transparent_0%,rgb(var(--mood-base))_92%)]" />

        <div className="relative mx-auto grid w-full max-w-7xl items-center gap-12 lg:grid-cols-[1.02fr_0.98fr]">
          <div className="max-w-3xl space-y-7 mood-fade-up">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.06] px-3 py-1.5 text-[11px] font-medium uppercase tracking-[0.22em] text-gray-300 shadow-[0_12px_40px_rgb(0_0_0/0.22)] backdrop-blur-xl">
              <span className="h-2 w-2 rounded-full bg-accent shadow-[0_0_22px_rgb(var(--mood-accent))]" />
              Mood AI super-workspace
            </div>

            <div className="space-y-5">
              <h1 className="max-w-4xl text-[clamp(2.8rem,8vw,6.8rem)] font-semibold leading-[0.95] tracking-[-0.08em] text-white">
                Think, talk, research and create in one place.
              </h1>
              <p className="max-w-2xl text-base leading-8 text-gray-300 sm:text-xl">
                A refreshed AI workspace for sharp answers, live research, blind model debates, voice conversations, images and cinematic films with sound.
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <Link
                href="/login"
                className="group inline-flex items-center gap-2 rounded-2xl bg-accent px-5 py-3 text-sm font-semibold text-black shadow-[0_18px_48px_rgb(var(--mood-accent)_/_0.28)] transition hover:-translate-y-0.5 hover:brightness-110"
              >
                Start free
                <ArrowRight size={16} className="transition group-hover:translate-x-0.5" />
              </Link>
              <Link
                href="/chat"
                className="inline-flex items-center gap-2 rounded-2xl border border-white/12 bg-white/[0.06] px-5 py-3 text-sm font-semibold text-gray-100 backdrop-blur-xl transition hover:-translate-y-0.5 hover:bg-white/[0.1]"
              >
                <Play size={15} /> Open app
              </Link>
            </div>

            <div className="flex flex-wrap gap-2 pt-1">
              {proof.map((item) => (
                <span key={item} className="rounded-full border border-white/10 bg-black/20 px-3 py-1.5 text-[11px] text-gray-300 backdrop-blur-md">
                  {item}
                </span>
              ))}
            </div>
          </div>

          <div className="relative hidden lg:block">
            <div className="absolute -inset-8 rounded-[3rem] bg-accent/15 blur-3xl" />
            <div className="mood-glass relative overflow-hidden rounded-[2.25rem] p-4 shadow-[0_32px_90px_rgb(0_0_0/0.45)]">
              <div className="rounded-[1.75rem] border border-white/10 bg-[#101114]/88 p-4">
                <div className="mb-4 flex items-center justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-gray-500">Live workspace</p>
                    <h2 className="mt-1 text-lg font-semibold">Mood command deck</h2>
                  </div>
                  <span className="rounded-full bg-accent/15 px-3 py-1 text-xs text-accent">online</span>
                </div>
                <div className="space-y-3">
                  {modes.map(({ icon: Icon, label, title, text }) => (
                    <div key={label} className="rounded-3xl border border-white/8 bg-white/[0.045] p-4 transition hover:bg-white/[0.07]">
                      <div className="flex items-start gap-3">
                        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-accent/12 text-accent">
                          <Icon size={18} />
                        </span>
                        <div>
                          <p className="text-[11px] uppercase tracking-[0.22em] text-accent">{label}</p>
                          <h3 className="mt-1 font-semibold text-gray-100">{title}</h3>
                          <p className="mt-1.5 text-sm leading-6 text-gray-500">{text}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-4 grid grid-cols-3 gap-3">
                  {stats.map(([value, label]) => (
                    <div key={label} className="rounded-2xl border border-white/8 bg-black/20 p-3 text-center">
                      <div className="text-xl font-semibold text-white">{value}</div>
                      <div className="mt-1 text-[10px] leading-tight text-gray-500">{label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        <p aria-hidden className="absolute bottom-5 left-1/2 -translate-x-1/2 text-[10px] uppercase tracking-[0.32em] text-gray-600">
          scroll
        </p>
      </section>

      <section className="px-4 py-16 sm:px-6 sm:py-24">
        <div className="mx-auto max-w-7xl">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-accent">Refreshed end to end</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-5xl">Every mode now feels like one app.</h2>
            <p className="mt-4 text-sm leading-7 text-gray-500 sm:text-base">
              The new surface language brings softer glass, clearer hierarchy and faster paths from a question to an answer, report or finished piece of media.
            </p>
          </div>

          <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {features.map(([Icon, title, desc]) => (
              <div key={title} className="mood-card group p-5 transition duration-300 hover:-translate-y-1 hover:border-accent/35">
                <div className="mb-5 flex items-center justify-between">
                  <span className="grid h-11 w-11 place-items-center rounded-2xl bg-accent/12 text-accent shadow-[0_0_38px_-16px_rgb(var(--mood-accent))]">
                    <Icon size={19} />
                  </span>
                  <ArrowRight size={16} className="text-gray-600 transition group-hover:translate-x-0.5 group-hover:text-accent" />
                </div>
                <h3 className="text-base font-semibold text-gray-100">{title}</h3>
                <p className="mt-2 text-sm leading-7 text-gray-500">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="px-4 pb-16 sm:px-6 sm:pb-24">
        <div className="mood-glass mx-auto grid max-w-7xl gap-8 rounded-[2rem] p-6 sm:p-8 lg:grid-cols-[0.85fr_1.15fr] lg:p-10">
          <div className="space-y-4">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-accent">How it works</p>
            <h2 className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">Start with an idea. Ship a result.</h2>
            <p className="text-sm leading-7 text-gray-500">
              Mood keeps the app simple at the surface and powerful underneath: chat, research, arena, media and teams share context instead of competing for it.
            </p>
            <Link href="/login" className="inline-flex items-center gap-2 rounded-2xl bg-white px-5 py-3 text-sm font-semibold text-black transition hover:bg-accent">
              Create account <ArrowRight size={15} />
            </Link>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              ["01", "Ask anything", "Type, speak, attach files, or switch on DeepSearch, plugins and arena."],
              ["02", "Watch Mood work", "See citations, model debates, reasoning summaries and media stages as they happen."],
              ["03", "Save and share", "Export conversations, publish read-only links, and take the Android app with you."],
            ].map(([num, title, text]) => (
              <div key={num} className="rounded-3xl border border-white/10 bg-white/[0.05] p-5">
                <span className="text-xs font-semibold text-accent">{num}</span>
                <h3 className="mt-8 font-semibold text-gray-100">{title}</h3>
                <p className="mt-2 text-sm leading-6 text-gray-500">{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer className="border-t border-white/8 px-4 py-8 sm:px-6">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 text-xs text-gray-500">
          <span className="font-semibold text-gray-300">Mood AI</span>
          <span>© 2026 · Built with ❤️ in Accra</span>
          <span className="ml-auto -my-2 flex flex-wrap items-center gap-x-5">
            <Link href="/terms" className="inline-flex min-h-[44px] items-center transition hover:text-gray-300">
              Terms
            </Link>
            <Link href="/privacy" className="inline-flex min-h-[44px] items-center transition hover:text-gray-300">
              Privacy
            </Link>
            <Link href="/login" className="inline-flex min-h-[44px] items-center transition hover:text-gray-300">
              Sign in
            </Link>
          </span>
        </div>
      </footer>
    </main>
  );
}
