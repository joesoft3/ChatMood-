export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

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

    // If path is now a relative API path, build absolute from API
    if (path.startsWith("/api/v1/")) {
      // API is like https://host/api/v1  -> origin = https://host
      try {
        const apiUrl = new URL(API);
        return `${apiUrl.origin}${path}`;
      } catch {
        // API may be relative? Fallback to current origin + path
        if (typeof window !== "undefined") {
          return `${window.location.origin}${path}`;
        }
        return path;
      }
    }

    // Otherwise try to parse as absolute URL
    const u = new URL(raw, typeof window !== "undefined" ? window.location.origin : "http://localhost:3000");

    // If localhost -> rebuild from API
    if (u.hostname === "localhost" || u.hostname === "127.0.0.1") {
      const m = raw.match(/\/reels\/files\/([^/?]+)/) || raw.match(/\/media\/files\/([^/?]+)/);
      const fname = m ? m[1] : null;
      if (fname) {
        try {
          const apiUrl = new URL(API);
          const isReel = raw.includes("/reels/files/");
          return `${apiUrl.origin}/api/v1/${isReel ? "reels" : "media"}/files/${fname}`;
        } catch {
          return raw;
        }
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

export const token = {
  get(): string | null {
    return typeof window === "undefined" ? null : localStorage.getItem("mood_token");
  },
  set(t: string) {
    localStorage.setItem("mood_token", t);
  },
  clear() {
    localStorage.removeItem("mood_token");
  },
};

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
  const tk = token.get();
  if (tk) headers["Authorization"] = `Bearer ${tk}`;
  const ph = pageHost();
  if (ph) headers["X-Mood-Host"] = ph;
  const res = await guardedFetch(`${API}${path}`, { ...opts, headers });
  if (!res.ok) throw new Error(await errorMessage(res));
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : (res.blob() as any)) as Promise<T>;
}
