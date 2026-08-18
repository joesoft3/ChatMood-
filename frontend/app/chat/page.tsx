"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Download, FileText, Image as ImageIcon, Link2Off, ListChecks, PenLine, Share2, Sparkles, Telescope } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import { streamChat } from "@/lib/stream";
import { OPEN_CONV_KEY, useConversations } from "@/lib/conversations";
import AppShell from "@/components/AppShell";
import MessageBubble, { ChatMedia, ChatMsg } from "@/components/MessageBubble";
import Composer, { FileChip } from "@/components/Composer";
import ArenaPanel, { ArenaEvt } from "@/components/ArenaPanel";
import ThinkingPanel, { ThinkEvt } from "@/components/ThinkingPanel";
import ModelPicker from "@/components/ModelPicker";
import CanvasPanel from "@/components/CanvasPanel";

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
  // 🗂 Project mode via /chat?project=<id> — the chat inherits the project brief
  const [projectId, setProjectId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("");
  const [billingNote, setBillingNote] = useState("");
  const [billingCta, setBillingCta] = useState<"" | "upgrade">("");
  const [teamConvs, setTeamConvs] = useState<{ id: string; title: string; author: string }[] | null>(null);
  const [showTeam, setShowTeam] = useState(false);
  const [draft, setDraft] = useState<{ text: string; nonce: number } | undefined>(undefined);
  const answerStartRef = useRef<HTMLDivElement>(null);
  const previousMessageCount = useRef(0);
  const lastLoaded = useRef<string | null>(null);
  const skipNextLoad = useRef(false);
  const busyRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const pendingOpenRef = useRef(false);
  const [transportError, setTransportError] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [funMode, setFunMode] = useState(false);
  const [temporary, setTemporary] = useState(false);
  const [researchDepth, setResearchDepth] = useState<"deep" | "deeper">("deep");
  const [canvas, setCanvas] = useState<{ title: string; content: string } | null>(null);

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

  // Keep the beginning of each new answer in view. While the assistant is
  // streaming, the bubble grows downward without repeatedly pulling the
  // viewport back to its last line, so the response reads top-to-bottom.
  useEffect(() => {
    if (msgs.length > previousMessageCount.current && msgs[msgs.length - 1]?.role === "assistant") {
      answerStartRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    previousMessageCount.current = msgs.length;
  }, [msgs.length]);

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
      // Preserve every other param when scrubbing ?billing — dropping them here
      // was silently discarding ?project= / ?c= deep links.
      q.delete("billing");
      const rest = q.toString();
      window.history.replaceState({}, "", window.location.pathname + (rest ? `?${rest}` : ""));
    }
    // 🗂 /chat?project=<id> — file this conversation under a project
    const proj = q.get("project");
    if (proj) {
      setProjectId(proj);
      apiFetch<{ name: string; emoji: string }>(`/projects/${proj}`)
        .then((p) => setProjectName(`${p.emoji ?? "🗂"} ${p.name}`))
        .catch(() => setProjectId(null));
    }
    // 🔗 /chat?c=<id> — deep link straight to a conversation (task threads, project lists)
    const openConv = q.get("c");
    if (openConv) {
      pendingOpenRef.current = true;
      setActiveId(openConv);
    }
    apiFetch<{ fun_mode?: boolean }>("/auth/me")
      .then((me) => {
        if (me.fun_mode) setFunMode(true);
      })
      .catch(() => {});
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

  // Chat opens clean by default. Only an explicit library action may reopen
  // a saved conversation (the history menu still selects one directly).
  useEffect(() => {
    if (pendingOpenRef.current || activeId || wsId) return;
    pendingOpenRef.current = true;
    try {
      const pending = localStorage.getItem(OPEN_CONV_KEY);
      if (pending) {
        localStorage.removeItem(OPEN_CONV_KEY);
        setActiveId(pending);
      }
    } catch {
      /* storage unavailable */
    }
  }, [activeId, setActiveId, wsId]);

  // The Chat destination means “new chat”; history items set activeId directly.
  useEffect(() => {
    const h = () => {
      if (busyRef.current) return;
      setFiles([]);
      setActiveId(null);
    };
    window.addEventListener("mood:new-chat", h);
    return () => window.removeEventListener("mood:new-chat", h);
  }, [setActiveId]);

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
      setSuggestions([]);
      return;
    }
    if (skipNextLoad.current) {
      skipNextLoad.current = false;
      lastLoaded.current = activeId;
      return;
    }
    // Tapping history loads conversation; media cards include edit (redesign) buttons
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
              id: m.id,
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

  async function send(text: string, search: boolean, regenerate = false, forceRematch = false, editFrom?: string) {
    // Keep every prompt on the streaming path. The API detects image/video
    // requests (including flyers, logos, banners and stickers) and emits its
    // real media lifecycle, then persists the answer and the asset. A former
    // client-only shortcut faked a successful generation and immediately
    // cleared the thread; it also stopped this page from compiling, which
    // blocked the production chat-home deployment entirely.
    if ((!text.trim() && files.length === 0 && !regenerate) || busy) return;
    setSuggestions([]);
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
          project_id: projectId,
          message: text,
          files: fileIds,
          search,
          plugins: pluginMode,
          regenerate,
          depth: deepMode ? researchDepth : undefined,
          model,
          think: thinkOn,
          arena: useArena,
          arena_extra: arenaExtra,
          rematch: forceRematch || undefined,
          edit_from: editFrom,
          fun: funMode,
          temporary,
        },
        (ev) => {
          if (ev.type === "meta") {
            if (ev.model) patchLast((m) => ({ ...m, model: ev.model }));
            if (ev.user_message_id) {
              setMsgs((m) => {
                const a = [...m];
                for (let i = a.length - 1; i >= 0; i--) {
                  if (a[i].role === "user") {
                    a[i] = { ...a[i], id: ev.user_message_id };
                    break;
                  }
                }
                return a;
              });
            }
            if (ev.conversation_id && !activeId) {
              newId = ev.conversation_id;
              skipNextLoad.current = true; // keep the streamed messages; don't refetch
            }
          }
          if (ev.type === "suggestions" && ev.suggestions?.length) {
            setSuggestions(ev.suggestions.filter(Boolean).slice(0, 3));
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
              media: [{
                kind: ev.kind ?? "image",
                url: ev.url,
                prompt: ev.prompt,
                stored: ev.stored,
                file_id: ev.file_id,
                pending: false,
              }],
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
        const message = e.message ?? "Request failed";
        if (/Can't reach|Failed to fetch|NetworkError/i.test(message)) {
          setTransportError(message);
          window.setTimeout(() => setTransportError(""), 8000);
        }
        patchLast((m) => ({ ...m, content: "⚠️ " + message }));
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
      busyRef.current = false;
    }
  }

  /** ✏️ Rewind from a user turn and resend the edited text. */
  async function editMessage(index: number, text: string) {
    if (busy) return;
    const target = msgs[index];
    if (!target?.id) return;
    setMsgs((m) => m.slice(0, index));
    await send(text, true, false, false, target.id);
  }

  /** 🎨 Edit a generation — prefill the composer with a remix instruction.
   *  The chat media router already treats "change the sky to sunset" as a
   *  refine of the previous generation, so this just seeds the phrasing. */
  function editMedia(m: ChatMedia) {
    const verb = m.kind === "image" ? "Edit this image" : "Edit this video";
    setDraft({ text: `${verb}: `, nonce: Date.now() });
  }

  /** 🗑 Delete a generation from the library, and drop its card from the thread. */
  async function deleteMedia(m: ChatMedia) {
    if (!m.file_id) return;
    if (!window.confirm("Delete this generation from your library? This can't be undone.")) return;
    try {
      await apiFetch(`/files/${m.file_id}`, { method: "DELETE" });
      // Remove the card locally so the thread matches reality without a reload.
      setMsgs((prev) =>
        prev.map((msg) =>
          msg.media?.some((x) => x.file_id === m.file_id)
            ? { ...msg, media: msg.media.filter((x) => x.file_id !== m.file_id) }
            : msg,
        ),
      );
    } catch (e: any) {
      setTransportError(e?.message ?? "Couldn't delete that file");
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
      setTransportError(e.message ?? "Voice request failed");
      window.setTimeout(() => setTransportError(""), 8000);
    } finally {
      setBusy(false);
      busyRef.current = false;
    }
  }

  function exportChat() {
    const title = convs.find((c) => c.id === activeId)?.title || "mood-conversation";
    const md: string[] = [`# ${title}`, "", `_Exported from ChatMood · ${new Date().toLocaleString()}_`, ""];
    for (const m of msgs) {
      md.push(m.role === "user" ? "## 🧑 You" : "## ✦ ChatMood", "", m.content, "");
    }
    const blob = new Blob([md.join("\n")], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = title.replace(/[^\w-]+/g, "-").slice(0, 60) + ".md";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const activeTitle = convs.find((c) => c.id === activeId)?.title;

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
      setTransportError(e.message ?? "Revoke failed");
      window.setTimeout(() => setTransportError(""), 8000);
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
        funMode={funMode}
        toggleFun={() => {
          const next = !funMode;
          setFunMode(next);
          void apiFetch("/auth/preferences", {
            method: "PATCH",
            body: JSON.stringify({ fun_mode: next }),
          }).catch(() => {});
        }}
        temporary={temporary}
        toggleTemporary={() => setTemporary((v) => !v)}
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
      researchDepth={researchDepth}
      setResearchDepth={setResearchDepth}
    />
  );

  /** 🏠 Empty-home starters. `prompt` is the single source of truth: it seeds the
   *  composer AND the button's accessible name, so the two can't drift apart. */
  const homeActions = [
    {
      icon: Sparkles,
      label: "Help me write",
      prompt: "Help me write ",
      onClick: () => setDraft({ text: "Help me write ", nonce: Date.now() }),
    },
    {
      icon: Telescope,
      label: "Research a topic",
      prompt: "Research ",
      // Also flips deep-research mode on — the composer shows a dismissible
      // "Research mode" pill in bare mode so the state is never invisible.
      onClick: () => {
        setDeepMode(true);
        setDraft({ text: "Research ", nonce: Date.now() });
      },
    },
    {
      icon: ImageIcon,
      label: "Create an image",
      prompt: "Create an image of ",
      onClick: () => setDraft({ text: "Create an image of ", nonce: Date.now() }),
    },
    {
      icon: PenLine,
      label: "Brainstorm ideas",
      prompt: "Brainstorm ideas for ",
      onClick: () => setDraft({ text: "Brainstorm ideas for ", nonce: Date.now() }),
    },
    {
      icon: ListChecks,
      label: "Make a plan",
      prompt: "Make a plan for ",
      onClick: () => setDraft({ text: "Make a plan for ", nonce: Date.now() }),
    },
    {
      icon: FileText,
      label: "Summarize text",
      prompt: "Summarize the following: ",
      onClick: () => setDraft({ text: "Summarize the following: ", nonce: Date.now() }),
    },
  ] as const;

  const chatTabs = (
    <div className="flex items-center justify-center gap-7 h-full">
      <span className="py-1 text-sm font-semibold text-white">Ask</span>
      <button onClick={() => router.push("/images")} className="py-1 text-sm text-gray-500 transition hover:text-gray-200">Imagine</button>
      {/* 📺 Creator Reel — the shared feed creators post their videos to */}
      <button onClick={() => router.push("/reel")} className="py-1 text-sm text-gray-500 transition hover:text-gray-200">Reel</button>
    </div>
  );

  return (
    <AppShell title={activeTitle || "ChatMood Chat"} headerCenter={emptyHome ? chatTabs : undefined}>
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
            {/* 📺 Creator Reel — keeps the feed reachable from inside a conversation,
                not just the empty-chat home (the tab row there vanishes once chat starts). */}
            <button onClick={() => router.push("/reel")} className="rounded-full px-3 py-1.5 text-xs text-gray-500 hover:text-gray-300 transition">
              Reel
            </button>
          </div>
          <div className="min-w-0 flex-1 hidden sm:block">
            <p className="truncate text-sm font-medium text-gray-200">{activeTitle || (wsId ? `👥 ${wsName || "Team"} — new chat` : "New chat")}</p>
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
      </div>
        </>
      )}
      {/* 🗂 Project mode — the standing brief is applied server-side; say so plainly
          so the user knows why answers differ from a loose chat. */}
      {projectId && (
        <div className="shrink-0 border-b border-line bg-accent/5 px-3 sm:px-4 py-1.5 flex items-center gap-2 text-[11px]">
          <span className="truncate text-gray-300">
            {projectName || "🗂 Project"} — this chat follows the project brief &amp; pinned files
          </span>
          <button
            onClick={() => router.push(`/projects`)}
            className="ml-auto shrink-0 text-accent hover:underline"
          >
            manage
          </button>
        </div>
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
      {transportError && (
        <div role="alert" className="border-b border-red-400/20 bg-red-400/10 px-3 py-2 text-xs text-red-200 flex items-center gap-2 shrink-0">
          <span className="flex-1">{transportError}</span>
          <button type="button" onClick={() => setTransportError("")} className="text-red-200/70 hover:text-red-100" aria-label="Dismiss server error">✕</button>
        </div>
      )}
      {billingNote && (
        <div className="border-b border-accent/30 bg-accent/10 px-3 sm:px-4 py-2 text-xs text-accent flex items-center gap-2 shrink-0">
          <span className="flex-1">{billingNote}</span>
          {billingCta === "upgrade" && (
            <button
              onClick={() => router.push("/upgrade")}
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
      {/* On the empty home the scroll area becomes a flex column so the greeting
          block can center against the REAL remaining space (flex-1) instead of a
          hardcoded viewport calc. In a conversation it stays a plain scroll box. */}
      <div
        className={`flex-1 min-h-0 overflow-y-auto scrollbar-thin px-3 sm:px-4 py-5 sm:py-6 compact-v bg-[radial-gradient(circle_at_top,rgba(124,155,255,0.08),transparent_34%)] ${
          emptyHome ? "flex flex-col" : ""
        }`}
      >
        <div
          className={`max-w-3xl xl:max-w-[50rem] 2xl:max-w-[52rem] mx-auto space-y-5 sm:space-y-6 mood-fade-up ${
            emptyHome ? "flex w-full flex-1 flex-col" : ""
          }`}
        >
          {emptyHome && (
            /* 🏠 ChatGPT-style home: greeting → composer → model row → starters.
               Centering uses flex-1 against the scroll container rather than a
               hardcoded `min-h-[calc(100dvh-11rem)]`. That 11rem could only ever
               be right for one breakpoint: this block sits INSIDE a flex column
               that has already subtracted the mobile header, the bottom tab bar
               and its own padding, so on a phone with safe-area insets the old
               min-height exceeded the available box and the "centered" column
               overflowed into a scroll. `flex-1` measures the real remaining
               space at every size instead. */
            <div className="flex flex-1 flex-col items-center justify-center gap-6 py-6 sm:gap-7 sm:py-8">
              <div className="flex flex-col items-center gap-3 text-center select-none">
                <span className="grid h-11 w-11 place-items-center rounded-2xl bg-[#141415] border border-white/8 shadow-[0_0_55px_-16px_rgb(var(--mood-accent)/0.65)]">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src="/icon.png" alt="" className="h-6 w-6 rounded-lg" />
                </span>
                {/* h1, not h2: on the empty home `headerCenter` replaces AppShell's
                    mobile <h1>, so this was the only heading on the page and it
                    started at level 2 — a skipped level with no h1 for screen
                    readers to anchor to. */}
                <h1 className="text-center text-[clamp(1.85rem,4.6vw,2.6rem)] font-semibold tracking-tight text-white">
                  What can I help with?
                </h1>
              </div>
              {/* Composer, model row and starters share ONE width token so the
                  stack reads as a single column. The starters used to be max-w-2xl
                  against a max-w-xl composer — visibly wider than the input they
                  feed. max-w-2xl matches the conversation composer's first step
                  (max-w-3xl is its inner cap) far more closely, so sending the
                  first message no longer snaps the input ~33% wider. */}
              <div className="w-full max-w-2xl">{composerEl(true)}</div>
              <div className="flex w-full max-w-2xl justify-center">{pickerEl(true)}</div>
              <div className="w-full max-w-2xl px-2">
                {/* nav, not a bare div: this is a set of controls, and the label
                    was previously on a plain <div> where it announced nothing. */}
                <nav className="flex flex-wrap items-center justify-center gap-2" aria-label="Conversation starters">
                  {homeActions.map(({ icon: Icon, label, onClick, prompt }) => (
                    <button
                      key={label}
                      onClick={onClick}
                      /* The visible label is a short verb ("Help me write"), but
                         what the button DOES is prefill a specific prompt. Spell
                         that out for screen readers instead of leaving them to
                         guess that a nav button types into an input. */
                      aria-label={`${label} — prefills the message box with “${prompt.trim()}”`}
                      className="touch-manipulation inline-flex items-center gap-2 rounded-full border border-white/8 bg-[#141415] px-4 py-2.5 text-xs text-gray-300 transition hover:border-white/15 hover:bg-white/[0.045] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
                    >
                      <Icon size={15} className="text-accent" aria-hidden="true" />
                      {label}
                    </button>
                  ))}
                </nav>
              </div>
            </div>
          )}
          {msgs.map((m, i) => (
            <div
              key={i}
              ref={i === msgs.length - 1 && m.role === "assistant" ? answerStartRef : undefined}
            >
              <MessageBubble
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
                onEditMedia={editMedia}
                onDeleteMedia={deleteMedia}
                onEditUser={
                  !busy && m.role === "user" && m.id
                    ? (text) => void editMessage(i, text)
                    : undefined
                }
              />
            </div>
          ))}
        </div>
      </div>
      {!emptyHome && (
        <>
          {suggestions.length > 0 && !busy && (
            <div className="shrink-0 border-t border-white/5 bg-[#0f0f10]/80 px-3 py-2 sm:px-4">
              <nav
                className="mx-auto flex max-w-3xl flex-wrap items-center justify-center gap-2 xl:max-w-4xl"
                aria-label="Suggested follow-ups"
              >
                {suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => void send(s, true)}
                    className="touch-manipulation inline-flex max-w-full items-center rounded-full border border-white/8 bg-[#141415] px-3.5 py-1.5 text-xs text-gray-300 transition hover:border-white/15 hover:bg-white/[0.045] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
                  >
                    <span className="truncate">{s}</span>
                  </button>
                ))}
              </nav>
            </div>
          )}
          {pickerEl(false)}
          {composerEl(false)}
        </>
      )}
      {canvas && (
        <div className="pointer-events-none absolute inset-y-0 right-0 z-30 flex max-w-full">
          <div className="pointer-events-auto h-full w-[min(28rem,100vw)] shadow-[-24px_0_48px_rgb(0_0_0/0.35)]">
            <CanvasPanel
              open
              title={canvas.title}
              content={canvas.content}
              onClose={() => setCanvas(null)}
              onUse={(text) => {
                setDraft({ text, nonce: Date.now() });
                setCanvas(null);
              }}
            />
          </div>
        </div>
      )}
    </AppShell>
  );
}
