"use client";

import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Brain, Check, Clapperboard, Copy, Download, RotateCcw, Search, Sparkles, Square, Swords, Volume2 } from "lucide-react";
import { apiFetch } from "@/lib/api";
import ArenaPanel from "./ArenaPanel";
import ThinkingPanel from "./ThinkingPanel";

/** DeepSearch answers persist sources as a markdown tail ("- [n](url)") — recover them for the chips row. */
export function extractCitationUrls(content: string): string[] {
  const urls: string[] = [];
  const re = /^\s*-\s*\[\d+\]\((https?:\/\/[^)\s]+)\)/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    if (!urls.includes(m[1])) urls.push(m[1]);
  }
  return urls;
}

export interface AgentStep {
  agent: string;
  task: string;
  status: "queued" | "running" | "done";
  preview?: string;
}

export interface ResearchProgress {
  subtopics: string[];
  log: { icon: string; text: string }[];
}

export interface ArenaState {
  draftOrder: string[];
  drafts: { provider: string; content: string; round: number }[];
  votes: { provider: string; ballot: { vote: string; rationale: string } | null; valid: boolean }[];
  scores?: Record<string, { accuracy?: number; clarity?: number }>;
  winner?: string;
  usage?: Record<string, { in: number; out: number }>;
  events: any[];
}

export interface ThinkState {
  provider: string;
  traces: string[];
  summary?: string;
  elapsedMs: number;
  usage?: Record<string, { in: number; out: number }>;
  events: any[];
}

export interface ConfirmAction {
  id: string;
  name: string;
  args: Record<string, any>;
  status: "pending" | "approved" | "rejected" | "failed";
  note?: string;
}

export interface ChatMedia {
  kind: "image" | "video";
  url?: string;
  prompt?: string;
  stored?: string;
  pending?: boolean;
  stage?: string;
  done?: number;
  total?: number;
}

export interface ChatMsg {
  role: "user" | "assistant" | "system";
  content: string;
  author?: string;
  citations?: string[];
  steps?: AgentStep[];
  research?: ResearchProgress;
  model?: string;
  tools?: { name: string; ok: boolean }[];
  actions?: ConfirmAction[];
  arena?: ArenaState;
  think?: ThinkState;
  media?: ChatMedia[];
}

const AGENT_ICON: Record<string, string> = { researcher: "🔍", coder: "⌨️", writer: "✍️", critic: "🧐" };

function MediaBlock({ m }: { m: ChatMedia }) {
  const label =
    m.kind === "image"
      ? "Generating your image…"
      : m.stage === "storyboard"
        ? "Storyboarding your reel…"
        : m.stage === "compositing"
          ? "Compositing your reel…"
          : m.stage === "voice"
            ? "Recording the voiceover…"
            : m.stage === "scenes" && m.total
              ? `Directing scenes (${m.done ?? 0}/${m.total})…`
              : "Directing your reel…";

  if (m.pending || !m.url) {
    return (
      <div className="mb-3 overflow-hidden rounded-3xl border border-white/10 bg-[#171718] shadow-[0_14px_32px_rgb(0_0_0/0.22)]">
        <div className="aspect-video w-full animate-pulse bg-gradient-to-br from-white/5 via-white/10 to-white/5" />
        <p className="px-4 py-3 text-xs text-gray-400 flex items-center gap-2">
          <span className="inline-block h-3 w-3 animate-spin rounded-full border border-accent border-t-transparent" />
          {m.kind === "image" ? "🎨" : "🎬"} {label}
        </p>
      </div>
    );
  }

  return (
    <div className="mb-3 overflow-hidden rounded-3xl border border-white/10 bg-[#171718] shadow-[0_14px_32px_rgb(0_0_0/0.22)]">
      {m.kind === "image" ? (
        <a href={m.url} target="_blank" rel="noreferrer" title="Open full-size">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={m.url} alt={m.prompt ?? "Generated image"} className="block w-full max-w-lg" />
        </a>
      ) : (
        <video src={m.url} controls playsInline preload="metadata" className="block w-full max-w-lg bg-black" />
      )}
      <div className="flex items-center gap-2 px-4 py-2.5 text-[11px] text-gray-500">
        <span className="truncate flex-1">
          {m.kind === "image" ? "🎨" : "🎬"} {m.prompt}
        </span>
        {m.stored === "r2" && <span className="shrink-0" title="Saved to your library">☁️</span>}
        <a
          href={m.url}
          target="_blank"
          rel="noreferrer"
          download
          title="Download"
          className="shrink-0 text-gray-500 hover:text-white transition"
        >
          <Download size={13} />
        </a>
      </div>
    </div>
  );
}

function ToolPills({ tools }: { tools: { name: string; ok: boolean }[] }) {
  return (
    <div className="mb-3 flex flex-wrap gap-1.5">
      {tools.map((t, i) => (
        <span
          key={i}
          className={`text-[11px] rounded-full border px-2.5 py-1 ${
            t.ok
              ? "bg-accent/10 border-accent/25 text-accent"
              : "bg-red-400/10 border-red-400/30 text-red-400"
          }`}
        >
          🧩 {t.name} {t.ok ? "✓" : "✗"}
        </span>
      ))}
    </div>
  );
}

function PendingAssistantState({ msg }: { msg: ChatMsg }) {
  let icon = <Brain size={14} className="text-accent" />;
  let title = "Thinking through the answer…";
  let detail = "ChatMood is working on your response.";
  let activity = ["understanding", "reasoning", "drafting"];

  const pendingMedia = msg.media?.find((m) => m.pending);
  if (pendingMedia) {
    icon = pendingMedia.kind === "image" ? <Sparkles size={14} className="text-accent" /> : <Clapperboard size={14} className="text-accent" />;
    title = pendingMedia.kind === "image" ? "Generating your image…" : "Generating your video…";
    detail = pendingMedia.stage
      ? `Stage: ${pendingMedia.stage}${pendingMedia.total ? ` · ${pendingMedia.done ?? 0}/${pendingMedia.total}` : ""}`
      : "Preparing the media pipeline.";
    activity = pendingMedia.kind === "image"
      ? ["interpreting prompt", "composing scene", "rendering image"]
      : ["planning shots", "directing scenes", "rendering video"];
  } else if (msg.research) {
    icon = <Search size={14} className="text-accent" />;
    title = "Searching and comparing sources…";
    detail = msg.research.log[msg.research.log.length - 1]?.text ?? "Building a grounded answer with live sources.";
    activity = ["searching web", "comparing evidence", "writing report"];
  } else if (msg.arena && !msg.arena.winner) {
    icon = <Swords size={14} className="text-accent" />;
    title = "Drafting across multiple models…";
    detail = "The arena is collecting drafts, votes and the judge verdict.";
    activity = ["collecting drafts", "scoring arguments", "judging winner"];
  } else if (msg.think && msg.think.traces.length > 0) {
    icon = <Brain size={14} className="text-accent" />;
    title = "Reasoning through the answer…";
    detail = "Live reasoning is in progress before the final response is written.";
    activity = ["mapping context", "testing ideas", "forming answer"];
  } else if (msg.steps?.length) {
    icon = <Sparkles size={14} className="text-accent" />;
    title = "Working through the task…";
    detail = "Specialist workers are planning, researching or writing.";
    activity = ["planning", "delegating", "assembling result"];
  }

  return (
    <div className="rounded-3xl border border-white/8 bg-[#171718] px-4 py-3.5 shadow-[0_12px_28px_rgb(0_0_0/0.14)]">
      <div className="flex items-center gap-2 text-sm text-gray-200">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-accent/10">{icon}</span>
        <span className="font-medium">{title}</span>
        <span className="ml-auto inline-block h-2 w-2 animate-pulse rounded-full bg-accent/80" />
      </div>
      <p className="mt-1.5 text-xs text-gray-500 leading-relaxed">{detail}</p>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {activity.map((item, i) => (
          <span
            key={item}
            className="inline-flex items-center gap-1 rounded-full border border-white/8 bg-white/5 px-2.5 py-1 text-[11px] text-gray-400"
            style={{ animationDelay: `${i * 120}ms` }}
          >
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent/80 animate-pulse" />
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function ResearchPanel({ r }: { r: ResearchProgress }) {
  return (
    <div className="mb-3 rounded-xl border border-line bg-base/60 p-3 space-y-2">
      <p className="text-xs font-medium text-gray-400">🔭 Deep research</p>
      {r.subtopics.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {r.subtopics.map((s, i) => (
            <span
              key={i}
              className="text-[11px] rounded-full bg-accent/10 border border-accent/25 text-accent px-2.5 py-1"
            >
              {s}
            </span>
          ))}
        </div>
      )}
      {r.log.length > 0 && (
        <div className="space-y-1 max-h-40 overflow-y-auto scrollbar-thin">
          {r.log.map((l, i) => (
            <p key={i} className="text-[11px] text-gray-500 leading-snug">
              {l.icon} {l.text}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentSteps({ steps }: { steps: AgentStep[] }) {
  return (
    <div className="mb-3 rounded-xl border border-line bg-base/60 p-3 space-y-2">
      <p className="text-xs font-medium text-gray-400">🤖 Agent team</p>
      {steps.map((s, i) => (
        <div key={i} className="flex items-start gap-2 text-xs">
          <span className="shrink-0">{s.status === "done" ? "✅" : s.status === "running" ? "⏳" : "▫️"}</span>
          <div className="min-w-0">
            <span className="text-accent font-medium">
              {AGENT_ICON[s.agent] ?? "🤖"} {s.agent}
            </span>
            <span className="text-gray-400"> — {s.task}</span>
            {s.preview && s.status === "done" && <p className="text-gray-600 truncate">{s.preview}</p>}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Code block with a proper header + copy button (ChatGPT-style polish). */
function CodePre(props: any) {
  const ref = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);
  const child = Array.isArray(props.children) ? props.children[0] : props.children;
  const cls = child?.props?.className ?? "";
  const lang = ((cls.match(/language-([A-Za-z0-9_+-]+)/)?.[1] ?? "code") as string)
    .replace(/[-_]/g, " ")
    .trim();
  return (
    <div className="group/code overflow-hidden rounded-2xl border border-white/8 bg-[#0f1012] shadow-[0_14px_32px_rgb(0_0_0/0.2)] my-3">
      <div className="flex items-center justify-between gap-3 border-b border-white/6 px-3 py-2 text-[10px] uppercase tracking-[0.14em] text-gray-500">
        <span>{lang}</span>
        <button
          onClick={async () => {
            await navigator.clipboard.writeText(ref.current?.innerText ?? "");
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
          className="rounded-lg border border-white/8 bg-white/5 px-2 py-1 tracking-normal text-gray-400 hover:bg-white/10 hover:text-white transition"
        >
          {copied ? "Copied ✓" : "Copy code"}
        </button>
      </div>
      <pre ref={ref} {...props} className={`${props.className ?? ""} !m-0 !border-0 !bg-transparent !p-4`} />
    </div>
  );
}

export default function MessageBubble({
  msg,
  onRegenerate,
  onRematch,
  isStreaming = false,
}: {
  msg: ChatMsg;
  onRegenerate?: () => void;
  onRematch?: () => void;
  isStreaming?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState("");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  async function copyMessage() {
    await navigator.clipboard.writeText(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  async function readAloud() {
    setReadError("");
    if (reading) {
      audioRef.current?.pause();
      setReading(false);
      return;
    }
    try {
      setReading(true);
      const blob = await apiFetch<Blob>("/voice/tts", {
        method: "POST",
        body: JSON.stringify({ text: msg.content.slice(0, 3900) }),
      });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => setReading(false);
      audio.onerror = () => setReading(false);
      await audio.play();
    } catch (e: any) {
      setReading(false);
      setReadError(e.message ?? "Read-aloud unavailable (set OPENAI_API_KEY)");
    }
  }

  if (msg.role === "user") {
    return (
      <div className="flex justify-end mood-fade-up">
        <div className="flex max-w-[min(88%,42rem)] flex-col items-end gap-1">
          {msg.author && <span className="text-[10px] text-gray-500 pr-1">🧑 {msg.author}</span>}
          <div className="rounded-[1.55rem] border border-accent/20 bg-accent/15 px-4 py-3 text-sm text-gray-100 shadow-[0_12px_28px_rgb(0_0_0/0.14)] whitespace-pre-wrap [overflow-wrap:anywhere]">
            {msg.content}
          </div>
        </div>
      </div>
    );
  }

  const hasBody = msg.content.trim().length > 0;
  const hasPendingMedia = Boolean(msg.media?.some((m) => m.pending));
  const showPendingState = !hasBody && !hasPendingMedia;
  const headerLabel = msg.research
    ? "Searching"
    : msg.arena && !msg.arena.winner
      ? "Arena"
      : msg.think && (isStreaming || msg.think.traces.length > 0)
        ? "Reasoning"
        : hasPendingMedia
          ? (msg.media?.[0]?.kind === "image" ? "Image studio" : "Video studio")
          : isStreaming
            ? "Working"
            : "ChatMood";
  const assistantIcon = msg.research
    ? <Search size={13} />
    : msg.arena && !msg.arena.winner
      ? <Swords size={13} />
      : msg.think && (isStreaming || msg.think.traces.length > 0)
        ? <Brain size={13} />
        : hasPendingMedia
          ? (msg.media?.[0]?.kind === "image" ? <Sparkles size={13} /> : <Clapperboard size={13} />)
          : <Sparkles size={13} />;

  return (
    <div className="group flex items-start gap-3 sm:gap-4 mood-fade-up">
      <div className="hidden sm:inline-flex mt-1 h-8 w-8 shrink-0 items-center justify-center rounded-full border border-white/8 bg-white/5 text-accent shadow-[0_8px_20px_rgb(0_0_0/0.16)]">
        {assistantIcon}
      </div>
      <div className="min-w-0 flex-1 max-w-full">
        <div className="mb-2 flex items-center gap-2 text-xs text-gray-500">
          <span className="inline-flex sm:hidden h-7 w-7 items-center justify-center rounded-full border border-white/8 bg-white/5 text-accent shadow-[0_6px_18px_rgb(0_0_0/0.16)]">
            {assistantIcon}
          </span>
          <span className="font-medium text-gray-300">ChatMood</span>
          <span className="rounded-full border border-white/8 bg-white/5 px-2 py-0.5 text-[10px] text-gray-400">{headerLabel}</span>
          {isStreaming && <span className="inline-flex h-2 w-2 animate-pulse rounded-full bg-accent/80" />}
        </div>
        <div className="msg rounded-[1.55rem] sm:rounded-[1.8rem] border border-white/6 bg-[#141415]/96 px-4 sm:px-5 py-3.5 sm:py-4 text-gray-200 leading-relaxed text-[15px] shadow-[0_12px_28px_rgb(0_0_0/0.16)]">
          {msg.research && <ResearchPanel r={msg.research} />}
          {msg.steps && msg.steps.length > 0 && <AgentSteps steps={msg.steps} />}
          {msg.think && <ThinkingPanel state={msg.think} replayEvents={msg.think.events} />}
          {msg.arena && <ArenaPanel state={msg.arena} replayEvents={msg.arena.events} />}
          {msg.tools && msg.tools.length > 0 && <ToolPills tools={msg.tools} />}
          {msg.media && msg.media.length > 0 && (
            <div className="space-y-3">
              {msg.media.map((m, i) => (
                <MediaBlock key={i} m={m} />
              ))}
            </div>
          )}
          {showPendingState ? (
            <PendingAssistantState msg={msg} />
          ) : (
            <>
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ pre: CodePre as any }}>
                {msg.content}
              </ReactMarkdown>
              {isStreaming && hasBody && !hasPendingMedia && (
                <div className="mt-1 inline-flex items-center gap-2 rounded-full border border-white/8 bg-white/5 px-2.5 py-1 text-[11px] text-gray-500">
                  <span className="typing-cursor inline-block h-3 w-[2px] rounded-full bg-accent/80" />
                  streaming response…
                </div>
              )}
            </>
          )}

          {(() => {
            const cites = msg.citations && msg.citations.length > 0 ? msg.citations : extractCitationUrls(msg.content);
            if (cites.length === 0) return null;
            return (
              <div className="mt-3 border-t border-line pt-2">
                <p className="mb-1.5 text-xs font-medium text-gray-500">📚 Sources · {cites.length}</p>
                <div className="flex flex-wrap gap-1.5">
                  {cites.map((c, i) => {
                    let host = c;
                    try {
                      host = new URL(c).hostname.replace(/^www\./, "");
                    } catch {}
                    return (
                      <a
                        key={i}
                        href={c}
                        target="_blank"
                        rel="noreferrer"
                        title={c}
                        className="inline-flex items-center gap-1.5 rounded-full border border-line bg-base/60 px-2.5 py-1 text-[11px] text-accent hover:border-accent/50 hover:bg-accent/10 transition"
                      >
                        <span className="grid h-4 w-4 place-items-center rounded-full bg-accent/15 text-[10px] font-bold">{i + 1}</span>
                        {host}
                      </a>
                    );
                  })}
                </div>
              </div>
            );
          })()}

          {readError && (
            <div role="alert" className="mt-3 flex items-center gap-2 rounded-xl border border-red-400/20 bg-red-400/10 px-3 py-2 text-xs text-red-200">
              <span className="flex-1">{readError}</span>
              <button type="button" onClick={() => setReadError("")} aria-label="Dismiss read-aloud error">✕</button>
            </div>
          )}
          {msg.content.length > 0 && (
            <div className="mt-3 flex items-center gap-2 text-gray-600 flex-wrap">
              <button onClick={copyMessage} title="Copy answer" className="rounded-lg px-2 py-1 hover:bg-white/5 hover:text-gray-300 transition">
                {copied ? <Check size={13} className="text-green-400" /> : <Copy size={13} />}
              </button>
              <button onClick={readAloud} title={reading ? "Stop reading" : "Read aloud"} className="rounded-lg px-2 py-1 hover:bg-white/5 hover:text-gray-300 transition">
                {reading ? <Square size={12} className="text-accent" /> : <Volume2 size={13} />}
              </button>
              {onRegenerate && (
                <button onClick={onRegenerate} title="Regenerate response" className="rounded-lg px-2 py-1 hover:bg-white/5 hover:text-gray-300 transition">
                  <RotateCcw size={13} />
                </button>
              )}
              {onRematch && (
                <button onClick={onRematch} title="⚔️ Rematch — providers try to beat this answer" className="rounded-lg px-2 py-1 hover:bg-white/5 hover:text-gray-300 transition text-[12px]">
                  ⚔️
                </button>
              )}
              {msg.model && <span className="text-[10px] ml-auto rounded-full border border-white/5 bg-white/5 px-2 py-0.5">{msg.model}</span>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
