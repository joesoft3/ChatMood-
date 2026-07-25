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


def test_max_cascade_attempts_configurable(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "VIDEO_MAX_CASCADE_ATTEMPTS", 5)
    monkeypatch.setattr(settings, "VIDEO_PROVIDER", "reel")
    assert video.MAX_CASCADE_ATTEMPTS == 5


def test_lean_retry_preserved():
    # The structured helper is preserved per-provider (reel/pollinations/xai)
    assert callable(video._lean_retry)
