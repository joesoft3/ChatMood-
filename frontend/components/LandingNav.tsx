"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, Menu, X } from "lucide-react";

interface ExploreItem {
  icon: string;
  label: string;
  hint: string;
  href: string;
}

const EXPLORE_ITEMS: ExploreItem[] = [
  { icon: "💬", label: "Chat", hint: "Streaming answers with memory", href: "/chat" },
  { icon: "📺", label: "Reel", hint: "The creator feed — watch & post videos", href: "/reel" },
  { icon: "🔭", label: "Deep research", hint: "Multi-source reports, live citations", href: "/deepsearch" },
  { icon: "🎬", label: "Films", hint: "Storyboarded video with voice & sound", href: "/films" },
  { icon: "🖼️", label: "Images", hint: "Generate and iterate visuals", href: "/images" },
  { icon: "🎨", label: "Design", hint: "Brand-ready concepts in chat", href: "/design" },
  { icon: "🎤", label: "Voice", hint: "Talk naturally, hear answers back", href: "/voice" },
];

const ANCHORS = [
  { href: "/reel", label: "Reel" },
  { href: "/films", label: "Films" },
  { href: "/deepsearch", label: "Research" },
];

/**
 * Landing navigation — refreshed as a compact glass command bar with desktop
 * quick links, an accessible Explore dropdown, and a mobile drawer.
 */
export default function LandingNav() {
  const [open, setOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileOpen]);

  const onMenuKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const items = rootRef.current?.querySelectorAll<HTMLAnchorElement>('[role="menuitem"]');
    if (!items?.length) return;
    const idx = Array.from(items).findIndex((el) => el === document.activeElement);
    const next = e.key === "ArrowDown" ? (idx + 1) % items.length : (idx - 1 + items.length) % items.length;
    items[next]?.focus();
  };

  return (
    <header className="fixed inset-x-0 top-0 z-40 px-3 pt-3 sm:px-5">
      <nav
        aria-label="Landing"
        className="mood-glass mx-auto flex h-16 max-w-7xl items-center gap-3 rounded-3xl px-3 shadow-[0_18px_60px_rgb(0_0_0/0.32)] sm:px-4"
      >
        <Link href="/" className="flex items-center gap-2.5 shrink-0 rounded-2xl px-1.5 py-1 transition hover:bg-white/[0.05]">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/icon.png" alt="" className="h-9 w-9 rounded-2xl shadow-[0_0_32px_-12px_rgb(var(--mood-accent))]" />
          <span className="text-sm font-semibold tracking-tight text-white">Mood AI</span>
        </Link>

        <div className="hidden items-center gap-1 md:flex">
          <div ref={rootRef} className="relative" onKeyDown={onMenuKeyDown}>
            <button
              ref={triggerRef}
              type="button"
              aria-haspopup="menu"
              aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
              className="flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.04] px-3.5 py-2 text-xs font-medium text-gray-300 transition hover:bg-white/[0.08] hover:text-white"
            >
              Explore
              <ChevronDown size={13} className={`transition-transform ${open ? "rotate-180" : ""}`} />
            </button>

            {open && (
              <div
                role="menu"
                aria-label="Explore the studios"
                className="absolute left-0 top-full mt-3 w-72 overflow-hidden rounded-3xl border border-white/10 bg-[#101114]/95 p-2 shadow-[0_24px_70px_rgb(0_0_0/0.5)] backdrop-blur-2xl"
              >
                {EXPLORE_ITEMS.map((item) => (
                  <Link
                    key={item.href}
                    role="menuitem"
                    href={item.href}
                    onClick={() => setOpen(false)}
                    className="flex items-start gap-3 rounded-2xl px-3 py-3 transition hover:bg-white/[0.07] focus:bg-white/[0.07] focus:outline-none"
                  >
                    <span className="mt-0.5 text-base leading-none">{item.icon}</span>
                    <span className="min-w-0">
                      <span className="block text-[13px] font-medium text-gray-100">{item.label}</span>
                      <span className="mt-0.5 block text-[11px] leading-snug text-gray-500">{item.hint}</span>
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </div>

          {ANCHORS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-full px-3.5 py-2 text-xs font-medium text-gray-400 transition hover:bg-white/[0.06] hover:text-white"
            >
              {item.label}
            </Link>
          ))}
        </div>

        <div className="ml-auto hidden items-center gap-2 sm:flex">
          <Link
            href="/login"
            className="rounded-full px-4 py-2 text-xs font-medium text-gray-300 transition hover:bg-white/[0.06] hover:text-white"
          >
            Sign in
          </Link>
          <Link
            href="/login"
            className="rounded-full bg-accent px-4 py-2 text-xs font-semibold text-black shadow-[0_12px_28px_rgb(var(--mood-accent)/0.24)] transition hover:brightness-110"
          >
            Get started
          </Link>
        </div>

        <button
          type="button"
          onClick={() => setMobileOpen((v) => !v)}
          className="ml-auto inline-flex h-10 w-10 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.05] text-gray-300 transition hover:bg-white/[0.09] hover:text-white sm:hidden"
          aria-expanded={mobileOpen}
          aria-label={mobileOpen ? "Close menu" : "Open menu"}
        >
          {mobileOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
      </nav>

      {mobileOpen && (
        <div className="mood-glass mx-auto mt-2 max-w-7xl rounded-3xl p-2 sm:hidden">
          <div className="grid gap-1">
            {EXPLORE_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileOpen(false)}
                className="flex items-center gap-3 rounded-2xl px-3 py-3 text-sm text-gray-200 transition hover:bg-white/[0.07]"
              >
                <span>{item.icon}</span>
                <span className="flex-1">{item.label}</span>
                <span className="text-[10px] text-gray-600">{item.hint}</span>
              </Link>
            ))}
            <div className="mt-2 grid grid-cols-2 gap-2">
              <Link href="/login" onClick={() => setMobileOpen(false)} className="rounded-2xl border border-white/10 px-4 py-3 text-center text-xs font-medium text-gray-300">
                Sign in
              </Link>
              <Link href="/login" onClick={() => setMobileOpen(false)} className="rounded-2xl bg-accent px-4 py-3 text-center text-xs font-semibold text-black">
                Start free
              </Link>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
