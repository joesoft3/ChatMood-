"""🎬 Reel Studio — duet, effects and burned-in captions for creator reels.

Every ffmpeg invocation is a *pure argv builder* so the whole thing is
unit-testable without the binary (same pattern as services/soundtrack.py and
services/editor.py).

Three capabilities:

* **Duet** — stack your clip beside (or above) someone else's reel inside one
  9:16 frame, the way TikTok/Instagram duets read.
* **Effects** — a named look table (grade + optional motion), applied
  server-side on post. The browser previews the same looks live with CSS
  filters, so what a creator sees while editing matches what gets burned in.
* **Captions** — auto-transcribed with Whisper (reusing `editor.transcribe_srt`)
  and burned in via libass. NOTE: this ffmpeg build ships **without** the
  `drawtext` filter, so text goes through `subtitles=` (libass), which is both
  available and better at wrapping/outlining anyway.
"""

from __future__ import annotations

import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from .soundtrack import ffmpeg_path


class StudioError(Exception):
    pass


# Reel canvas: portrait 1080x1920 everywhere, so duets and effects compose
# predictably no matter what the creator uploaded.
REEL_W, REEL_H = 1080, 1920


# ------------------------------------------------------------------ effects
@dataclass(frozen=True)
class Effect:
    label: str
    emoji: str
    vf: str        # ffmpeg filter chain burned in server-side
    css: str       # equivalent CSS filter for the live browser preview


# `css` deliberately mirrors `vf` as closely as CSS allows: the preview is a
# promise about the render, so a look that can't be approximated in CSS
# doesn't belong in this table.
EFFECTS: dict[str, Effect] = {
    "none":    Effect("Original", "🎞", "", "none"),
    "warm":    Effect("Warm", "🌅",
                      "eq=brightness=0.03:saturation=1.12,colorbalance=rs=0.08:gs=0.02:bs=-0.06",
                      "saturate(1.12) sepia(0.18) brightness(1.03)"),
    "cool":    Effect("Cool", "❄️",
                      "eq=brightness=0.01:saturation=1.05,colorbalance=bs=0.08:rs=-0.05",
                      "saturate(1.05) hue-rotate(-10deg) brightness(1.01)"),
    "vivid":   Effect("Vivid", "🔥", "eq=contrast=1.15:saturation=1.35",
                      "contrast(1.15) saturate(1.35)"),
    "mono":    Effect("Mono", "🖤", "hue=s=0,eq=contrast=1.06",
                      "grayscale(1) contrast(1.06)"),
    "vintage": Effect("Vintage", "📼",
                      "curves=vintage,eq=saturation=0.85,vignette=PI/5",
                      "sepia(0.45) saturate(0.85) contrast(1.05)"),
    "dream":   Effect("Dream", "✨",
                      "eq=brightness=0.05:saturation=1.1,boxblur=2:1:cr=0:ar=0",
                      "saturate(1.1) brightness(1.05) blur(1px)"),
    "noir":    Effect("Noir", "🎬",
                      "hue=s=0,eq=contrast=1.35:brightness=-0.03,vignette=PI/4",
                      "grayscale(1) contrast(1.35) brightness(0.97)"),
}

# Playback-speed presets. atempo keeps audio pitch sane within 0.5–2.0, which
# is exactly the range we expose.
SPEEDS: dict[str, float] = {"0.5x": 0.5, "1x": 1.0, "1.5x": 1.5, "2x": 2.0}

DUET_LAYOUTS = ("side", "top", "green")  # green = your clip inset over theirs


def effect_catalog() -> list[dict]:
    """Serialized effect table — the studio UI renders straight from this."""
    return [
        {"id": k, "label": e.label, "emoji": e.emoji, "css": e.css}
        for k, e in EFFECTS.items()
    ]


def probe_has_audio(path: str) -> bool:
    """Does this file carry an audio stream?

    `ffprobe` is NOT shipped by the imageio-ffmpeg wheel (and isn't on PATH on
    slim hosts), so editor.has_audio_stream silently returns its optimistic
    default there. Referencing `[0:a]` on a silent clip then fails the entire
    duet filtergraph, so we parse `ffmpeg -i` stderr instead — that always
    exists, because it *is* the binary we render with.
    """
    exe = ffmpeg_path()
    if not exe:
        return False
    try:
        out = subprocess.run([exe, "-hide_banner", "-i", path],
                             capture_output=True, text=True, timeout=30).stderr
    except Exception:  # noqa: BLE001 — a probe must never break a render
        return False
    return bool(re.search(r"Stream #\d+:\d+.*: Audio:", out))


def _tail(dst: str, crf: str = "23") -> list[str]:
    return [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", crf,
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", dst,
    ]


# --------------------------------------------------------------------- duet
def build_duet_cmd(mine: str, theirs: str, dst: str, layout: str = "side",
                   seconds: int = 30, audio: str = "both",
                   mine_has_audio: bool = True, theirs_has_audio: bool = True) -> list[str]:
    """Compose a duet into one 1080x1920 frame (pure argv builder).

    layout="side"  → their clip left, yours right (the classic duet read)
    layout="top"   → theirs on top, yours underneath
    layout="green" → theirs full-frame with your clip as a corner inset

    `audio`: both | mine | theirs — a duet where two people talk over each
    other is unwatchable, so creators can mute a side.

    `*_has_audio` must reflect the real streams: referencing `[0:a]` on a
    silent clip makes ffmpeg fail the whole graph with "Stream specifier ':a'
    matches no streams", so a silent side degrades to the other one's track
    (or to no audio at all) instead of killing the render.
    """
    if layout not in DUET_LAYOUTS:
        raise StudioError(f"unknown duet layout: {layout}")

    if layout == "side":
        # each half is 540x1920 so the stacked result is exactly the canvas
        half_w, half_h = REEL_W // 2, REEL_H
        chain = (
            f"[0:v]scale={half_w}:{half_h}:force_original_aspect_ratio=increase,"
            f"crop={half_w}:{half_h},setsar=1[a];"
            f"[1:v]scale={half_w}:{half_h}:force_original_aspect_ratio=increase,"
            f"crop={half_w}:{half_h},setsar=1[b];"
            f"[a][b]hstack=inputs=2[v]"
        )
    elif layout == "top":
        half_w, half_h = REEL_W, REEL_H // 2
        chain = (
            f"[0:v]scale={half_w}:{half_h}:force_original_aspect_ratio=increase,"
            f"crop={half_w}:{half_h},setsar=1[a];"
            f"[1:v]scale={half_w}:{half_h}:force_original_aspect_ratio=increase,"
            f"crop={half_w}:{half_h},setsar=1[b];"
            f"[a][b]vstack=inputs=2[v]"
        )
    else:  # green — inset, bottom-right, ~32% width with a small margin
        inset_w = int(REEL_W * 0.32)
        margin = 28
        chain = (
            f"[0:v]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
            f"crop={REEL_W}:{REEL_H},setsar=1[bg];"
            f"[1:v]scale={inset_w}:-2,setsar=1[fg];"
            f"[bg][fg]overlay=W-w-{margin}:H-h-{margin}[v]"
        )

    cmd = [ffmpeg_path() or "ffmpeg", "-y", "-i", theirs, "-i", mine]

    # Resolve the requested mix against what actually exists on each input.
    want_theirs = audio in ("both", "theirs") and theirs_has_audio
    want_mine = audio in ("both", "mine") and mine_has_audio
    maps: list[str] = []
    if want_theirs and want_mine:
        # dropout_transition=0 avoids the pumping fade amix applies when one
        # side ends early
        chain += ";[0:a][1:a]amix=inputs=2:duration=shortest:dropout_transition=0[aout]"
        maps = ["-map", "[aout]"]
    elif want_theirs:
        chain += ";[0:a]anull[aout]"
        maps = ["-map", "[aout]"]
    elif want_mine:
        chain += ";[1:a]anull[aout]"
        maps = ["-map", "[aout]"]

    cmd += ["-filter_complex", chain, "-map", "[v]", *maps]
    if maps:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]   # both sides silent (or muted) → a clean silent duet
    cmd += ["-shortest", "-t", str(seconds)]
    cmd += _tail(dst)
    return cmd


# ------------------------------------------------------------------ effects
def build_effect_cmd(src: str, dst: str, effect: str = "none",
                     speed: float = 1.0, seconds: int | None = None) -> list[str]:
    """Apply a look (and optional speed change) to a clip (pure argv builder)."""
    if effect not in EFFECTS:
        raise StudioError(f"unknown effect: {effect}")
    speed = max(0.5, min(float(speed or 1.0), 2.0))

    vf_parts = [f"scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase",
                f"crop={REEL_W}:{REEL_H}", "setsar=1"]
    look = EFFECTS[effect].vf
    if look:
        vf_parts.append(look)
    if speed != 1.0:
        vf_parts.append(f"setpts={1 / speed:.4f}*PTS")

    cmd = [ffmpeg_path() or "ffmpeg", "-y", "-i", src, "-vf", ",".join(vf_parts)]
    if speed != 1.0:
        # atempo is only valid in 0.5–2.0 — the same range we clamp to above.
        cmd += ["-filter:a", f"atempo={speed:.4f}"]
    else:
        cmd += ["-c:a", "copy"]
    if seconds:
        cmd += ["-t", str(seconds)]
    cmd += _tail(dst)
    return cmd


# ----------------------------------------------------------------- captions
# libass style: high-contrast white on a soft shadow, sitting above the caption
# gradient so burned text never collides with the on-screen UI.
CAPTION_STYLES: dict[str, str] = {
    "clean": "FontName=DejaVu Sans,FontSize=15,Bold=1,PrimaryColour=&H00FFFFFF,"
             "OutlineColour=&H90000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=120",
    "bold":  "FontName=DejaVu Sans,FontSize=19,Bold=1,PrimaryColour=&H0000F0FF,"
             "OutlineColour=&HC0000000,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginV=130",
    "box":   "FontName=DejaVu Sans,FontSize=15,Bold=1,PrimaryColour=&H00FFFFFF,"
             "BackColour=&H90000000,BorderStyle=3,Outline=0,Shadow=0,Alignment=2,MarginV=120",
}


def _ass_escape(path: str) -> str:
    """subtitles= takes a filter-arg path: ':' and '\\' must be escaped or the
    graph parser splits the option in the wrong place (Windows paths, mostly)."""
    return path.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


def build_caption_cmd(src: str, dst: str, srt_path: str, style: str = "clean",
                      fontsdir: str | None = None) -> list[str]:
    """Burn an .srt into the video with libass (pure argv builder).

    This build of ffmpeg has no `drawtext` filter, so captions go through
    `subtitles=` — which is the better tool regardless: it wraps, outlines and
    times text without hand-rolled escaping.
    """
    st = CAPTION_STYLES.get(style, CAPTION_STYLES["clean"])
    sub = f"subtitles={_ass_escape(srt_path)}"
    if fontsdir:
        sub += f":fontsdir={_ass_escape(fontsdir)}"
    sub += f":force_style='{st}'"
    return [ffmpeg_path() or "ffmpeg", "-y", "-i", src, "-vf", sub,
            "-c:a", "copy", *_tail(dst)]


_SRT_TIME = re.compile(r"^\d\d:\d\d:\d\d,\d\d\d --> \d\d:\d\d:\d\d,\d\d\d")


def srt_to_text(srt: str, limit: int = 300) -> str:
    """Flatten an .srt into a caption string (for prefilling the post caption)."""
    out: list[str] = []
    for line in (srt or "").splitlines():
        s = line.strip()
        if not s or s.isdigit() or _SRT_TIME.match(s):
            continue
        out.append(s)
    return " ".join(out)[:limit].strip()


def write_srt(work: Path, text: str) -> Path:
    """Persist a manually-typed/edited SRT so it can be burned in."""
    p = work / "captions.srt"
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------- execution
def run(cmd: list[str], timeout: int = 300) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0 or (cmd[-1] and not Path(cmd[-1]).exists()):
        raise StudioError(f"reel studio render failed: {(proc.stderr or '')[-400:]}")


def new_reel_name() -> tuple[str, str]:
    """(<uuid>, '<uuid>_r.mp4') — the janitor-safe reel media name."""
    u = uuid.uuid4().hex
    return u, f"{u}_r.mp4"


def media_path(name: str) -> Path:
    return Path(settings.MEDIA_DIR) / name
