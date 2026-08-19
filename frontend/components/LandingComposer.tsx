"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp, Plus } from "lucide-react";
import { token } from "@/lib/api";

const STARTERS = [
  { label: "Create image", href: "/signup", prompt: "Create an image of " },
  { label: "Help me write", href: "/signup", prompt: "Help me write " },
  { label: "Research", href: "/signup", prompt: "Research " },
  { label: "Make a plan", href: "/signup", prompt: "Make a plan for " },
];

/**
 * ChatGPT.com-style hero composer. Logged-in visitors go straight to /chat;
 * everyone else lands on sign-up with the typed prompt preserved.
 */
export default function LandingComposer() {
  const router = useRouter();
  const [value, setValue] = useState("");

  function go(prompt?: string) {
    const text = (prompt ?? value).trim();
    if (token.get()) {
      router.push("/chat");
      return;
    }
    const next = text ? `/signup?next=${encodeURIComponent("/chat")}` : "/signup";
    router.push(next);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    go();
  }

  return (
    <div className="mx-auto w-full max-w-[48rem] space-y-5">
      <form onSubmit={onSubmit} className="flex items-end gap-1 rounded-[28px] bg-composer px-2 py-2 shadow-[0_0_0_1px_rgb(var(--mood-line))]">
        <span className="composer-btn mb-0.5 grid place-items-center rounded-full text-gray-400" aria-hidden>
          <Plus size={20} />
        </span>
        <label className="sr-only" htmlFor="landing-ask">
          Ask anything
        </label>
        <textarea
          id="landing-ask"
          rows={1}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              go();
            }
          }}
          placeholder="Ask anything"
          className="composer-input min-h-[2.75rem] min-w-0 flex-1 resize-none bg-transparent px-1 py-2.5 text-[15px] leading-6 outline-none"
        />
        <button
          type="submit"
          className="composer-btn composer-send mb-0.5 rounded-full"
          aria-label="Start chatting"
        >
          <ArrowUp size={18} strokeWidth={2.4} />
        </button>
      </form>
      <nav className="flex flex-wrap items-center justify-center gap-2" aria-label="Suggested starts">
        {STARTERS.map((s) => (
          <button
            key={s.label}
            type="button"
            onClick={() => go(s.prompt)}
            className="rounded-full bg-composer px-4 py-2 text-sm text-gray-200 transition hover:bg-white/10"
          >
            {s.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
