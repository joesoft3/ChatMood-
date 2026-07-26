"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Image as ImageIcon, Search, ShieldCheck, Sparkles } from "lucide-react";
import { apiFetch, token } from "@/lib/api";
import { BrandMark, useBrand } from "@/lib/brand";

const inputCls =
  "w-full rounded-2xl border border-white/10 bg-white/[0.055] px-4 py-3 text-sm text-gray-100 outline-none transition placeholder:text-gray-600 focus:border-accent/55 focus:bg-white/[0.075]";

const PERKS = [
  {
    icon: Sparkles,
    title: "Write and refine",
    text: "Draft, brainstorm, tighten tone and turn rough notes into polished work.",
  },
  {
    icon: Search,
    title: "Research with sources",
    text: "Run cited DeepSearch reports and keep every source ready for follow-up.",
  },
  {
    icon: ImageIcon,
    title: "Create visuals",
    text: "Generate images, direct videos and iterate without leaving the workspace.",
  },
  {
    icon: ShieldCheck,
    title: "Private workspace",
    text: "Chats, files, memory, domains and approvals stay tied to one clean account.",
  },
] as const;

export default function LoginPage() {
  const router = useRouter();
  const brand = useBrand();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await apiFetch<{ access_token: string }>(`/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify(
          mode === "register"
            ? {
                email,
                password,
                display_name: name || undefined,
              }
            : { email, password }
        ),
      });
      token.set(res.access_token);
      const next = new URLSearchParams(window.location.search).get("next");
      router.push(next && next.startsWith("/") ? next : "/chat");
    } catch (err: any) {
      setError(err.message ?? "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-base px-4 py-8 sm:px-6">
      <div aria-hidden className="mood-aurora absolute inset-0" />
      <div className="relative mx-auto grid min-h-[calc(100vh-4rem)] w-full max-w-6xl items-center gap-8 lg:grid-cols-[1.05fr_0.95fr]">
        <section className="hidden flex-col gap-7 pr-6 lg:flex">
          <Link href="/" className="inline-flex w-fit items-center gap-2 rounded-full border border-white/10 bg-white/[0.06] px-3 py-1.5 text-[11px] uppercase tracking-[0.18em] text-gray-400 backdrop-blur-xl transition hover:text-gray-200">
            <BrandMark brand={brand} /> {brand?.brand_name ?? "Mood AI"}
          </Link>
          <div className="space-y-5">
            <h1 className="max-w-2xl text-5xl font-semibold leading-[0.98] tracking-[-0.06em] text-white xl:text-6xl">
              Welcome to the refreshed AI workspace.
            </h1>
            <p className="max-w-xl text-base leading-8 text-gray-400">
              Sign in to keep chat, research, images, films, teams and approvals flowing through one calm interface on desktop and mobile.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {PERKS.map(({ icon: Icon, title, text }) => (
              <div key={title} className="mood-card p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-gray-200">
                  <span className="inline-flex h-9 w-9 items-center justify-center rounded-2xl bg-accent/12 text-accent">
                    <Icon size={15} />
                  </span>
                  {title}
                </div>
                <p className="mt-2 text-sm leading-relaxed text-gray-500">{text}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mood-glass w-full max-w-md justify-self-center rounded-[2rem] p-6 shadow-[0_28px_80px_rgb(0_0_0/0.32)] sm:p-8">
          <div className="mb-6 text-center">
            <div className="inline-flex h-14 w-14 items-center justify-center rounded-3xl border border-white/10 bg-white/[0.06] shadow-[0_0_48px_-18px_rgb(var(--mood-accent))]">
              <BrandMark brand={brand} />
            </div>
            <h1 className="mt-4 text-2xl font-semibold tracking-tight text-white">{brand?.brand_name ?? "Mood AI"}</h1>
            {brand && <p className="mt-1 text-[10px] text-gray-500">powered by Mood AI</p>}
            <p className="mt-2 text-sm text-gray-500">
              {mode === "login" ? "Pick up where you left off" : "Create your free workspace"}
            </p>
          </div>

          <form onSubmit={submit} className="space-y-3">
            {mode === "register" && (
              <input className={inputCls} placeholder="Display name" value={name} onChange={(e) => setName(e.target.value)} />
            )}
            <input
              className={inputCls}
              type="email"
              required
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <input
              className={inputCls}
              type="password"
              required
              minLength={8}
              placeholder="Password (8+ chars)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {error && <p className="rounded-2xl border border-red-400/20 bg-red-400/10 px-3 py-2 text-sm text-red-300">{error}</p>}
            <button
              disabled={busy}
              className="group flex w-full items-center justify-center gap-2 rounded-2xl bg-accent py-3 font-semibold text-black shadow-[0_16px_34px_rgb(var(--mood-accent)/0.28)] transition hover:-translate-y-0.5 hover:brightness-110 disabled:translate-y-0 disabled:opacity-40"
            >
              {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
              {!busy && <ArrowRight size={16} className="transition group-hover:translate-x-0.5" />}
            </button>
          </form>

          <p className="mt-5 text-center text-xs text-gray-500">
            {mode === "login" ? "No account? " : "Have an account? "}
            <button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")} className="inline-flex min-h-[44px] items-center px-1 text-accent underline">
              {mode === "login" ? "Sign up" : "Sign in"}
            </button>
          </p>

          <p className="mt-2 text-center text-[11px] leading-relaxed text-gray-600">
            By continuing you agree to the <a href="/terms" className="inline-flex min-h-[44px] items-center underline hover:text-gray-400">Terms of Service</a> and <a href="/privacy" className="inline-flex min-h-[44px] items-center underline hover:text-gray-400">Privacy Policy</a>.
          </p>
        </section>
      </div>
    </main>
  );
}
