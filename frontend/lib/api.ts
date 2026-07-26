const RAW_API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
export const API = RAW_API.replace(/\/+$/, "");

export const token = {
  get(): string | null {
    if (typeof window === "undefined") return null;
    try {
      return localStorage.getItem("mood_token");
    } catch {
      return null;
    }
  },
  set(t: string) {
    try {
      localStorage.setItem("mood_token", t);
    } catch {
      /* private mode / storage unavailable */
    }
  },
  clear() {
    try {
      localStorage.removeItem("mood_token");
    } catch {
      /* private mode / storage unavailable */
    }
  },
};

function toPlainHeaders(src?: HeadersInit): Record<string, string> {
  if (!src) return {};
  if (src instanceof Headers) return Object.fromEntries(src.entries());
  if (Array.isArray(src)) return Object.fromEntries(src);
  return { ...src };
}

function getHeader(headers: Record<string, string>, name: string): string | undefined {
  const key = Object.keys(headers).find((k) => k.toLowerCase() === name.toLowerCase());
  return key ? headers[key] : undefined;
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const j = await res.json();
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) {
      return j.detail
        .map((d: any) => {
          const loc = Array.isArray(d?.loc) ? d.loc.filter((x: string) => x !== "body").join(".") : "request";
          return d?.msg ? `${loc}: ${d.msg}` : JSON.stringify(d);
        })
        .join("; ");
    }
    if (typeof j.message === "string") return j.message;
    return JSON.stringify(j);
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

/** Host of the page the user is on — lets the backend attribute per-domain analytics
 *  (the API itself is always reached on the platform's own host). */
function pageHost(): string | null {
  return typeof window === "undefined" ? null : window.location.host;
}

export function handleAuthExpired(message = "Your session expired. Please sign in again.") {
  const hadToken = Boolean(token.get());
  token.clear();
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("mood:auth-expired", { detail: { message } }));
  if (!hadToken || window.location.pathname === "/login") return;
  const next = window.location.pathname + window.location.search;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

const sleep = (ms: number) => new Promise((resolve) => globalThis.setTimeout(resolve, ms));

/** Raw browser fetch errors ("Failed to fetch") read unprofessionally — translate.
 * Safe reads get two short retries because the Fly app can briefly wake from idle.
 * Mutating requests are never replayed here; callers can decide whether retrying
 * their particular operation is safe.
 */
async function guardedFetch(input: string, init: RequestInit): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const retryable = method === "GET" || method === "HEAD" || method === "OPTIONS";
  const attempts = retryable ? 3 : 1;
  let lastError: unknown;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const res = await fetch(input, init);
      if (retryable && attempt + 1 < attempts && [502, 503, 504].includes(res.status)) {
        await sleep(450 * (attempt + 1));
        continue;
      }
      return res;
    } catch (e) {
      if (!(e instanceof TypeError)) throw e;
      lastError = e;
      if (attempt + 1 < attempts) await sleep(450 * (attempt + 1));
    }
  }

  if (lastError instanceof TypeError) {
    throw new Error("Can't reach the Mood AI server — it may be starting up or your connection dropped. Try again in a few seconds.");
  }
  throw lastError;
}

export async function apiFetch<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers = toPlainHeaders(opts.headers);
  if (!(opts.body instanceof FormData) && !getHeader(headers, "Content-Type")) {
    headers["Content-Type"] = "application/json";
  }
  const tk = token.get();
  if (tk) headers["Authorization"] = `Bearer ${tk}`;
  const ph = pageHost();
  if (ph) headers["X-Mood-Host"] = ph;

  const res = await guardedFetch(`${API}${path.startsWith("/") ? path : `/${path}`}`, { ...opts, headers });
  if (res.status === 401) {
    const msg = await errorMessage(res);
    handleAuthExpired(msg || "Your session expired. Please sign in again.");
    throw new Error(msg || "Your session expired. Please sign in again.");
  }
  if (!res.ok) throw new Error(await errorMessage(res));
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : (res.blob() as any)) as Promise<T>;
}
