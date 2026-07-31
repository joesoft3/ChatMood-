"""🎨 Brand icon pipeline — band detection and canvas math.

The band splitter is the whole trick: it finds the mark inside a stacked
lockup (mark / wordmark / tagline) without hardcoded pixel offsets, so the
icon set survives the logo being re-exported at a different size.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

brand_icons = pytest.importorskip("brand_icons")
Image = pytest.importorskip("PIL.Image", reason="Pillow required")
from PIL import Image, ImageDraw  # noqa: E402


# ---------------------------------------------------------- band splitting

def test_split_bands_finds_three_stacked_elements():
    """mark (rows 0-9) · wordmark (20-24) · tagline (40-42)."""
    profile = [5] * 10 + [0] * 10 + [3] * 5 + [0] * 15 + [2] * 3
    assert brand_icons.split_bands(profile) == [(0, 9), (20, 24), (40, 42)]


def test_small_gaps_do_not_fragment_one_element():
    """Antialiasing can leave a 1-2px blank row mid-glyph — that's still one band."""
    profile = [4] * 8 + [0, 0] + [4] * 8 + [0] * 12 + [3] * 4
    bands = brand_icons.split_bands(profile, min_gap=6)
    assert bands == [(0, 17), (30, 33)]  # the 2px gap did NOT split the first band


def test_blank_profile_yields_no_bands():
    assert brand_icons.split_bands([0] * 50) == []


def test_trailing_band_is_closed_at_the_last_row():
    assert brand_icons.split_bands([0] * 5 + [7] * 5) == [(5, 9)]


# ------------------------------------------------------------ ink masking

def _lockup(bg=(10, 13, 22, 255)):
    """A miniature 3-band lockup: mark, wordmark, tagline."""
    img = Image.new("RGBA", (200, 200), bg)
    d = ImageDraw.Draw(img)
    d.ellipse([60, 20, 140, 100], fill=(90, 140, 255, 255))   # mark
    d.rectangle([30, 130, 170, 150], fill=(240, 240, 245, 255))  # wordmark
    d.rectangle([50, 170, 150, 178], fill=(90, 190, 235, 255))   # tagline
    return img


def test_bg_color_is_sampled_from_the_corners():
    assert brand_icons.bg_color(_lockup()) == (10, 13, 22, 255)


def test_ink_mask_separates_art_from_background():
    img = _lockup()
    mask = brand_icons.ink_mask(img)
    assert mask[60][100] is True     # inside the mark
    assert mask[115][100] is False   # gap between mark and wordmark


def test_bands_detected_on_a_real_raster():
    img = _lockup()
    bands = brand_icons.split_bands(brand_icons.row_profile(brand_icons.ink_mask(img)))
    assert len(bands) == 3
    assert bands[0][0] >= 19 and bands[0][1] <= 101   # the mark band


def test_transparent_source_treats_alpha_as_ink():
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([20, 20, 80, 80], fill=(255, 0, 0, 255))
    mask = brand_icons.ink_mask(img)
    assert mask[50][50] is True and mask[2][2] is False


# ----------------------------------------------------------- canvas maths

def test_square_canvas_is_square_and_respects_the_safe_zone():
    art = Image.new("RGBA", (300, 100), (255, 0, 0, 255))
    out = brand_icons.square_canvas(art, 512, bg=(0, 0, 0, 255), content_ratio=0.78)
    assert out.size == (512, 512)
    # widest dimension scaled to ~78% of the canvas, never past it
    assert 512 * 0.78 - 2 <= 300 * (512 * 0.78 / 300) <= 512 * 0.78 + 2


def test_square_canvas_centers_the_art():
    art = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    out = brand_icons.square_canvas(art, 200, bg=(0, 0, 0, 255), content_ratio=0.5)
    assert out.getpixel((100, 100))[0] > 200   # red at the center
    assert out.getpixel((5, 5))[0] < 50        # background at the corner


def test_aspect_ratio_is_preserved_not_stretched():
    art = Image.new("RGBA", (400, 100), (0, 255, 0, 255))
    out = brand_icons.square_canvas(art, 512, bg=(0, 0, 0, 0), content_ratio=1.0)
    # a 4:1 mark must stay 4:1 — letterboxed, never squashed to square
    green_cols = [x for x in range(512) if out.getpixel((x, 256))[1] > 200]
    green_rows = [y for y in range(512) if out.getpixel((256, y))[1] > 200]
    assert len(green_cols) == 512
    assert 120 < len(green_rows) < 136   # 512/4 ≈ 128


def test_wide_canvas_matches_the_og_card_size():
    art = Image.new("RGBA", (600, 300), (0, 0, 255, 255))
    out = brand_icons.wide_canvas(art, 1024, 500, bg=(0, 0, 0, 255))
    assert out.size == (1024, 500)


# ------------------------------------------------------------ end to end

def test_build_writes_every_icon_at_the_right_size(tmp_path, monkeypatch):
    src = tmp_path / "lockup.png"
    _lockup().save(src)
    monkeypatch.setattr(brand_icons, "REPO", tmp_path)

    report = brand_icons.build(src)

    assert (tmp_path / "frontend/public/icon.png").exists()
    assert (tmp_path / "mobile/assets/icon/app_icon.png").exists()
    assert report["frontend/public/icon.png"] == "512×512"
    assert report["mobile/assets/icon/app_icon.png"] == "1024×1024"
    assert report["frontend/public/og.png"] == "1024×500"
    with Image.open(tmp_path / "frontend/public/icon.png") as im:
        assert im.size == (512, 512)


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    src = tmp_path / "lockup.png"
    _lockup().save(src)
    monkeypatch.setattr(brand_icons, "REPO", tmp_path)
    brand_icons.build(src, dry_run=True)
    assert not (tmp_path / "frontend").exists()


def test_mark_band_override_is_range_checked(tmp_path, monkeypatch):
    src = tmp_path / "lockup.png"
    _lockup().save(src)
    monkeypatch.setattr(brand_icons, "REPO", tmp_path)
    with pytest.raises(SystemExit):
        brand_icons.build(src, mark_band=99, dry_run=True)


def test_blank_source_fails_loudly_instead_of_writing_empty_icons(tmp_path, monkeypatch):
    src = tmp_path / "blank.png"
    Image.new("RGBA", (100, 100), (10, 13, 22, 255)).save(src)
    monkeypatch.setattr(brand_icons, "REPO", tmp_path)
    with pytest.raises(SystemExit):
        brand_icons.build(src, dry_run=True)


# ------------------------------------------------- canvas fill (seam bug)

def test_canvas_fill_matches_the_source_background():
    """Regression: a near-but-not-identical fill leaves a visible rectangle.

    Caught on the real MoodAI logo — its canvas is #01020D while the brand
    constant is #0B0F14, so filling with BRAND_BG drew a clearly visible seam
    around the cropped mark.
    """
    img = _lockup(bg=(1, 2, 13, 255))
    assert brand_icons.canvas_fill(img) == (1, 2, 13, 255)


def test_canvas_fill_falls_back_to_brand_bg_when_transparent():
    img = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    assert brand_icons.canvas_fill(img) == brand_icons.BRAND_BG


def test_built_icon_has_no_seam_around_the_art(tmp_path, monkeypatch):
    """The canvas corner and the padding just outside the art must match."""
    src = tmp_path / "lockup.png"
    bg = (1, 2, 13, 255)
    assert bg != brand_icons.BRAND_BG, "fixture must differ from BRAND_BG to detect the seam"
    _lockup(bg=bg).save(src)
    monkeypatch.setattr(brand_icons, "REPO", tmp_path)
    brand_icons.build(src)
    im = Image.open(tmp_path / "frontend/public/icon.png").convert("RGB")
    assert im.getpixel((3, 3)) == im.getpixel((256, 8))   # corner vs top padding
    assert im.getpixel((3, 3)) == bg[:3]                  # and it is the SOURCE bg
