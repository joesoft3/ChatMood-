"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  Bot,
  Globe,
  Headphones,
  Image as ImageIcon,
  Mic,
  Paperclip,
  Plus,
  Puzzle,
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
  /** Arena / thinking states for the hint line. */
  arenaMode?: boolean;
  thinkOn?: boolean;
  files: FileChip[];
  onRemoveFile: (id: string) => void;
  onUpload: (f: File) => Promise<void>;
  onSend: (text: string, search: boolean) => Promise<void>;
  onVoice: (blob: Blob) => Promise<void>;
  /** Home actions prefill the input without sending (nonce retriggers). */
  draft?: { text: string; nonce: number };
  /** bare = rendered inside the centered empty home. */
  bare?: boolean;
  /** DeepSearch: "deep" (2 rounds) or "deeper" (3 rounds). */
  researchDepth?: "deep" | "deeper";
  setResearchDepth?: (d: "deep" | "deeper") => void;
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
  researchDepth = "deep",
  setResearchDepth,
}: Props) {
  const [input, setInput] = useState("");
  const [searchOn, setSearchOn] = useState(true);
  const [showMore, setShowMore] = useState(false);
  const [composerError, setComposerError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const canSend = !busy && (input.trim().length > 0 || files.length > 0);

  useEffect(() => {
    if (!draft) return;
    setInput(draft.text);
    const frame = window.requestAnimationFrame(() => {
      const t = inputRef.current;
      if (!t) return;
      t.focus();
      t.style.height = "auto";
      t.style.height = Math.min(t.scrollHeight, 200) + "px";
      t.setSelectionRange(draft.text.length, draft.text.length);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [draft]);

  useEffect(() => {
    if (!showMore) return;
    const close = (event: PointerEvent) => {
      const target = event.target as HTMLElement;
      if (!target.closest("[data-composer-menu]")) setShowMore(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [showMore]);

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
    t.style.height = Math.min(t.scrollHeight, 200) + "px";
  }

  function toggleTool(setter: (value: boolean) => void, value: boolean) {
    setter(!value);
    setShowMore(false);
  }

  const placeholder = deepMode
    ? "Ask a research question…"
    : agentMode
      ? "Give the agent team a goal…"
      : arenaMode
        ? "Pose a question for the arena…"
        : model === "grok-code-fast-1"
          ? "Describe code to write or a bug to fix…"
          : thinkOn
            ? "Ask something worth reasoning through…"
            : "Ask anything";

  const chips: { key: string; label: string; onClear: () => void }[] = [];
  if (deepMode) chips.push({ key: "deep", label: "Deep research", onClear: () => setDeepMode(false) });
  if (agentMode) chips.push({ key: "agent", label: "Agent", onClear: () => setAgentMode(false) });
  if (pluginMode) chips.push({ key: "plugins", label: "Plugins", onClear: () => setPluginMode(false) });
  if (voiceMode) chips.push({ key: "voice", label: "Voice", onClear: () => setVoiceMode(false) });
  if (!searchOn) chips.push({ key: "search-off", label: "Search off", onClear: () => setSearchOn(true) });

  return (
    <div className={bare ? "w-full" : "bg-base px-3 pb-3 pt-1 sm:px-4 sm:pb-4"}>
      <div className="relative mx-auto w-full max-w-[48rem] space-y-2" data-composer-menu>
        {showMore && (
          <div className="absolute bottom-full left-0 z-30 mb-2 w-[min(20rem,calc(100vw-1.5rem))] overflow-hidden rounded-2xl border border-white/10 bg-[rgb(var(--mood-panel))] py-1 shadow-[0_16px_40px_rgb(0_0_0/0.45)]">
            <MenuRow
              icon={<Paperclip size={16} />}
              label="Add photos & files"
              onClick={() => {
                setShowMore(false);
                fileRef.current?.click();
              }}
            />
            <MenuRow
              icon={<Globe size={16} />}
              label="Web search"
              active={searchOn}
              onClick={() => {
                setSearchOn(!searchOn);
                setShowMore(false);
              }}
            />
            <MenuRow
              icon={<Telescope size={16} />}
              label="Deep research"
              active={deepMode}
              onClick={() => toggleTool(setDeepMode, deepMode)}
            />
            <MenuRow
              icon={<Bot size={16} />}
              label="Agent team"
              active={agentMode}
              onClick={() => toggleTool(setAgentMode, agentMode)}
            />
            <MenuRow
              icon={<Puzzle size={16} />}
              label="Plugins"
              active={pluginMode}
              onClick={() => toggleTool(setPluginMode, pluginMode)}
            />
            <MenuRow
              icon={<Headphones size={16} />}
              label="Voice replies"
              active={voiceMode}
              onClick={() => toggleTool(setVoiceMode, voiceMode)}
            />
            <MenuRow
              icon={<ImageIcon size={16} />}
              label="Create image"
              onClick={() => {
                setInput((v) => v || "Create an image of ");
                setShowMore(false);
                window.requestAnimationFrame(() => inputRef.current?.focus());
              }}
            />
          </div>
        )}

        {files.length > 0 && (
          <div className="flex flex-wrap gap-2 px-1">
            {files.map((f) => (
              <span
                key={f.id}
                className="flex max-w-full items-center gap-1.5 rounded-full bg-composer px-3 py-1.5 text-xs text-gray-300"
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
          <div role="alert" className="flex items-center gap-2 rounded-xl bg-red-400/10 px-3 py-2 text-xs text-red-200">
            <span className="flex-1">{composerError}</span>
            <button type="button" onClick={() => setComposerError("")} className="text-red-200/70 hover:text-red-100" aria-label="Dismiss composer error">
              ✕
            </button>
          </div>
        )}

        {deepMode && setResearchDepth && (
          <div className="flex justify-center gap-1.5">
            <button
              type="button"
              onClick={() => setResearchDepth("deep")}
              className={`rounded-full px-2.5 py-1 text-[11px] transition ${
                researchDepth === "deep" ? "bg-white/10 text-gray-100" : "text-gray-500 hover:text-white"
              }`}
            >
              Deep
            </button>
            <button
              type="button"
              onClick={() => setResearchDepth("deeper")}
              className={`rounded-full px-2.5 py-1 text-[11px] transition ${
                researchDepth === "deeper" ? "bg-white/10 text-gray-100" : "text-gray-500 hover:text-white"
              }`}
            >
              Deeper
            </button>
          </div>
        )}

        {chips.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-1">
            {chips.map((c) => (
              <button
                key={c.key}
                type="button"
                onClick={c.onClear}
                className="inline-flex items-center gap-1 rounded-full bg-white/8 px-2.5 py-1 text-[11px] text-gray-300 transition hover:bg-white/12"
                aria-label={`Turn off ${c.label}`}
              >
                {c.label} <X size={11} />
              </button>
            ))}
          </div>
        )}

        <div className="flex items-end gap-1 rounded-[28px] bg-composer px-2 py-2 shadow-[0_0_0_1px_rgb(var(--mood-line))] focus-within:shadow-[0_0_0_1px_rgb(var(--mood-muted)/0.45)]">
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
            onClick={() => setShowMore((v) => !v)}
            title="Add files and tools"
            aria-label="Add files and tools"
            aria-expanded={showMore}
            className={`composer-btn mb-0.5 rounded-full transition ${showMore ? "bg-white/10 text-gray-100" : "text-gray-400 hover:bg-white/8 hover:text-white"}`}
          >
            <Plus size={20} />
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
            placeholder={placeholder}
            className="composer-input min-h-[2.75rem] min-w-0 flex-1 resize-none overflow-y-auto bg-transparent px-1 py-2.5 text-[15px] leading-6 outline-none placeholder-gray-500"
          />
          <button
            type="button"
            onClick={toggleMic}
            title={recording ? "Stop recording" : voiceMode ? "Talk" : "Dictate"}
            aria-label={recording ? "Stop recording" : voiceMode ? "Talk" : "Dictate"}
            className={`composer-btn mb-0.5 rounded-full transition ${recording ? "bg-red-400/15 text-red-400 animate-pulse" : "text-gray-400 hover:bg-white/8 hover:text-white"}`}
          >
            {recording ? <Square size={16} /> : <Mic size={18} />}
          </button>
          {busy ? (
            <button
              type="button"
              onClick={onStop}
              title="Stop generating"
              className="composer-btn composer-send mb-0.5 rounded-full transition hover:opacity-90"
              aria-label="Stop generating"
            >
              <Square size={14} />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!canSend}
              className="composer-btn composer-send mb-0.5 rounded-full transition hover:opacity-90 disabled:opacity-30"
              aria-label="Send"
            >
              <ArrowUp size={18} strokeWidth={2.4} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function MenuRow({
  icon,
  label,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm transition hover:bg-white/5 ${active ? "text-gray-100" : "text-gray-300"}`}
    >
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-white/5 text-gray-300">{icon}</span>
      <span className="flex-1">{label}</span>
      {active && <span className="text-[11px] text-gray-500">On</span>}
    </button>
  );
}
