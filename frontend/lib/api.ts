import { API, apiOrigin } from "./apiBase";

export { API };

/**
 * Resolve a media URL that may be:
 * - old absolute BACKEND_PUBLIC_URL (http://localhost:8000/api/v1/...) -> rebuild from API
 * - new relative /api/v1/... -> make absolute from API origin
 * - already absolute correct host -> keep but force https if page is https (mixed-content fix)
 */
export function resolveMediaUrl(raw: string): string {
  if (!raw) return "";
  try {
    // If it's already a blob: URL, keep it
    if (raw.startsWith("blob:") || raw.startsWith("data:")) return raw;

    // Extract the /api/v1/... part if present
    let path = raw;
    if (raw.includes("/api/v1/")) {
      const idx = raw.indexOf("/api/v1/");
      path = raw.slice(idx); // e.g. /api/v1/reels/files/xxx
    }

    // If path is now a relative API path, hang it off the API origin. With a
    // same-origin (proxied) API that origin IS the page origin, so the result
    // stays same-origin and never points at the visitor's own machine.
    if (path.startsWith("/api/v1/")) {
      return `${apiOrigin()}${path}`;
    }

    // Otherwise try to parse as absolute URL
    const u = new URL(raw, typeof window !== "undefined" ? window.location.origin : "http://localhost:3000");

    // If localhost -> rebuild from API
    if (u.hostname === "localhost" || u.hostname === "127.0.0.1") {
      const m = raw.match(/\/reels\/files\/([^/?]+)/) || raw.match(/\/media\/files\/([^/?]+)/);
      const fname = m ? m[1] : null;
      if (fname) {
        const isReel = raw.includes("/reels/files/");
        return `${apiOrigin()}/api/v1/${isReel ? "reels" : "media"}/files/${fname}`;
      }
    }

    // Mixed-content fix: if page is https and url is http, upgrade to https
    if (typeof window !== "undefined" && window.location.protocol === "https:" && u.protocol === "http:") {
      u.protocol = "https:";
      return u.toString();
    }

    return raw;
  } catch {
    return raw;
  }
}

const TOKEN_KEY = "mood_token";
const AUTH_ANON = /^\/auth\/(login|register|clerk)$/;

/** JWTs are three base64url segments. Garbage leftovers (and the literal
 *  string "undefined" from a botched login) must not count as signed-in —
 *  that was the "always Invalid or expired token" loop: login saw a truthy
 *  localStorage value and bounced straight back to /chat. */
function looksLikeJwt(raw: string): boolean {
  const parts = raw.split(".");
  return parts.length === 3 && parts.every((p) => p.length > 0);
}

export const token = {
  get(): string | null {
    if (typeof window === "undefined") return null;
    try {
      const raw = (localStorage.getItem(TOKEN_KEY) ?? "").trim();
      if (!raw || raw === "undefined" || raw === "null" || !looksLikeJwt(raw)) {
        if (raw) localStorage.removeItem(TOKEN_KEY);
        return null;
      }
      return raw;
    } catch {
      return null;
    }
  },
  set(t: string) {
    const value = (t ?? "").trim();
    if (!value || !looksLikeJwt(value)) {
      token.clear();
      return;
    }
    localStorage.setItem(TOKEN_KEY, value);
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable */
    }
  },
};

function isPublicPath(pathname: string): boolean {
  return (
    pathname === "/" ||
    pathname.startsWith("/login") ||
    pathname.startsWith("/signup") ||
    pathname.startsWith("/signin") ||
    pathname.startsWith("/privacy") ||
    pathname.startsWith("/terms") ||
    pathname.startsWith("/shared") ||
    pathname.startsWith("/order") ||
    pathname.startsWith("/account-deletion") ||
    pathname.startsWith("/f/")
  );
}

let bouncingToLogin = false;

/** Drop a dead session and send the user to sign-in (app pages only). */
export function forgetSession(reason: "expired" | "missing" = "expired"): void {
  token.clear();
  if (typeof window === "undefined" || bouncingToLogin) return;
  const path = window.location.pathname;
  if (isPublicPath(path)) return;
  bouncingToLogin = true;
  const next = `${path}${window.location.search}`;
  const q = new URLSearchParams();
  if (reason === "expired") q.set("expired", "1");
  if (next.startsWith("/") && !next.startsWith("//")) q.set("next", next);
  window.location.assign(`/login?${q.toString()}`);
}

/** True when the stored JWT still authenticates against this backend. */
export async function verifySession(): Promise<boolean> {
  if (!token.get()) return false;
  try {
    await apiFetch("/auth/me");
    return Boolean(token.get());
  } catch {
    return Boolean(token.get());
  }
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const j = await res.json();
    return typeof j.detail === "string" ? j.detail : JSON.stringify(j);
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

/** Host of the page the user is on — lets the backend attribute per-domain analytics
 *  (the API itself is always reached on the platform's own host). */
function pageHost(): string | null {
  return typeof window === "undefined" ? null : window.location.host;
}

/** Raw browser fetch errors ("Failed to fetch") read unprofessionally — translate.
 * Safe reads get two short retries because the Fly app can briefly wake from idle.
 * Mutating requests are never replayed here; callers can decide whether retrying
 * their particular operation is safe.
 */
async function guardedFetch(input: string, init: RequestInit): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const retryable = method === "GET" || method === "HEAD" || method === "OPTIONS";
  let lastError: unknown;
  const attempts = retryable ? 3 : 1;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await fetch(input, init);
    } catch (e) {
      if (!(e instanceof TypeError)) throw e;
      lastError = e;
      if (attempt + 1 < attempts) {
        await new Promise((resolve) => window.setTimeout(resolve, 500 * (attempt + 1)));
      }
    }
  }

  if (lastError instanceof TypeError) {
    throw new Error("Can't reach the ChatMood server — it may be starting up or your connection dropped. Try again in a few seconds.");
  }
  throw lastError;
}

export async function apiFetch<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...((opts.headers as Record<string, string>) || {}) };
  if (!(opts.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  // Login/register must not send a leftover (possibly dead) Bearer token.
  const tk = AUTH_ANON.test(path) ? null : token.get();
  if (tk) headers["Authorization"] = `Bearer ${tk}`;
  const ph = pageHost();
  if (ph) headers["X-Mood-Host"] = ph;
  const res = await guardedFetch(`${API}${path}`, { ...opts, headers });
  if (!res.ok) {
    const msg = await errorMessage(res);
    if (tk && res.status === 401) {
      forgetSession("expired");
    }
    throw new Error(msg);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : (res.blob() as any)) as Promise<T>;
}
