# 🎨 Brand icons

One source lockup → every icon the web app, PWA and Android client need.

```bash
python3 scripts/brand_icons.py path/to/chatmood-logo.png
cd mobile && dart run flutter_launcher_icons     # regenerate Android mipmaps
```

## What it produces

| Output | Size | Contents |
| --- | --- | --- |
| `frontend/public/icon.png` | 512×512 | the **mark alone**, maskable safe zone |
| `mobile/assets/icon/app_icon.png` | 1024×1024 | the mark (source for `flutter_launcher_icons`) |
| `frontend/public/logo.png` | trimmed | mark + wordmark (tagline dropped) |
| `frontend/public/og.png` | 1024×500 | the full lockup, social card |

## Why a script instead of hand-cropping

A brand logo is a **lockup** — mark on top, wordmark beneath, tagline under
that. An app icon needs the *mark alone*, square and centered. Cropping that by
hand once per size is how icon sets drift: the PWA icon ends up framed slightly
differently from the Android launcher, and nobody notices until the app is on a
home screen next to its own splash screen.

The script finds the mark structurally rather than by pixel offsets:

1. Build an **ink mask** — every pixel that differs from the background (sampled
   from the four corners, so it works on both the midnight canvas and a
   transparent export).
2. Collapse it to a **row profile** (ink pixels per row).
3. **Split into bands** on runs of empty rows. `min_gap=6` keeps antialiasing
   from fragmenting one glyph into several bands.
4. The **topmost band is the mark**. Override with `--mark-band N` if a
   particular layout confuses the detector.

Because it's structural, re-exporting the logo at another resolution produces
the same crop — no constants to update.

## Maskable safe zone

Android adaptive icons and Chrome's `purpose: "any maskable"` may crop the icon
to a circle. Content is scaled to **78%** of the canvas
(`MASKABLE_CONTENT`) and centered, so nothing important is clipped on a round
launcher. Aspect ratio is always preserved — a wide mark is letterboxed, never
squashed.

## Tests

```bash
cd backend && python -m pytest tests/test_brand_icons.py -q   # 16 tests
```

Band splitting (including the small-gap and blank-input cases), ink masking on
both opaque and transparent sources, canvas centering, aspect-ratio
preservation, and an end-to-end build that asserts every output size. A blank
source **fails loudly** rather than silently writing empty icons.
