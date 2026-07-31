"use client";

import { Brain, Swords } from "lucide-react";

export interface ModelOption {
  id: string;
  label: string;
  icon: string;
  hint: string;
}

export const MODEL_OPTIONS: ModelOption[] = [
  { id: "auto", label: "Auto", icon: "🚀", hint: "best pick per message" },
  { id: "grok-3-mini", label: "Mini", icon: "💸", hint: "cheapest, quick answers" },
  { id: "grok-4-fast", label: "S1 MoodAI-4-Fast", icon: "⚡", hint: "newest gen · 2M ctx" },
  { id: "grok-4", label: "S1 MoodAI-4", icon: "👑", hint: "flagship · 🧠 reasoning" },
  { id: "grok-code-fast-1", label: "Code", icon: "💻", hint: "grok-code-fast-1 · 🧠 reasoning" },
];

const ARENA_EXTRAS = ["", "gemini-2.5-flash", "grok-code-fast-1"] as const;

interface Props {
  model: string;
  setModel: (m: string) => void;
  thinkOn: boolean;
  toggleThink: () => void;
  /** Whether the current model supports 🧠 extended reasoning. */
  thinkSupported: boolean;
  arenaMode: boolean;
  toggleArena: () => void;
  arenaExtra: string;
  setArenaExtra: (v: string) => void;
  /** 🏠 bare = transparent + centered, for the Grok-style empty home. */
  bare?: boolean;
}

/** Compact model / thinking / arena control row above the composer. */
export default function ModelPicker({
  model,
  setModel,
  thinkOn,
  toggleThink,
  thinkSupported,
  arenaMode,
  toggleArena,
  arenaExtra,
  setArenaExtra,
  bare = false,
}: Props) {
  return (
    <div className={bare ? "w-full" : "border-t border-white/5 bg-[#121213]/90 backdrop-blur px-2 sm:px-3 pt-2 pb-1 compact-v"}>
      <div className={bare ? "w-full flex items-center justify-center gap-2 flex-wrap" : "max-w-3xl xl:max-w-4xl 2xl:max-w-5xl mx-auto flex items-center gap-1.5 sm:gap-2 flex-wrap overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"}>
        <div className={bare ? "flex items-center gap-1 rounded-full bg-[#141415] border border-white/8 p-1 max-w-full overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" : "flex items-center gap-1 rounded-full bg-[#141415] border border-white/8 p-1 shrink-0 shadow-[0_10px_24px_rgb(0_0_0/0.18)] max-w-full overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"}>
          {MODEL_OPTIONS.map((o) => (
            <button
              key={o.id}
              onClick={() => setModel(o.id)}
              title={`${o.label} — ${o.hint}`}
              className={`rounded-full px-3 py-1.5 text-[10px] sm:text-[11px] font-medium transition flex items-center gap-1.5 shrink-0 whitespace-nowrap ${
                model === o.id && !arenaMode
                  ? "bg-accent text-black shadow-[0_8px_20px_rgb(var(--mood-accent)/0.3)]"
                  : "text-gray-400 hover:text-white hover:bg-white/5"
              }`}
            >
              <span className="hide-xxs">{o.icon}</span> {o.label}
            </button>
          ))}
        </div>
        <button
          onClick={toggleThink}
          disabled={!thinkSupported || arenaMode}
          title={
            thinkSupported
              ? "Extended reasoning — shows a 🧠 thinking trace (slower)"
              : "Thinking needs S1 MoodAI-4, Auto, or S1 Code (not 4-fast, not arena)"
          }
          className={`rounded-full border px-3 py-1.5 text-[10px] sm:text-[11px] font-medium transition flex items-center gap-1.5 shrink-0 ${
            thinkOn && thinkSupported && !arenaMode
              ? "bg-purple-400/15 border-purple-400/35 text-purple-300"
              : "border-white/8 bg-[#141415] text-gray-500 hover:text-white disabled:opacity-35 disabled:cursor-not-allowed"
          }`}
        >
          <Brain size={12} /> Thinking
        </button>
        <button
          onClick={toggleArena}
          title="⚔️ arena — multiple AI providers draft in parallel, blind-vote, Grok-4 judges (premium)"
          className={`rounded-full border px-3 py-1.5 text-[10px] sm:text-[11px] font-medium transition flex items-center gap-1.5 shrink-0 ${
            arenaMode
              ? "bg-accent/15 border-accent/35 text-accent"
              : "border-white/8 bg-[#141415] text-gray-500 hover:text-white"
          }`}
        >
          <Swords size={12} /> Arena
        </button>
        {arenaMode && (
          <select
            value={arenaExtra}
            onChange={(e) => setArenaExtra(e.target.value)}
            title="Extra provider to add to the arena (needs its API key configured server-side)"
            className="rounded-full bg-[#141415] border border-white/8 text-[10px] sm:text-[11px] text-gray-400 px-3 py-1.5 outline-none focus:border-accent/50 shrink-0"
          >
            {ARENA_EXTRAS.map((v) => (
              <option key={v || "none"} value={v}>
                {v === "" ? "＋ 3 providers (default)" : `＋ ${v}`}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}
