"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { BookOpen, Brain, Check, ChevronDown, Ghost, Smile, Swords, X } from "lucide-react";

export interface ModelOption {
  id: string;
  label: string;
  icon: string;
  hint: string;
}

export const MODEL_OPTIONS: ModelOption[] = [
  { id: "auto", label: "Auto", icon: "🚀", hint: "best pick per message" },
  { id: "grok-3-mini", label: "Mini", icon: "💸", hint: "cheapest, quick answers" },
  { id: "grok-4-fast", label: "S1 ChatMood-4-Fast", icon: "⚡", hint: "newest gen · 2M ctx" },
  { id: "grok-4", label: "S1 ChatMood-4", icon: "👑", hint: "flagship · reasoning" },
  { id: "grok-code-fast-1", label: "Code", icon: "💻", hint: "grok-code-fast-1 · reasoning" },
];

const ARENA_EXTRAS = ["", "gemini-2.5-flash", "grok-code-fast-1"] as const;

interface Props {
  model: string;
  setModel: (m: string) => void;
  thinkOn: boolean;
  toggleThink: () => void;
  /** Whether the current model supports extended reasoning. */
  thinkSupported: boolean;
  arenaMode: boolean;
  toggleArena: () => void;
  arenaExtra: string;
  setArenaExtra: (v: string) => void;
  funMode?: boolean;
  toggleFun?: () => void;
  temporary?: boolean;
  toggleTemporary?: () => void;
  studyMode?: boolean;
  toggleStudy?: () => void;
  gptLabel?: string | null;
  onClearGpt?: () => void;
  /** Kept for callers; the picker is always the ChatGPT header dropdown now. */
  bare?: boolean;
}

/** ChatGPT-style model dropdown for the main header. */
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
  funMode = false,
  toggleFun,
  temporary = false,
  toggleTemporary,
  studyMode = false,
  toggleStudy,
  gptLabel = null,
  onClearGpt,
}: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const current = MODEL_OPTIONS.find((o) => o.id === model) ?? MODEL_OPTIONS[0];
  const title = gptLabel || (arenaMode ? "Arena" : current.label);

  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative min-w-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="inline-flex max-w-full items-center gap-1 rounded-lg px-2 py-1 text-[17px] font-semibold tracking-tight text-gray-100 transition hover:bg-white/5"
      >
        <span className="truncate">{title}</span>
        <ChevronDown size={16} className={`shrink-0 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div
          role="listbox"
          aria-label="Model and modes"
          className="absolute left-0 top-full z-40 mt-1 w-[min(20rem,calc(100vw-1.5rem))] overflow-hidden rounded-2xl border border-white/10 bg-[rgb(var(--mood-panel))] py-1 shadow-[0_16px_40px_rgb(0_0_0/0.45)]"
        >
          {MODEL_OPTIONS.map((o) => {
            const active = model === o.id && !arenaMode;
            return (
              <button
                key={o.id}
                type="button"
                role="option"
                aria-selected={active}
                onClick={() => {
                  setModel(o.id);
                  if (arenaMode) toggleArena();
                  setOpen(false);
                }}
                className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm transition hover:bg-white/5"
              >
                <span className="w-5 shrink-0 text-center" aria-hidden>
                  {o.icon}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-medium text-gray-100">{o.label}</span>
                  <span className="block text-[11px] text-gray-500">{o.hint}</span>
                </span>
                {active && <Check size={16} className="shrink-0 text-gray-300" />}
              </button>
            );
          })}
          <div className="my-1 border-t border-white/8" />
          <ModeRow
            icon={<Brain size={15} />}
            label="Thinking"
            hint={thinkSupported ? "Show a reasoning trace" : "Needs Auto, S1 ChatMood-4, or Code"}
            active={thinkOn && thinkSupported && !arenaMode}
            disabled={!thinkSupported || arenaMode}
            onClick={() => {
              toggleThink();
              setOpen(false);
            }}
          />
          <ModeRow
            icon={<Swords size={15} />}
            label="Arena"
            hint="Models debate, then a judge picks"
            active={arenaMode}
            onClick={() => {
              toggleArena();
              setOpen(false);
            }}
          />
          {toggleFun && (
            <ModeRow
              icon={<Smile size={15} />}
              label="Fun"
              hint="Wittier voice — facts stay true"
              active={funMode}
              onClick={() => {
                toggleFun();
                setOpen(false);
              }}
            />
          )}
          {toggleStudy && (
            <ModeRow
              icon={<BookOpen size={15} />}
              label="Study"
              hint="Socratic tutor — hints, then a quiz"
              active={studyMode}
              onClick={() => {
                toggleStudy();
                setOpen(false);
              }}
            />
          )}
          {toggleTemporary && (
            <ModeRow
              icon={<Ghost size={15} />}
              label="Temporary"
              hint="Hidden from history, never remembered"
              active={temporary}
              onClick={() => {
                toggleTemporary();
                setOpen(false);
              }}
            />
          )}
          {gptLabel && (
            <div className="mx-2 mt-1 flex items-center gap-2 rounded-xl border border-accent/25 bg-accent/10 px-3 py-2 text-xs text-accent">
              <span className="min-w-0 flex-1 truncate">{gptLabel}</span>
              {onClearGpt && (
                <button type="button" onClick={onClearGpt} aria-label="Stop using this GPT" className="hover:text-white">
                  <X size={12} />
                </button>
              )}
            </div>
          )}
          {arenaMode && (
            <div className="px-3 py-2">
              <select
                value={arenaExtra}
                onChange={(e) => setArenaExtra(e.target.value)}
                title="Extra provider to add to the arena"
                className="w-full rounded-xl border border-white/8 bg-white/5 px-3 py-2 text-xs text-gray-300 outline-none"
              >
                {ARENA_EXTRAS.map((v) => (
                  <option key={v || "none"} value={v}>
                    {v === "" ? "Default panel (3 providers)" : `+ ${v}`}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ModeRow({
  icon,
  label,
  hint,
  active,
  disabled,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  hint: string;
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm transition hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40"
    >
      <span className="grid h-5 w-5 shrink-0 place-items-center text-gray-400">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block font-medium text-gray-100">{label}</span>
        <span className="block text-[11px] text-gray-500">{hint}</span>
      </span>
      {active && <Check size={16} className="shrink-0 text-gray-300" />}
    </button>
  );
}
