/** Safe in-app path for post-auth redirects. Rejects protocol-relative and off-site URLs. */
export function safeNextPath(raw: string | null | undefined): string | null {
  if (!raw) return null;
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.includes("\\")) return null;
  return raw;
}

export function signInHref(next?: string | null): string {
  const n = safeNextPath(next);
  return n ? `/login?next=${encodeURIComponent(n)}` : "/login";
}

export function signUpHref(next?: string | null): string {
  const n = safeNextPath(next);
  return n ? `/signup?next=${encodeURIComponent(n)}` : "/signup";
}

/** Current page as a `next=` target (used when the app shell bounces a guest). */
export function currentNextPath(): string | null {
  if (typeof window === "undefined") return null;
  const here = `${window.location.pathname}${window.location.search}`;
  if (
    here.startsWith("/login") ||
    here.startsWith("/signup") ||
    here.startsWith("/signin")
  ) {
    return null;
  }
  return safeNextPath(here);
}
