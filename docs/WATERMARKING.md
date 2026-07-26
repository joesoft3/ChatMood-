# 🏷 Watermarking

Free-tier renders carry a small "Made with Mood AI" badge. **Paid plans and
admins render clean.** This is the conversion lever for the creation surfaces:
every free flyer, film and generated image quietly advertises the product, and
removing the badge is a concrete reason to upgrade.

---

## The entitlement rule

One predicate, one place — [`services/watermark.should_watermark()`](../backend/app/services/watermark.py):

```python
should_watermark(user) -> bool
```

| Who | Badged? |
| --- | --- |
| `free` plan | ✅ yes |
| Any other plan (`pro`, and any future tier) | ❌ no |
| Admins — `users.is_admin` **or** an `ADMIN_EMAILS` entry | ❌ no |
| Anonymous / public render | ✅ yes (treated as free) |
| `WATERMARK_ENABLED=false` | ❌ no (feature off) |

Two deliberate choices:

- **Paid detection is a denylist of one** (`plan != "free"`), not an allowlist.
  When a new tier is added, the failure mode is "we forgot to badge a paying
  customer" rather than "we stamped one" — a badge on a paid export is a refund
  request, so that's the safe direction to be wrong in.
- **Admins are exempt even on the free plan**, so owner demos, marketing shots
  and Play Store screenshots come out clean without plan juggling.

Every render path calls this predicate rather than re-deriving "is this user
premium?" — the whole point is that there is nowhere for the two answers to
diverge.

## Where it applies

| Surface | Path | What gets badged |
| --- | --- | --- |
| 🎨 Design Studio | `services/designer.generate_design()` | web **and** print tiers |
| 🎬 Storyboard films | `services/film_jobs` | the film + its poster frame |
| ✂️ Auto-Edit | `services/editor_jobs` | the finished clip |
| 💬 In-chat images & video | `routes/chat._persist_generated_media()` | the archived bytes |

Two design decisions worth knowing:

**Stamped at render time, not at download.** Design exports are cached by
filename (`{id}_x_{preset}.png`) with no entitlement in the key. Badging at
download would mean either re-deriving entitlement on every delivery path
(export presets, direct download, print pack, public share link — four chances
to miss one) or serving a stale cached artifact after an upgrade. Baking the
badge into the source render at creation makes every downstream path inherit it
automatically, with no cache to invalidate.

**Films persist the decision** (`films.watermarked`). The resume path rebuilds
its job payload from the database row, so a render interrupted by a restart
re-applies the *original* decision instead of re-deriving it — otherwise a user
who upgraded mid-render would get a half-badged film.

## How the badge is drawn

Rendered by **Pillow**, then composited by ffmpeg's `overlay` filter.

Not `drawtext`: this codebase already documents that the shipped ffmpeg build
has no `drawtext` (see `api/routes/reels.py`), and serverless images carry no
system fonts. Pillow is a hard dependency, the repo bundles
`DejaVuSans-Bold.ttf`, and rasterizing the badge once to a transparent PNG means
the *same* asset composites onto both stills and video through a filter every
ffmpeg build supports.

- A dark translucent pill with near-white text — legible over both bright and
  dark artwork without a hard border fighting the composition.
- Sized as a fraction of output width, so it reads the same on a 900 px reel and
  a 4000 px print export instead of vanishing on one of them.
- Cached per width bucket — it's identical for every free user, so
  re-rasterizing per render would be pure waste.
- Bottom-right, matching where the codebase already stamps brand logos.

## Fail-open, always

A watermark failure must never cost a user a render they already spent quota on.
Missing ffmpeg, a missing font, a failed encode, a timeout, corrupt bytes — every
path returns the **original** file or bytes untouched, logs a warning, and moves
on. The file swap is atomic (`tmp.replace(path)`), so a reader can never observe
a half-written render, and scratch files are cleaned up on failure.

Losing a badge is an acceptable outcome. Losing a customer's render is not.

## Configuration

```bash
WATERMARK_ENABLED=true      # master switch — false disables it for everyone
WATERMARK_TEXT=             # blank → "Made with {APP_NAME}"
WATERMARK_TIMEOUT_S=90      # cap on the stamping encode; on timeout the clean render ships
```

White-label deployments will usually want `WATERMARK_TEXT` set to their own
brand, or `WATERMARK_ENABLED=false` if they don't badge at all.

## Migration

```bash
cd backend && alembic upgrade head   # 0025_watermark_flags
```

Adds `designs.watermarked` and `films.watermarked`, both defaulting to false.
Existing rows correctly report `false` — they predate the feature and genuinely
carry no badge. Guarded per column, so it is re-runnable and safe on
deployments whose tables came from `Base.metadata.create_all`.

## Tests

```bash
cd backend && python -m pytest tests/test_watermark.py -q   # 29 tests
```

Covering entitlement in **both** directions (free is badged / paid and admins
are not), future-tier safety, env-listed owners, fail-safe behavior when the
admin lookup throws, badge rendering and scaling, the ffmpeg argv builders
(video re-encodes but copies audio; stills use `-frames:v 1`), the bytes path
including JPEG targets, fail-open on missing ffmpeg / failed encode / garbage
input, and end-to-end wiring through the design, film and in-chat routes.

Both regression directions were verified by mutation: breaking the paid-user
exemption fails 6 tests, and disabling badging for free users fails 6 tests.
