/**
 * 🌐 Single source of truth for "where is the API?".
 *
 * The old rule was `NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"`, and
 * that default is what turns a perfectly good deploy into a dead page: the
 * value is inlined into the **browser** bundle at build time, so every visitor
 * whose machine is not the dev box tries to call a server on *their own*
 * laptop. On an https host it is also blocked as mixed content before the
 * request is even attempted.
 *
 * New rule:
 *   1. `NEXT_PUBLIC_API_URL` set  → use it verbatim (unchanged behaviour for
 *      every existing Netlify/Vercel/Fly deployment that already sets it).
 *   2. not set                    → **same-origin** `/api/v1`. The browser then
 *      talks to the host it was served from, and `next.config.mjs` rewrites
 *      that path onto the real backend (`BACKEND_ORIGIN`, default
 *      http://localhost:8000). Works on localhost, on a sandbox preview URL,
 *      behind Caddy, and behind any reverse proxy — with zero rebuilds.
 *
 * Server-side rendering can't fetch a relative URL, so `serverApiBase()` walks
 * back up to an absolute origin for the few routes that fetch during SSR.
 */

const RAW = (process.env.NEXT_PUBLIC_API_URL ?? "").trim();

/** Base path/URL the browser should call. Relative ("/api/v1") when unconfigured. */
export const API = RAW ? RAW.replace(/\/+$/, "") : "/api/v1";

/** True when {@link API} is a same-origin path rather than an absolute URL. */
export const API_IS_RELATIVE = API.startsWith("/");

/**
 * Origin that serves the API (no trailing slash, no `/api/v1`).
 * Relative bases resolve against the page origin, which is exactly what a
 * proxied deployment wants. Returns "" during SSR of a relative base.
 */
export function apiOrigin(): string {
  if (!API_IS_RELATIVE) {
    try {
      return new URL(API).origin;
    } catch {
      return "";
    }
  }
  return typeof window === "undefined" ? "" : window.location.origin;
}

/** Absolute API base usable from Node during SSR (never relative). */
export function serverApiBase(): string {
  if (!API_IS_RELATIVE) return API;
  const origin = (
    process.env.BACKEND_ORIGIN ??
    process.env.INTERNAL_API_ORIGIN ??
    "http://localhost:8000"
  ).replace(/\/+$/, "");
  return `${origin}/api/v1`;
}

/** WebSocket base for the API (`ws(s)://…/api/v1`), correct on http and https. */
export function apiWsBase(): string {
  if (!API_IS_RELATIVE) return API.replace(/^http/, "ws");
  if (typeof window === "undefined") return API;
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}${API}`;
}
