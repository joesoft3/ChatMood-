"""⭐ Reel premium — one place that answers "can this creator do that?".

Every gate on the Reel surface resolves through `entitlements()`, for the same
reason the watermark rule lives in one function: a perk that silently stops
applying is lost revenue, and one that wrongly blocks a paying creator is a
support ticket. Two answers to the same question must not be able to diverge.

The catalogue is also what the **paywall UI renders from**, so a locked feature
always explains itself with the same wording the server enforces — you can't
ship a lock the backend doesn't actually apply, or vice versa.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import settings

# Effects reserved for Pro. Deliberately the three "look expensive" grades —
# the free set still covers every everyday need, so the paywall reads as an
# upgrade rather than a mutilation.
PREMIUM_EFFECTS = frozenset({"noir", "dream", "vintage"})

# Upload ceilings (MB) and clip length (seconds) per tier.
FREE_MAX_MB = 60
PRO_MAX_MB = 100
FREE_MAX_SECONDS = 60
PRO_MAX_SECONDS = 180


@dataclass(frozen=True)
class Perk:
    id: str
    label: str
    detail: str
    free: bool          # available on the free plan?
    emoji: str = "⭐"

    def as_dict(self, unlocked: bool) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "detail": self.detail,
            "emoji": self.emoji,
            "free": self.free,
            "unlocked": unlocked,
        }


PERKS: tuple[Perk, ...] = (
    Perk("no_watermark", "Watermark-free reels", "Post without the ChatMood badge burned into your video.", False, "🏷"),
    Perk("premium_effects", "Cinematic effects", "Noir, Dream and Vintage grades — the looks that read as film.", False, "🎨"),
    Perk("hd_export", "1080p HD export", "Publish at full 1080×1920 instead of 720p.", False, "📺"),
    Perk("long_clips", f"{PRO_MAX_SECONDS // 60}-minute clips", f"Post up to {PRO_MAX_SECONDS // 60} minutes ({PRO_MAX_MB} MB) instead of {FREE_MAX_SECONDS}s.", False, "⏱"),
    Perk("go_live", "Go Live", "Broadcast to the feed in real time with a live viewer count.", False, "🔴"),
    Perk("analytics", "Creator analytics", "Per-reel views, likes, saves and share breakdowns over time.", False, "📊"),
    Perk("post", "Unlimited posting", "Upload and share as many reels as you like.", True, "🎬"),
    Perk("duet", "Duets & reposts", "Collaborate with any creator on the feed.", True, "🎭"),
)


def is_premium(user) -> bool:
    """The single entitlement predicate for the Reel surface.

    Mirrors the watermark rule: any non-free plan counts, and admins are treated
    as premium so owner demos and store screenshots aren't crippled. A future
    tier is premium by default — the safe direction to be wrong in.
    """
    if user is None:
        return False
    plan = (getattr(user, "plan", "free") or "free").strip().lower()
    if plan not in ("", "free"):
        return True
    try:
        from ..api.deps import is_effective_admin

        return bool(is_effective_admin(user))
    except Exception:
        return False


def entitlements(user) -> dict:
    """Everything the Reel UI needs to render locks, caps and the paywall."""
    premium = is_premium(user)
    return {
        "premium": premium,
        "plan": (getattr(user, "plan", "free") or "free"),
        "perks": [p.as_dict(premium or p.free) for p in PERKS],
        "premium_effects": sorted(PREMIUM_EFFECTS),
        "max_mb": PRO_MAX_MB if premium else FREE_MAX_MB,
        "max_seconds": PRO_MAX_SECONDS if premium else FREE_MAX_SECONDS,
        "resolution": "1080x1920" if premium else "720x1280",
        "watermark": not premium,
        "go_live": premium and live_configured(),
        "live_provider": settings.LIVE_PROVIDER or "",
        "live_configured": live_configured(),
    }


def max_bytes(user) -> int:
    return (PRO_MAX_MB if is_premium(user) else FREE_MAX_MB) * 1024 * 1024


def max_seconds(user) -> int:
    return PRO_MAX_SECONDS if is_premium(user) else FREE_MAX_SECONDS


def effect_allowed(user, effect: str) -> bool:
    return (effect or "none") not in PREMIUM_EFFECTS or is_premium(user)


def upgrade_message(what: str) -> str:
    """Consistent, actionable copy for a 402. Never a bare 'forbidden'."""
    return f"{what} is a Pro feature — upgrade in Settings → Upgrade to unlock it."


# ───────────────────────────────────────────────────────── live streaming

def live_configured() -> bool:
    """Is a real broadcast provider wired up?

    Go Live needs infrastructure this repo does not host (RTMP ingest + HLS/WebRTC
    egress). Rather than fake it, the feature reports itself unavailable until a
    provider key exists — the UI then says "coming soon" honestly instead of
    handing a creator a dead Start button.
    """
    provider = (settings.LIVE_PROVIDER or "").strip().lower()
    if provider == "mux":
        return bool(settings.MUX_TOKEN_ID and settings.MUX_TOKEN_SECRET)
    if provider == "cloudflare":
        return bool(settings.CLOUDFLARE_STREAM_TOKEN and settings.CLOUDFLARE_ACCOUNT_ID)
    if provider == "livekit":
        return bool(settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET and settings.LIVEKIT_URL)
    return False


def live_providers() -> list[dict]:
    """Provider readiness for the UI — honest about what still needs keys."""
    return [
        {
            "id": "mux",
            "label": "Mux Video",
            "configured": bool(settings.MUX_TOKEN_ID and settings.MUX_TOKEN_SECRET),
            "env": "MUX_TOKEN_ID + MUX_TOKEN_SECRET",
        },
        {
            "id": "cloudflare",
            "label": "Cloudflare Stream",
            "configured": bool(settings.CLOUDFLARE_STREAM_TOKEN and settings.CLOUDFLARE_ACCOUNT_ID),
            "env": "CLOUDFLARE_STREAM_TOKEN + CLOUDFLARE_ACCOUNT_ID",
        },
        {
            "id": "livekit",
            "label": "LiveKit",
            "configured": bool(
                settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET and settings.LIVEKIT_URL
            ),
            "env": "LIVEKIT_API_KEY + LIVEKIT_API_SECRET + LIVEKIT_URL",
        },
    ]
