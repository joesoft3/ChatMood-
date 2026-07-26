import { API, token } from "@/lib/api";

/**
 * Download a file the browser can't just link to.
 *
 * `<a download>` only works for same-origin URLs, and our stable download route
 * (`/files/{id}/download`) lives on the API origin behind a Bearer token — so a
 * plain anchor either 401s or, cross-origin, silently *navigates* instead of
 * saving. Fetching to a Blob and clicking a synthetic anchor is what makes
 * "Download" actually put a file on disk, with the right filename.
 *
 * Falls back to opening the URL in a new tab if the fetch fails (e.g. an
 * expired provider hotlink), because a new tab the user can right-click beats a
 * button that appears to do nothing.
 */
export async function downloadFile(fileId: string, filename?: string): Promise<void> {
  const tk = token.get();
  const url = `${API}/files/${fileId}/download`;
  try {
    const res = await fetch(url, {
      headers: tk ? { Authorization: `Bearer ${tk}` } : {},
      // the route 307s to a presigned R2 link; follow it
      redirect: "follow",
    });
    if (!res.ok) throw new Error(`${res.status}`);
    const blob = await res.blob();
    saveBlob(blob, filename || filenameFromResponse(res) || "chatmood-download");
  } catch {
    window.open(url, "_blank", "noopener");
  }
}

/** Download something we only have a plain URL for (provider hotlinks). */
export async function downloadUrl(url: string, filename: string): Promise<void> {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${res.status}`);
    saveBlob(await res.blob(), filename);
  } catch {
    // Cross-origin fetch can be blocked by CORS — a new tab still lets the
    // user save it manually, which is strictly better than nothing happening.
    window.open(url, "_blank", "noopener");
  }
}

function filenameFromResponse(res: Response): string {
  const cd = res.headers.get("content-disposition") || "";
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  return m ? decodeURIComponent(m[1]) : "";
}

function saveBlob(blob: Blob, filename: string): void {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke late: Safari cancels an in-flight download if the URL dies too soon.
  window.setTimeout(() => URL.revokeObjectURL(href), 10_000);
}

/** A sensible filename from the prompt: "a red kite at dusk" → chatmood-a-red-kite-at-dusk.png */
export function mediaFilename(prompt: string | undefined, kind: "image" | "video"): string {
  const slug = (prompt || kind)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48) || kind;
  return `chatmood-${slug}.${kind === "image" ? "png" : "mp4"}`;
}
