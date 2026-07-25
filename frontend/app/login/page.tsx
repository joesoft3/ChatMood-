"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Image as ImageIcon, Search, ShieldCheck, Sparkles } from "lucide-react";
import { apiFetch, token } from "@/lib/api";
import { BrandMark, useBrand } from "@/lib/brand";

const inputCls =
  "w-full rounded-2xl bg-[#111214] border border-white/8 px-4 py-3 text-sm text-gray-100 outline-none focus:border-accent/50 placeholder-gray-600 transition";

const PERKS = [
  {
    icon: Sparkles,
    title: "Write and refine",
    text: "Draft messages, fix tone, brainstorm ideas, and push from rough notes to polished work.",
  },
  {
    icon: Search,
    title: "Research with sources",
    text: "Run deep, cited research and keep the report in your library for later follow-up.",
  },
  {
    icon: ImageIcon,
    title: "Create visuals",
    text: "Generate images, direct videos, and iterate on media without leaving the workspace.",
  },
  {
    icon: ShieldCheck,
    title: "Private workspace",
    text: "Keep chats, files, memory, domains, and approvals tied to one clean account.",
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
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,rgba(124,155,255,0.14),transparent_34%)] px-4 py-8 sm:px-6">
      <div className="mx-auto grid min-h-[calc(100vh-4rem)] w-full max-w-6xl items-center gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="hidden lg:flex flex-col gap-6 pr-6">
          <div className="space-y-4">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/8 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-gray-500">
              <BrandMark brand={brand} /> {brand?.brand_name ?? "Mood AI"}
            </div>
            <h1 className="text-4xl xl:text-5xl font-semibold tracking-tight text-white leading-[1.05]">
              A focused AI workspace for chat, research, images and video.
            </h1>
            <p className="max-w-xl text-base text-gray-400 leading-relaxed">
              Sign in to keep every conversation, source, generation, team workflow and approval in one clean workspace that feels fast on mobile and desktop.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            {PERKS.map(({ icon: Icon, title, text }) => (
              <div key={title} className="rounded-2xl border border-white/8 bg-[#141415] p-4 shadow-[0_12px_28px_rgb(0_0_0/0.16)]">
                <div className="flex items-center gap-2 text-sm font-medium text-gray-200">
                  <span className="inline-flex h-8 w-8 items-center justify-center rounded-xl bg-accent/10 text-accent">
                    <Icon size={15} />
                  </span>
                  {title}
                </div>
                <p className="mt-2 text-sm leading-relaxed text-gray-500">{text}</p>
              </div>
            ))}
          </div>
        </section>

        <div className="w-full max-w-sm justify-self-center bg-[#141415] border border-white/8 rounded-3xl p-8 space-y-6 shadow-[0_18px_48px_rgb(0_0_0/0.24)]">
          <div className="text-center space-y-2">
            <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-white/5 border border-white/8">
              <BrandMark brand={brand} />
            </div>
            <h1 className="text-2xl font-semibold text-white">{brand?.brand_name ?? "Mood AI"}</h1>
            {brand && <p className="text-[10px] text-gray-500">powered by Mood AI</p>}
            <p className="text-sm text-gray-500">
              {mode === "login" ? "Welcome back" : "Create your account"}
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
            {error && <p className="text-sm text-red-400">{error}</p>}
            <button
              disabled={busy}
              className="w-full rounded-2xl bg-accent text-black font-semibold py-3 disabled:opacity-40 hover:brightness-110 transition shadow-[0_10px_24px_rgb(var(--mood-accent)/0.3)]"
            >
              {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>

          <p className="text-xs text-center text-gray-500">
            {mode === "login" ? "No account? " : "Have an account? "}
            <button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")} className="inline-flex min-h-[44px] items-center px-1 text-accent underline">
              {mode === "login" ? "Sign up" : "Sign in"}
            </button>
          </p>

          <p className="text-[11px] text-center text-gray-600 leading-relaxed">
            By continuing you agree to the <a href="/terms" className="inline-flex min-h-[44px] items-center underline hover:text-gray-400">Terms of Service</a> and <a href="/privacy" className="inline-flex min-h-[44px] items-center underline hover:text-gray-400">Privacy Policy</a>.
          </p>
        </div>
      </div>
    </div>
  );
}
