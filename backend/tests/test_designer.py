"""🎨 Design Studio unit tests — presets, prompt compiler, provider gating,
ffmpeg argv builders, data-uri fetch, and the generate pipeline (mocked)."""

import base64
from pathlib import Path

import pytest

from app.api.routes.media import SERVED_NAME_RE
from app.services import designer as dzn
from app.services import soundtrack


# ------------------------------------------------------------------ presets
def test_kind_presets_have_print_tier_bigger_than_web():
    assert set(dzn.KIND_PRESETS) == {"flyer", "logo", "banner", "sticker"}
    for k, p in dzn.KIND_PRESETS.items():
        assert p.print_w > p.web_w and p.print_h > p.web_h, k
        # aspect consistency between web and print tiers (≤1% drift)
        assert abs(p.print_w / p.print_h - p.web_w / p.web_h) < 0.01, k
        assert p.gpt_image_size == f"{p.web_w}x{p.web_h}"


def test_print_tier_is_true_300dpi_paper_grade():
    """Every kind's print master must clear the resolution a print shop needs:
    ≥2400 px on the short edge (A5-at-300-DPI class) and ≥2× the web tier."""
    for k, p in dzn.KIND_PRESETS.items():
        assert min(p.print_w, p.print_h) >= 2400, f"{k} print tier too small for paper"
        assert p.print_scale >= 2.0, f"{k} barely upscales ({p.print_scale}×)"
        assert p.print_dpi == 300, k


def test_cutout_kinds_never_crop_and_allow_transparency():
    """Cropping a logo/sticker destroys the mark — those kinds must contain-fit."""
    assert dzn.TRANSPARENT_KINDS == {"logo", "sticker"}
    for k in dzn.TRANSPARENT_KINDS:
        assert dzn.KIND_PRESETS[k].fit == "contain", k
        assert dzn.KIND_PRESETS[k].transparent_ok, k
    # full-bleed kinds still cover-crop so there are no letterbox bars in print
    for k in ("flyer", "banner"):
        assert dzn.KIND_PRESETS[k].fit == "cover", k
        assert not dzn.KIND_PRESETS[k].transparent_ok, k


def test_sticker_preset_is_square_diecut_grade():
    p = dzn.KIND_PRESETS["sticker"]
    assert p.web_w == p.web_h and p.print_w == p.print_h  # square die-cut
    assert p.print_w == 3000  # 10 cm at 300 DPI
    assert "die-cut" in p.hint and "outline" in p.hint


def test_style_and_palette_tables_non_empty():
    assert len(dzn.STYLE_PRESETS) >= 5 and "minimal" in dzn.STYLE_PRESETS
    assert "auto" in dzn.PALETTES and len(dzn.PALETTES) >= 5


# ------------------------------------------------------------ prompt compile
def test_compile_prompt_weaves_kind_style_palette_and_brief():
    p = dzn.compile_design_prompt("Launch party Friday 8pm", "flyer", "neon", "sunset")
    assert "flyer" in p.lower()
    assert dzn.STYLE_PRESETS["neon"] in p
    assert dzn.PALETTES["sunset"] in p
    assert "Launch party Friday 8pm" in p
    assert "watermark" in p.lower()


def test_compile_prompt_transparent_and_auto_palette():
    p = dzn.compile_design_prompt("Acme coffee cup mark", "logo", "minimal", "auto", transparent=True)
    assert "transparent background" in p
    for word in dzn.PALETTES.values():
        if word:
            assert word not in p  # auto palette injects no palette clause


def test_compile_prompt_unknown_kind_falls_back():
    p = dzn.compile_design_prompt("x", "poster", "nope", "nope")
    assert "flyer" in p.lower()


# ----------------------------------------------------------- provider gating
def test_native_opts_only_for_gpt_image_family():
    assert dzn.supports_native_image_opts("gpt-image-1")
    assert not dzn.supports_native_image_opts("grok-2-image-1212")
    assert dzn.provider_image_kwargs("grok-2-image-1212", "flyer", False) == {}


def test_native_kwargs_size_quality_and_transparent():
    kw = dzn.provider_image_kwargs("gpt-image-1", "logo", transparent=True)
    # transparency also forces PNG — webp/jpeg would flatten the cut-out
    assert kw == {"size": "1024x1024", "quality": "high",
                  "background": "transparent", "output_format": "png"}
    kw2 = dzn.provider_image_kwargs("gpt-image-1", "banner", transparent=False)
    assert kw2["size"] == "1536x1024" and "background" not in kw2
    assert "output_format" not in kw2
    assert dzn.provider_image_kwargs("gpt-image-1", "sticker", True)["size"] == "1024x1024"


# --------------------------------------------------------------- argv builds
def test_normalize_cmd_cover_crop(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_normalize_cmd("in.png", "out.png", 1024, 1536)
    assert cmd[:3] == ["/bin/ffmpeg", "-y", "-i"]
    vf = cmd[cmd.index("-vf") + 1]
    assert "force_original_aspect_ratio=increase" in vf and "crop=1024:1536" in vf
    assert cmd[-1] == "out.png"


def test_normalize_contain_fit_never_crops_the_mark(monkeypatch):
    """A logo whose render is off-aspect must be letterboxed, not amputated."""
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_normalize_cmd("in.png", "out.png", 1024, 1024, fit="contain")
    vf = cmd[cmd.index("-vf") + 1]
    assert "force_original_aspect_ratio=decrease" in vf
    assert "crop=" not in vf                       # nothing is thrown away
    assert "pad=1024:1024:(ow-iw)/2:(oh-ih)/2:color=white" in vf   # print-safe, not black


def test_normalize_contain_pads_transparent_when_alpha(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_normalize_cmd("in.png", "out.png", 1024, 1024, fit="contain", alpha=True)
    vf = cmd[cmd.index("-vf") + 1]
    assert "color=#00000000" in vf and vf.endswith("format=rgba")
    assert cmd[cmd.index("-pix_fmt") + 1] == "rgba"


def test_normalize_flattens_to_rgb_when_opaque(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_normalize_cmd("in.png", "out.png", 1024, 1536)
    assert cmd[cmd.index("-pix_fmt") + 1] == "rgb24"
    assert cmd[cmd.index("-compression_level") + 1] == dzn.PNG_COMPRESSION


def test_upscale_cmd_300dpi_lanczos(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_upscale_cmd("in.png", "out.png", 2480, 3508)
    assert "scale=2480:3508:flags=lanczos" in cmd[cmd.index("-vf") + 1]
    i = cmd.index("-dpi")
    assert cmd[i + 1] == "300"


def test_upscale_sharpens_after_lanczos(monkeypatch):
    """Lanczos enlargement is soft — the print master gets an unsharp pass,
    applied after the scale and only on luma so cut-out edges stay clean."""
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    vf = dzn.build_upscale_cmd("in.png", "out.png", 4096, 4096)[
        dzn.build_upscale_cmd("in.png", "out.png", 4096, 4096).index("-vf") + 1
    ]
    assert vf.index("scale=") < vf.index("unsharp="), "sharpen must follow the upscale"
    assert vf.endswith(dzn.PRINT_UNSHARP)
    assert dzn.PRINT_UNSHARP.endswith(":0")  # alpha/chroma amount 0
    plain = dzn.build_upscale_cmd("in.png", "out.png", 2048, 2048, sharpen=False)
    assert "unsharp" not in plain[plain.index("-vf") + 1]


def test_upscale_keeps_alpha_for_cutouts(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_upscale_cmd("in.png", "out.png", 4096, 4096, alpha=True)
    assert cmd[cmd.index("-vf") + 1].endswith("format=rgba")
    assert cmd[cmd.index("-pix_fmt") + 1] == "rgba"


# ------------------------------------------------------------------- fetch
def test_fetch_image_bytes_decodes_data_uri():
    raw = b"\x89PNG\r\n\x1a\n" + b"x" * 600
    uri = "data:image/png;base64," + base64.b64encode(raw).decode()
    import asyncio

    assert asyncio.run(dzn._fetch_image_bytes(uri)) == raw


# ---------------------------------------------------------------- pipeline
def _fake_png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def test_generate_design_no_ffmpeg_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(dzn.settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: None)

    async def fake_brief(idea, kind, style, palette):
        return f"AD: {idea}"

    async def fake_image(prompt, **kw):
        assert kw == {}  # default model is grok-2-image-1212 → no native opts
        return "data:image/png;base64," + base64.b64encode(_fake_png()).decode()

    monkeypatch.setattr(dzn, "enhance_brief", fake_brief)
    monkeypatch.setattr(dzn.llm, "generate_image", fake_image)

    import asyncio

    out = asyncio.run(dzn.generate_design("Coffee shop launch", "flyer", "bold", "gold"))
    assert out["brief"] == "AD: Coffee shop launch"
    assert (tmp_path / out["file"]).exists() and (tmp_path / out["print_file"]).exists()
    assert out["note"] and "ffmpeg" in out["note"]
    # raw staging file must be cleaned up
    assert not list(tmp_path.glob("*_raw.png"))


def test_generate_design_transparent_retry_without_native_bg(monkeypatch, tmp_path):
    monkeypatch.setattr(dzn.settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: None)
    monkeypatch.setattr(dzn.settings, "MODEL_IMAGE", "gpt-image-1")
    monkeypatch.setattr(dzn, "enhance_brief", lambda i, k, s, p: i)  # sync? no — always async in prod
    calls = []

    async def fake_image(prompt, **kw):
        calls.append(dict(kw))
        if kw.get("background") == "transparent":
            return None  # provider rejected transparent
        return "data:image/png;base64," + base64.b64encode(_fake_png()).decode()

    async def fake_brief(idea, kind, style, palette):
        return idea

    monkeypatch.setattr(dzn, "enhance_brief", fake_brief)
    monkeypatch.setattr(dzn.llm, "generate_image", fake_image)

    import asyncio

    out = asyncio.run(dzn.generate_design("Acme mark", "logo", "minimal", "auto", transparent=True, enhance=True))
    assert calls[0].get("background") == "transparent"
    assert "background" not in calls[1]
    assert out["native"] is True


def test_generate_design_pipeline_uses_kind_fit_and_alpha(monkeypatch, tmp_path):
    """Sticker/logo runs must contain-fit and carry alpha through both tiers;
    flyers must cover-crop and flatten."""
    monkeypatch.setattr(dzn.settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    monkeypatch.setattr(dzn.settings, "MODEL_IMAGE", "gpt-image-1")
    seen: list[list[str]] = []

    def fake_run(cmd):
        seen.append(cmd)
        Path(cmd[-1]).write_bytes(_fake_png())

    async def fake_brief(idea, kind, style, palette):
        return idea

    async def fake_image(prompt, **kw):
        return "data:image/png;base64," + base64.b64encode(_fake_png()).decode()

    monkeypatch.setattr(dzn, "_run", fake_run)
    monkeypatch.setattr(dzn, "enhance_brief", fake_brief)
    monkeypatch.setattr(dzn.llm, "generate_image", fake_image)

    import asyncio

    out = asyncio.run(dzn.generate_design("Kente robot mascot", "sticker",
                                          transparent=True, enhance=False))
    norm_vf, up_vf = (c[c.index("-vf") + 1] for c in seen[:2])
    assert "force_original_aspect_ratio=decrease" in norm_vf and "crop=" not in norm_vf
    assert "#00000000" in norm_vf                      # transparent die-cut padding
    assert "unsharp" in up_vf and "scale=3000:3000" in up_vf
    assert all(c[c.index("-pix_fmt") + 1] == "rgba" for c in seen[:2])
    assert out["alpha"] is True and out["fit"] == "contain"
    assert (out["print_width"], out["print_height"], out["print_dpi"]) == (3000, 3000, 300)

    seen.clear()
    out2 = asyncio.run(dzn.generate_design("Chop bar opening", "flyer",
                                           transparent=True, enhance=False))
    assert "crop=1024:1536" in seen[0][seen[0].index("-vf") + 1]   # full-bleed
    assert all(c[c.index("-pix_fmt") + 1] == "rgb24" for c in seen[:2])
    assert out2["alpha"] is False and out2["fit"] == "cover"       # flyers ignore transparency


def test_generate_design_rejects_unknown_kind():
    import asyncio

    with pytest.raises(dzn.DesignError):
        asyncio.run(dzn.generate_design("x", "postcard"))


# ------------------------------------------------------------- janitor guard
def test_design_filenames_are_not_publicly_served_or_swept():
    """Design files must neither be served by the public /media/files route
    nor swept by the 24h video janitor — they persist until owner deletes."""
    web = "a" * 32 + "_d.png"
    pr = "a" * 32 + "_dp.png"
    for name in (web, pr):
        assert not SERVED_NAME_RE.match(name), name
        assert not soundtrack.MEDIA_NAME_RE.match(name), name
        assert not soundtrack.MEDIA_POSTER_RE.match(name), name
