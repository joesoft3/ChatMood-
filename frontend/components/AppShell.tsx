"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  AlarmClock,
  AudioLines,
  Bot,
  Brush,
  ChevronDown,
  Clapperboard,
  FolderKanban,
  FolderOpen,
  Image as ImageIcon,
  LogOut,
  Menu,
  MoreHorizontal,
  Puzzle,
  Settings,
  ShieldCheck,
  SquarePen,
  Telescope,
  Tv,
} from "lucide-react";
import ThemeToggle from "@/components/ThemeToggle";
import ConversationList from "./ConversationList";
import ErrorBoundary from "./ErrorBoundary";
import { API, apiFetch, token } from "@/lib/api";
import { currentNextPath, signInHref } from "@/lib/auth";
import { applyAccent, applyFavicon, BrandMark } from "@/lib/brand";

const OWNER_EMAIL = (process.env.NEXT_PUBLIC_OWNER_EMAIL ?? "joesoft2024@gmail.com").toLowerCase();

const PRIMARY_NAV = [
  { href: "/images", label: "Images", icon: ImageIcon },
  { href: "/gpts", label: "GPTs", icon: Bot },
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/files", label: "Library", icon: FolderOpen },
] as const;

const MORE_NAV = [
  { href: "/voice", label: "Voice", icon: AudioLines },
  { href: "/reel", label: "Reel", icon: Tv },
  { href: "/films", label: "Films", icon: Clapperboard },
  { href: "/design", label: "Design", icon: Brush },
  { href: "/tasks", label: "Tasks", icon: AlarmClock },
  { href: "/plugins", label: "Plugins", icon: Puzzle },
  { href: "/deepsearch", label: "Research", icon: Telescope },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;

/**
 * ChatGPT-style app shell: left rail (new chat, destinations, dated history,
 * account) + a quiet main column. The phone tab bar stays on studio routes
 * and hides on /chat so the empty home matches chatgpt.com.
 */
export default function AppShell({
  title,
  children,
  headerRight,
  headerCenter,
  headerLeft,
  mobileMenuOnly = false,
}: {
  title: string;
  children: React.ReactNode;
  headerRight?: React.ReactNode;
  headerCenter?: React.ReactNode;
  /** ChatGPT-style header control — usually the model dropdown. */
  headerLeft?: React.ReactNode;
  mobileMenuOnly?: boolean;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [me, setMe] = useState<{
    is_admin?: boolean;
    email?: string;
    display_name?: string;
    plan?: string;
  } | null>(null);
  const [brand, setBrand] = useState<{
    brand_name: string;
    domain: string;
    accent?: string | null;
    logo_data?: string | null;
  } | null>(null);
  const pathname = usePathname();
  const router = useRouter();
  const rootRef = useRef<HTMLDivElement>(null);
  const isChat = pathname === "/chat";
  const isOwner = Boolean(me?.is_admin) && (me?.email ?? "").toLowerCase() === OWNER_EMAIL;

  useEffect(() => {
    if (!token.get()) router.push(signInHref(currentNextPath()));
  }, [router, pathname]);

  useEffect(() => {
    if (!token.get()) return;
    apiFetch<{ is_admin?: boolean; email?: string; display_name?: string; plan?: string }>("/auth/me")
      .then(setMe)
      .catch(() => {});
  }, []);

  useEffect(() => {
    const host = window.location.host;
    if (/localhost|127\.0\.0\.1/.test(host)) return;
    fetch(`${API}/domains/by-host?host=${encodeURIComponent(host)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (b?.brand_name) {
          setBrand(b);
          document.title = `${b.brand_name} — AI assistant`;
          if (b.accent) applyAccent(b.accent);
          if (b.logo_data) applyFavicon(b.logo_data);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const setH = () => {
      const h = window.visualViewport?.height ?? window.innerHeight;
      el.style.setProperty("--app-h", `${Math.round(h)}px`);
    };
    setH();
    window.addEventListener("resize", setH);
    window.visualViewport?.addEventListener("resize", setH);
    window.visualViewport?.addEventListener("scroll", setH);
    return () => {
      window.removeEventListener("resize", setH);
      window.visualViewport?.removeEventListener("resize", setH);
      window.visualViewport?.removeEventListener("scroll", setH);
    };
  }, []);

  function logout() {
    token.clear();
    router.push("/login");
  }

  const IDLE_RESET_MS = 5 * 60 * 1000;
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    let last = Date.now();
    const navHome = () => {
      if (window.location.pathname !== "/chat") router.push("/chat");
    };
    const goHome = () => {
      last = Date.now();
      window.dispatchEvent(new CustomEvent("mood:idle-reset"));
      navHome();
    };
    const arm = () => {
      last = Date.now();
      if (timer) clearTimeout(timer);
      timer = setTimeout(goHome, IDLE_RESET_MS);
    };
    const onVisible = () => {
      if (!document.hidden && Date.now() - last >= IDLE_RESET_MS) goHome();
    };
    const evts = ["pointerdown", "touchstart", "keydown", "wheel"];
    evts.forEach((e) => window.addEventListener(e, arm, { passive: true, capture: true }));
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("mood:idle-reset", navHome);
    arm();
    return () => {
      if (timer) clearTimeout(timer);
      evts.forEach((e) => window.removeEventListener(e, arm, { capture: true } as EventListenerOptions));
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("mood:idle-reset", navHome);
    };
  }, [router]);

  function navigateTo(href: string) {
    if (href === "/chat") window.dispatchEvent(new CustomEvent("mood:new-chat"));
    setDrawerOpen(false);
  }

  function newChat() {
    window.dispatchEvent(new CustomEvent("mood:new-chat"));
    setDrawerOpen(false);
    if (pathname !== "/chat") router.push("/chat");
  }

  const brandName = brand?.brand_name ?? "ChatMood";
  const display = me?.display_name?.trim() || me?.email?.split("@")[0] || "You";
  const initial = display.slice(0, 1).toUpperCase();
  const planLabel = (me?.plan || "free").replace(/^./, (c) => c.toUpperCase());

  const sideNav = (
    <div className="flex h-full flex-col bg-panel">
      <div className="flex shrink-0 items-center gap-2 px-3 pb-1 pt-3">
        <Link href="/chat" onClick={() => navigateTo("/chat")} className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1 py-1 hover:bg-white/5">
          <BrandMark brand={brand} size="h-6 w-6" />
          <span className="truncate text-sm font-semibold tracking-tight text-gray-100">{brandName}</span>
        </Link>
      </div>
      <div className="shrink-0 space-y-0.5 px-2 pt-2">
        <button
          type="button"
          onClick={newChat}
          className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-sm text-gray-100 transition hover:bg-white/5"
        >
          <SquarePen size={16} /> New chat
        </button>
        {PRIMARY_NAV.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            onClick={() => navigateTo(href)}
            className={`flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition ${
              pathname === href ? "bg-white/10 text-gray-100" : "text-gray-300 hover:bg-white/5"
            }`}
          >
            <Icon size={16} /> {label}
          </Link>
        ))}
        <button
          type="button"
          onClick={() => setMoreOpen((v) => !v)}
          className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-sm text-gray-300 transition hover:bg-white/5"
          aria-expanded={moreOpen}
        >
          <MoreHorizontal size={16} />
          More
          <ChevronDown size={14} className={`ml-auto text-gray-600 transition-transform ${moreOpen ? "rotate-180" : ""}`} />
        </button>
        {moreOpen && (
          <div className="space-y-0.5 pb-1">
            {MORE_NAV.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                onClick={() => navigateTo(href)}
                className={`flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition ${
                  pathname === href ? "bg-white/10 text-gray-100" : "text-gray-400 hover:bg-white/5 hover:text-gray-200"
                }`}
              >
                <Icon size={16} /> {label}
              </Link>
            ))}
            {isOwner && (
              <Link
                href="/admin"
                onClick={() => setDrawerOpen(false)}
                className={`flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition ${
                  pathname === "/admin" ? "bg-white/10 text-gray-100" : "text-gray-400 hover:bg-white/5 hover:text-gray-200"
                }`}
              >
                <ShieldCheck size={16} /> Owner
              </Link>
            )}
          </div>
        )}
      </div>
      <ConversationList onNavigate={() => setDrawerOpen(false)} />
      <div className="relative shrink-0 border-t border-white/5 p-2">
        {accountOpen && (
          <div className="absolute inset-x-2 bottom-full z-20 mb-1 overflow-hidden rounded-xl border border-white/10 bg-[rgb(var(--mood-base))] py-1 shadow-[0_16px_40px_rgb(0_0_0/0.4)]">
            <div className="px-3 py-2">
              <p className="truncate text-sm font-medium text-gray-100">{display}</p>
              <p className="truncate text-[11px] text-gray-500">{me?.email}</p>
            </div>
            <Link
              href="/upgrade"
              onClick={() => setDrawerOpen(false)}
              className="block px-3 py-2 text-sm text-gray-300 hover:bg-white/5"
            >
              {planLabel} plan
            </Link>
            <div className="px-1">
              <ThemeToggle />
            </div>
            <Link
              href="/settings"
              onClick={() => setDrawerOpen(false)}
              className="flex items-center gap-2 px-3 py-2 text-sm text-gray-300 hover:bg-white/5"
            >
              <Settings size={15} /> Settings
            </Link>
            <button
              type="button"
              onClick={logout}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-gray-400 hover:bg-white/5 hover:text-red-400"
            >
              <LogOut size={15} /> Log out
            </button>
          </div>
        )}
        <button
          type="button"
          onClick={() => setAccountOpen((v) => !v)}
          className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition hover:bg-white/5"
          aria-expanded={accountOpen}
        >
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-white/10 text-xs font-semibold">
            {initial}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm text-gray-100">{display}</span>
            <span className="block truncate text-[11px] text-gray-500">{planLabel}</span>
          </span>
        </button>
      </div>
    </div>
  );

  return (
    <div ref={rootRef} className="app-height flex overflow-hidden bg-base">
      <aside className="hidden w-[260px] shrink-0 flex-col bg-panel lg:flex">{sideNav}</aside>

      <div
        className={`fixed inset-0 z-40 lg:hidden transition-[visibility] duration-200 ${
          drawerOpen ? "visible" : "invisible"
        }`}
      >
        <div
          onClick={() => setDrawerOpen(false)}
          className={`absolute inset-0 h-full bg-black/50 transition-opacity duration-200 ${
            drawerOpen ? "opacity-100" : "opacity-0"
          }`}
        />
        <div
          className={`absolute inset-y-0 left-0 w-[280px] bg-panel transform transition-transform duration-200 pb-[env(safe-area-inset-bottom)] ${
            drawerOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          {sideNav}
        </div>
      </div>

      <div className="relative z-0 flex min-h-0 min-w-0 flex-1 flex-col bg-base">
        {mobileMenuOnly ? (
          <button
            onClick={() => setDrawerOpen((v) => !v)}
            className="lg:hidden fixed left-3 top-[max(0.75rem,env(safe-area-inset-top))] z-50 touch-manipulation rounded-lg p-2 text-gray-300 hover:bg-white/5 hover:text-white"
            aria-label={drawerOpen ? "Close menu" : "Open menu"}
          >
            <Menu size={20} />
          </button>
        ) : (
          <header className="flex shrink-0 items-center gap-1 bg-base px-2 py-2 pt-[max(0.5rem,env(safe-area-inset-top))] lg:px-3">
            <button
              onClick={() => setDrawerOpen(true)}
              className="touch-manipulation rounded-lg p-2 text-gray-300 hover:bg-white/5 hover:text-white lg:hidden"
              aria-label="Open menu"
            >
              <Menu size={20} />
            </button>
            <div className="min-w-0 flex-1">
              {headerLeft ? (
                headerLeft
              ) : headerCenter ? (
                headerCenter
              ) : (
                <h1 className="truncate px-2 text-sm font-semibold text-gray-100 lg:text-[17px]">{title}</h1>
              )}
            </div>
            {headerRight}
            <button
              type="button"
              onClick={newChat}
              className="rounded-lg p-2 text-gray-300 hover:bg-white/5 hover:text-white lg:hidden"
              aria-label="New chat"
            >
              <SquarePen size={18} />
            </button>
          </header>
        )}

        <div className="relative flex min-h-0 flex-1 flex-col">
          <ErrorBoundary>{children}</ErrorBoundary>
        </div>

        {isOwner && pathname !== "/admin" && (
          <Link
            href="/admin"
            aria-label="Open owner panel"
            title="Owner panel"
            className="absolute bottom-6 right-6 z-30 hidden items-center gap-2 rounded-full bg-white px-3.5 py-2.5 text-xs font-semibold text-black shadow-lg hover:opacity-90 md:flex"
          >
            <ShieldCheck size={16} />
            Admin
          </Link>
        )}

        {!isChat && (
          <nav className="relative z-10 shrink-0 border-t border-white/5 bg-base pb-[env(safe-area-inset-bottom)] px-2 pt-1 md:hidden">
            <div className="grid grid-cols-5">
              {[
                { href: "/chat", label: "Chat", icon: SquarePen },
                { href: "/images", label: "Images", icon: ImageIcon },
                { href: "/reel", label: "Reel", icon: Tv },
                { href: "/gpts", label: "GPTs", icon: Bot },
                { href: "/settings", label: "Settings", icon: Settings },
              ].map(({ href, label, icon: Icon }) => {
                const active = pathname === href;
                return (
                  <Link
                    key={href}
                    href={href}
                    onClick={() => navigateTo(href)}
                    className={`flex flex-col items-center justify-center gap-0.5 py-2 text-[10px] ${
                      active ? "text-gray-100" : "text-gray-500"
                    }`}
                  >
                    <Icon size={18} />
                    <span className="max-[340px]:hidden">{label}</span>
                  </Link>
                );
              })}
            </div>
          </nav>
        )}
      </div>
    </div>
  );
}
