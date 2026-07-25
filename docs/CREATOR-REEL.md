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
- **For you** shows the shared live feed; **My reels** shows your own posts,
  including unposted ones so you can put them back.

## API

| Endpoint | Notes |
|---|---|
| `GET /api/v1/reels` | feed, newest first, 20 per page (`?mine=true`, `?offset=`) |
| `POST /api/v1/reels/upload` | multipart `file` + `caption` → new post |
| `POST /api/v1/reels/share` | `{film_id}` or `{url}` + `caption` → new post |
| `GET /api/v1/reels?saved=true` | 🔖 your saved collection, newest **save** first |
| `GET /api/v1/reels/stats` | 📊 profile totals across everything you've posted |
| `POST /api/v1/reels/{id}/like` | idempotent toggle → `{liked, likes}` |
| `POST /api/v1/reels/{id}/save` | idempotent bookmark toggle → `{saved, saves}` |
| `POST /api/v1/reels/{id}/share` | tally + the link to copy → `{shares, url}` |
| `POST /api/v1/reels/{id}/view` | bump the view counter |
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
- **My reels** shows a stats strip — posts · live · views · likes · shares —
  from `GET /reels/stats`, plus per-card **unpost** and **delete**.

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
