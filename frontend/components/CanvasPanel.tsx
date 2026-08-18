"use client";

import { useEffect, useState } from "react";
import { Copy, Download, PanelRightClose, Sparkles } from "lucide-react";
import { copyText } from "@/lib/clipboard";

/**
 * Grok-style Canvas — a side workspace for long-form answers and code.
 * Opens from an assistant bubble; the user can edit, copy, download, or
 * send the canvas back into the composer.
 */
export default function CanvasPanel({
  open,
  title,
  content,
  onClose,
  onUse,
}: {
  open: boolean;
  title: string;
  content: string;
  onClose: () => void;
  onUse: (text: string) => void;
}) {
  const [draft, setDraft] = useState(content);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (open) setDraft(content);
  }, [open, content]);

  if (!open) return null;

  async function copy() {
    const ok = await copyText(draft);
    setCopied(ok);
    window.setTimeout(() => setCopied(false), 1500);
  }

  function download() {
    const blob = new Blob([draft], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = (title || "chatmood-canvas").replace(/[^\w-]+/g, "-").slice(0, 48) + ".md";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <aside
      className="flex h-full min-h-0 w-full max-w-xl shrink-0 flex-col border-l border-white/8 bg-[#101112]"
      aria-label="Canvas"
    >
      <header className="flex items-center gap-2 border-b border-white/8 px-3 py-2.5">
        <Sparkles size={14} className="text-accent" />
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-gray-100">{title || "Canvas"}</h2>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1.5 text-gray-500 hover:bg-white/5 hover:text-white"
          aria-label="Close canvas"
        >
          <PanelRightClose size={16} />
        </button>
      </header>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="min-h-0 flex-1 resize-none bg-transparent px-4 py-3 font-mono text-[13px] leading-relaxed text-gray-200 outline-none"
        aria-label="Canvas editor"
      />
      <footer className="flex flex-wrap items-center gap-2 border-t border-white/8 px-3 py-2.5">
        <button
          type="button"
          onClick={() => void copy()}
          className="inline-flex items-center gap-1 rounded-lg border border-white/8 px-2.5 py-1.5 text-[11px] text-gray-300 hover:bg-white/5"
        >
          <Copy size={12} /> {copied ? "Copied" : "Copy"}
        </button>
        <button
          type="button"
          onClick={download}
          className="inline-flex items-center gap-1 rounded-lg border border-white/8 px-2.5 py-1.5 text-[11px] text-gray-300 hover:bg-white/5"
        >
          <Download size={12} /> Download
        </button>
        <button
          type="button"
          onClick={() => onUse(draft)}
          className="ml-auto inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1.5 text-[11px] font-semibold text-black hover:brightness-110"
        >
          Use in chat
        </button>
      </footer>
    </aside>
  );
}
