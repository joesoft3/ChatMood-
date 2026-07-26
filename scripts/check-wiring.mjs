#!/usr/bin/env node
/**
 * 🔌 Wiring gate — every button must lead somewhere real.
 *
 *   node scripts/check-wiring.mjs [--routes /tmp/routes.json]
 *
 * A dead button is the most embarrassing class of bug: it looks finished, ships,
 * and fails in front of a user (or a Play Store reviewer). This checks the three
 * ways a control can be dead, offline and with no dependencies:
 *
 *   1. **API path doesn't exist.** Every `apiFetch("/x")` in the frontend is
 *      matched against the FastAPI route table (exported from the OpenAPI spec),
 *      with `{param}` segments normalized so `/tasks/${id}` matches `/tasks/{tid}`.
 *   2. **Internal link 404s.** Every `href="/x"` must correspond to a real
 *      Next.js route under `app/`, including dynamic `[slug]` segments.
 *   3. **Button does nothing.** A `<button>` with no `onClick`, `type="submit"`,
 *      `form=`, or `disabled` is almost certainly unfinished.
 *
 * Exits non-zero on any finding, so CI can gate on it.
 */

import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname.replace(/\/$/, "");
const FRONTEND = join(ROOT, "frontend");
const APP_DIR = join(FRONTEND, "app");

const args = process.argv.slice(2);
const routesFlag = args.indexOf("--routes");
const ROUTES_FILE = routesFlag >= 0 ? args[routesFlag + 1] : join(ROOT, ".routes.json");

const problems = [];
const notes = [];

/* ─────────────────────────────────────────────── file walking */

function walk(dir, out = []) {
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === ".next" || entry.startsWith(".")) continue;
    const p = join(dir, entry);
    const st = statSync(p);
    if (st.isDirectory()) walk(p, out);
    else if (/\.(tsx|ts)$/.test(p)) out.push(p);
  }
  return out;
}

const files = [
  ...walk(APP_DIR),
  ...walk(join(FRONTEND, "components")),
  ...walk(join(FRONTEND, "lib")),
];

/* ────────────────────────────────── 1. API paths vs backend routes */

/** Does a normalized call path correspond to a real backend route?
 *
 *  A `{}` in the CALL is a runtime value: it may fill a route parameter
 *  (`/tasks/{}` → `/tasks/{tid}`) or stand in for a literal segment the code
 *  chooses at runtime (`/admin/payments/{}/{}` → `.../{pid}/approve`). A `{}`
 *  in the ROUTE is a path parameter and matches any single call segment.
 *  Trailing `{}` are also allowed to be an appended querystring. */
function matchesRoute(callPath, routes) {
  if (routes.has(callPath)) return true;
  // Drop trailing interpolations that are really a querystring: `/reels{}{}...`
  const trimmed = callPath.replace(/(\{\}|[^/])*$/, "");
  const callSegs = callPath.split("/").filter(Boolean);
  for (const route of routes) {
    const routeSegs = route.split("/").filter(Boolean);
    if (routeSegs.length !== callSegs.length) continue;
    const same = routeSegs.every(
      (rs, i) => rs === callSegs[i] || rs === "{}" || callSegs[i] === "{}",
    );
    if (same) return true;
  }
  // `/reels${query}` → the base collection route.
  const base = callPath.replace(/\{\}.*$/, "").replace(/\/$/, "");
  return Boolean(base) && routes.has(base) && trimmed !== undefined;
}

/** Expand `${x ? "a" : "b"}` and `${'"'"'a'"'"'}`-style literal choices into concrete paths.
 *  Union types like `useState<"login"|"register">` reach us as a bare `${mode}`,
 *  which we cannot resolve statically — those stay as `{}` and match a path
 *  parameter, which is the correct conservative behavior. */
function expandLiteralChoices(str) {
  const ternary = /\$\{[^{}]*\?\s*["'"'"']([^"'"'"']+)["'"'"']\s*:\s*["'"'"']([^"'"'"']+)["'"'"']\s*\}/;
  const m = str.match(ternary);
  if (!m) return [str];
  return [
    ...expandLiteralChoices(str.replace(ternary, m[1])),
    ...expandLiteralChoices(str.replace(ternary, m[2])),
  ];
}

/** Replace every `${...}` (including nested braces / ternaries) with `{}`. */
function stripInterpolations(str) {
  let out = "";
  for (let i = 0; i < str.length; i += 1) {
    if (str[i] === "$" && str[i + 1] === "{") {
      let depth = 1;
      i += 2;
      while (i < str.length && depth > 0) {
        if (str[i] === "{") depth += 1;
        else if (str[i] === "}") depth -= 1;
        i += 1;
      }
      i -= 1;
      out += "{}";
    } else {
      out += str[i];
    }
  }
  return out;
}

/** `/api/v1/tasks/{tid}` → `/tasks/{}` so params compare structurally. */
function normalize(path) {
  return path
    .replace(/^\/api\/v1/, "")
    .replace(/\{[^}]+\}/g, "{}")
    .replace(/\$\{[^}]*\}/g, "{}")
    .replace(/\/+$/, "");
}

let backendRoutes = null;
if (existsSync(ROUTES_FILE)) {
  backendRoutes = new Set(JSON.parse(readFileSync(ROUTES_FILE, "utf8")).map(normalize));
} else {
  notes.push(
    `route table not found at ${relative(ROOT, ROUTES_FILE)} — API checks skipped ` +
      `(generate it from the FastAPI app; see the header of this script)`,
  );
}

// Matches apiFetch("/x"), apiFetch<T>(`/x/${id}`), and the streamTo/fetch helpers.
const API_CALL =
  /(?:apiFetch|streamTo|streamChat)\s*(?:<[^>]*>)?\s*\(\s*(?:`((?:[^`\\]|\\.)*)`|"([^"]*)"|'([^']*)')/g;

if (backendRoutes) {
  for (const file of files) {
    const src = readFileSync(file, "utf8");
    for (const m of src.matchAll(API_CALL)) {
      let path = m[1] ?? m[2] ?? m[3] ?? "";
      if (!path.startsWith("/")) continue;
      // `${...}` interpolations are runtime values. They may stand for a whole
      // path segment (`/tasks/${id}`), a trailing querystring (`/reels${query}`),
      // or a mid-segment fragment (`/x/${a}/${b ? "y" : "z"}`). Collapse each to
      // a single `{}` segment and compare structurally — anything else would
      // flag every dynamic call in the codebase as broken.
      const raw = path;
      // A `${cond ? "a" : "b"}` picks between literal segments — expand it so
      // /auth/${mode} is verified as BOTH /auth/login and /auth/register rather
      // than dismissed as dynamic.
      const candidates = expandLiteralChoices(path).map((c) =>
        normalize(stripInterpolations(c).split("?")[0]),
      );
      const ok = candidates.some((norm) => matchesRoute(norm, backendRoutes));
      if (ok) continue;
      problems.push(
        `${relative(ROOT, file)}: API call to "${raw}" has no backend route ` +
          `(tried ${candidates.join(", ")})`,
      );
    }
  }
}

/* ─────────────────────────────────── 2. internal links vs app routes */

function pageRoutes(dir, prefix = "", out = new Set()) {
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir)) {
    if (entry.startsWith("_") || entry === "node_modules") continue;
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) {
      const seg = entry.startsWith("(") ? "" : `/${entry}`;
      pageRoutes(p, prefix + seg, out);
    } else if (/^page\.(tsx|ts|jsx|js)$/.test(entry)) {
      out.add(prefix || "/");
    }
  }
  return out;
}

const routes = pageRoutes(APP_DIR);
// `[token]` → `{}` so /shared/abc matches /shared/[token]
const routePatterns = [...routes].map((r) => r.replace(/\[[^\]]+\]/g, "{}"));

const HREF = /href=\{?["'`](\/[^"'`{}\s]*)["'`]/g;

for (const file of files) {
  const src = readFileSync(file, "utf8");
  for (const m of src.matchAll(HREF)) {
    const href = m[1].split("?")[0].split("#")[0].replace(/\/$/, "") || "/";
    // Static assets and API endpoints aren't page routes.
    if (/\.(png|jpg|jpeg|svg|webmanifest|ico|mp4|txt|xml|webp)$/.test(href)) continue;
    if (href.startsWith("/api/")) continue;
    const norm = href.replace(/\/[a-z0-9-]{6,}$/i, "/{}");
    if (routePatterns.includes(href) || routePatterns.includes(norm)) continue;
    problems.push(`${relative(ROOT, file)}: link to "${href}" has no page route`);
  }
}

/* ────────────────────────────────────────── 3. inert buttons */

for (const file of files) {
  const src = readFileSync(file, "utf8");
  // Opening <button ...> tags, including multi-line attribute blocks.
  for (const m of src.matchAll(/<button\b([^>]*)>/gs)) {
    const attrs = m[1];
    const wired =
      /onClick|onPointerDown|onMouseDown|type=["'{]?submit|form=|disabled/.test(attrs);
    if (!wired) {
      const line = src.slice(0, m.index).split("\n").length;
      problems.push(`${relative(ROOT, file)}:${line}: <button> has no onClick/submit handler`);
    }
  }
}

/* ─────────────────────────────────────────────────── report */

for (const n of notes) console.log(`⚠️  ${n}`);
if (problems.length) {
  console.error(`\n❌ wiring check failed — ${problems.length} problem(s):\n`);
  for (const p of problems) console.error("   " + p);
  process.exit(1);
}
console.log(
  `✅ wiring check passed — ${files.length} files · ${routes.size} page routes` +
    (backendRoutes ? ` · ${backendRoutes.size} API routes` : ""),
);
