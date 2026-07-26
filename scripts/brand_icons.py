#!/usr/bin/env python3
"""🎨 Brand icon pipeline — one source lockup → every icon the apps need.

    python3 scripts/brand_icons.py path/to/chatmood-logo.png

A brand logo is usually a *lockup*: the mark on top, the wordmark under it, a
tagline under that. An app icon needs the **mark alone**, square and centered —
cropping that by hand once per size is how icon sets drift out of sync.

This script does it deterministically:

  frontend/public/icon.png        512×512   mark, maskable safe-zone
  frontend/public/logo.png        trimmed   mark + wordmark (no tagline)
  frontend/public/og.png          1024×500  full lockup, social card
  mobile/assets/icon/app_icon.png 1024×1024 mark (flutter_launcher_icons source)

How the mark is found (`split_bands`): the lockup is separated by horizontal
bands of background. We build a row-wise "ink profile", split it on empty runs,
and take the topmost band — that's the mark. No hardcoded pixel offsets, so it
survives the logo being re-exported at another size.

Pass --mark-band N to override if a logo's layout confuses the detector.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - the message IS the behavior
    sys.exit("Pillow is required:  pip install pillow")

REPO = Path(__file__).resolve().parent.parent

# Matches the app's midnight canvas (manifest background_color / adaptive icon).
BRAND_BG = (11, 15, 20, 255)  # #0B0F14

# A maskable icon may be cropped to a circle by the launcher; keeping content
# inside ~80% of the canvas is the safe zone Android/Chrome document.
MASKABLE_CONTENT = 0.78


def bg_color(img: Image.Image) -> tuple[int, int, int, int]:
    """Background sampled from the four corners (the logo's own canvas color)."""
    w, h = img.size
    corners = [img.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    opaque = [c for c in corners if c[3] > 8]
    if not opaque:
        return (0, 0, 0, 0)  # fully transparent source
    # the modal corner, so one odd corner can't skew it
    return max(set(opaque), key=opaque.count)


def ink_mask(img: Image.Image, tol: int = 26) -> list[list[bool]]:
    """Per-pixel "is this artwork, not background?" mask."""
    bg = bg_color(img)
    px = img.load()
    w, h = img.size
    transparent_bg = bg[3] <= 8
    out = []
    for y in range(h):
        row = []
        for x in range(w):
            r, g, b, a = px[x, y]
            if a <= 8:
                row.append(False)
            elif transparent_bg:
                row.append(True)
            else:
                row.append(abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > tol)
            # note: alpha-only sources short-circuit above
        out.append(row)
    return out


def row_profile(mask: list[list[bool]]) -> list[int]:
    return [sum(row) for row in mask]


def split_bands(profile: list[int], min_ink: int = 1, min_gap: int = 6) -> list[tuple[int, int]]:
    """Contiguous (top, bottom) row bands of artwork, separated by empty runs.

    `min_gap` stops antialiasing noise or a tight mark/wordmark spacing from
    fragmenting one element into several bands. Pure function — unit-tested.
    """
    bands: list[tuple[int, int]] = []
    start: int | None = None
    gap = 0
    for y, ink in enumerate(profile):
        if ink >= min_ink:
            if start is None:
                start = y
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                bands.append((start, y - gap))
                start = None
                gap = 0
    if start is not None:
        bands.append((start, len(profile) - 1))
    return [b for b in bands if b[1] >= b[0]]


def column_extent(mask: list[list[bool]], top: int, bottom: int) -> tuple[int, int]:
    """Left/right ink bounds within a row band."""
    left, right = None, None
    for y in range(top, bottom + 1):
        row = mask[y]
        for x, v in enumerate(row):
            if v:
                if left is None or x < left:
                    left = x
                if right is None or x > right:
                    right = x
    if left is None:
        return 0, len(mask[0]) - 1
    return left, right


def crop_band(img: Image.Image, mask: list[list[bool]], band: tuple[int, int]) -> Image.Image:
    top, bottom = band
    left, right = column_extent(mask, top, bottom)
    return img.crop((left, top, right + 1, bottom + 1))


def square_canvas(art: Image.Image, size: int, *, bg, content_ratio: float) -> Image.Image:
    """Center `art` on a square canvas, scaled to fill `content_ratio` of it."""
    target = max(1, int(size * content_ratio))
    scale = min(target / art.width, target / art.height)
    new = (max(1, round(art.width * scale)), max(1, round(art.height * scale)))
    art = art.resize(new, Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), bg)
    canvas.alpha_composite(art, ((size - new[0]) // 2, (size - new[1]) // 2))
    return canvas


def wide_canvas(art: Image.Image, w: int, h: int, *, bg, content_ratio: float = 0.82) -> Image.Image:
    scale = min((w * content_ratio) / art.width, (h * content_ratio) / art.height)
    new = (max(1, round(art.width * scale)), max(1, round(art.height * scale)))
    art = art.resize(new, Image.LANCZOS)
    canvas = Image.new("RGBA", (w, h), bg)
    canvas.alpha_composite(art, ((w - new[0]) // 2, (h - new[1]) // 2))
    return canvas


def canvas_fill(img: Image.Image) -> tuple[int, int, int, int]:
    """Canvas color for the generated icons.

    Uses the SOURCE logo's own background rather than a hardcoded brand color:
    a cropped band carries its background with it, so filling the canvas with a
    near-but-not-identical color leaves a visible rectangular seam around the
    art (measured: source #01020D vs brand #0B0F14 — clearly visible on a phone
    home screen). Only a fully transparent source falls back to BRAND_BG.
    """
    bg = bg_color(img)
    return BRAND_BG if bg[3] <= 8 else bg


def build(source: Path, *, mark_band: int | None = None, dry_run: bool = False) -> dict[str, str]:
    img = Image.open(source).convert("RGBA")
    mask = ink_mask(img)
    bands = split_bands(row_profile(mask))
    if not bands:
        raise SystemExit(f"{source}: no artwork detected (is the image blank?)")

    idx = mark_band if mark_band is not None else 0
    if not 0 <= idx < len(bands):
        raise SystemExit(f"--mark-band {idx} out of range (found {len(bands)} bands)")

    mark = crop_band(img, mask, bands[idx])
    # logo.png = mark + wordmark (everything except a trailing tagline band)
    upper = bands[: max(1, len(bands) - 1)] if len(bands) > 2 else bands
    lock_top, lock_bottom = upper[0][0], upper[-1][1]
    lockup = crop_band(img, mask, (lock_top, lock_bottom))
    full = crop_band(img, mask, (bands[0][0], bands[-1][1]))

    fill = canvas_fill(img)  # match the source bg — a mismatch shows as a seam
    outputs = {
        "frontend/public/icon.png": square_canvas(
            mark, 512, bg=fill, content_ratio=MASKABLE_CONTENT
        ),
        "mobile/assets/icon/app_icon.png": square_canvas(
            mark, 1024, bg=fill, content_ratio=MASKABLE_CONTENT
        ),
        "frontend/public/logo.png": lockup,
        "frontend/public/og.png": wide_canvas(full, 1024, 500, bg=fill),
    }

    report = {
        "bands": str([f"{t}-{b}" for t, b in bands]),
        "mark": f"{mark.width}×{mark.height} (band {idx})",
    }
    for rel, im in outputs.items():
        dst = REPO / rel
        report[rel] = f"{im.width}×{im.height}"
        if dry_run:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith("logo.png"):
            im.save(dst, "PNG")          # keep the lockup's own transparency
        else:
            im.convert("RGBA").save(dst, "PNG")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate ChatMood icons from one source lockup.")
    ap.add_argument("source", type=Path, help="brand lockup PNG/JPG (mark + wordmark)")
    ap.add_argument("--mark-band", type=int, default=None,
                    help="0-based band index to use as the mark (default: topmost)")
    ap.add_argument("--dry-run", action="store_true", help="report sizes without writing")
    a = ap.parse_args()
    if not a.source.exists():
        raise SystemExit(f"source not found: {a.source}")
    for k, v in build(a.source, mark_band=a.mark_band, dry_run=a.dry_run).items():
        print(f"{k:34s} {v}")
    if not a.dry_run:
        print("\nNext:  cd mobile && dart run flutter_launcher_icons")


if __name__ == "__main__":
    main()
