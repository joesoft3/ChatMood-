"""Zero-IO status helpers for the text / image / video "brain" routing.

These are operational summaries for the owner UI: they explain which provider is
currently active for each modality and whether a configured fallback path exists.
No network calls happen here — this is pure config/runtime introspection.
"""

from __future__ import annotations

from typing import Any

from ..config import settings
from .llm import llm
from .media import _ffmpeg_exe


def _video_chain() -> list[str]:
    return [p.strip().lower() for p in (settings.VIDEO_PROVIDER or "reel").split(",") if p.strip()]


def text_brain_status() -> dict[str, Any]:
    flagship_provider, flagship_model = llm._failover(None, settings.MODEL_CHAT)
    fast_provider, fast_model = llm._failover(None, settings.MODEL_FAST)
    flagship_rescue = llm._rescue_chain(flagship_provider, flagship_model)
    fast_rescue = llm._rescue_chain(fast_provider, fast_model)
    return {
        "primary": {
            "provider": flagship_provider or "xai",
            "model": flagship_model,
            "configured": bool(settings.XAI_API_KEY or flagship_provider != "xai"),
        },
        "fast": {
            "provider": fast_provider or "xai",
            "model": fast_model,
        },
        "fallbacks": {
            "arena": bool(settings.ARENA_AI_API_KEY and settings.ARENA_AI_MODEL),
            "llm_fallback": bool(settings.LLM_FALLBACK_PROVIDER and settings.LLM_FALLBACK_MODEL),
            "freetheai": bool(settings.FREETHEAI_API_KEY and settings.FREETHEAI_MODEL),
            "extrabrain": bool(settings.EXTRA_BRAIN_API_KEY and settings.EXTRA_BRAIN_MODEL),
        },
        "rescue_chain": [{"provider": p or "xai", "model": m} for p, m in flagship_rescue],
        "fast_rescue_chain": [{"provider": p or "xai", "model": m} for p, m in fast_rescue],
        "ready": bool(flagship_model),
    }


def image_brain_status() -> dict[str, Any]:
    # IMAGE_FALLBACK_PROVIDER is a comma-separated cascade of FREE engines
    # (pollinations needs no key; gemini/huggingface/cloudflare ride free daily
    # quotas). With no xAI key the first entry is the primary image engine.
    chain = [p.strip().lower() for p in (settings.IMAGE_FALLBACK_PROVIDER or "").split(",") if p.strip()]
    free_primary = bool(chain) and not settings.XAI_API_KEY
    mode = chain[0] if free_primary else "xai"
    primary_models = {
        "pollinations": settings.POLLINATIONS_MODEL,
        "gemini": settings.GEMINI_IMAGE_MODEL,
        "huggingface": settings.HF_IMAGE_MODEL,
        "hf": settings.HF_IMAGE_MODEL,
        "cloudflare": settings.WORKERS_AI_IMAGE_MODEL,
        "workers-ai": settings.WORKERS_AI_IMAGE_MODEL,
    }
    cf_id = settings.WORKERS_AI_ACCOUNT_ID or settings.CLOUDFLARE_ACCOUNT_ID
    cf_token = settings.WORKERS_AI_API_TOKEN or settings.CLOUDFLARE_API_TOKEN
    return {
        "mode": mode,
        "primary": {
            "provider": mode,
            "model": primary_models.get(mode, settings.MODEL_IMAGE),
        },
        "xai_configured": bool(settings.XAI_API_KEY),
        "fallback_provider": (settings.IMAGE_FALLBACK_PROVIDER or "").strip().lower() or None,
        "fallback_chain": chain,
        "pollinations": {
            "enabled": "pollinations" in chain,
            "model": settings.POLLINATIONS_MODEL,
            "url": settings.POLLINATIONS_IMAGE_URL,
        },
        "free_engines": {
            "gemini": {"enabled": "gemini" in chain, "configured": bool(settings.GEMINI_API_KEY), "model": settings.GEMINI_IMAGE_MODEL},
            "huggingface": {
                "enabled": "huggingface" in chain or "hf" in chain,
                "configured": bool(settings.HF_API_TOKEN),
                "model": settings.HF_IMAGE_MODEL,
            },
            "cloudflare": {
                "enabled": "cloudflare" in chain or "workers-ai" in chain,
                "configured": bool(cf_id and cf_token),
                "model": settings.WORKERS_AI_IMAGE_MODEL,
            },
        },
        "persist": bool(settings.IMAGE_PERSIST),
        "ready": bool(free_primary or settings.XAI_API_KEY),
    }


def video_brain_status() -> dict[str, Any]:
    ffmpeg_ready = bool(_ffmpeg_exe())
    chain = _video_chain()
    providers = []
    for name in chain:
        if name == "reel":
            ready = bool(settings.REEL_ENABLED and ffmpeg_ready)
            reason = "ffmpeg ready" if ready else "needs ffmpeg + REEL_ENABLED=true"
        elif name == "pollinations":
            ready = bool(settings.POLLINATIONS_API_KEY)
            reason = "API key set" if ready else "needs POLLINATIONS_API_KEY"
        elif name in ("gemini", "veo"):
            ready = bool(settings.GEMINI_API_KEY)
            reason = "GEMINI_API_KEY set" if ready else "needs GEMINI_API_KEY (free AI Studio key)"
        elif name in ("huggingface", "hf"):
            ready = bool(settings.HF_API_TOKEN)
            reason = "HF_API_TOKEN set" if ready else "needs HF_API_TOKEN (free HF token)"
        elif name == "xai":
            ready = bool(settings.XAI_API_KEY)
            reason = "xAI key set" if ready else "needs XAI_API_KEY"
        else:
            ready = False
            reason = "unknown provider"
        providers.append({"provider": name, "ready": ready, "reason": reason})

    narration_cloudflare = bool(
        settings.EMBED_API_KEY and (settings.EMBED_API_BASE_URL or "").startswith("https://api.cloudflare.com")
    )
    return {
        "chain": chain,
        "providers": providers,
        "ffmpeg": ffmpeg_ready,
        "reel_enabled": bool(settings.REEL_ENABLED),
        "storyboard": bool(settings.REEL_STORYBOARD),
        "narration": {
            "enabled": bool(settings.REEL_NARRATION),
            "extra_brain_tts": bool(settings.EXTRA_BRAIN_API_KEY),
            "cloudflare_aura": narration_cloudflare,
            "openai_soundtrack": bool(settings.OPENAI_API_KEY),
        },
        "ready": any(p["ready"] for p in providers),
    }


def brain_status() -> dict[str, Any]:
    return {
        "text": text_brain_status(),
        "image": image_brain_status(),
        "video": video_brain_status(),
    }
