"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Image as ImageIcon, Search, ShieldCheck, Sparkles } from "lucide-react";
import { apiFetch, token } from "@/lib/api";
import { BrandMark, useBrand } from "@/lib/brand";
import { safeNextPath, signInHref, signUpHref } from "@/lib/auth";

const inputCls =
  "w-full rounded-2xl bg-composer px-4 py-3 text-sm text-gray-100 outline-none placeholder-gray-600 transition";

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

export default function AuthScreen({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const brand = useBrand();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [accessCode, setAccessCode] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [nextPath, setNextPath] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const next = safeNextPath(params.get("next"));
    setNextPath(next);
    if (params.get("deleted") === "1") {
      setNotice("Your ChatMood account and data were permanently deleted.");
    }
    if (token.get() && params.get("deleted") !== "1") {
      router.replace(next && next.startsWith("/") ? next : "/chat");
    }
  }, [router]);

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
                app_password: accessCode.trim() || undefined,
              }
            : { email, password }
        ),
      });
      token.set(res.access_token);
      const next = nextPath ?? safeNextPath(new URLSearchParams(window.location.search).get("next"));
      router.push(next ?? "/chat");
    } catch (err: any) {
      setError(err.message ?? "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const switchHref = mode === "login" ? signUpHref(nextPath) : signInHref(nextPath);

  return (
    /* Height uses dvh, not vh. iOS Safari's 100vh includes the collapsible URL
       bar, so `min-h-screen` + `calc(100vh-4rem)` reserved more space than the
       screen actually shows and pushed the card's lower half (submit button,
       "Sign up" toggle, Terms links) below the fold on first paint. The rest of
       the app already avoids raw vh via .app-height / --app-h (globals.css);
       this page bypasses AppShell, so it opts into dvh directly. */
    <div className="min-h-[100dvh] bg-base px-4 py-8 sm:px-6">
      <div className="mx-auto grid min-h-[calc(100dvh-4rem)] w-full max-w-6xl items-center gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="hidden lg:flex flex-col gap-6 pr-6">
          <div className="space-y-4">
            <div className="inline-flex items-center gap-2 rounded-full bg-composer px-3 py-1 text-[11px] text-gray-500">
              <BrandMark brand={brand} /> {brand?.brand_name ?? "ChatMood"}
            </div>
            {/* Deliberately not an <h1>: this whole section is `hidden lg:flex`,
                so an h1 here would disappear below lg AND compete with the sign-in
                card's h1 above it. It's a tagline, styled large — the heading role
                lives on the card, which renders at every breakpoint. */}
            <p className="text-4xl xl:text-5xl font-semibold tracking-tight text-white leading-[1.05]">
              A focused AI workspace for chat, research, images and video.
            </p>
            <p className="max-w-xl text-base text-gray-400 leading-relaxed">
              {mode === "login"
                ? "Sign in to keep every conversation, source, generation, team workflow and approval in one clean workspace that feels fast on mobile and desktop."
                : "Create a free account to keep every conversation, source, generation, team workflow and approval in one clean workspace."}
            </p>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            {PERKS.map(({ icon: Icon, title, text }) => (
              <div key={title} className="rounded-2xl bg-composer p-4">
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

        <div className="w-full max-w-sm justify-self-center rounded-3xl bg-composer p-8 space-y-6">
          <div className="text-center space-y-2">
            <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-white/5">
              <BrandMark brand={brand} />
            </div>
            {/* The page's single <h1>. The marketing headline in the left panel
                is visually larger, but it lives in a `hidden lg:flex` section —
                so making *it* the h1 would leave the page with no h1 at all
                below lg. This card renders at every breakpoint, so the heading
                belongs here. */}
            <h1 className="text-2xl font-semibold text-white">{brand?.brand_name ?? "ChatMood"}</h1>
            {brand && <p className="text-[10px] text-gray-500">powered by ChatMood</p>}
            <p className="text-sm text-gray-500">
              {mode === "login" ? "Welcome back — sign in" : "Create your account — sign up"}
            </p>
          </div>

          {notice && (
            <p role="status" className="text-sm text-emerald-400 text-center">
              {notice}
            </p>
          )}

          <form onSubmit={submit} className="space-y-3">
            {mode === "register" && (
              <>
                <label htmlFor="login-name" className="sr-only">
                  Display name
                </label>
                <input
                  id="login-name"
                  className={inputCls}
                  autoComplete="name"
                  placeholder="Display name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </>
            )}
            <label htmlFor="login-email" className="sr-only">
              Email
            </label>
            <input
              id="login-email"
              className={inputCls}
              type="email"
              required
              autoComplete="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <label htmlFor="login-password" className="sr-only">
              Password
            </label>
            <input
              id="login-password"
              className={inputCls}
              type="password"
              required
              minLength={mode === "register" ? 8 : undefined}
              autoComplete={mode === "register" ? "new-password" : "current-password"}
              placeholder={mode === "register" ? "Password (8+ chars)" : "Password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {mode === "register" && (
              <>
                <label htmlFor="login-access-code" className="sr-only">
                  App access code
                </label>
                <input
                  id="login-access-code"
                  className={inputCls}
                  type="password"
                  autoComplete="one-time-code"
                  placeholder="App access code (if required)"
                  value={accessCode}
                  onChange={(e) => setAccessCode(e.target.value)}
                />
                <p className="px-1 text-[11px] leading-relaxed text-gray-600">
                  Some deployments require an owner-provided code before new accounts can be created.
                </p>
              </>
            )}
            {error && (
              <p role="alert" className="text-sm text-red-400">
                {error}
              </p>
            )}
            <button
              disabled={busy}
              className="w-full rounded-full bg-white py-3 font-semibold text-black transition hover:opacity-90 disabled:opacity-40"
            >
              {busy ? "Working…" : mode === "login" ? "Sign in" : "Sign up"}
            </button>
          </form>

          <p className="text-xs text-center text-gray-500">
            {mode === "login" ? "No account? " : "Have an account? "}
            <Link
              href={switchHref}
              className="inline-flex min-h-[44px] items-center px-1 text-accent underline"
            >
              {mode === "login" ? "Sign up" : "Sign in"}
            </Link>
          </p>

          <p className="text-[11px] text-center text-gray-600 leading-relaxed">
            By continuing you agree to the{" "}
            <a href="/terms" className="inline-flex min-h-[44px] items-center underline hover:text-gray-400">
              Terms of Service
            </a>{" "}
            and{" "}
            <a href="/privacy" className="inline-flex min-h-[44px] items-center underline hover:text-gray-400">
              Privacy Policy
            </a>
            .
          </p>
        </div>
      </div>
    </div>
  );
}
