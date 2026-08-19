import type { Metadata } from "next";
import Link from "next/link";
import ErrorBoundary from "@/components/ErrorBoundary";
import LandingComposer from "@/components/LandingComposer";
import LandingFaq, { FAQ_ITEMS } from "@/components/LandingFaq";
import LandingGate from "@/components/LandingGate";
import LandingNav from "@/components/LandingNav";

export const metadata: Metadata = {
  title: "ChatMood — chat, research, images and AI films",
  description:
    "ChatMood is an AI workspace for streaming chat, live-cited research, images, films and voice.",
  alternates: { canonical: "/" },
};

const features: [string, string, string][] = [
  ["💬", "Streaming chat", "Frontier-grade models with a sharp, witty personality — answers, your rules."],
  ["🎬", "Video with sound & voice", "Text-to-video with an AI voiceover and a cinematic ambient mix."],
  ["⚔️", "Arena", "S1 ChatMood-4, GPT and Gemini debate blind. Ballots, verdicts and rematch."],
  ["🔭", "Deep research", "Multi-source investigations with live citations and a saved library."],
  ["🧠", "Long-term memory", "ChatMood remembers what matters between conversations. You stay in control."],
  ["🎤", "Voice mode", "Speak naturally and hear answers back — full duplex voice conversations."],
];

export default function Home() {
  return (
    <main className="flex min-h-[100dvh] flex-col bg-base">
      <LandingGate />
      <ErrorBoundary>
        <LandingNav />
      </ErrorBoundary>

      <section className="flex min-h-[100svh] flex-col items-center justify-center px-4 pb-16 pt-24 sm:px-6">
        <div className="mx-auto w-full max-w-[48rem] space-y-8 text-center">
          <div className="space-y-3">
            <p className="text-sm text-gray-500">ChatMood</p>
            <h1 className="text-[clamp(2rem,6vw,2.75rem)] font-semibold tracking-tight text-gray-100">
              What can I help with?
            </h1>
          </div>
          <LandingComposer />
          <div className="flex flex-wrap items-center justify-center gap-3 pt-1">
            <Link
              href="/signup"
              className="rounded-full bg-white px-5 py-2.5 text-sm font-semibold text-black transition hover:opacity-90"
            >
              Sign up — free
            </Link>
            <Link href="/login" className="rounded-full px-5 py-2.5 text-sm text-gray-300 transition hover:bg-white/5">
              Log in
            </Link>
          </div>
        </div>
      </section>

      <section className="border-t border-line px-4 py-16 sm:px-6 sm:py-20">
        <div className="mx-auto max-w-4xl 2xl:max-w-6xl">
          <h2 className="text-center text-xl font-semibold">One workspace, every mode</h2>
          <p className="mt-2 text-center text-sm text-gray-500">
            Chat, research, images and films — without hopping tabs or losing context.
          </p>
          <div className="mt-10 grid gap-3 sm:grid-cols-2 md:grid-cols-3">
            {features.map(([icon, title, desc]) => (
              <div key={title} className="space-y-2 rounded-2xl bg-composer p-5">
                <div className="text-2xl">{icon}</div>
                <h3 className="font-semibold">{title}</h3>
                <p className="text-sm leading-relaxed text-gray-500">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <LandingFaq />

      {/* FAQPage structured data — same copy as the rendered accordion (LandingFaq),
          so rich results match what visitors actually read. */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            mainEntity: FAQ_ITEMS.map(([name, text]) => ({
              "@type": "Question",
              name,
              acceptedAnswer: { "@type": "Answer", text },
            })),
          }),
        }}
      />

      <section className="border-t border-line px-4 py-14 sm:px-6">
        <div className="mx-auto max-w-4xl space-y-5 rounded-3xl bg-composer p-8 text-center sm:p-10 2xl:max-w-6xl">
          <h2 className="text-xl font-semibold sm:text-2xl">Take ChatMood everywhere</h2>
          <p className="mx-auto max-w-lg text-sm leading-relaxed text-gray-400">
            The Android app brings push notifications for Arena verdicts and approvals, voice mode on the go, and the
            full studio in your pocket.
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            <a
              href="https://github.com/joesoft3/moodai/releases/latest"
              target="_blank"
              rel="noreferrer"
              className="rounded-full bg-white px-5 py-2.5 text-sm font-semibold text-black transition hover:opacity-90"
            >
              Android APK — latest release
            </a>
            <span className="rounded-full px-5 py-2.5 text-sm text-gray-500">Google Play — in review</span>
            <a
              href="https://github.com/joesoft3/moodai"
              target="_blank"
              rel="noreferrer"
              className="rounded-full px-5 py-2.5 text-sm text-gray-300 transition hover:bg-white/5"
            >
              Star on GitHub
            </a>
          </div>
        </div>
      </section>

      <footer className="border-t border-line px-4 py-8 sm:px-6">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center gap-x-6 gap-y-3 text-xs text-gray-500 2xl:max-w-6xl">
          <span className="font-semibold text-gray-300">ChatMood</span>
          <span>© 2026 · Built with ❤️ in Accra</span>
          <span className="ml-auto -my-2 flex flex-wrap items-center gap-x-5">
            <Link href="/terms" className="inline-flex min-h-[44px] items-center transition hover:text-gray-300">
              Terms of Service
            </Link>
            <Link href="/privacy" className="inline-flex min-h-[44px] items-center transition hover:text-gray-300">
              Privacy Policy
            </Link>
            <Link href="/login" className="inline-flex min-h-[44px] items-center transition hover:text-gray-300">
              Log in
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
