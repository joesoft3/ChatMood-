"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Bot, Brain, Download, Image as ImageIcon, Link2Off, Share2, Sparkles, Swords, Telescope } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import { streamChat } from "@/lib/stream";
import { LAST_CONV_KEY, useConversations } from "@/lib/conversations";
import AppShell from "@/components/AppShell";
import MessageBubble, { ChatMsg } from "@/components/MessageBubble";
import Composer, { FileChip } from "@/components/Composer";
import ArenaPanel, { ArenaEvt } from "@/components/ArenaPanel";
import ThinkingPanel, { ThinkEvt } from "@/components/ThinkingPanel";
import ModelPicker from "@/components/ModelPicker";

/** 🧠 Only these models support extended reasoning (grok-4-fast has no thinking trace). */
const THINKABLE = ["grok-4", "auto", "grok-code-fast-1"];


export default function ChatPage() {
  const router = useRouter();
  const { convs, activeId, setActiveId, refresh } = useConversations();
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [files, setFiles] = useState<FileChip[]>([]);
  const [busy, setBusy] = useState(false);
  const [voiceMode, setVoiceMode] = useState(false);
  const [agentMode, setAgentModeState] = useState(false);
  const [deepMode, setDeepModeState] = useState(false);
  const [pluginMode, setPluginMode] = useState(false);
  const [model, setModel] = useState("auto");
  const [thinkOn, setThinkOn] = useState(false);
  const [arenaMode, setArenaMode] = useState(false);
  const [arenaExtra, setArenaExtra] = useState("");
  const [shared, setShared] = useState(false);
  const [shareMsg, setShareMsg] = useState("");
  const [wsId, setWsId] = useState<string | null>(null);
  const [wsName, setWsName] = useState("");
  const [billingNote, setBillingNote] = useState("");
  const [billingCta, setBillingCta] = useState<"" | "upgrade">("");
  const [teamConvs, setTeamConvs] = useState<{ id: string; title: string; author: string }[] | null>(null);
  const [showTeam, setShowTeam] = useState(false);
  const [draft, setDraft] = useState<{ text: string; nonce: number } | undefined>(undefined);
  const bottomRef = useRef<HTMLDivElement>(null);
  const lastLoaded = useRef<string | null>(null);
  const skipNextLoad = useRef(false);
  const busyRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const restoredRef = useRef(false);

  // Agent mode, Deep search and Arena are mutually exclusive
  function setAgentMode(v: boolean) {
    setAgentModeState(v);
    if (v) {
      setDeepModeState(false);
      setArenaMode(false);
    }
  }
  function setDeepMode(v: boolean) {
    setDeepModeState(v);
    if (v) {
      setAgentModeState(false);
      setArenaMode(false);
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs]);

  // Team workspace mode via /chat?ws=<id> (linked from Settings → Teams)
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    // Return from Stripe checkout (arena premium upgrade): ?billing=success|cancelled
    const billing = q.get("billing");
    const id = q.get("ws");
    if (billing) {
      if (billing === "cancelled") {
        setBillingNote(
          "⚔️ Arena needs Pro. Pick/enable another channel in Settings → Providers, then retry the arena."
        );
        setArenaMode(true);
      } else if (billing === "success") {
        setBillingNote("🎉 Welcome to Pro — arena, thinking models & premium quota unlocked.");
        setTimeout(() => {
          setBillingNote("");
          setBillingCta("");
        }, 9000);
      }
      window.history.replaceState({}, "", window.location.pathname + (id ? `?ws=${id}` : ""));
    }
    if (!id) return;
    setWsId(id);
    Promise.all([
      apiFetch<{ name: string }>(`/workspaces/${id}`),
      apiFetch<{ conversations: { id: string; title: string; author: string }[] }>(`/workspaces/${id}/conversations`),
    ])
      .then(([d, c]) => {
        setWsName(d.name as any);
        setTeamConvs(c.conversations);
      })
      .catch(() => setWsId(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Resume the conversation you last had open (once per visit, when nothing is selected)
  useEffect(() => {
    if (restoredRef.current || activeId || convs.length === 0 || wsId) return;
    restoredRef.current = true;
    try {
      const last = localStorage.getItem(LAST_CONV_KEY);
      if (last && convs.some((c) => c.id === last)) setActiveId(last);
    } catch {
      /* storage unavailable */
    }
  }, [convs, activeId, setActiveId, wsId]);

  // 🏠 Idle auto-reset: AppShell fires mood:idle-reset after 5 min of inactivity.
  // We only comply when NOT streaming (never chop a live answer); the activeId→null
  // effect above then clears the view back to the Grok-clean home, and the ☰
  // history gets a debounced refresh ping so the chat is listed immediately.
  useEffect(() => {
    const h = () => {
      if (busyRef.current) return;
      setShowTeam(false);
      setFiles([]);
      setActiveId(null);
      window.dispatchEvent(new CustomEvent("mood:conversations-changed"));
    };
    window.addEventListener("mood:idle-reset", h);
    return () => window.removeEventListener("mood:idle-reset", h);
  }, [setActiveId]);

  // Load messages whenever the globally-selected conversation changes
  useEffect(() => {
    if (!activeId) {
      lastLoaded.current = null;
      setMsgs([]);
      return;
    }
    if (skipNextLoad.current) {
      skipNextLoad.current = false;
      lastLoaded.current = activeId;
      return;
    }
    if (lastLoaded.current === activeId || busyRef.current) return;
    lastLoaded.current = activeId;
    setMsgs([]);
    setFiles([]);
    apiFetch<any>(`/conversations/${activeId}`)
      .then((d) => {
        const authors: Record<string, string> = d.authors ?? {};
        setMsgs(
          d.messages.map((m: any) => {
            const meta = m.meta ?? {};
            return {
              role: m.role,
              content: m.content,
              author: m.user_id ? (authors[m.user_id] ?? "member") : undefined,
              arena:
                meta.mode === "arena"
                  ? {
                      draftOrder: meta.draft_order ?? [],
                      drafts: meta.drafts ?? [],
                      votes: meta.votes ?? [],
                      scores: meta.scores,
                      winner: meta.winner,
                      usage: meta.usage,
                      events: [{ type: "arena_verdict", ...(meta as any) }],
                    }
                  : undefined,
              think:
                meta.mode === "chat+think"
                  ? {
                      provider: meta.provider ?? "",
                      traces: meta.think_traces ?? [],
                      summary: meta.thinking_summary ?? undefined,
                      elapsedMs: meta.think_time_ms ?? 0,
                      usage: meta.think_usage,
                      events: [{ type: "thinking_end", ...(meta as any) }],
                    }
                  : undefined,
              media: Array.isArray(meta.media) && meta.media.length > 0 ? meta.media : undefined,
            };
          })
        );
      })
      .catch(console.error);
  }, [activeId]);

  // Keyboard shortcuts: ⌘K new chat · `/` focus input · Esc stop
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setActiveId(null);
      }
      if (e.key === "/" && !(e.target as HTMLElement).matches("input,textarea")) {
        e.preventDefault();
        document.getElementById("composer-input")?.focus();
      }
      if (e.key === "Escape") stop();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function patchLast(fn: (m: ChatMsg) => ChatMsg) {
    setMsgs((m) => {
      const a = [...m];
      a[a.length - 1] = fn({ ...a[a.length - 1] });
      return a;
    });
  }

  async function send(text: string, search: boolean, regenerate = false, forceRematch = false) {
    if ((!text.trim() && files.length === 0 && !regenerate) || busy) return;
    setBusy(true);
    busyRef.current = true;
    const useArena = (arenaMode || forceRematch) && !regenerate;
    const useThink = thinkOn && !arenaMode && !agentMode && THINKABLE.includes(model);
    const specialMode = agentMode || deepMode || useArena;
    const fileIds = specialMode || regenerate ? [] : files.map((f) => f.id);
    setMsgs((m) => [
      ...m,
      { role: "user", content: text, author: wsId ? "you" : undefined },
      { role: "assistant", content: "" },
    ]);
    setFiles([]);
    const endpoint = agentMode
      ? "/agents/stream"
      : deepMode
        ? "/deepsearch/stream"
        : useArena
          ? "/agents/arena/stream"
          : "/chat/stream";
    const pushLog = (icon: string, line: string) =>
      patchLast((m) =>
        m.research
          ? { ...m, research: { ...m.research, log: [...m.research.log, { icon, text: line }].slice(-14) } }
          : m
      );
    let newId: string | null = null;
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await streamChat(
        {
          conversation_id: activeId,
          workspace_id: wsId,
          message: text,
          files: fileIds,
          search,
          plugins: pluginMode,
          regenerate,
          depth: deepMode ? "deep" : undefined,
          model,
          think: thinkOn,
          arena: useArena,
          arena_extra: arenaExtra,
          rematch: forceRematch || undefined,
        },
        (ev) => {
          if (ev.type === "meta") {
            if (ev.model) patchLast((m) => ({ ...m, model: ev.model }));
            if (ev.conversation_id && !activeId) {
              newId = ev.conversation_id;
              skipNextLoad.current = true; // keep the streamed messages; don't refetch
            }
          }
          // multi-agent progress
          if (ev.type === "plan" && ev.steps)
            patchLast((m) => ({
              ...m,
              steps: (ev.steps ?? []).map((s) => ({ agent: s.agent, task: s.task, status: "queued" as const })),
            }));
          if (ev.type === "step_start" && ev.i != null)
            patchLast((m) => ({
              ...m,
              steps: m.steps?.map((s, idx) => (idx === ev.i ? { ...s, status: "running" as const } : s)),
            }));
          if (ev.type === "step_done" && ev.i != null)
            patchLast((m) => ({
              ...m,
              steps: m.steps?.map((s, idx) =>
                idx === ev.i ? { ...s, status: "done" as const, preview: ev.preview } : s
              ),
            }));
          // deepsearch progress
          if (ev.type === "subtopics" && ev.subtopics)
            patchLast((m) => ({ ...m, research: { subtopics: ev.subtopics ?? [], log: [] } }));
          if (ev.type === "round_start") pushLog("🔁", `Research round ${ev.round} of ${ev.total}`);
          if (ev.type === "query_start" && ev.query) pushLog("🔍", ev.query);
          if (ev.type === "query_done" && ev.query) pushLog("✅", `${ev.query} — ${ev.sources ?? 0} sources`);
          if (ev.type === "reflect" && ev.note) pushLog("🧭", `Gap analysis: ${ev.note}`);
          if (ev.type === "round_done" && ev.sources != null) pushLog("📚", `${ev.sources} unique sources collected`);
          if (ev.type === "writing") pushLog("✍️", "Writing the report…");
          if (ev.type === "tools" && ev.calls) patchLast((m) => ({ ...m, tools: ev.calls }));
          // staged write actions no longer pop up in-chat — they wait in the Plugin Store inbox (/plugins)
          // ⚔️ arena: drafts, votes, winner
          if (ev.type === "topic" || ev.type.startsWith("draft_") || ev.type.startsWith("vote_"))
            patchLast((m) => ({
              ...m,
              arena: { draftOrder: [], drafts: [], votes: [], events: [...(m.arena?.events ?? []), ev as ArenaEvt] },
            }));
          if (ev.type === "arena_verdict")
            patchLast((m) => ({
              ...m,
              arena: {
                draftOrder: ev.draft_order ?? [],
                drafts: ev.drafts ?? [],
                votes: ev.votes ?? [],
                scores: ev.scores,
                winner: ev.winner,
                usage: ev.usage,
                events: [...(m.arena?.events ?? []), ev as ArenaEvt],
              },
            }));
          // 🎨🎬 in-chat creation (image/video generated inline)
          if (ev.type === "media_start")
            patchLast((m) => ({
              ...m,
              media: [{ kind: ev.kind ?? "image", prompt: ev.prompt ?? "", pending: true }],
            }));
          if (ev.type === "media_progress")
            patchLast((m) =>
              m.media?.length
                ? { ...m, media: [{ ...m.media[0], stage: ev.stage, done: ev.done, total: ev.total, pending: true }] }
                : m
            );
          if (ev.type === "media")
            patchLast((m) => ({
              ...m,
              media: [{ kind: ev.kind ?? "image", url: ev.url, prompt: ev.prompt, stored: ev.stored, pending: false }],
            }));
          // 🧠 extended reasoning (grok-4 / grok-code-fast-1)
          if (ev.type === "thinking_start")
            patchLast((m) => ({ ...m, think: { provider: ev.provider ?? "", traces: [], elapsedMs: 0, events: [] } }));
          if (ev.type === "thinking_trace" && ev.trace)
            patchLast((m) =>
              m.think ? { ...m, think: { ...m.think, traces: [...m.think.traces, ev.trace!] } } : m
            );
          if (ev.type === "thinking")
            patchLast((m) =>
              m.think
                ? {
                    ...m,
                    think: {
                      ...m.think,
                      summary: ev.thinking?.summary ?? undefined,
                      elapsedMs: ev.think_time_ms ?? m.think.elapsedMs,
                      usage: ev.usage,
                      events: [...m.think.events, ev as ThinkEvt],
                    },
                  }
                : m
            );
          if (ev.type === "delta" && ev.text) patchLast((m) => ({ ...m, content: m.content + ev.text }));
          if (ev.type === "citations") patchLast((m) => ({ ...m, citations: ev.citations }));
          if (ev.type === "error") {
            if (ev.error_code === "plan_limit") {
              setBillingNote(ev.message ?? "⚔️ Arena needs Pro — upgrade to unlock more debates.");
              setBillingCta("upgrade");
            }
            setMsgs((m) => {
              const a = [...m];
              a[a.length - 1] = {
                role: "assistant",
                content: (ev.error_code === "plan_limit" ? "🔒 " : "⚠️ ") + (ev.message ?? "Something went wrong"),
              };
              return a;
            });
          }
        },
        endpoint,
        ac.signal
      );
      if (newId) setActiveId(newId);
      await refresh();
    } catch (e: any) {
      if (e?.name === "AbortError") {
        patchLast((m) => ({ ...m, content: m.content + "\n\n⏹ *Stopped by user*" }));
      } else {
        patchLast((m) => ({ ...m, content: "⚠️ " + (e.message ?? "Request failed") }));
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
      busyRef.current = false;
    }
  }

  /** ⚔️ Rematch: rerun the arena — drafters are shown this winner and asked to beat it. */
  async function rematch() {
    if (busy) return;
    const lastUser = [...msgs].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    await send(lastUser.content, false, false, true);
  }

  async function regenerate() {
    if (!activeId || busy) return;
    const lastUser = [...msgs].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    // Drop the trailing exchange locally; server replays it cleanly
    setMsgs((m) => {
      const a = [...m];
      while (a.length && a[a.length - 1].role !== "user") a.pop();
      a.pop();
      return a;
    });
    await send(lastUser.content, true, true);
  }

  async function uploadFile(f: File) {
    const fd = new FormData();
    fd.append("file", f);
    const saved = await apiFetch<FileChip>("/files", { method: "POST", body: fd });
    setFiles((p) => [...p, saved]);
  }

  async function handleVoice(blob: Blob) {
    if (busy) return;
    setBusy(true);
    busyRef.current = true;
    try {
      const fd = new FormData();
      fd.append("file", blob, "voice.webm");
      if (activeId) fd.append("conversation_id", activeId);
      const res = await apiFetch<any>("/voice/chat", { method: "POST", body: fd });
      if (!activeId) {
        skipNextLoad.current = true;
        setActiveId(res.conversation_id);
      }
      setMsgs((m) => [
        ...m,
        { role: "user", content: "🎙️ " + res.transcript },
        { role: "assistant", content: res.reply },
      ]);
      if (res.audio_b64) void new Audio("data:audio/mpeg;base64," + res.audio_b64).play();
      await refresh();
    } catch (e: any) {
      alert(e.message ?? "Voice request failed");
    } finally {
      setBusy(false);
      busyRef.current = false;
    }
  }

  function exportChat() {
    const title = convs.find((c) => c.id === activeId)?.title || "mood-conversation";
    const md: string[] = [`# ${title}`, "", `_Exported from Mood AI · ${new Date().toLocaleString()}_`, ""];
    for (const m of msgs) {
      md.push(m.role === "user" ? "## 🧑 You" : "## ✦ Mood", "", m.content, "");
    }
    const blob = new Blob([md.join("\n")], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = title.replace(/[^\w-]+/g, "-").slice(0, 60) + ".md";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const activeTitle = convs.find((c) => c.id === activeId)?.title;
  const modeMeta = useMemo(() => {
    if (arenaMode) return { label: "Arena", tone: "accent", icon: <Swords size={12} /> };
    if (deepMode) return { label: "Deep research", tone: "accent", icon: <Telescope size={12} /> };
    if (agentMode) return { label: "Agent", tone: "accent", icon: <Bot size={12} /> };
    if (thinkOn) return { label: "Thinking", tone: "purple", icon: <Brain size={12} /> };
    return { label: "Chat", tone: "default", icon: <Sparkles size={12} /> };
  }, [agentMode, arenaMode, deepMode, thinkOn]);
  const modelLabel = useMemo(() => {
    if (model === "grok-4") return "S1 Mood-4";
    if (model === "grok-4-fast") return "S1 Mood-4-Fast";
    if (model === "grok-code-fast-1") return "Code";
    if (model === "grok-3-mini") return "Mini";
    return "Auto";
  }, [model]);

  async function shareChat() {
    if (!activeId) return;
    try {
      const r = await apiFetch<{ token: string; path: string }>(`/conversations/${activeId}/share`, {
        method: "POST",
      });
      const url = `${window.location.origin}${r.path}`;
      (await copyText(url))
        ? setShareMsg("Link copied ✓")
        : setShareMsg(`Link ready — long-press to copy: ${url}`);
      setShared(true);
      setTimeout(() => setShareMsg(""), 2500);
    } catch (e: any) {
      setShareMsg("⚠️ " + (e.message ?? "Share failed"));
      setTimeout(() => setShareMsg(""), 2500);
    }
  }

  async function revokeShare() {
    if (!activeId || !confirm("Revoke the public link? Anyone with it will lose access.")) return;
    try {
      await apiFetch(`/conversations/${activeId}/share`, { method: "DELETE" });
      setShared(false);
    } catch (e: any) {
      alert(e.message ?? "Revoke failed");
    }
  }

  const emptyHome = msgs.length === 0;

  const pickerEl = (bare: boolean) =>
    !deepMode && (
      <ModelPicker
        model={model}
        setModel={setModel}
        thinkOn={thinkOn}
        toggleThink={() => setThinkOn((v) => !v)}
        thinkSupported={arenaMode ? false : THINKABLE.includes(model)}
        arenaMode={arenaMode}
        toggleArena={() => {
          setArenaMode((v) => !v);
          setAgentModeState(false);
        }}
        arenaExtra={arenaExtra}
        setArenaExtra={setArenaExtra}
        bare={bare}
      />
    );

  const composerEl = (bare: boolean) => (
    <Composer
      busy={busy}
      onStop={stop}
      voiceMode={voiceMode}
      setVoiceMode={setVoiceMode}
      agentMode={agentMode}
      setAgentMode={setAgentMode}
      deepMode={deepMode}
      setDeepMode={setDeepMode}
      model={model}
      arenaMode={arenaMode}
      thinkOn={thinkOn && THINKABLE.includes(model) && !arenaMode}
      pluginMode={pluginMode}
      setPluginMode={setPluginMode}
      files={files}
      onRemoveFile={(id) => setFiles((f) => f.filter((x) => x.id !== id))}
      onUpload={uploadFile}
      onSend={(t, s) => send(t, s, false)}
      onVoice={handleVoice}
      draft={draft}
      bare={bare}
    />
  );

  const homeActions = [
    {
      icon: Sparkles,
      label: "Write or brainstorm",
      onClick: () => setDraft({ text: "Help me write ", nonce: Date.now() }),
    },
    {
      icon: Telescope,
      label: "Research a topic",
      onClick: () => {
        setDeepMode(true);
        setDraft({ text: "Research ", nonce: Date.now() });
      },
    },
    {
      icon: ImageIcon,
      label: "Create an image",
      onClick: () => setDraft({ text: "Create an image of ", nonce: Date.now() }),
    },
  ] as const;

  const chatTabs = (
    <div className="flex items-center justify-center gap-7 h-full">
      <span className="relative py-1 text-sm font-semibold text-white after:absolute after:inset-x-0 after:-bottom-2 after:h-0.5 after:rounded-full after:bg-white">Ask</span>
      <button onClick={() => router.push("/images")} className="py-1 text-sm text-gray-500 transition hover:text-gray-200">Imagine</button>
    </div>
  );

  return (
    <AppShell title={activeTitle || "Mood Chat"} headerCenter={emptyHome ? chatTabs : undefined}>
      {emptyHome && <div className="hidden lg:flex h-12 items-center border-b border-white/5 bg-[#0f1011]/88 px-6 backdrop-blur">{chatTabs}</div>}
      {!emptyHome && (
        <>
      {/* conversation toolbar — cleaner and closer to ChatGPT, with live workspace status */}
      <div className="border-b border-white/5 px-3 sm:px-4 py-3 shrink-0 compact-v bg-[#0f1011]/88 backdrop-blur space-y-2.5">
        <div className="flex items-center gap-2 sm:gap-3">
          <div className="flex items-center gap-1 rounded-full border border-white/8 bg-[#141415] p-1 shrink-0 shadow-[0_10px_24px_rgb(0_0_0/0.18)]">
            <span className="rounded-full bg-white text-black px-3 py-1.5 text-xs font-semibold">Ask</span>
            <button onClick={() => router.push("/images")} className="rounded-full px-3 py-1.5 text-xs text-gray-500 hover:text-gray-300 transition">
              Imagine
            </button>
          </div>
          <div className="min-w-0 flex-1 hidden sm:block">
            <p className="truncate text-sm font-medium text-gray-200">{activeTitle || (wsId ? `👥 ${wsName || "Team"} — new chat` : "New chat")}</p>
            <p className="truncate text-[11px] text-gray-500">Auto-saved conversation · premium live workspace shell</p>
          </div>
          {msgs.length > 0 && (
            <div className="ml-auto flex items-center gap-1.5 shrink-0">
              <button onClick={shareChat} className="inline-flex items-center gap-1 rounded-full border border-white/8 bg-[#141415] px-3 py-1.5 hover:text-gray-300 transition" title="Create a public read-only link">
                <Share2 size={13} /> <span className="hidden sm:inline">Share</span>
              </button>
              {shared && (
                <button onClick={revokeShare} className="inline-flex items-center gap-1 rounded-full border border-white/8 bg-[#141415] px-3 py-1.5 hover:text-red-400 transition" title="Revoke the public link">
                  <Link2Off size={13} /> <span className="hidden sm:inline">Revoke</span>
                </button>
              )}
              <button onClick={exportChat} className="inline-flex items-center gap-1 rounded-full border border-white/8 bg-[#141415] px-3 py-1.5 hover:text-gray-300 transition">
                <Download size={13} /> <span className="hidden sm:inline">Export</span>
              </button>
            </div>
          )}
        </div>
        <div className="sm:hidden flex items-center gap-2 min-w-0">
          <span className="truncate text-sm text-gray-300 flex-1">{activeTitle || (wsId ? `👥 ${wsName || "Team"} — new chat` : "New chat")}</span>
          {wsId && (
            <button
              onClick={() => {
                const next = !showTeam;
                setShowTeam(next);
                if (next)
                  apiFetch<{ conversations: any[] }>(`/workspaces/${wsId}/conversations`)
                    .then((c) => setTeamConvs(c.conversations))
                    .catch(() => {});
              }}
              className="rounded-full border border-white/8 bg-[#141415] px-2.5 py-1 text-[10px] text-gray-400 hover:text-white transition shrink-0"
              title="Team workspace conversations"
            >
              👥 Team
            </button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-accent/20 bg-accent/10 px-2.5 py-1 text-[11px] text-accent">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" /> Live
          </span>
          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] ${
            modeMeta.tone === "purple"
              ? "border-purple-400/25 bg-purple-400/10 text-purple-300"
              : modeMeta.tone === "accent"
                ? "border-accent/25 bg-accent/10 text-accent"
                : "border-white/8 bg-white/5 text-gray-400"
          }`}>
            {modeMeta.icon} {modeMeta.label}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/8 bg-white/5 px-2.5 py-1 text-[11px] text-gray-400">
            🤖 {modelLabel}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/8 bg-white/5 px-2.5 py-1 text-[11px] text-gray-400">
            💬 {msgs.length} message{msgs.length === 1 ? "" : "s"}
          </span>
          {wsId && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/8 bg-white/5 px-2.5 py-1 text-[11px] text-gray-400">
              👥 {wsName || "Team workspace"}
            </span>
          )}
        </div>
      </div>
        </>
      )}
      {showTeam && wsId && (
        <div className="border-b border-line bg-panel px-3 sm:px-4 py-2 shrink-0 max-h-48 overflow-y-auto scrollbar-thin">
          <p className="text-[11px] text-gray-500 mb-1.5">Shared with the team — anyone in this workspace can read &amp; continue these</p>
          {!teamConvs || teamConvs.length === 0 ? (
            <p className="text-xs text-gray-600 py-1">No team conversations yet — send a message to start one.</p>
          ) : (
            <div className="space-y-1">
              {teamConvs.map((c) => (
                <button
                  key={c.id}
                  onClick={() => {
                    setShowTeam(false);
                    setActiveId(c.id);
                  }}
                  className={`w-full text-left text-xs rounded-lg px-2.5 py-1.5 border transition flex items-center gap-2 ${
                    c.id === activeId ? "bg-accent/10 border-accent/40 text-accent" : "bg-white/5 border-line text-gray-300 hover:bg-white/10"
                  }`}
                >
                  <span className="flex-1 truncate">{c.title}</span>
                  <span className="text-[10px] text-gray-500 shrink-0">by {c.author}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {billingNote && (
        <div className="border-b border-accent/30 bg-accent/10 px-3 sm:px-4 py-2 text-xs text-accent flex items-center gap-2 shrink-0">
          <span className="flex-1">{billingNote}</span>
          {billingCta === "upgrade" && (
            <button
              onClick={() => router.push("/settings")}
              className="rounded-lg bg-accent text-black font-semibold px-3 py-1 hover:brightness-110 transition shrink-0"
            >
              ✨ Upgrade to Pro
            </button>
          )}
          <button
            onClick={() => {
              setBillingNote("");
              setBillingCta("");
            }}
            className="text-accent/70 hover:text-accent shrink-0"
          >
            ✕
          </button>
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-3 sm:px-4 py-5 sm:py-6 compact-v bg-[radial-gradient(circle_at_top,rgba(124,155,255,0.08),transparent_34%)]">
        <div className="max-w-3xl xl:max-w-[50rem] 2xl:max-w-[52rem] mx-auto space-y-5 sm:space-y-6 mood-fade-up">
          {emptyHome && (
            <div className="flex min-h-[calc(100dvh-10rem)] flex-col items-center justify-center gap-6 py-8 sm:gap-7">
              <h2 className="text-center text-[clamp(2rem,4vw,2.75rem)] font-semibold tracking-tight text-white">How can I help?</h2>
              <div className="w-full max-w-xl">{composerEl(true)}</div>
              <div className="grid w-full max-w-xl grid-cols-1 gap-2 sm:grid-cols-3" aria-label="Start with an action">
                {homeActions.map(({ icon: Icon, label, onClick }) => (
                  <button
                    key={label}
                    onClick={onClick}
                    className="touch-manipulation flex items-center justify-center gap-2 rounded-xl border border-white/8 bg-[#141415] px-3 py-3 text-xs text-gray-400 transition hover:border-white/15 hover:bg-white/[0.045] hover:text-white"
                  >
                    <Icon size={14} className="text-accent" />
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}
          {msgs.map((m, i) => (
            <MessageBubble
              key={i}
              msg={m}
              isStreaming={busy && i === msgs.length - 1 && m.role === "assistant"}
              onRegenerate={
                !busy && i === msgs.length - 1 && m.role === "assistant" && msgs.length >= 2
                  ? regenerate
                  : undefined
              }
              onRematch={
                !busy && i === msgs.length - 1 && m.role === "assistant" && m.arena ? rematch : undefined
              }
            />
          ))}
          <div ref={bottomRef} />
        </div>
      </div>
      {!emptyHome && (
        <>
          {pickerEl(false)}
          {composerEl(false)}
        </>
      )}
    </AppShell>
  );
}
