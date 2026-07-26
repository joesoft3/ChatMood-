# 📺 Creator Reel — the shared creator feed

A single public feed every signed-in creator can watch and post to. Two ways in:

- **Upload** — a creator posts their own clip from the camera roll.
- **Share** — a creator posts something Mood already generated (a storyboard
  film, or a video made in chat). Nothing is copied: the reel row points at the
  media that already exists.

## Where the button lives

| Surface | Entry point |
|---|---|
| App home (`/chat`) | **Reel** tab in the top row, beside *Ask* and *Imagine* |
| Landing page (`/`) | **📺 Reel** button in the top nav, plus an *Explore* entry |
| Every studio | **Reel** item in the app sidebar |

## The screen (`/reel`)

Full-bleed vertical snap feed — one reel per screen, the same shape people
already know from Reels/TikTok/Shorts:

- Autoplay is driven by an `IntersectionObserver` at a 0.6 visibility ratio, so
  only the reel actually on screen decodes. Off-screen `<video>` elements are
  paused — the fastest way to melt a phone battery is to leave them running.
- Tap the video to pause/resume; the speaker toggles mute (starts muted so
  autoplay is allowed by browser policy).
- Likes are optimistic and reconcile against the server's authoritative count,
  rolling back if the request fails.
- A view is counted once per card per mount, when it first becomes visible.
- **Neighbour preloading**: the active card and its immediate neighbours (±1)
  use `preload="auto"` while distant cards stay on `"metadata"`. This is most of
  what makes a feed feel *instant* rather than *loading* — the next reel is
  already buffered when your thumb lands — without pulling the whole feed over
  someone's mobile data.
- **Buffering spinner** instead of a frozen play icon: a play button over a
  stalled video reads as "broken", a spinner reads as "loading".
- **Scrubbable progress bar** — drag (or arrow-key) back to the bit you liked.
  The old one was a read-only 2 px sliver; the bar keeps a generous invisible
  hit area and grows on hover/drag so it's usable with a thumb.
- Four tabs: **For you** (ranked), **Following** (creators you follow, newest
  first), **Saved**, and **My reels** — which includes unposted ones so you can
  put them back.

## API

| Endpoint | Notes |
|---|---|
| `GET /api/v1/reels` | 🏆 **ranked** For You feed, 20 per page (`?sort=new` for chronological, `?mine=true`, `?following=true`, `?offset=`) |
| `POST /api/v1/reels/upload` | multipart `file` + `caption` → new post |
| `POST /api/v1/reels/share` | `{film_id}` or `{url}` + `caption` → new post |
| `GET /api/v1/reels?saved=true` | 🔖 your saved collection, newest **save** first |
| `GET /api/v1/reels/stats` | 📊 profile totals across everything you've posted |
| `POST /api/v1/reels/{id}/like` | idempotent toggle → `{liked, likes}` |
| `POST /api/v1/reels/{id}/save` | idempotent bookmark toggle → `{saved, saves}` |
| `POST /api/v1/reels/{id}/share` | tally + the link to copy → `{shares, url}` |
| `GET /api/v1/reels/effects` | 🎨 effect catalog (+ CSS preview), speeds, caption styles, duet layouts |
| `POST /api/v1/reels/{id}/duet` | 🎭 multipart clip + `layout`/`audio`/`effect` → new duet reel |
| `POST /api/v1/reels/{id}/repost` | 🔁 repost to your profile, crediting the root author |
| `POST /api/v1/reels/{id}/view` | bump the view counter |
| `POST /api/v1/reels/{id}/watch` | ⏱ watch telemetry `{watched_ms, duration_s, replays}` → ranking signal |
| `GET /api/v1/reels/{id}/comments` | 💬 comments, newest first, 30 per page |
| `POST /api/v1/reels/{id}/comments` | `{body}` → new comment (≤ 500 chars, 10/min) |
| `DELETE /api/v1/reels/{id}/comments/{cid}` | yours anywhere; any comment on a reel you own |
| `POST /api/v1/reels/authors/{author_id}/follow` | ➕ idempotent follow toggle → `{following, followers}` |
| `GET /api/v1/reels/following` | author ids you follow |
| `POST /api/v1/reels/{id}/visibility` | `{"live": false}` unposts; author only |
| `DELETE /api/v1/reels/{id}` | deletes the row **and** uploaded bytes; author only |
| `GET /api/v1/reels/files/{name}` | public streaming (see below) |

Uploads: MP4/MOV/WebM, ≤ 100 MB, rate-limited 4/min (×4 on pro).

## 📊 Engagement counters

Every card carries four numbers, denormalised onto the `reels` row so the feed
never runs three `COUNT(*)`s per card:

| Counter | Semantics |
|---|---|
| 👁 **views** | pure tally, counted once per card per mount when it first becomes visible |
| ❤️ **likes** | per-user **toggle** — `(reel_id, user_id)` PK makes a double-tap idempotent |
| 🔖 **saves** | per-user **toggle**, and the row that powers your private Saved tab |
| ➤ **shares** | pure **tally** — sharing the same reel twice really is two shares, so it deliberately does *not* toggle |

Likes and saves are reconcilable from their join tables; views and shares are
counters only. The UI updates optimistically and then reconciles against the
server's authoritative number, rolling back if the request fails.

**Share** uses the native share sheet where the browser has one
(`navigator.share`) and falls back to copying the link. A dismissed share sheet
is *not* counted — only a completed share or a successful copy increments.

## 🔖 Saved & 🎬 profile

- **Saved tab** (`?saved=true`) lists your bookmarks ordered by *when you saved
  them*, not when they were posted — a save is its own event with its own
  timestamp. Un-saving from inside the tab removes the card immediately.
- Unposting a reel drops it out of everyone's Saved tab too (the join filters
  on `status == "live"`), and deleting clears both join tables explicitly:
  SQLite doesn't honour `ON DELETE CASCADE` unless `PRAGMA foreign_keys` is on,
  so orphan likes/saves would otherwise break other users' Saved tabs.
- **My reels** shows a stats strip — followers · posts · views · likes ·
  comments · **% watched** — from `GET /reels/stats`, plus per-card **unpost**
  and **delete**. Mean completion is there because it is the number that
  actually predicts reach, where views only describe the past.
- Your own live cards carry a small **analytics chip** (`% watched · views`) so
  you can see *why* a reel is or isn't travelling, green above 60 %.

## 🏆 The "For You" algorithm

`services/reel_rank.py`. A reverse-chronological list is the difference between
a demo and a product: the newest upload always wins, a great reel is buried
within the hour, and one creator posting ten times owns the whole feed. The
ranked feed replaces that with the model short-video apps actually use:

```
score = log10(1 + weighted_engagement) × (1 + 2·completion) × time_decay × affinity × diversity
```

| Term | Why it's there |
|---|---|
| **Weighted engagement** | Actions are weighted by *intent*: view `0.05` < like `1` < comment `2.5` < save `3` < share `4` < repost `5`. A thousand passive autoplays should not outrank fifteen people who put their name on it. |
| **`log10` compression** | Without it one runaway hit outscores everything posted since by so much that no decay curve can retire it, and the feed freezes around last week's winner. Same reason Reddit/HN compress their vote term. |
| **Completion rate** | The strongest quality signal there is, and the one metric you can't farm by posting more. A reel people finish beats one with equal likes that everybody swipes away from. |
| **Time decay** | `(2/(age_h + 2))^1.6` — a gravity curve. Fresh surfaces, but proven work stays competitive for about a day. |
| **Affinity** | `×2.2` if you follow the creator, `×1.35` if you've liked their work before (implicit taste — this is what personalizes the feed on day one, before anyone presses Follow). Your own reels are damped `×0.55` in your own For You. |
| **Diversity** | The *k*-th consecutive reel by one author is multiplied by `0.55^k`, so a prolific creator can't wall off the feed. Deterministic, so pagination stays stable. |
| **Exploration floor** | A brand-new reel with zero engagement still scores `0.25`, fading over 6 h — otherwise nothing new ever earns the impressions it needs to prove itself. |

The floor is **calibrated, not vibes**: a strong reel (5k views / 800 likes /
200 shares / 90 % completion) scores ≈ 0.42 at 12 h and ≈ 0.008 at 7 days, so a
floor of 0.25 lets it beat fresh uploads for its first day and retires it inside
a week. `test_reel_ranking.py` pins that window down.

Ranking runs over a **candidate window** (the 500 freshest live reels) rather
than the whole table — ranking is only meaningful among plausible candidates,
and pulling everything into Python to sort it is how feeds fall over. Viewer
terms (affinity, diversity) are applied in Python because they differ per
viewer; everything else is denormalized onto the row.

> `?sort=new` keeps the old reverse-chronological feed — "show me the latest" is
> a legitimate thing to want, it just isn't a good *default*.

## ⏱ Watch telemetry — the signal that makes ranking work

A view tally can't tell a masterpiece from something people bail on in 400 ms,
so the player reports real watch time on swipe-away (`POST /reels/{id}/watch`).

- `watched_ms` accumulates **playing time**, summed from `timeupdate` deltas —
  not wall-clock, so a paused or buffering reel can't inflate it.
- Reported on swipe-away, unmount, `visibilitychange` **and** `pagehide`: a
  swipe is often a page teardown, and an unreported watch is a lost signal.
- Aggregates are adjusted **by delta** per `(reel, viewer)`, so re-watching a
  reel twenty times refines the number instead of stacking twenty samples.
- Everything is clamped server-side (≤ 6 h, completion ≤ 1.0). A hostile client
  reporting `completion: 50` cannot buy the top slot.

## ➕ Follow — now a real graph

Follow used to be a `localStorage` set: the badge flipped to "Following" and
nothing else in the product ever knew — it didn't change the feed and it
vanished when you switched device. That is the single most "cheap demo" tell in
a short-video app, because following is supposed to *change what you see*.

`reel_follows` is keyed by author **user id**, not display name (names are
editable and non-unique, so a name-keyed graph silently re-points at another
creator). It powers the **Following** tab and the affinity term above.

## 💬 Comments

Flat, not threaded — one level is the 90 % case and threading turns the feed
query into a recursive CTE for very little gain. The count is denormalized onto
the reel row so a feed card needs no extra request. You can always delete your
own comment; the **reel's author can delete any comment on their own post**,
which is the minimum viable moderation story.

## 🎬 Reel Studio — duet, effects, captions

`services/reel_studio.py` holds pure argv builders (unit-testable without the
binary, same pattern as `soundtrack.py` / `editor.py`). Everything composes onto
one **1080×1920** canvas so results are predictable whatever was uploaded.

**Duet** (`POST /reels/{id}/duet`, multipart) — stacks your clip with theirs:

| layout | result |
|---|---|
| `side` | theirs left, yours right (the classic duet read) |
| `top` | theirs on top, yours underneath |
| `green` | theirs full-frame, yours as a corner inset |

`audio` is `both | mine | theirs` — two people talking over each other is
unwatchable. The original is never modified: a duet is a **new** reel carrying
`parent_id`/`parent_author`, so the first creator keeps attribution.

**Effects** (`GET /reels/effects`) — 8 looks, each pairing an ffmpeg chain with
an equivalent **CSS filter**. The browser previews with the CSS while you edit
and the server burns the ffmpeg chain in on post, so the preview is a promise
about the render rather than a rough guess. Speeds 0.5×–2× (clamped to the
range `atempo` accepts). Effects fail **open**: a look that won't render must
never cost a creator their upload.

**Captions** — auto-transcribed with Whisper (reusing `editor.transcribe_srt`,
so there is exactly one transcription path) and burned in with libass.
This ffmpeg build ships **no `drawtext` filter**, so text goes through
`subtitles=` — which wraps, outlines and times text better anyway. Set
`REEL_FONTS_DIR` on hosts with no system fonts.

## 🎞 The editor — record, arrange, publish

Tapping **Post** opens a full editor instead of a bare file picker.

**Record** — `getUserMedia` + `MediaRecorder` capture straight in the browser
(front camera, 1080×1920 preferred). Codec support differs per browser, so we
probe `isTypeSupported` and let the UA choose rather than throwing
`NotSupportedError`. The stream is always released on close — a page that keeps
the camera light on after you leave is the fastest way to lose trust.

**Timeline** — up to 10 clips, each with its own trim, effect, speed and
volume. `+ Video`, `+ Audio` and `+ Overlay` stage more sources.

| Control | What it does |
|---|---|
| ✂️ **Split** | cuts the selected clip at the preview playhead into two clips |
| ⧉ **Duplicate** | repeats a clip in place (a beat-repeat, without re-uploading) |
| 🗑 **Remove** | drops it, and unstages the asset if nothing else references it |
| **Trim** | in/out sliders per clip |
| 🔊 **Clip volume** | the *volume split* — duck a clip under the music bed |

**+ Audio** lays a music/voiceover bed under the whole timeline with its own
volume, so "clip at 30%, track at 85%" is two sliders. **+ Overlay** pins a
second video picture-in-picture to any corner at 15–60% width, previewed live
in the editor at the exact corner and size it will render.

**Publish** renders the entire timeline in a **single ffmpeg pass**. Chaining
one pass per operation would re-encode the footage each time and visibly soften
it. Staged assets are cleaned up once the render lands.

### Staging & safety
Assets upload to `_ra` names — deliberately outside the `_r.mp4` serving
pattern, so an unpublished draft is never in anyone's feed (nothing links to it:
no `Reel` row ever references an `_ra` name). They *are* served, because the
editor has to play back what you just recorded.

`publish` resolves every clip name through a strict `DRAFT_RE` allowlist.
Client-supplied filenames are hostile input: without it, a caller could pass
`../../etc/passwd` and have ffmpeg read arbitrary files into a published video.

The timeline builder also generates an `anullsrc` track for silent clips —
`concat` demands audio on *every* segment, and a screen recording with no audio
would otherwise fail the whole graph with "Stream specifier ':a' matches no
streams".

| Endpoint | Notes |
|---|---|
| `POST /api/v1/reels/assets` | stage a clip or audio track (`kind=video\|audio`) |
| `DELETE /api/v1/reels/assets/{name}` | discard a staged asset |
| `POST /api/v1/reels/publish` | render the timeline → a published reel |

## 🔁 Repost & 📣 social share

**Repost** (`POST /reels/{id}/repost`) copies no bytes — the new row points at
the same media and credits the author. Reposting a repost credits the **root**
author, not the middle-man, and reposting your own reel (or the same one twice)
is a `409` rather than a silent duplicate.

Because reposts share the original's file, delete only unlinks media when **no
other row references that filename** — otherwise deleting a repost would break
the original's playback.

**Share sheet** — WhatsApp · X · Facebook · TikTok · Instagram, with real brand
glyphs (lucide ships none, by trademark policy). TikTok and Instagram have **no
public web share intent**, so those copy the link to paste; pretending otherwise
would open a dead tab. A dismissed native share sheet is *not* counted.

## Feed behaviour

- **Infinite scroll** — the API paginates 20 per page and returns `next_offset`;
  the feed appends the next page ~1.5 screens from the end, de-duping by id so
  a reel posted mid-scroll can't appear twice.
- **A network failure is not an empty feed.** If the request fails the screen
  says so and offers *Try again*, instead of the cheerful "the reel is quiet"
  empty state — which reads as "your reels are gone".
- **Views count once per reel per session.** The guard lives at module scope,
  not in a component ref, so remounting a card (switching tabs, reloading the
  feed) can't re-count a view that was already recorded.
- **Refresh on focus** — returning to the tab reloads the feed and stats, since
  counts move while you're away.

## Two details worth knowing

**Reel media is never swept by the media janitor.** Muxed films are ephemeral —
a janitor purges `<hex32>.mp4`, `_e.mp4` and `_p.jpg` after `MEDIA_TTL_HOURS`
(24h). Reel posts are keepsakes, so they use the `_r.mp4` / `_rp.jpg` suffixes,
which deliberately fall outside every sweep pattern. A feed whose videos
evaporate overnight is not a feed. There is a regression test for exactly this.

**Shares can't hotlink.** `POST /reels/share` accepts a `url` only if it points
at media this deployment serves (`/api/v1/media/files/…` or
`/api/v1/reels/files/…`). Arbitrary external URLs are rejected with `422`, so
the feed can only ever carry media Mood produced or a creator uploaded.

Serving is public like `/media/files` so `<video>` tags and mobile players work
without auth headers; names are 128-bit random hex and the route hard-matches
the reel filename patterns, so nothing outside the reel namespace is readable.

## Moderation

Every post carries its author, and the author can unpost or delete at any time.
`status` is `live | hidden`; only `live` rows appear in the shared feed. Deleting
a post also unlinks its uploaded bytes (shares leave the original film alone) and
cascades its likes.

## Schema

Migration `0021_reels` adds two tables:

- `reels` — one row per post (`source` = `upload | film | chat`), indexed on
  `user_id`, `status` and `created_at` (the feed sort key).
- `reel_likes` — `(reel_id, user_id)` composite primary key, which is what makes
  liking idempotent rather than double-counting a double-tap.

`created_at` carries a Python-side microsecond default in addition to the server
default: SQLite's `CURRENT_TIMESTAMP` is only second-resolution, so two posts in
the same second would tie and the paginated feed could skip or repeat rows. Feed
queries also order by `id` as a deterministic tiebreak.

## Screenshots

Captured against a running stack seeded with 8 sample clips across 4 creators
(`docs/screenshots/`):

`reel-all-screens.png` is a single contact sheet of all eight, grouped by
entry points / feed / composer — the quickest way to see everything at once.

| Shot | What it shows |
|---|---|
| `reel-07-chat-home-tabs.png` | **Reel** tab at the top of the app home, beside *Ask* / *Imagine* |
| `reel-09-landing-nav.png` | 📺 **Reel** button in the landing top nav |
| `reel-01-reel-mobile.png` | feed on mobile — video playing, author, caption, like/mute rail |
| `reel-02-reel-scrolled.png` | snap-scroll to the next reel (different creator + counts) |
| `reel-05-my-reels.png` | *My reels* — 🗑 delete appears **only** on your own posts |
| `reel-06-reel-desktop.png` | desktop: feed column centred, sidebar shows the Reel item |
| `reel-03-composer-upload.png` | composer, Upload tab (MP4/MOV/WebM · up to 100 MB) |
| `reel-04-composer-share.png` | composer, Share-a-film tab (empty state when no finished films) |
