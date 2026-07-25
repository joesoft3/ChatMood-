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
| `POST /api/v1/reels/{id}/like` | idempotent toggle → `{liked, likes}` |
| `POST /api/v1/reels/{id}/view` | bump the view counter |
| `POST /api/v1/reels/{id}/visibility` | `{"live": false}` unposts; author only |
| `DELETE /api/v1/reels/{id}` | deletes the row **and** uploaded bytes; author only |
| `GET /api/v1/reels/files/{name}` | public streaming (see below) |

Uploads: MP4/MOV/WebM, ≤ 100 MB, rate-limited 4/min (×4 on pro).

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
