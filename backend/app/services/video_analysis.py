"""Video file analysis: ffmpeg samples frames + audio track → Grok vision captions +
Whisper transcript → an LLM scene-by-scene summary. Needs ffmpeg on the backend
image (installed in backend/Dockerfile); degrades gracefully without it."""

import asyncio
import base64
import glob
import logging
import os
import shutil
import tempfile

from ..config import settings
from .llm import llm

log = logging.getLogger(__name__)

VIDEO_EXTS = {"mp4", "mov", "webm", "mkv", "m4v"}

# Frame sampling strategies
SAMPLING_UNIFORM = "uniform"          # fixed interval (default)
SAMPLING_SCENE = "scene"              # scene-change detection
SAMPLING_KEYFRAME = "keyframe"        # sample only I-frames


class VideoAnalysisError(Exception):
    pass


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


async def _run(cmd: list[str], timeout: int = 120) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise VideoAnalysisError(f"ffmpeg timed out on: {' '.join(cmd[:3])}")
    if proc.returncode != 0:
        raise VideoAnalysisError(f"ffmpeg failed: {err.decode(errors='ignore')[:200]}")


async def _caption_frame(path: str) -> str | None:
    try:
        b64 = base64.b64encode(open(path, "rb").read()).decode()
        text = await llm.complete(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Describe this video frame in 1-2 sentences: subjects, setting, action, any on-screen text.",
                        },
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
            model=settings.MODEL_VISION,
            max_tokens=160,
        )
        return (text or "").strip() or None
    except Exception as e:
        log.warning("frame caption failed: %s", e)
        return None


async def analyze_video_file(
    data: bytes,
    ext: str,
    *,
    sampling: str = SAMPLING_UNIFORM,
    interval_sec: float = 5.0,
    max_frames: int | None = None,
    scene_threshold: float = 0.3,
) -> dict:
    """Extract + understand. Returns {frames, captions, audio_wav_bytes}.

    New frame sampling strategies (v1.9.8+):
    - uniform (default): fixed interval, one frame every N seconds
    - scene: scene-change detection (threshold 0.3), captures motion events
    - keyframe: sample only I-frames (most visually distinct frames)
    """
    if not have_ffmpeg():
        raise VideoAnalysisError("ffmpeg isn't installed on the backend image — video analysis unavailable")
    cap = max_frames if max_frames is not None else settings.VIDEO_ANALYSIS_FRAMES
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, f"input.{ext}")
        with open(src, "wb") as fh:
            fh.write(data)
        try:
            vf = build_sample_filter(sampling, interval_sec, cap, scene_threshold)
            await _run(
                [
                    "ffmpeg", "-y", "-i", src,
                    "-vf", vf,
                    "-frames:v", str(cap),
                    "-q:v", "4",
                    os.path.join(td, "frame%02d.jpg"),
                ],
                120,
            )
        except VideoAnalysisError as e:
            raise VideoAnalysisError(f"Could not read this video ({e})")
        frame_paths = sorted(glob.glob(os.path.join(td, "frame*.jpg")))

        wav = os.path.join(td, "audio.wav")
        audio_bytes = b""
        try:
            await _run(["ffmpeg", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-t", "720", "-f", "wav", wav], 120)
            if os.path.getsize(wav) > 8000:
                audio_bytes = open(wav, "rb").read()
        except (VideoAnalysisError, OSError):
            audio_bytes = b""  # silent video — frames only

        captions = [c for c in [await _caption_frame(p) for p in frame_paths] if c]
        return {"frames": len(frame_paths), "captions": captions, "audio_wav_bytes": audio_bytes}


def video_ext(filename: str) -> str | None:
    ext = os.path.splitext((filename or "").lower())[1].lstrip(".")
    return ext if ext in VIDEO_EXTS else None


def build_sample_filter(
    strategy: str = SAMPLING_UNIFORM,
    interval_sec: float = 5.0,
    max_frames: int = 6,
    scene_threshold: float = 0.3,
) -> str:
    """Build an ffmpeg -vf string for intelligent frame sampling.

    - uniform:  fps=1/<interval> (one frame every N seconds)
    - scene:    select='gte(scene,0.3)', then cap frames
    - keyframe: select='eq(pict_type,I)' with interval throttle
    """
    if strategy == SAMPLING_SCENE:
        return (
            f"select='gte(scene,{scene_threshold})',"
            f"scale=768:-2,fps=1/30,"
            f"trim=duration={max(1, max_frames * 5)}"
        )
    if strategy == SAMPLING_KEYFRAME:
        return f"select='eq(pict_type,I)',scale=768:-2,fps=1/{interval_sec}"
    # uniform default
    return f"fps=1/{max(1, interval_sec)},scale=768:-2"
