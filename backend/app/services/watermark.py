"""🏷 Output watermarking — free tier gets a badge, paid tiers and admins don't.

**The entitlement rule lives in exactly one place** (`should_watermark`), because
a watermark that leaks onto a paying customer's export is a refund request, and
one that silently *stops* applying to free users is lost revenue. Every render
path calls the same predicate rather than re-deriving "is this user premium?".

Who is exempt:
  • any paid plan (anything that isn't `free` — future tiers are exempt by
    default, which is the safe direction to be wrong in), and
  • admins / the deployment owner (`is_effective_admin`: the DB flag OR an
    ADMIN_EMAILS entry), so owner demos and store screenshots come out clean.

**Why Pillow renders the badge instead of ffmpeg's `drawtext`:** this codebase
already documents that the shipped ffmpeg build has no `drawtext`
(see `api/routes/reels.py`), and serverless images carry no system fonts. Pillow
is a hard dependency, the repo bundles a font, and rendering the badge to a
transparent PNG once means the *same* asset composites onto both images and
video through a plain `overlay` filter — which every ffmpeg build supports.

Everything here is best-effort: a watermark failure must never destroy or block
a render the user already paid for in tokens. On any error the original file is
left untouched.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

from ..config import settings

log = logging.getLogger(__name__)

# Cache the rendered badge per (text, width) — it is identical for every free
# user, so re-rasterizing it on each render would be pure waste.
_badge_cache: dict[tuple[str, int], str] = {}


def is_premium_plan(plan: str | None) -> bool:
    """Any plan that isn't the free tier counts as paid.

    Deliberately a denylist of one rather than an allowlist: when a new tier is
    added, the failure mode is "we forgot to watermark a paying customer",
    not "we stamped one".
    """
    return (plan or "free").strip().lower() not in ("", "free")


def should_watermark(user) -> bool:
    """The single source of truth for whether this user's output gets a badge."""
    if not settings.WATERMARK_ENABLED:
        return False
    if user is None:
        return True  # anonymous/public render → treat as free tier
    if is_premium_plan(getattr(user, "plan", "free")):
        return False
    try:
        from ..api.deps import is_effective_admin

        if is_effective_admin(user):
            return False
    except Exception:  # never let an import/lookup problem decide entitlement
        log.warning("admin check failed during watermark decision — defaulting to free-tier behavior")
    return True


def watermark_text() -> str:
    """Badge wording — defaults to the deployment's own app name."""
    return (settings.WATERMARK_TEXT or f"Made with {settings.APP_NAME}").strip()[:60]


def _font(size: int):
    """Bundled bold font first (serverless images ship none), then system paths."""
    from PIL import ImageFont

    from .designer import _FONT_CANDIDATES

    for path in _FONT_CANDIDATES:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_badge(text: str, target_w: int, dst: Path) -> bool:
    """Rasterize a translucent pill badge to a transparent PNG. Pure-ish + testable.

    Sized as a fraction of the destination width so the badge reads the same on
    a 900px reel and a 4000px print export instead of vanishing on one of them.
    """
    try:
        from PIL import Image, ImageDraw

        scale = max(0.4, min(2.5, target_w / 1280))
        font_size = max(11, int(22 * scale))
        pad_x, pad_y = int(14 * scale), int(9 * scale)
        radius = int(10 * scale)

        font = _font(font_size)
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        box = probe.textbbox((0, 0), text, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]

        w, h = tw + pad_x * 2, th + pad_y * 2
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Dark translucent pill + near-white text: legible over both bright and
        # dark artwork without a hard border fighting the composition.
        draw.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=radius, fill=(0, 0, 0, 130))
        draw.text((pad_x - box[0], pad_y - box[1]), text, font=font, fill=(255, 255, 255, 225))

        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, "PNG")
        return dst.exists()
    except Exception as e:
        log.warning("watermark badge render failed: %s", e)
        return False


def _badge_for(target_w: int) -> str | None:
    """Path to a cached badge PNG for this output width (rendered on first use)."""
    text = watermark_text()
    key = (text, max(320, (target_w // 320) * 320))  # bucket widths → few variants
    hit = _badge_cache.get(key)
    if hit and Path(hit).exists():
        return hit
    dst = Path(settings.MEDIA_DIR) / f"_wm_{abs(hash(key)) % (10**10)}.png"
    if render_badge(text, key[1], dst):
        _badge_cache[key] = str(dst)
        return str(dst)
    return None


def build_overlay_cmd(src: str, badge: str, dst: str, *, video: bool, pad: int = 24) -> list[str]:
    """ffmpeg argv compositing the badge bottom-right (pure builder — unit-tested).

    Bottom-right matches where this codebase already stamps brand logos, and the
    `overlay` filter is universally available (unlike `drawtext`).
    """
    from .soundtrack import ffmpeg_path

    graph = f"[0:v][1:v]overlay=W-w-{pad}:H-h-{pad}"
    cmd = [ffmpeg_path() or "ffmpeg", "-y", "-i", src, "-i", badge, "-filter_complex", graph]
    if video:
        # Re-encode video (an overlay can't be stream-copied) but keep audio as-is.
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart"]
    else:
        cmd += ["-frames:v", "1"]
    cmd.append(dst)
    return cmd


async def apply_to_file(path: Path, *, video: bool | None = None, width: int | None = None) -> bool:
    """Stamp a rendered file in place. Returns True only if the file was changed.

    Fail-open by construction: if ffmpeg or the badge is unavailable, or the
    encode fails, the ORIGINAL file is left exactly as it was. Losing the
    watermark is an acceptable outcome; losing the user's render is not.
    """
    from .soundtrack import ffmpeg_path

    try:
        if not path.exists() or not ffmpeg_path():
            return False
        if video is None:
            video = path.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv")
        badge = _badge_for(width or _probe_width(path) or 1280)
        if not badge:
            return False

        tmp = path.parent / f"{path.stem}_wm{path.suffix}"
        cmd = build_overlay_cmd(str(path), badge, str(tmp), video=bool(video))
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=settings.WATERMARK_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            tmp.unlink(missing_ok=True)
            log.warning("watermark timed out for %s — serving clean render", path.name)
            return False

        if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            log.warning("watermark ffmpeg failed for %s: %s", path.name,
                        (err or b"").decode(errors="replace")[-300:])
            return False
        tmp.replace(path)  # atomic swap — readers never see a half-written file
        return True
    except Exception as e:
        log.warning("watermark skipped for %s: %s", path, e)
        return False


def apply_to_bytes(data: bytes, *, suffix: str = ".png") -> bytes:
    """Stamp raw image bytes (the in-chat image path never touches MEDIA_DIR).

    Returns the ORIGINAL bytes unchanged on any failure.
    """
    try:
        from PIL import Image

        import io

        img = Image.open(io.BytesIO(data))
        img = img.convert("RGBA")
        badge_path = _badge_for(img.width)
        if not badge_path:
            return data

        badge = Image.open(badge_path).convert("RGBA")
        pad = max(10, int(img.width * 0.018))
        img.alpha_composite(badge, (img.width - badge.width - pad, img.height - badge.height - pad))

        out = io.BytesIO()
        if suffix.lower() in (".jpg", ".jpeg"):
            img.convert("RGB").save(out, "JPEG", quality=92)
        else:
            img.save(out, "PNG")
        return out.getvalue()
    except Exception as e:
        log.warning("byte watermark skipped: %s", e)
        return data


def _probe_width(path: Path) -> int | None:
    """Best-effort pixel width so the badge scales to the artwork."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.width
    except Exception:
        pass
    try:
        from .soundtrack import ffmpeg_path

        ff = ffmpeg_path()
        if not ff:
            return None
        # ffprobe sits beside ffmpeg in every build we ship with.
        probe = str(Path(ff).parent / "ffprobe")
        if not Path(probe).exists():
            return None
        out = subprocess.run(
            [probe, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=20,
        )
        return int((out.stdout or "").strip().split(",")[0])
    except Exception:
        return None
