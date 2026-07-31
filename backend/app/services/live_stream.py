"""🔴 Live streaming — provider adapter for real broadcast.

This repo does **not** host video infrastructure. Real live video needs RTMP
ingest, transcoding and HLS/WebRTC egress, which is a managed product (Mux,
Cloudflare Stream, LiveKit), not something a FastAPI process should pretend to
do. So this module is a thin, honest adapter:

* `create_stream()` provisions an ingest endpoint + playback URL at whichever
  provider is configured, and returns a normalized `LiveTarget`.
* Every provider returns the SAME shape, so the routes, the database row and the
  player never learn which vendor is behind them — swapping providers is an env
  change.
* With **no provider configured, `create_stream()` raises `LiveNotConfigured`**
  rather than inventing a fake URL. A creator gets "Go Live isn't switched on
  yet", not a Start button that silently produces nothing.

Adding a provider = one function + a `provider_configured` branch. Nothing else
in the codebase changes.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

import httpx

from ..config import settings

log = logging.getLogger(__name__)


class LiveNotConfigured(Exception):
    """No streaming provider has credentials — Go Live is unavailable."""


class LiveProviderError(Exception):
    """The provider rejected the request (bad key, quota, outage)."""


@dataclass(frozen=True)
class LiveTarget:
    """Normalized stream handle — identical shape for every provider."""

    provider: str
    stream_id: str        # provider-side id, for teardown
    ingest_url: str       # RTMP endpoint the broadcaster pushes to
    stream_key: str       # secret — only ever shown to the owning creator
    playback_url: str     # HLS/WebRTC URL viewers watch

    def as_owner_dict(self) -> dict:
        """Full detail — ONLY for the creator who owns the stream."""
        return {
            "provider": self.provider,
            "stream_id": self.stream_id,
            "ingest_url": self.ingest_url,
            "stream_key": self.stream_key,
            "playback_url": self.playback_url,
        }

    def as_viewer_dict(self) -> dict:
        """Viewer-safe subset. The stream key is a WRITE credential: anyone
        holding it can broadcast as this creator, so it must never reach the
        feed payload."""
        return {"provider": self.provider, "playback_url": self.playback_url}


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(20.0, read=30.0)


# ─────────────────────────────────────────────────────────────── Mux

async def _create_mux() -> LiveTarget:
    auth = base64.b64encode(
        f"{settings.MUX_TOKEN_ID}:{settings.MUX_TOKEN_SECRET}".encode()
    ).decode()
    async with httpx.AsyncClient(timeout=_timeout()) as c:
        r = await c.post(
            "https://api.mux.com/video/v1/live-streams",
            headers={"Authorization": f"Basic {auth}"},
            json={
                "playback_policy": ["public"],
                "new_asset_settings": {"playback_policy": ["public"]},
                "latency_mode": "low",
                "reconnect_window": 60,
            },
        )
    if r.status_code >= 400:
        raise LiveProviderError(f"Mux rejected the stream ({r.status_code}): {r.text[:200]}")
    d = (r.json() or {}).get("data") or {}
    playback = (d.get("playback_ids") or [{}])[0].get("id", "")
    return LiveTarget(
        provider="mux",
        stream_id=d.get("id", ""),
        ingest_url="rtmps://global-live.mux.com:443/app",
        stream_key=d.get("stream_key", ""),
        playback_url=f"https://stream.mux.com/{playback}.m3u8" if playback else "",
    )


async def _delete_mux(stream_id: str) -> None:
    auth = base64.b64encode(
        f"{settings.MUX_TOKEN_ID}:{settings.MUX_TOKEN_SECRET}".encode()
    ).decode()
    async with httpx.AsyncClient(timeout=_timeout()) as c:
        await c.delete(
            f"https://api.mux.com/video/v1/live-streams/{stream_id}",
            headers={"Authorization": f"Basic {auth}"},
        )


# ────────────────────────────────────────────────── Cloudflare Stream

async def _create_cloudflare() -> LiveTarget:
    base = f"https://api.cloudflare.com/client/v4/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}/stream/live_inputs"
    async with httpx.AsyncClient(timeout=_timeout()) as c:
        r = await c.post(
            base,
            headers={"Authorization": f"Bearer {settings.CLOUDFLARE_STREAM_TOKEN}"},
            json={"meta": {"name": "MoodAI live"}, "recording": {"mode": "automatic"}},
        )
    if r.status_code >= 400:
        raise LiveProviderError(f"Cloudflare rejected the stream ({r.status_code}): {r.text[:200]}")
    d = (r.json() or {}).get("result") or {}
    rtmps = d.get("rtmps") or {}
    uid = d.get("uid", "")
    return LiveTarget(
        provider="cloudflare",
        stream_id=uid,
        ingest_url=rtmps.get("url", ""),
        stream_key=rtmps.get("streamKey", ""),
        playback_url=(
            f"https://customer-{settings.CLOUDFLARE_ACCOUNT_ID}.cloudflarestream.com/{uid}/manifest/video.m3u8"
            if uid
            else ""
        ),
    )


async def _delete_cloudflare(stream_id: str) -> None:
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{settings.CLOUDFLARE_ACCOUNT_ID}/stream/live_inputs/{stream_id}"
    )
    async with httpx.AsyncClient(timeout=_timeout()) as c:
        await c.delete(url, headers={"Authorization": f"Bearer {settings.CLOUDFLARE_STREAM_TOKEN}"})


# ───────────────────────────────────────────────────────────── LiveKit

async def _create_livekit(room: str) -> LiveTarget:
    """LiveKit is WebRTC-native: the browser publishes directly, so there is no
    RTMP key. The `stream_key` slot carries the room name instead, and the
    client mints its join token from the LiveKit SDK."""
    return LiveTarget(
        provider="livekit",
        stream_id=room,
        ingest_url=settings.LIVEKIT_URL,
        stream_key=room,
        playback_url=f"{settings.LIVEKIT_URL}?room={room}",
    )


# ────────────────────────────────────────────────────────────── public

async def create_stream(*, room_hint: str = "") -> LiveTarget:
    """Provision a live stream at the configured provider.

    Raises LiveNotConfigured when no provider has keys — callers turn that into
    a clear "Go Live isn't switched on yet" rather than a broken stream.
    """
    from .reel_premium import live_configured

    provider = (settings.LIVE_PROVIDER or "").strip().lower()
    if not live_configured():
        raise LiveNotConfigured(
            "Live streaming isn't configured on this deployment. "
            "Set LIVE_PROVIDER and the matching provider keys to enable Go Live."
        )
    if provider == "mux":
        return await _create_mux()
    if provider == "cloudflare":
        return await _create_cloudflare()
    if provider == "livekit":
        return await _create_livekit(room_hint or "chatmood-live")
    raise LiveNotConfigured(f"Unknown LIVE_PROVIDER: {provider!r}")


async def destroy_stream(provider: str, stream_id: str) -> bool:
    """Best-effort teardown so a finished broadcast stops billing.

    Never raises: a stream the provider already reaped, or a transient API
    error, must not stop us marking the reel as ended in our own database.
    """
    if not stream_id:
        return False
    try:
        p = (provider or "").lower()
        if p == "mux":
            await _delete_mux(stream_id)
        elif p == "cloudflare":
            await _delete_cloudflare(stream_id)
        else:
            return False  # livekit rooms expire on their own
        return True
    except Exception as e:
        log.warning("live stream teardown failed (%s/%s): %s", provider, stream_id, e)
        return False
