"""Test coverage for video file analysis — frame sampling + audio transcript + vision captioning."""

import pytest

from app.services import video_analysis


def test_video_ext_recognizes_known_formats():
    assert video_analysis.video_ext("clip.mp4") == "mp4"
    assert video_analysis.video_ext("movie.mov") == "mov"
    assert video_analysis.video_ext("clip.mkv") == "mkv"
    assert video_analysis.video_ext("unknown.xyz") is None
    assert video_analysis.video_ext("") is None


def test_have_ffmpeg_detects_binary(monkeypatch):
    monkeypatch.setattr(video_analysis.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    assert video_analysis.have_ffmpeg() is True


def test_have_ffmpeg_false_when_missing(monkeypatch):
    monkeypatch.setattr(video_analysis.shutil, "which", lambda name: None)
    assert video_analysis.have_ffmpeg() is False


def test_video_analysis_raises_without_ffmpeg(monkeypatch):
    monkeypatch.setattr(video_analysis, "have_ffmpeg", lambda: False)
    with pytest.raises(video_analysis.VideoAnalysisError, match="ffmpeg"):
        import asyncio
        asyncio.run(video_analysis.analyze_video_file(b"fake", "mp4"))


def test_build_sample_filter_uniform():
    vf = video_analysis.build_sample_filter(
        video_analysis.SAMPLING_UNIFORM, interval_sec=5.0, max_frames=6
    )
    assert "fps=1/5" in vf and "scale=768:-2" in vf


def test_build_sample_filter_scene():
    vf = video_analysis.build_sample_filter(
        video_analysis.SAMPLING_SCENE, interval_sec=5.0, max_frames=6, scene_threshold=0.3
    )
    assert "gte(scene,0.3)" in vf and "scale=768:-2" in vf


def test_build_sample_filter_keyframe():
    vf = video_analysis.build_sample_filter(
        video_analysis.SAMPLING_KEYFRAME, interval_sec=5.0, max_frames=6
    )
    assert "eq(pict_type,I)" in vf and "scale=768:-2" in vf
