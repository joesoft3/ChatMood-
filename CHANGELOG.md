# Changelog

All notable changes, fixes, and new features shipped to `main` for Mood AI.
Each entry links the pull request it landed in. Dates are UTC.

---

## 2026-07-26

### 🏷 Free-tier watermarking (Pro & admins render clean)

Generated output on the free plan now carries a subtle "Made with Mood AI" badge.
Paid plans and admins are unaffected. Guide: [docs/WATERMARKING.md](docs/WATERMARKING.md).

- **One entitlement rule, one place** (`services/watermark.should_watermark()`), because
  the two failure modes cost real money in opposite directions: a badge on a paying
  customer's export is a refund request, and a missing badge on free output is lost
  conversion. Paid detection is a **denylist of one** (`plan != "free"`) so any future
  tier is exempt by default — the safe direction to be wrong in. Admins
  (`is_admin` **or** an `ADMIN_EMAILS` entry) render clean even on the free plan, so
  owner demos and store screenshots need no plan juggling.
- **Applied across every creation surface** — 🎨 Design Studio (web *and* print tiers),
  🎬 storyboard films (film + poster), ✂️ Auto-Edit clips, and 💬 in-chat image/video,
  which is stamped at the single `_persist_generated_media()` chokepoint.
- **Stamped at render time, not download.** Design exports are cached by filename with
  no entitlement in the key, so badging at delivery would mean re-deriving entitlement
  on four separate download paths *or* serving a stale artifact after an upgrade. Baking
  it into the source render means every downstream path inherits it and there is no
  cache to invalidate. Films additionally **persist** the decision, so a render resumed
  after a restart re-applies the original one instead of half-badging a film whose owner
  upgraded mid-render.
- **Pillow draws the badge, ffmpeg composites it.** Not `drawtext` — this codebase
  already documents that the shipped ffmpeg build lacks it and serverless images ship no
  fonts. Rasterizing once to a transparent PNG means the same asset overlays onto both
  stills and video via a filter every build supports. The badge scales with output width
  (so it neither dominates a reel nor vanishes on a 4000px print export) and is cached
  per width bucket.
- **Fail-open by construction.** Missing ffmpeg, missing font, failed encode, timeout or
  corrupt bytes all return the original file/bytes untouched; the swap is atomic and
  scratch files are cleaned up. Losing a badge is acceptable; losing a paid-for render
  is not.
- Config: `WATERMARK_ENABLED` · `WATERMARK_TEXT` (white-label) · `WATERMARK_TIMEOUT_S`.
  Migration `0025_watermark_flags` adds `designs.watermarked` / `films.watermarked`
  (guarded, re-runnable, verified up→down→up).
- **Tests: +29** (512 total, all passing) covering entitlement in both directions,
  future-tier safety, env-listed owners, fail-safe behavior when the admin lookup throws,
  badge rendering/scaling, the argv builders (video re-encodes but copies audio), the
  bytes path incl. JPEG targets, fail-open paths, and wiring through the design, film and
  in-chat routes. Both regression directions were confirmed by mutation testing —
  breaking the paid exemption fails 6 tests; disabling free-tier badging fails 6.

### ⏰🗂🔑 Scheduled tasks · Projects · OpenAI-compatible developer API

Three Grok-parity surfaces that turn Mood from *something you ask* into *something
that works for you*. Full guide: [docs/TASKS-PROJECTS-API.md](docs/TASKS-PROJECTS-API.md).

- **⏰ Scheduled tasks (`/tasks`).** Save a prompt once and Mood runs it unattended —
  `once` / `hourly` / `daily` / `weekly` (weekday mask), all in UTC with the local
  equivalent shown as you pick. A task runs through `chat`, `deepsearch` or `agent`
  mode, appends its answer to a dedicated conversation (so a recurring task reads as
  one growing briefing thread rather than littering the sidebar), and pushes a
  notification. **Run now** tests a task *without* consuming its next scheduled slot.
  - Correctness by construction: due tasks are **claimed atomically**
    (`UPDATE … WHERE last_status != 'running'`), so multiple Fly machines can never
    double-run one; `next_run_at` advances **at claim time**, so a crash mid-run
    resumes on the next slot instead of hot-looping on an overdue row; runs are capped
    by `SCHEDULER_RUN_TIMEOUT_S` and metered as `task` usage events; a failing task
    records the error, keeps its schedule, and never kills the loop.
  - Schedule arithmetic is **cron-free and pure** (`services/schedule.py`) — four
    shapes cover the product, and being I/O-free is what makes it testable without a
    clock. `/healthz` now reports scheduler state for operators.
- **🗂 Projects (`/projects`).** Durable containers for work spanning many chats: a
  **standing brief** plus **pinned documents** that every chat inside inherits, on
  every turn. Project context is injected directly after the persona so it outranks
  memory, recall and doc-RAG; budgets are bounded so a long-lived project can't push
  the actual conversation out of the window; the whole path is fail-open. Injection
  keys off the *conversation's* project, so a filed chat keeps its brief forever, not
  just on the turn that created it. **Deleting a project deletes nothing real** — its
  chats and uploads simply unfile.
- **🔑 Developer API (`/api/v1/public`).** OpenAI-compatible, so `openai-python`, the
  Vercel AI SDK, LangChain and existing curl snippets work by changing two strings.
  `/chat/completions` (streaming `chat.completion.chunk` frames + `[DONE]`),
  `/search` (grounded answer + structured citations), `/images`, `/models`, `/usage`.
  Stable `mood-*` aliases decouple callers from the backing models, and an unknown
  alias falls back to the flagship rather than breaking a pinned integration.
  - Keys are `mk_live_…`, stored as **SHA-256 only** — the plaintext appears exactly
    once, in the response that mints it. Scoped (`chat`/`search`/`images`),
    per-key rate-limited, soft-revocable (immediate, but the audit row survives).
    Session JWTs are rejected on the developer surface and vice-versa, so revoking a
    key genuinely revokes that integration. Every call meters as an `api` event and
    counts against the same plan and dashboard.
- **Plumbing.** Migration `0024_projects_tasks_keys` (existence-guarded, re-runnable,
  verified up → down → up); `conversations.project_id`; `task`/`api` meters added to
  both plan tiers; Tasks + Projects in the app nav; the API-key manager in Settings;
  `/chat?project=…` and `/chat?c=…` deep links.
- **Fixed along the way:** the `?billing=` cleanup in chat rewrote the URL with only
  `?ws=`, silently discarding every other query param — it now preserves them, which
  is what makes the new `?project=` / `?c=` deep links survive a Stripe return.
- **Tests: +62** (482 total, all passing) covering schedule arithmetic and DST-free
  UTC edges, the atomic claim under a simulated race, unattended run/failure/metering
  paths, project context injection and non-destructive deletion, cross-tenant access
  on every new route, key hashing/scope enforcement/revocation, and the OpenAI
  envelope + streaming frame shapes.

### 📚 Docs index + automated housekeeping gate (PR #21)

- **`docs/README.md` — a real documentation index.** All 33 guides in `docs/` are now
  listed in one place, grouped by task (start here · hosting & infra · domains &
  white-label · product surfaces · mobile & store release · auth/policy/compliance ·
  testing & ops), each with a one-line description of what it actually covers. Previously
  the only way to find a guide was to `ls docs/` and guess from the filename.
- **`scripts/check-docs.mjs` — offline, dependency-free docs gate.** Verifies that (1)
  every relative markdown link resolves to a file that exists, (2) every `#anchor`
  exists as a heading in its target document, (3) no guide in `docs/` is orphaned from
  the index, and (4) every guide opens with a level-1 `# Title`. Fenced and inline code
  are stripped first, so illustrative snippets like `[n](url)` in ARCHITECTURE.md don't
  trip it. Failures are grouped per file with an actionable message.
- **Ready to wire into CI as a third `test.yml` job** alongside `backend-unit` and
  `web-typecheck` — the copy-paste job block lives in [docs/README.md](docs/README.md#wiring-the-gate-into-ci).
  (Not applied in this PR: the automation that opened it cannot write to
  `.github/workflows/`.) The check never fetches external URLs, so it cannot flake
  on a third-party outage.
- **README:** links the new index from the intro and the repo map, and adds a
  **"Checks to run before opening a PR"** table mapping each CI job to its local
  command (`pytest backend/tests -q`, `npm run typecheck`, `node scripts/check-docs.mjs`).
- Docs/CI only — no application, API or schema changes.

---

## 2026-07-25

### 🎵 TikTok-style Reel polish (PR #20)

- **TikTok-style interactions on the existing full-bleed vertical snap feed** (the feed itself
  shipped in PR #18): creator **avatar + red follow "+" badge** atop the action rail (local-only,
  `localStorage`-persisted follow set), **double-tap-to-like** with a heart that bursts where you
  tapped (single tap still pauses; 240 ms disambiguation; double-tap never unlikes), a **spinning
  vinyl music disc** in the bottom-right corner, a scrolling **"♪ original sound — @author"**
  marquee under the caption, and **TikTok-style underline top tabs** (For you / Saved / My reels).
- Frontend-only (`frontend/app/reel/page.tsx`) — no backend/API/schema changes; `npm run verify`
  (typecheck + build) green.

### 📺 Creator Reel (merged from PR #16)

- **`/reel` creator feed** — one shared public feed: full-bleed vertical snap, one reel per
  screen, `IntersectionObserver`-gated autoplay (only the on-screen reel decodes), optimistic
  likes reconciled against the server, once-per-card views, *For you* + *My reels* tabs.
- **Two ways in** — upload your own clip, or share a finished film / in-chat generation
  (nothing copied; shares only accept media this deployment serves — hotlinks rejected).
- **🎞 Reel editor** — record or add clips, timeline with duplicate/split/reorder, overlay
  text, effects (CSS-accurate previews of the ffmpeg chain), auto-captions, then publish in
  one ffmpeg pass; **_r/_rp files are deliberately outside the media janitor's sweep patterns,
  so reels survive the 24h TTL** that purges ephemeral films.
- **Duet, effects, repost & social share sheet**, view/like counters, saved tab and
  per-reel stats; backend schema in migrations `0021_reels` → `0023_reel_studio`.
- **🖨 Print-grade graphics (Design Studio)** — sticker kind with die-cut transparency,
  per-kind DPI/print sizes, export presets filtered to what each design actually rendered.
- 🛠 Also merges PR #16's reliability work: backend pytest gate restored, cascade-attempt
  count read live from settings, terminal reel progress uses the canonical `{stage, done,
  total}` completion contract.

### 👁 Reel button visibility fixes (this branch, on top of #16)

- **Mobile bottom tab bar dropped the Reel button** — the phone bar renders `NAV.slice(0, 5)`
  and PR #16 inserted Reel at index 5, so on phones it was drawer-only. Reel now sits in the
  first five (Chat · Voice · Images · **Reel** · Films); a code comment guards the ordering.
- **The chat Reel tab vanished in conversations** — Ask/Imagine/Reel only rendered on the
  empty-chat home, so the moment a conversation opened there was no Reel entry anywhere on
  screen. The conversation toolbar pill now carries **Reel** too (all viewport sizes).


### 🎬 Landing & onboarding

- **Ambient video hero on the home page** — seamless 8-second procedural video loop
  (`frontend/public/hero-ambient.mp4`, 195 KB, H.264) in the Arena leather/teal palette,
  instant-paint JPEG poster, and `prefers-reduced-motion` support (loop pauses, poster stays). (#15)
- **Sticky `LandingNav` with an accessible Explore dropdown** — outside-click + Escape close,
  ↑/↓ arrow-key navigation, `aria-haspopup`/`aria-expanded` semantics — linking Chat,
  Deep Research, Films, Images, Design and Voice. (#15)
- **Calmer landing structure** — full-viewport video hero melting into the page background,
  trimmed 6-card feature grid, same 3-steps + Android sections. (#15)

### 🛡 Reliability & ops

- **Atomic Redis rate limiter** — the old `INCR` + `EXPIRE` pipeline could leave keys without
  an expiry after a crash, permanently throttling users. Replaced with a single **Lua script**
  so increment and expiry happen atomically. All rate-limit paths (chat, picker, videos,
  battles, invites, exports) now ride it. (#14)
- **React `ErrorBoundary`** — a render/runtime fault anywhere in the app shell now shows a
  polished recovery UI (icon, message, "Try again") instead of a blank page; sidebar, tab bar
  and navigation survive. Wrapped around every page's content in `AppShell`, plus the landing
  hero/nav. (#14, #15)
- **Structured `/readyz`** — readiness now returns JSON with per-dependency latency in ms,
  version, and timestamp for ops dashboards and monitoring. (#14)
- **Docker Compose health checks** — `qdrant`, `backend` and `frontend` health checks with
  condition-based `depends_on` (`service_healthy`) so services start in order without races. (#14)

### 📜 Scrolling, layout & hit-testing (site-wide fix)

Audited every screen at 320–1600px in headless Chromium, asserting on computed layout and
`elementFromPoint` hit-testing: (#17)

- **Restored window scrolling on all public pages** — `html, body { height: 100% }` +
  `overflow-x: hidden` on both elements turned `<body>` into a fixed-height scroller, so
  End/PageDown/Space, `scrollIntoView()`, `#anchor` links and scroll restoration did nothing
  and /terms /privacy footer links were unreachable. Now `min-height` + `overflow-x` on
  `<html>` only.
- **Design Studio and Research got real scrollports** — both rendered ~1700px of content into
  an 844px box with no way to reach the rest (Generate design, Brand Kit, Batch studio,
  Client links were permanently off-screen). Both now own a `flex-1 min-h-0 overflow-y-auto`
  scrollport; `/plugins` received the missing `min-h-0` too.
- **Freed trapped sidebar buttons** — at viewport heights ≤720px the shrunken history list
  painted its “New chat” button *under* the nav block: visible but impossible to click.
- **Voice analyzer no longer overlaps the live transcript** — closed `<details>` panels are
  now collapsed outright instead of keeping a measured box on top of the transcript.
- **Touch targets** — footer/legal/auth links (13–16px) and Design checkboxes (13px) grew to
  comfortable tap sizes.

### ✨ Chat experience refinements (#2–#5, #9–#12)

- **Focused Ask / Imagine chat home** — the empty chat surface is now a minimal composer with
  three clean starter actions; the full conversation composer and controls return once a chat
  starts. (#2)
- **Home action fixes** — cursor lands at the end of prefilled drafts, “Research a topic”
  visibly enters research mode with a prefilled prompt, plus a clear research-mode control and
  contextual placeholder in the minimal composer. (#3)
- **Calmer chat recovery** — disruptive connection alerts became inline dismissible notices;
  safe read requests auto-retry while the backend wakes from idle; “Chat” always opens a clean
  new-chat surface while explicit history/library selection is preserved; the Mood AI mark sits
  centered on the empty chat home. (#5)
- **Clean conversation header** — removed the redundant Live/Chat/Auto/message-count status row,
  the auto-saved subtitle, and the extra Ask tab marker so conversation text flows. (#9)
- **Anchored streaming answers** — each new answer pins its start and grows top-to-bottom
  instead of chasing the last streamed line on every delta. (#10)
- **Focused assistant screen experiment** — a chrome-free `/assistant` route was tried (#11)
  and reverted (#12) after review; the integrated chat surface remains the single home.

### 🎨 Mobile & voice polish (#4, #6–#8)

- **Arena warm paper/leather palette across the app** — replaced blue-gray surfaces, borders
  and text ramps; typed composer text explicitly inherits the theme foreground so it stays
  visible. (#6)
- **Roomier mobile composer** — bigger touch area and textarea; Agent, Deep, Plugins and Voice
  collapsed into one compact “More tools” menu; redundant tool-chip/status rows removed. (#4)
- **Voice Studio mobile layout** — content scrolls independently without overflowing into the
  bottom navigation, and the live transcript sits in a bounded scroll region that can't cover
  the orb, analysis panel, or navigation. (#7)
- **Simplified Voice mobile chrome** — header bar removed (menu button stays in its safe-area
  position), and the analyzer's default disclosure triangle is gone. (#8)

## 2026-07-24

### 🔧 Platform hardening (#1)

- Stabilized the frontend build/typecheck flow (Next dynamic-route typing for public/shared
  pages, route-aware typecheck, production build verification) and cleared current dependency
  audit findings.
- **Cloudflare-assisted custom-domain setup** with provider-readiness visibility for
  registrars/DNS.
- **Brain routing observability** for text/image/video plus image-generation fallback
  behavior.
- SEO crawl controls and a **5boost.me cutover runbook + checker**
  ([docs/5BOOST-ME-CUTOVER.md](docs/5BOOST-ME-CUTOVER.md)).

---

## Earlier foundation (pre-PR baseline)

The initial scaffold already shipped: streaming Grok chat with Live Search grounding,
long-term memory with cross-chat recall (Qdrant), document & media analysis, image
generation, realtime voice sessions (WebSocket with barge-in + sentence-chunked TTS),
multi-agent mode, ⚔️ Arena multi-model debates with rematches and white-label arenas,
Think mode, DeepSearch, Gmail/Calendar/GitHub plugins with human-in-the-loop approvals,
team workspaces, custom domains (DNS-verified + registrar purchases with Stripe renewals),
domain analytics, owner panel, plan-aware Pro perks, one-env LLM failover, pluggable
R2/local/Docker file storage, the professional 🎬 video studio with 🎙 Cinema Sound and
🎞 Storyboard films, auto-deploy workflows (Vercel/Netlify/Fly), and the Flutter mobile
client — see the [README](README.md) feature list for the full surface.
