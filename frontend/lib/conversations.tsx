"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { apiFetch, token } from "./api";

export interface ConvItem {
  id: string;
  title: string;
  pinned?: boolean;
  updated_at?: string | null;
}

/** Legacy key retained for integrations that still clear the previous selection. */
export const LAST_CONV_KEY = "mood.lastConvId";
/** One-shot target used when a library surface explicitly opens a chat. */
export const OPEN_CONV_KEY = "mood.openConvId";

interface CtxType {
  convs: ConvItem[];
  activeId: string | null;
  setActiveId: (id: string | null) => void;
  refresh: () => Promise<void>;
  remove: (id: string) => Promise<void>;
  pin: (id: string, pinned: boolean) => Promise<void>;
}

const Ctx = createContext<CtxType | null>(null);

export function useConversations(): CtxType {
  const c = useContext(Ctx);
  if (!c) throw new Error("useConversations must be used inside ConversationsProvider");
  return c;
}

export function ConversationsProvider({ children }: { children: React.ReactNode }) {
  const [convs, setConvs] = useState<ConvItem[]>([]);
  const [activeIdState, setActiveIdState] = useState<string | null>(null);
  const pathname = usePathname();

  // Selecting a conversation remembers it across reloads; clearing (new chat) forgets it
  const setActiveId = useCallback((id: string | null) => {
    setActiveIdState(id);
    try {
      if (id) localStorage.setItem(LAST_CONV_KEY, id);
      else localStorage.removeItem(LAST_CONV_KEY);
    } catch {
      /* storage unavailable */
    }
  }, []);
  const activeId = activeIdState;

  const refresh = useCallback(async () => {
    if (!token.get()) return;
    try {
      setConvs(await apiFetch<ConvItem[]>("/conversations"));
    } catch {
      /* not logged in yet / api down */
    }
  }, []);

  // Refetch on every route change so the list is fresh after login/navigation
  useEffect(() => {
    void refresh();
  }, [refresh, pathname]);

  // The Chat destination is always a clean new-chat surface. History items
  // select activeId directly, while other surfaces can explicitly clear it
  // before routing to /chat.
  useEffect(() => {
    const h = () => setActiveId(null);
    window.addEventListener("mood:new-chat", h);
    return () => window.removeEventListener("mood:new-chat", h);
  }, [setActiveId]);

  // Any feature can ping "conversations changed" (idle home-reset, share/join
  // flows, background jobs) → debounced refresh so ☰ history is always current
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | null = null;
    const h = () => {
      if (t) clearTimeout(t);
      t = setTimeout(() => void refresh(), 400);
    };
    window.addEventListener("mood:conversations-changed", h);
    return () => window.removeEventListener("mood:conversations-changed", h);
  }, [refresh]);

  // Keep chat history feeling live while the app is open.
  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.hidden) return;
      void refresh();
    }, 20000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const pin = useCallback(async (id: string, pinned: boolean) => {
    setConvs((c) => {
      const next = c.map((x) => (x.id === id ? { ...x, pinned } : x));
      return next.sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)));
    });
    try {
      await apiFetch(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify({ pinned }) });
    } catch {
      void refresh();
    }
  }, [refresh]);

  const remove = useCallback(async (id: string) => {
    setConvs((c) => c.filter((x) => x.id !== id));
    setActiveIdState((curr) => {
      const next = curr === id ? null : curr;
      try {
        if (next) localStorage.setItem(LAST_CONV_KEY, next);
        else localStorage.removeItem(LAST_CONV_KEY);
      } catch {
        /* storage unavailable */
      }
      return next;
    });
    try {
      await apiFetch(`/conversations/${id}`, { method: "DELETE" });
    } catch {
      /* ignore */
    }
  }, []);

  return (
    <Ctx.Provider value={{ convs, activeId, setActiveId, refresh, remove, pin }}>{children}</Ctx.Provider>
  );
}
