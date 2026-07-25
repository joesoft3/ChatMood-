"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Paperclip, SendHorizontal, Square, X } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { streamChat } from "@/lib/stream";
import { useConversations } from "@/lib/conversations";
import { token } from "@/lib/api";

interface AssistantFile {
  id: string;
  filename: string;
  mime: string;
}

interface AssistantMessage {
  role: "user" | "assistant";
  content: string;
}

export default function AssistantPage() {
  const router = useRouter();
  const { refresh } = useConversations();
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [files, setFiles] = useState<AssistantFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const answerRef = useRef<HTMLDivElement>(null);
  const previousCount = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!token.get()) router.replace("/login");
  }, [router]);

  // New answers start at their first line and grow downward while streaming.
  useEffect(() => {
    if (messages.length > previousCount.current && messages[messages.length - 1]?.role === "assistant") {
      answerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    previousCount.current = messages.length;
  }, [messages.length]);

  function growInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setError("");
    setInput(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = `${Math.min(e.target.scrollHeight, 180)}px`;
  }

  async function upload(file: File) {
    setError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const saved = await apiFetch<AssistantFile>("/files", { method: "POST", body: fd });
      setFiles((current) => [...current, saved]);
    } catch (e: any) {
      setError(e.message ?? "File upload failed");
    }
  }

  async function send() {
    if (busy || (!input.trim() && files.length === 0)) return;
    const text = input.trim();
    const outgoingFiles = files.map((file) => file.id);
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setError("");
    setInput("");
    setFiles([]);
    if (inputRef.current) inputRef.current.style.height = "auto";
    setMessages((current) => [
      ...current,
      { role: "user", content: text || "Attached file" },
      { role: "assistant", content: "" },
    ]);

    try {
      await streamChat(
        {
          conversation_id: conversationId,
          message: text,
          files: outgoingFiles,
          search: false,
          model: "auto",
        },
        (event) => {
          if (event.type === "meta" && event.conversation_id) {
            setConversationId(event.conversation_id);
          }
          if (event.type === "delta" && event.text) {
            setMessages((current) => {
              const next = [...current];
              next[next.length - 1] = { ...next[next.length - 1], content: next[next.length - 1].content + event.text };
              return next;
            });
          }
          if (event.type === "error") {
            const message = event.message ?? "Mood AI could not answer right now.";
            setError(message);
            setMessages((current) => {
              const next = [...current];
              next[next.length - 1] = { ...next[next.length - 1], content: `⚠️ ${message}` };
              return next;
            });
          }
        },
        "/chat/stream",
        controller.signal
      );
      await refresh();
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        const message = e.message ?? "Mood AI could not answer right now.";
        setError(message);
        setMessages((current) => {
          const next = [...current];
          next[next.length - 1] = { ...next[next.length - 1], content: `⚠️ ${message}` };
          return next;
        });
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  return (
    <main className="h-[100dvh] overflow-hidden bg-base text-gray-100">
      <div className="mx-auto flex h-full w-full max-w-3xl flex-col px-4">
        <div className="flex shrink-0 flex-col items-center gap-2 py-6 sm:py-8">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/icon.png"
            alt="Mood AI Assistant"
            className="h-12 w-12 rounded-2xl ring-1 ring-line shadow-[0_0_48px_-14px_rgb(var(--mood-accent)/0.7)]"
          />
          <h1 className="text-center text-lg font-semibold tracking-tight text-gray-100">Mood AI Assistant</h1>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin pb-6">
          <div className="space-y-5 py-4">
            {messages.length === 0 ? (
              <div className="flex min-h-[35vh] items-center justify-center text-center text-sm text-gray-500">
                Ask Mood AI Assistant anything.
              </div>
            ) : (
              messages.map((message, index) => (
                <div
                  key={index}
                  ref={index === messages.length - 1 && message.role === "assistant" ? answerRef : undefined}
                  className={message.role === "user" ? "flex justify-end" : "flex justify-start"}
                >
                  <div
                    className={
                      message.role === "user"
                        ? "max-w-[88%] rounded-3xl bg-accent/15 px-4 py-3 text-sm text-gray-100"
                        : "max-w-[92%] rounded-3xl bg-panel px-4 py-3 text-[15px] leading-7 text-gray-100"
                    }
                  >
                    {message.role === "assistant" && !message.content ? (
                      <span className="text-gray-500">…</span>
                    ) : message.role === "assistant" ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                    ) : (
                      message.content
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="shrink-0 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3">
          {error && <p className="mb-2 px-2 text-xs text-red-300">{error}</p>}
          {files.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2 px-1">
              {files.map((file) => (
                <span key={file.id} className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-line bg-panel px-3 py-1.5 text-xs text-gray-300">
                  <span className="max-w-[15rem] truncate">{file.filename}</span>
                  <button type="button" onClick={() => setFiles((current) => current.filter((item) => item.id !== file.id))} aria-label={`Remove ${file.filename}`}>
                    <X size={13} />
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="flex min-h-[4.5rem] items-center gap-1 rounded-[1.8rem] border border-line bg-panel px-2.5 py-2.5 shadow-[0_18px_40px_rgb(0_0_0/0.2)] focus-within:border-accent/60">
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.json,.png,.jpg,.jpeg,.webp,.gif"
              onChange={async (event) => {
                const file = event.target.files?.[0];
                if (file) await upload(file);
                event.target.value = "";
              }}
            />
            <button type="button" onClick={() => fileRef.current?.click()} className="composer-btn shrink-0 rounded-xl text-gray-400 hover:bg-white/5 hover:text-gray-100" aria-label="Choose a file">
              <Paperclip size={20} />
            </button>
            <textarea
              ref={inputRef}
              value={input}
              rows={1}
              onChange={growInput}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
              placeholder="Message Mood AI Assistant…"
              className="composer-input min-h-[3.25rem] min-w-0 flex-1 resize-none overflow-y-auto bg-transparent px-1 py-2.5 text-sm leading-6 outline-none"
            />
            <button
              type="button"
              onClick={busy ? stop : () => void send()}
              disabled={!busy && !input.trim() && files.length === 0}
              className="composer-btn shrink-0 rounded-2xl bg-accent text-black shadow-[0_8px_24px_rgb(var(--mood-accent)/0.3)] transition hover:brightness-110 disabled:opacity-30"
              aria-label={busy ? "Stop generating" : "Send message"}
            >
              {busy ? <Square size={18} /> : <SendHorizontal size={19} />}
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}
