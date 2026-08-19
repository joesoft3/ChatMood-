"""Missing media-service tests — cascade, progress, structured errors, lean-retry."""

import pytest

from app.services.media import (
    VideoGenerationError,
    VideoNotConfigured,
    VideoOptions,
    VideoProgress,
    build_video_payload,
    compile_prompt,
    video,
)


def test_video_progress_structured():
    p = VideoProgress(stage="scenes", done=2, total=4, note="halfway")
    d = p.to_dict()
    assert d == {"stage": "scenes", "done": 2, "total": 4, "note": "halfway"}


def test_video_progress_omits_empty_note():
    """Progress events without context stay a stable 3-key wire contract."""
    assert VideoProgress(stage="compositing", done=1, total=1).to_dict() == {
        "stage": "compositing", "done": 1, "total": 1,
    }


def test_video_errors_structured():
    assert VideoNotConfigured.CATEGORY == "configuration"
    assert VideoNotConfigured.RECOVERABLE is True
    assert VideoGenerationError.CATEGORY == "generation"
    assert VideoGenerationError.RECOVERABLE is True


def test_video_errors_prefixed():
    exc = VideoNotConfigured("key missing")
    assert "[video:config]" in str(exc)
    exc2 = VideoGenerationError("timeout")
    assert "[video:generation]" in str(exc2)


def test_compile_prompt_layers_presets():
    out = compile_prompt("lighthouse", VideoOptions(style="cinematic", quality="720p"))
    assert "lighthouse" in out
    assert "cinematic" in out
    assert "720p" not in out  # quality tag is separate, but preset present
    assert "Avoid:" in out


def test_build_video_payload_full():
    payload = build_video_payload("model-x", "compiled", VideoOptions(duration=8, aspect_ratio="16:9", quality="1080p"))
    assert payload["model"] == "model-x"
    assert payload["prompt"] == "compiled"
    assert payload["duration"] == 8
    assert payload["aspect_ratio"] == "16:9"
    assert payload["resolution"] == "1080p"


def test_build_video_payload_with_image():
    payload = build_video_payload("model-x", "compiled", VideoOptions(), image={"url": "http://img"})
    assert payload["image"] == {"url": "http://img"}


# ───────────────────────────── free video providers (gemini veo + huggingface)


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_gemini_video_requires_key(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    with pytest.raises(VideoNotConfigured):
        _run(video._gemini_veo("a kente robot dancing adowa", VideoOptions(duration=8)))


def test_hf_video_requires_token(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "HF_API_TOKEN", "")
    with pytest.raises(VideoNotConfigured):
        _run(video._hf_video("a kente robot dancing adowa", VideoOptions(duration=8)))


def test_video_cascade_prefers_gemini_over_reel(monkeypatch):
    from app.config import settings
    from app.services import media as media_mod

    monkeypatch.setattr(settings, "VIDEO_PROVIDER", "gemini,reel")
    monkeypatch.setattr(settings, "VIDEO_MAX_CASCADE_ATTEMPTS", 1)

    async def _fake_veo(self, prompt, opts):
        return "https://api.test/api/v1/media/files/veo-fake.mp4", False

    monkeypatch.setattr(media_mod.VideoService, "_gemini_veo", _fake_veo)
    url, _ = _run(video.generate("tide rolling over labadi beach", VideoOptions(duration=6)))
    assert url == "https://api.test/api/v1/media/files/veo-fake.mp4"


def test_video_cascade_falls_through_quota_exhaustion(monkeypatch):
    from app.config import settings
    from app.services import media as media_mod

    monkeypatch.setattr(settings, "VIDEO_PROVIDER", "gemini,huggingface,reel")
    monkeypatch.setattr(settings, "VIDEO_MAX_CASCADE_ATTEMPTS", 1)

    async def _quota(self, prompt, opts):
        raise VideoGenerationError("Gemini Veo free quota exhausted (429)")

    async def _no_token(self, prompt, opts):
        raise VideoNotConfigured("Set HF_API_TOKEN for huggingface video.")

    async def _reel_ok(self, prompt, opts, on_progress=None):
        return "https://api.test/api/v1/media/files/reel-fake.mp4", False

    monkeypatch.setattr(media_mod.VideoService, "_gemini_veo", _quota)
    monkeypatch.setattr(media_mod.VideoService, "_hf_video", _no_token)
    monkeypatch.setattr(media_mod.VideoService, "_reel", _reel_ok)
    url, _ = _run(video.generate("makola market at golden hour", VideoOptions()))
    assert url == "https://api.test/api/v1/media/files/reel-fake.mp4"


def test_free_video_unknown_member_still_cascades(monkeypatch):
    from app.config import settings
    from app.services import media as media_mod

    monkeypatch.setattr(settings, "VIDEO_PROVIDER", "teapot,reel")
    monkeypatch.setattr(settings, "VIDEO_MAX_CASCADE_ATTEMPTS", 1)

    async def _reel_ok(self, prompt, opts, on_progress=None):
        return "https://api.test/api/v1/media/files/reel-fake.mp4", False

    monkeypatch.setattr(media_mod.VideoService, "_reel", _reel_ok)
    url, _ = _run(video.generate("paper boats in the rain", VideoOptions()))
    assert url.endswith("reel-fake.mp4")


def test_veo_video_uri_parser():
    payload = {
        "done": True,
        "response": {
            "generateVideoResponse": {
                "generatedSamples": [
                    {"video": {"uri": "https://generativelanguage.googleapis.com/v1beta/files/x:download"}}
                ]
            }
        },
    }
    assert "files/x" in video._veo_video_uri(payload)
    assert video._veo_video_uri({"done": False}) is None
    assert video._veo_video_uri({"response": {"generateVideoResponse": {"generatedSamples": []}}}) is None
    # snake_case variant (belt + braces for upstream wire drift)
    assert video._veo_video_uri(
        {"response": {"generate_video_response": {"generated_samples": [{"video": {"uri": "u"}}]}}}
    ) == "u"


def test_max_cascade_attempts_configurable(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "VIDEO_MAX_CASCADE_ATTEMPTS", 5)
    monkeypatch.setattr(settings, "VIDEO_PROVIDER", "reel")
    assert video.MAX_CASCADE_ATTEMPTS == 5
    # live read: lowering it again takes effect without a restart, and it never
    # degenerates to zero attempts even if misconfigured
    monkeypatch.setattr(settings, "VIDEO_MAX_CASCADE_ATTEMPTS", 1)
    assert video.MAX_CASCADE_ATTEMPTS == 1
    monkeypatch.setattr(settings, "VIDEO_MAX_CASCADE_ATTEMPTS", 0)
    assert video.MAX_CASCADE_ATTEMPTS == 1


def test_lean_retry_preserved():
    # The structured helper is preserved per-provider (reel/pollinations/xai)
    assert callable(video._lean_retry)
