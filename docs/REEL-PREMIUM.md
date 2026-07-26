# ⭐🔴 Reel premium & Go Live

Two things ship together here: the **Creator Pro** paywall on the Reel surface,
and **Go Live** — real broadcast, gated behind Pro.

## Creator Pro

| Perk | Free | Pro |
| --- | --- | --- |
| 🏷 Watermark | badge burned in | clean |
| 🎨 Effects | Warm, Cool, Vivid, Mono | **+ Noir, Dream, Vintage** |
| 📺 Quality | 720×1280 | **1080×1920** |
| ⏱ Clip length | 60 s / 60 MB | **3 min / 100 MB** |
| 🔴 Go Live | — | **yes** |
| 📊 Analytics | — | **yes** |
| 🎬 Posting · 🎭 Duets | yes | yes |

Posting and duets stay **free on purpose**: a feed nobody can post to is worth
nothing, so the paywall sells polish and reach, not access.

### One entitlement source

Every gate resolves through `reel_premium.entitlements()`, and the UI renders
its padlocks from that same payload (`GET /reels/premium`). A lock therefore
cannot claim something the server doesn't enforce, and a perk cannot silently
stop applying — the two can't drift.

Blocked actions return **`402 Payment Required`** with actionable copy ("The
Noir effect is a Pro feature — upgrade in Settings → Upgrade"), never a bare
403. Admins are premium so owner demos and store screenshots aren't crippled,
and any future paid tier is premium by default.

## 🔴 Go Live

A broadcast **is a reel row** with `kind="live"`. It floats to the top of the
feed while streaming, then becomes an ordinary replay when the creator ends it —
so viewers keep the post they were already watching instead of it vanishing.

```
POST /reels/live/start          → provisions the stream, returns ingest + key
POST /reels/live/{id}/end       → tears down at the provider, keeps the replay
POST /reels/live/{id}/heartbeat → concurrent viewer count (+ peak)
```

### The security rule

The **stream key is a write credential**: anyone holding it can broadcast as
that creator. It is returned exactly once, to the owner, by `/live/start`.
`LiveTarget.as_viewer_dict()` exists specifically so the feed payload physically
cannot include it, and a test asserts the key never appears in a feed response.

### This repo does not host video

Real live video needs RTMP ingest, transcoding and HLS/WebRTC egress — a managed
product, not something a FastAPI process should fake. `services/live_stream.py`
is a thin adapter over one of:

| Provider | Env |
| --- | --- |
| Mux Video | `MUX_TOKEN_ID` + `MUX_TOKEN_SECRET` |
| Cloudflare Stream | `CLOUDFLARE_STREAM_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` |
| LiveKit (WebRTC) | `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` + `LIVEKIT_URL` |

```bash
LIVE_PROVIDER=mux
MUX_TOKEN_ID=…
MUX_TOKEN_SECRET=…
```

Every provider returns the same normalized `LiveTarget`, so the routes, the
database row and the player never learn which vendor is behind them — swapping
is an env change.

**With no provider configured, `create_stream()` raises rather than inventing a
URL.** A Pro creator then sees "Go Live isn't switched on yet" (503) instead of
a Start button that silently produces nothing. Entitlement and infrastructure
are tracked separately for exactly this reason: `go_live` is true only when the
creator is Pro **and** a provider has keys.

> **⚠️ This costs money.** Managed streaming bills per ingest/egress minute.
> `LIVE_MAX_MINUTES` exists to cap runaway broadcasts. Check your provider's
> pricing before switching this on.

### Broadcasting

The creator's phone or OBS pushes RTMP to the ingest URL. The in-app screen is a
**camera monitor plus the ingest credentials** — deliberately not a browser
encoder, because browser RTMP requires a WebRTC→RTMP bridge that only some
providers offer. LiveKit is the exception (WebRTC-native), which is why its
adapter carries a room name instead of a stream key.

## Migration

```bash
cd backend && alembic upgrade head   # 0027_reel_live_premium
```

Adds the `live_*` columns, `kind` and `watermarked` to `reels`. Guarded and
re-runnable.

## Tests

```bash
cd backend && python -m pytest tests/test_reel_premium.py -q   # 34 tests
```

Entitlement in both directions (free blocked / Pro allowed / admins premium /
future tiers premium), effect gating, plan-aware upload caps, provider
readiness, the full live lifecycle (start → viewers → end → replay), one
broadcast at a time, owner-only teardown, a viewer counter that can't go
negative, and **the feed never leaking a stream key**. Both security guards were
mutation-tested: leaking the key and dropping the Go Live paywall each fail the
suite.
