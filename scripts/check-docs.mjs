#!/usr/bin/env node
// ─────────────────────────────────────────────────────────────────────────────
// ChatMood — documentation housekeeping gate.
//
// Fast, dependency-free, offline. Run from anywhere:  node scripts/check-docs.mjs
//
// Checks:
//   1. Relative markdown links resolve to a file that exists on disk.
//   2. In-page anchors (#heading) exist in the target document.
//   3. Every docs/*.md is reachable from docs/README.md (no orphaned guides).
//   4. Every docs/*.md opens with a level-1 heading (used to build the index).
//
// Exits non-zero with a grouped report when anything is off. External http(s)
// links are deliberately NOT fetched — CI stays hermetic and never flakes on a
// third-party outage.
// ─────────────────────────────────────────────────────────────────────────────
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { join, dirname, relative, resolve, posix } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SKIP_DIRS = new Set([
  "node_modules", ".git", ".next", "build", "dist", ".venv",
  "__pycache__", ".dart_tool", "out", "coverage",
]);

/** Recursively collect tracked-ish markdown files. */
function markdownFiles(dir = ROOT, acc = []) {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue;
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) markdownFiles(full, acc);
    else if (entry.endsWith(".md")) acc.push(full);
  }
  return acc;
}

/** GitHub-flavoured heading -> anchor slug. */
function slug(heading) {
  return heading
    .trim()
    .toLowerCase()
    .replace(/[^\w\- \u00c0-\uffff]/g, "") // drop punctuation & emoji-adjacent marks
    .trim()
    .replace(/\s+/g, "-");
}

const anchorCache = new Map();
function anchorsOf(file) {
  if (anchorCache.has(file)) return anchorCache.get(file);
  const set = new Set();
  if (existsSync(file)) {
    let inFence = false;
    for (const line of readFileSync(file, "utf8").split("\n")) {
      if (/^\s*```/.test(line)) { inFence = !inFence; continue; }
      if (inFence) continue;
      const m = /^(#{1,6})\s+(.*?)\s*$/.exec(line);
      if (m) set.add(slug(m[2]));
      const named = /<a\s+(?:id|name)=["']([^"']+)["']/gi;
      let a;
      while ((a = named.exec(line))) set.add(a[1].toLowerCase());
    }
  }
  anchorCache.set(file, set);
  return set;
}

/** Strip fenced + inline code so links inside snippets are ignored. */
function stripCode(src) {
  return src.replace(/```[\s\S]*?```/g, "").replace(/`[^`\n]*`/g, "");
}

const files = markdownFiles().sort();
const problems = [];
const add = (file, msg) => problems.push({ file: relative(ROOT, file), msg });

// ── 1 & 2: link + anchor integrity ──────────────────────────────────────────
const linkRe = /\[[^\]]*\]\(\s*([^)\s]+)(?:\s+"[^"]*")?\s*\)/g;

for (const file of files) {
  const body = stripCode(readFileSync(file, "utf8"));
  let m;
  while ((m = linkRe.exec(body))) {
    const raw = m[1].trim();
    if (/^(https?:|mailto:|tel:|data:|\/\/)/i.test(raw)) continue;

    const [pathPart, anchor] = raw.split("#");

    if (!pathPart) {
      if (anchor && !anchorsOf(file).has(anchor.toLowerCase())) {
        add(file, `anchor "#${anchor}" not found in this document`);
      }
      continue;
    }

    const target = raw.startsWith("/")
      ? join(ROOT, pathPart)
      : resolve(dirname(file), decodeURIComponent(pathPart));

    if (!existsSync(target)) {
      add(file, `link target missing: ${raw}`);
      continue;
    }
    if (anchor && target.endsWith(".md") && !anchorsOf(target).has(anchor.toLowerCase())) {
      add(file, `anchor "#${anchor}" not found in ${posix.normalize(pathPart)}`);
    }
  }
}

// ── 3 & 4: docs/ index coverage + H1 presence ───────────────────────────────
const docsDir = join(ROOT, "docs");
const indexFile = join(docsDir, "README.md");

if (!existsSync(indexFile)) {
  problems.push({ file: "docs/README.md", msg: "docs index is missing" });
} else {
  const index = readFileSync(indexFile, "utf8");
  const guides = readdirSync(docsDir)
    .filter((f) => f.endsWith(".md") && f !== "README.md")
    .sort();

  for (const guide of guides) {
    if (!index.includes(`(${guide})`) && !index.includes(`(./${guide})`)) {
      problems.push({ file: "docs/README.md", msg: `guide not listed in the index: ${guide}` });
    }
    const first = readFileSync(join(docsDir, guide), "utf8")
      .split("\n")
      .find((l) => l.trim().length > 0);
    if (!first || !first.startsWith("# ")) {
      problems.push({ file: `docs/${guide}`, msg: "missing a level-1 (# ) title on the first line" });
    }
  }
}

// ── report ──────────────────────────────────────────────────────────────────
if (problems.length === 0) {
  console.log(`✅ docs check passed — ${files.length} markdown files, 0 problems`);
  process.exit(0);
}

console.error(`❌ docs check failed — ${problems.length} problem(s)\n`);
const byFile = new Map();
for (const p of problems) {
  if (!byFile.has(p.file)) byFile.set(p.file, []);
  byFile.get(p.file).push(p.msg);
}
for (const [file, msgs] of [...byFile].sort()) {
  console.error(`  ${file}`);
  for (const msg of msgs) console.error(`    · ${msg}`);
}
console.error("");
process.exit(1);
