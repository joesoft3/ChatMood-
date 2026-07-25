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


# =========================================================== 🎞 timeline edit
# The reel editor is a small non-linear timeline: an ordered list of video
# clips (each trimmable, with its own effect and volume) plus one optional
# audio bed and one optional picture-in-picture overlay. Everything renders in
# a SINGLE ffmpeg pass — chaining passes would re-encode the footage once per
# operation and visibly soften it.

MAX_CLIPS = 10               # keeps the filtergraph (and render time) sane
MAX_TOTAL_SECONDS = 180
OVERLAY_CORNERS = ("tr", "tl", "br", "bl")
FPS = 30
SR = 48000                   # one sample rate everywhere: concat needs it uniform


@dataclass
class Clip:
    """One segment on the timeline."""
    path: str
    start: float = 0.0            # trim in-point, seconds
    end: float | None = None      # trim out-point (None → to the end)
    effect: str = "none"
    speed: float = 1.0
    volume: float = 1.0           # 0 = muted, 1 = as recorded
    has_audio: bool = True

    @property
    def duration(self) -> float | None:
        if self.end is None:
            return None
        return max(0.05, self.end - self.start) / max(0.5, min(self.speed, 2.0))


@dataclass
class Overlay:
    """Picture-in-picture clip pinned to a corner."""
    path: str
    corner: str = "tr"
    scale: float = 0.30           # fraction of canvas width
    volume: float = 0.0           # silent by default — PiP audio usually clashes
    has_audio: bool = False


@dataclass
class AudioBed:
    """A music/voiceover track laid under the whole timeline."""
    path: str
    volume: float = 0.8
    start: float = 0.0


def _clamp(v: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(float(v), hi))
    except (TypeError, ValueError):
        return lo


def _overlay_xy(corner: str, pad: int = 40) -> str:
    return {
        "tr": f"W-w-{pad}:{pad}",
        "tl": f"{pad}:{pad}",
        "br": f"W-w-{pad}:H-h-{pad}",
        "bl": f"{pad}:H-h-{pad}",
    }.get(corner, f"W-w-{pad}:{pad}")


def build_timeline_cmd(
    clips: list[Clip],
    dst: str,
    *,
    bed: AudioBed | None = None,
    overlay: Overlay | None = None,
    original_volume: float = 1.0,
) -> list[str]:
    """Render the whole timeline in one pass (pure argv builder).

    Video: each clip is trimmed → normalised to the reel canvas → graded →
    speed-shifted, then all clips are concatenated.

    Audio is the fiddly part. `concat` demands every segment carry an audio
    stream, but a screen recording or a muted clip may have none — so silent
    clips get an `anullsrc` input of matching length. Without that the filter
    fails with "Stream specifier ':a' matches no streams" and the whole render
    dies (the same class of bug that broke duets on silent clips).
    """
    if not clips:
        raise StudioError("a timeline needs at least one clip")
    if len(clips) > MAX_CLIPS:
        raise StudioError(f"a reel can hold at most {MAX_CLIPS} clips")

    exe = ffmpeg_path() or "ffmpeg"
    inputs: list[str] = []
    silent_slots: list[tuple[int, float]] = []   # (input index, seconds)
    idx = 0
    clip_inputs: list[int] = []

    for c in clips:
        inputs += ["-i", c.path]
        clip_inputs.append(idx)
        idx += 1

    overlay_idx = None
    if overlay:
        inputs += ["-i", overlay.path]
        overlay_idx = idx
        idx += 1

    bed_idx = None
    if bed:
        inputs += ["-i", bed.path]
        bed_idx = idx
        idx += 1

    # Silent stand-ins are appended last so clip indices stay stable.
    silent_for: dict[int, int] = {}
    for n, c in enumerate(clips):
        if c.has_audio:
            continue
        secs = c.duration or 10.0
        inputs += ["-f", "lavfi", "-t", f"{secs:.3f}",
                   "-i", f"anullsrc=channel_layout=stereo:sample_rate={SR}"]
        silent_for[n] = idx
        silent_slots.append((idx, secs))
        idx += 1

    parts: list[str] = []
    vlabels: list[str] = []
    alabels: list[str] = []

    for n, c in enumerate(clips):
        i = clip_inputs[n]
        speed = _clamp(c.speed, 0.5, 2.0)
        # -- video
        v = f"[{i}:v]"
        seg = []
        if c.start or c.end is not None:
            trim = f"trim=start={c.start:.3f}"
            if c.end is not None:
                trim += f":end={c.end:.3f}"
            seg.append(trim)
            seg.append("setpts=PTS-STARTPTS")
        seg.append(f"scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase")
        seg.append(f"crop={REEL_W}:{REEL_H}")
        seg.append("setsar=1")
        look = EFFECTS.get(c.effect or "none", EFFECTS["none"]).vf
        if look:
            seg.append(look)
        if speed != 1.0:
            seg.append(f"setpts={1 / speed:.4f}*PTS")
        seg.append(f"fps={FPS}")
        parts.append(f"{v}{','.join(seg)}[v{n}]")
        vlabels.append(f"[v{n}]")

        # -- audio (real stream, or the silent stand-in)
        src = f"[{silent_for[n]}:a]" if n in silent_for else f"[{i}:a]"
        aseg = []
        if n not in silent_for and (c.start or c.end is not None):
            at = f"atrim=start={c.start:.3f}"
            if c.end is not None:
                at += f":end={c.end:.3f}"
            aseg.append(at)
        aseg.append(f"aresample={SR}")
        if speed != 1.0 and n not in silent_for:
            aseg.append(f"atempo={speed:.4f}")
        vol = _clamp(c.volume, 0.0, 2.0) * _clamp(original_volume, 0.0, 2.0)
        if vol != 1.0:
            aseg.append(f"volume={vol:.3f}")
        aseg.append("asetpts=N/SR/TB")
        parts.append(f"{src}{','.join(aseg)}[a{n}]")
        alabels.append(f"[a{n}]")

    n_clips = len(clips)
    if n_clips > 1:
        parts.append("".join(f"{v}{a}" for v, a in zip(vlabels, alabels))
                     + f"concat=n={n_clips}:v=1:a=1[vcat][acat]")
        vout, aout = "[vcat]", "[acat]"
    else:
        vout, aout = vlabels[0], alabels[0]

    # -- picture-in-picture
    if overlay and overlay_idx is not None:
        ow = max(80, int(REEL_W * _clamp(overlay.scale, 0.15, 0.6)))
        parts.append(f"[{overlay_idx}:v]scale={ow}:-2,setsar=1[ovl]")
        # shortest=0 → the base keeps playing after a short overlay ends
        parts.append(f"{vout}[ovl]overlay={_overlay_xy(overlay.corner)}:shortest=0[vpip]")
        vout = "[vpip]"
        if overlay.has_audio and overlay.volume > 0:
            parts.append(f"[{overlay_idx}:a]aresample={SR},"
                         f"volume={_clamp(overlay.volume, 0.0, 2.0):.3f},asetpts=N/SR/TB[ovla]")
            parts.append(f"{aout}[ovla]amix=inputs=2:duration=first:dropout_transition=0"
                         f",aresample={SR}[amixed]")
            aout = "[amixed]"

    # -- audio bed under everything (the "volume split")
    if bed and bed_idx is not None:
        bseg = [f"aresample={SR}"]
        if bed.start:
            bseg.insert(0, f"atrim=start={bed.start:.3f}")
        bseg.append(f"volume={_clamp(bed.volume, 0.0, 2.0):.3f}")
        bseg.append("asetpts=N/SR/TB")
        parts.append(f"[{bed_idx}:a]{','.join(bseg)}[bed]")
        # duration=first → the bed is trimmed to the video, never extends it
        parts.append(f"{aout}[bed]amix=inputs=2:duration=first:dropout_transition=0"
                     f",aresample={SR}[aout]")
        aout = "[aout]"

    cmd = [exe, "-y", *inputs, "-filter_complex", ";".join(parts),
           "-map", vout, "-map", aout, "-c:a", "aac", "-b:a", "128k"]
    cmd += _tail(dst)
    return cmd


def probe_duration(path: str) -> float:
    """Clip length in seconds (0.0 when unknown) — parsed from `ffmpeg -i`
    because imageio-ffmpeg ships no ffprobe."""
    exe = ffmpeg_path()
    if not exe:
        return 0.0
    try:
        out = subprocess.run([exe, "-hide_banner", "-i", path],
                             capture_output=True, text=True, timeout=30).stderr
    except Exception:  # noqa: BLE001
        return 0.0
    m = re.search(r"Duration: (\d+):(\d\d):(\d\d\.\d+)", out)
    if not m:
        return 0.0
    h, mi, sec = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + sec
