"use client";

import { useEffect, useRef, useState } from "react";
import {
  Bot,
  Globe,
  Headphones,
  Mic,
  MoreHorizontal,
  Paperclip,
  Puzzle,
  SendHorizontal,
  Square,
  Telescope,
  X,
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useRecorder } from "@/lib/use-recorder";

export interface FileChip {
  id: string;
  filename: string;
  mime: string;
}

interface Props {
  busy: boolean;
  onStop: () => void;
  voiceMode: boolean;
  setVoiceMode: (v: boolean) => void;
  agentMode: boolean;
  setAgentMode: (v: boolean) => void;
  deepMode: boolean;
  setDeepMode: (v: boolean) => void;
  pluginMode: boolean;
  setPluginMode: (v: boolean) => void;
  /** Active generation model — drives the hint under the composer. */
  model?: string;
  /** ⚔️ arena / 🧠 thinking states for the hint line. */
  arenaMode?: boolean;
  thinkOn?: boolean;
  files: FileChip[];
  onRemoveFile: (id: string) => void;
  onUpload: (f: File) => Promise<void>;
  onSend: (text: string, search: boolean) => Promise<void>;
  onVoice: (blob: Blob) => Promise<void>;
  /** 🎨🎬 Home actions prefill the input without sending (nonce retriggers). */
  draft?: { text: string; nonce: number };
  /** 🏠 bare = rendered inside the centered empty home. */
  bare?: boolean;
}

export default function Composer({
  busy,
  onStop,
  voiceMode,
  setVoiceMode,
  agentMode,
  setAgentMode,
  deepMode,
  setDeepMode,
  pluginMode,
  setPluginMode,
  model = "auto",
  arenaMode = false,
  thinkOn = false,
  files,
  onRemoveFile,
  onUpload,
  onSend,
  onVoice,
  draft,
  bare = false,
}: Props) {
  const [input, setInput] = useState("");
  const [searchOn, setSearchOn] = useState(true);
  const [showMore, setShowMore] = useState(false);
  const [composerError, setComposerError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const canSend = !busy && (input.trim().length > 0 || files.length > 0);
  const toolActive = agentMode || deepMode || pluginMode || voiceMode;

  // Home actions prefill the composer (never auto-send). Wait for the
  // controlled textarea to render before measuring it or placing the cursor;
  // otherwise the cursor can land at the old value's position.
  useEffect(() => {
    if (!draft) return;
    setInput(draft.text);
    const frame = window.requestAnimationFrame(() => {
      const t = inputRef.current;
      if (!t) return;
      t.focus();
      t.style.height = "auto";
      t.style.height = Math.min(t.scrollHeight, 160) + "px";
      t.setSelectionRange(draft.text.length, draft.text.length);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [draft]);

  // Close the compact tools menu when the user taps elsewhere.
  useEffect(() => {
    if (bare || !showMore) return;
    const close = (event: PointerEvent) => {
      const target = event.target as HTMLElement;
      if (!target.closest("[data-composer-menu]")) setShowMore(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [bare, showMore]);

  async function submit() {
    if (!canSend) return;
    const text = input;
    setComposerError("");
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";
    await onSend(text, searchOn);
  }

  async function handleAudio(blob: Blob) {
    if (voiceMode) {
      await onVoice(blob);
      return;
    }
    // Dictation mode: transcribe into the input box
    try {
      const fd = new FormData();
      fd.append("file", blob, "dictation.webm");
      const res = await apiFetch<{ text: string }>("/voice/transcribe", { method: "POST", body: fd });
      setInput((i) => (i ? i + " " : "") + res.text);
    } catch (e: any) {
      setComposerError(e.message ?? "Transcription failed");
    }
  }

  const { recording, start, stop } = useRecorder((blob) => void handleAudio(blob));

  async function toggleMic() {
    if (recording) stop();
    else {
      try {
        await start();
      } catch {
        setComposerError("Microphone access denied or unavailable.");
      }
    }
  }

  function autoGrow(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setComposerError("");
    setInput(e.target.value);
    const t = e.target;
    t.style.height = "auto";
    t.style.height = Math.min(t.scrollHeight, 160) + "px";
  }

  function toggleTool(setter: (value: boolean) => void, value: boolean) {
    setter(!value);
    setShowMore(false);
  }

  return (
    <div
      className={
        bare
          ? "w-full"
          : "border-t border-white/5 bg-[#0f0f10]/90 px-2 py-2.5 backdrop-blur sm:px-3 sm:py-3 compact-v"
      }
    >
      <div className="relative mx-auto max-w-3xl space-y-2.5 xl:max-w-4xl 2xl:max-w-5xl" data-composer-menu>
        {!bare && showMore && (
          <div className="absolute bottom-full right-1 z-30 mb-2 w-[min(22rem,calc(100vw-1.5rem))] rounded-2xl border border-white/10 bg-[#171718]/[.98] p-2 shadow-[0_18px_45px_rgb(0_0_0/0.5)] backdrop-blur-xl">
            <div className="px-2 pb-1.5 text-[10px] uppercase tracking-[0.16em] text-gray-600">More tools</div>
            <div className="grid grid-cols-2 gap-1.5">
              <button
                type="button"
                onClick={() => toggleTool(setAgentMode, agentMode)}
                className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 text-xs transition ${
                  agentMode ? "border-accent/35 bg-accent/10 text-accent" : "border-white/8 bg-white/5 text-gray-400 hover:bg-white/10 hover:text-white"
                }`}
              >
                <Bot size={15} /> Agent
              </button>
              <button
                type="button"
                onClick={() => toggleTool(setDeepMode, deepMode)}
                className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 text-xs transition ${
                  deepMode ? "border-accent/35 bg-accent/10 text-accent" : "border-white/8 bg-white/5 text-gray-400 hover:bg-white/10 hover:text-white"
                }`}
              >
                <Telescope size={15} /> Deep
              </button>
              <button
                type="button"
                onClick={() => toggleTool(setPluginMode, pluginMode)}
                className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 text-xs transition ${
                  pluginMode ? "border-accent/35 bg-accent/10 text-accent" : "border-white/8 bg-white/5 text-gray-400 hover:bg-white/10 hover:text-white"
                }`}
              >
                <Puzzle size={15} /> Plugins
              </button>
              <button
                type="button"
                onClick={() => toggleTool(setVoiceMode, voiceMode)}
                className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 text-xs transition ${
                  voiceMode ? "border-accent/35 bg-accent/10 text-accent" : "border-white/8 bg-white/5 text-gray-400 hover:bg-white/10 hover:text-white"
                }`}
              >
                <Headphones size={15} /> Voice
              </button>
            </div>
          </div>
        )}
        {files.length > 0 && (
          <div className="flex flex-wrap gap-2 px-1">
            {files.map((f) => (
              <span
                key={f.id}
                className="flex max-w-full items-center gap-1.5 rounded-full border border-white/5 bg-white/5 px-3 py-1.5 text-xs text-gray-300"
              >
                <span className="max-w-[180px] truncate">{f.filename}</span>
                <button
                  type="button"
                  onClick={() => onRemoveFile(f.id)}
                  className="text-gray-500 hover:text-red-400"
                  aria-label={`Remove ${f.filename}`}
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        )}
        {composerError && (
          <div role="alert" className="flex items-center gap-2 rounded-xl border border-red-400/20 bg-red-400/10 px-3 py-2 text-xs text-red-200">
            <span className="flex-1">{composerError}</span>
            <button type="button" onClick={() => setComposerError("")} className="text-red-200/70 hover:text-red-100" aria-label="Dismiss composer error">✕</button>
          </div>
        )}
        {bare && deepMode && (
          <div className="flex justify-center">
            <button
              type="button"
              onClick={() => setDeepMode(false)}
              className="inline-flex items-center gap-1.5 rounded-full border border-accent/25 bg-accent/10 px-2.5 py-1 text-[10px] text-accent transition hover:border-accent/45 hover:bg-accent/15"
              aria-label="Turn off research mode"
            >
              <Telescope size={12} /> Research mode <X size={11} />
            </button>
          </div>
        )}
        <div
          className={`${
            bare
              ? "min-h-[4rem] rounded-[1.55rem] border border-white/10 bg-white/[0.075] px-2 py-1.5 shadow-[0_18px_48px_rgb(0_0_0/0.28)] backdrop-blur-xl"
              : "min-h-[4.6rem] rounded-[1.9rem] border border-white/10 bg-white/[0.07] px-2.5 py-2.5 shadow-[0_20px_54px_rgb(0_0_0/0.34)] backdrop-blur-xl sm:px-3"
          } flex items-center gap-1 focus-within:border-accent/55 focus-within:shadow-[0_22px_60px_-12px_rgb(var(--mood-accent)/0.32)] transition`}
        >
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.json,.png,.jpg,.jpeg,.webp,.gif"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f) {
                try {
                  await onUpload(f);
                } catch (err: any) {
                  setComposerError(err.message ?? "Upload failed");
                }
              }
              e.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            title="Attach file"
            aria-label="Attach file"
            className="composer-btn shrink-0 rounded-xl text-gray-400 transition hover:bg-white/5 hover:text-white"
          >
            <Paperclip size={19} />
          </button>
          <textarea
            ref={inputRef}
            id="composer-input"
            value={input}
            onChange={autoGrow}
            rows={1}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={
              bare
                ? deepMode
                  ? "Ask a research question…"
                  : "Ask Mood anything…"
                : agentMode
                  ? "Give the agent team a goal…"
                  : deepMode
                    ? "Ask a complex question — deep multi-round research…"
                    : arenaMode
                      ? "Pose a question — 3+ AI models will debate it, Grok-4 judges…"
                      : model === "grok-code-fast-1"
                        ? "Describe code to write / a bug to fix (🧠 toggle for reasoning)…"
                        : thinkOn
                          ? "Ask something worth deep reasoning (grok-4 🧠)…"
                          : "Ask Mood anything…"
            }
            className="composer-input min-h-[3.25rem] min-w-0 flex-1 resize-none overflow-y-auto bg-transparent px-1 py-2.5 text-sm leading-6 outline-none placeholder-gray-600"
          />
          <button
            type="button"
            onClick={() => setSearchOn(!searchOn)}
            title="Toggle live web search"
            aria-label="Toggle live web search"
            className={`composer-btn shrink-0 rounded-xl transition ${searchOn ? "bg-accent/10 text-accent" : "text-gray-600 hover:bg-white/5 hover:text-white"}`}
          >
            <Globe size={19} />
          </button>
          {!bare && (
            <button
              type="button"
              onClick={() => setShowMore((v) => !v)}
              title="More chat tools"
              aria-label="More chat tools"
              aria-expanded={showMore}
              className={`composer-btn shrink-0 rounded-xl transition ${showMore || toolActive ? "bg-accent/10 text-accent" : "text-gray-400 hover:bg-white/5 hover:text-white"}`}
            >
              <MoreHorizontal size={20} />
            </button>
          )}
          <button
            type="button"
            onClick={toggleMic}
            title={recording ? "Stop recording" : voiceMode ? "Talk" : "Dictate"}
            aria-label={recording ? "Stop recording" : voiceMode ? "Talk" : "Dictate"}
            className={`composer-btn shrink-0 rounded-xl transition ${recording ? "bg-red-400/10 text-red-400 animate-pulse" : "text-gray-400 hover:bg-white/5 hover:text-white"}`}
          >
            {recording ? <Square size={19} /> : <Mic size={19} />}
          </button>
          {busy ? (
            <button
              type="button"
              onClick={onStop}
              title="Stop generating"
              className="composer-btn shrink-0 rounded-2xl bg-red-400/90 text-black shadow-[0_8px_24px_rgb(248_113_113/0.35)] transition hover:bg-red-400"
              aria-label="Stop generating"
            >
              <Square size={17} />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!canSend}
              className="composer-btn shrink-0 rounded-2xl bg-accent text-black shadow-[0_8px_24px_rgb(var(--mood-accent)/0.35)] transition hover:brightness-110 disabled:opacity-30"
              aria-label="Send"
            >
              <SendHorizontal size={19} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
