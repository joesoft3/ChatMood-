"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

interface ExploreItem {
  icon: string;
  label: string;
  hint: string;
  href: string;
}

/** Studios surfaced in the landing "Explore" dropdown. */
const EXPLORE_ITEMS: ExploreItem[] = [
  { icon: "💬", label: "Chat", hint: "Streaming answers with memory", href: "/chat" },
  { icon: "📺", label: "Reel", hint: "The creator feed — watch & post videos", href: "/reel" },
  { icon: "🔭", label: "Deep research", hint: "Multi-source reports, live citations", href: "/deepsearch" },
  { icon: "🎬", label: "Films", hint: "Storyboarded video with voice & sound", href: "/films" },
  { icon: "🖼️", label: "Images", hint: "Generate and iterate visuals", href: "/images" },
  { icon: "🎨", label: "Design", hint: "Brand-ready concepts in chat", href: "/design" },
  { icon: "🎤", label: "Voice", hint: "Talk naturally, hear answers back", href: "/voice" },
];

/**
 * 🧭 Landing navigation — sticky, glassy bar with the brand, an accessible
 * Explore dropdown (button + arrow/Escape/outside-click handling), and the
 * sign-in / get-started actions. Keyboard: ↑/↓ move through items, Esc
 * closes and refocuses the trigger, Tab follows natural focus order.
 */
export default function LandingNav() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Close on any outside pointer press.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

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
    <header className="fixed inset-x-0 top-0 z-40 border-b border-white/8 bg-[#161614]/75 backdrop-blur-md">
      <nav aria-label="Landing" className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2 shrink-0">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/icon.png" alt="" className="h-7 w-7 rounded-lg" />
          <span className="text-sm font-semibold tracking-wide">ChatMood</span>
        </Link>

        <div ref={rootRef} className="relative" onKeyDown={onMenuKeyDown}>
          <button
            ref={triggerRef}
            type="button"
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.03] px-3.5 py-1.5 text-xs font-medium text-gray-300 transition hover:bg-white/[0.07] hover:text-white"
          >
            Explore
            <ChevronDown size={13} className={`transition-transform ${open ? "rotate-180" : ""}`} />
          </button>

          {open && (
            <div
              role="menu"
              aria-label="Explore the studios"
              className="absolute left-0 top-full mt-2 w-64 overflow-hidden rounded-2xl border border-white/10 bg-[#171715]/97 p-1.5 shadow-[0_24px_48px_rgb(0_0_0/0.45)] backdrop-blur-xl"
            >
              {EXPLORE_ITEMS.map((item) => (
                <Link
                  key={item.href}
                  role="menuitem"
                  href={item.href}
                  onClick={() => setOpen(false)}
                  className="flex items-start gap-3 rounded-xl px-3 py-2.5 transition hover:bg-white/[0.06] focus:bg-white/[0.06] focus:outline-none"
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

        {/* 📺 Creator Reel — a first-class destination, not buried in Explore */}
        <Link
          href="/reel"
          className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-3.5 py-1.5 text-xs font-medium text-gray-300 transition hover:bg-white/[0.07] hover:text-white"
        >
          📺 Reel
        </Link>

        <div className="ml-auto flex items-center gap-2">
          <Link
            href="/login"
            className="hidden rounded-full px-3.5 py-1.5 text-xs font-medium text-gray-300 transition hover:text-white sm:block"
          >
            Sign in
          </Link>
          <Link
            href="/login"
            className="rounded-full bg-accent px-4 py-1.5 text-xs font-semibold text-black transition hover:brightness-110"
          >
            Get started
          </Link>
        </div>
      </nav>
    </header>
  );
}
