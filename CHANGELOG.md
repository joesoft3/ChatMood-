# Changelog

All notable changes, fixes, and new features shipped to `main` for Mood AI.
Each entry links the pull request it landed in. Dates are UTC.

---

## 2026-07-26

### 🏆 Reel: a real "For You" algorithm, follow graph, comments & watch telemetry

The reel looked the part but behaved like a demo underneath: the feed was a
plain `ORDER BY created_at DESC`, and **Follow was a `localStorage` set** that
flipped a badge and changed nothing. This is the pass that makes it behave like
the product it resembles.

- **🏆 Ranked For You feed** (`services/reel_rank.py`) —
  `log10(1 + weighted_engagement) × (1 + 2·completion) × time_decay × affinity ×
  diversity`. Actions are weighted by intent (view `0.05` → repost `5`), so a
  thousand passive autoplays don't outrank fifteen people who shared it.
  `?sort=new` keeps the chronological feed — a legitimate thing to want, just a
  bad *default*.
  - **Log compression** was added after a test caught the failure mode: with
    linear engagement one runaway hit outscored everything posted since, and no
    decay curve could retire it — the feed froze around last week's winner.
  - The exploration floor (`0.25`) is **calibrated, not guessed**: a strong reel
    scores ≈0.42 at 12 h and ≈0.008 at 7 days, so it beats fresh uploads for a
    day and retires inside a week. Tests pin that window.
  - **Author diversity** damps the *k*-th consecutive reel by one creator
    (`0.55^k`) so nobody can wall off the feed; deterministic, so pagination
    stays stable.
  - Ranking runs over a 500-reel candidate window — flat cost as the corpus
    grows, instead of sorting the whole table in Python.
- **➕ Follow is a real graph** (`reel_follows`, keyed by user **id** — display
  names are editable and non-unique). Drives a new **Following** tab and the
  affinity boost. Optimistic across every card by that creator at once.
- **⏱ Watch telemetry** (`reel_watches` + `POST /reels/{id}/watch`) — the signal
  ranking actually needs, since a view tally can't tell a masterpiece from
  something people bail on in 400 ms. Accumulates real *playing* time from
  `timeupdate` deltas (a paused reel can't inflate it), flushes on swipe-away,
  unmount, `visibilitychange` **and** `pagehide`, and adjusts aggregates **by
  delta** per viewer so re-watching refines rather than stacks. Clamped
  server-side: a client reporting `completion: 50` cannot buy the top slot.
- **💬 Comments** — flat, denormalized count on the feed card, 500-char limit,
  rate-limited. You can delete your own anywhere; a reel's author can moderate
  any comment on their own post.
- **📺 Playback that feels expensive** — neighbour preloading (`±1` card on
  `preload="auto"`) so the next swipe plays instantly; a buffering spinner
  instead of a play icon frozen over a stalled video; and a **scrubbable**
  progress bar (drag or arrow keys) replacing the read-only 2 px sliver.
- **📊 Creator analytics** — the profile strip now leads with **followers** and
  **% watched** (the number that predicts reach) beside the vanity counters, and
  your own live cards carry an inline `% watched · views` chip so you can see
  *why* a reel is or isn't travelling.
- **Migration `0024_reel_ranking`** — guarded/idempotent like 0022–0023, with
  all four paths tested (legacy table, re-run, downgrade, `create_all`). Fixed a
  downgrade bug found in testing: SQLite batch mode re-creates an index over a
  column being dropped in the same batch, so `ix_reels_hot_score` is now dropped
  first.
- **Deleting a reel** now clears its comments and watch rows too — SQLite
  doesn't honour `ON DELETE CASCADE` by default, so those would have been
  orphaned and kept feeding the ranker for a reel nobody can watch.
- **23 new tests** (`test_reel_ranking.py`), asserting behaviour rather than
  arithmetic: quality beats freshness but not forever, following changes the
  feed, one author can't dominate, hostile watch reports are neutralised.
  Verified end-to-end against a live server with a seeded 4-creator feed —
  the 97 %-watched reel moves from 3rd chronologically to 1st ranked.

### 🎙 One-command voice key setup + self-check (`scripts/set-voice-key.sh`)

- **Voice is the one feature gated behind `OPENAI_API_KEY`** (Whisper STT, TTS,
  read-aloud, the realtime voice WebSocket, and video voiceovers). Until it is set,
  `VoiceService` raises `VoiceNotConfigured` and the routes answer **503**. Adding the
  key previously meant hand-editing `.env` and finding out whether it worked by clicking
  around the app.
- **New `scripts/set-voice-key.sh`** — writes `OPENAI_API_KEY` (and optional
  `OPENAI_BASE_URL`) into `.env`, creating it from `.env.example` first, then **proves
  the key actually works**: auth (`GET /models`) → **TTS** (`POST /audio/speech`) →
  **Whisper STT** (`POST /audio/transcriptions`) — it speaks a sentence and transcribes
  its own audio back, closing the full voice loop before you deploy anything.
- **Distinguishes "my key is bad" from "my server doesn't have the key"**:
  `--check --api https://<host> --token <jwt>` probes the deployed backend's
  `/voice/tts` and maps a 503 to *"the SERVER has no OPENAI_API_KEY yet — set it in your
  host's variables + redeploy"*, with per-host instructions (Railway/Render/Fly/Vercel)
  printed on success.
- **Safe by construction**: hidden prompt input, the key is masked in all output
  (`sk-proj…AbCd`), `.env` is chmod 600, writes are idempotent (replace-or-append, never
  duplicate lines), `--check` never touches `.env`, and the script **refuses to write a
  secret into a git-tracked file**. 429s are called out as billing/quota rather than a
  bad key.
- Referenced from the README quickstart + capability table, `.env.example`,
  [docs/VIDEO-SOUND.md](docs/VIDEO-SOUND.md) and the
  [go-live clicksheet](docs/GO-LIVE-CLICKSHEET.md).

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
