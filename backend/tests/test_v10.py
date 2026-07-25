"""v1.0.0 units — 🖨 print exports, ⭐ brand icons/stamps, 📷➡️🎬 i2v payloads,
🤖 design agent tool registration."""

from app.api.routes.media import SERVED_NAME_RE
from app.services import designer as dzn
from app.services.media import VideoOptions, build_video_payload
from app.services import soundtrack
from app.services.plugins import tools as ptools


# --------------------------------------------------------------- print packs
def test_export_preset_table():
    assert set(dzn.EXPORT_PRESETS) == {
        "a4_bleed", "a5_bleed", "a3_bleed", "wa_status", "ig_post", "ig_square",
        "sticker_a4", "sticker_a4_mini",
    }
    assert dzn.EXPORT_PRESETS["a4_bleed"].bleed_px == 35
    assert dzn.EXPORT_PRESETS["wa_status"].bleed_px == 0
    # A3 is a true 300-DPI sheet (297×420 mm)
    a3 = dzn.EXPORT_PRESETS["a3_bleed"]
    assert (a3.trim_w, a3.trim_h) == (3508, 4961) and a3.bleed_px == 35


def test_export_dims_center_trim():
    d = dzn.export_dims("a4_bleed")
    assert d["bleed_w"] == 2480 + 70 and d["bleed_h"] == 3508 + 70
    assert d["canvas_w"] == d["bleed_w"] + 110
    assert d["trim_x"] == (d["canvas_w"] - 2480) // 2
    assert dzn.export_dims("wa_status")["canvas_w"] == 1080


def test_export_cmd_social_is_plain_crop(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_export_cmd("in.png", "out.png", "wa_status")
    vf = cmd[cmd.index("-vf") + 1]
    assert "crop=1080:1920" in vf
    assert "drawbox" not in vf and "-dpi" not in cmd


def test_export_cmd_print_has_marks_and_dpi(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_export_cmd("in.png", "out.png", "a4_bleed")
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.count("drawbox") == 8                      # 4 corners × 2 ticks
    assert "pad=" in vf and "white" in vf
    i = cmd.index("-dpi")
    assert cmd[i + 1] == "300"


def test_crop_mark_geometry():
    marks = dzn._crop_marks(100, 100, 2480, 3508, tick=38, gap=8)
    assert marks.count("drawbox") == 8
    for frag in ("x=54:y=100", "x=2588:y=100", "y=54", "y=3616"):
        assert frag in marks


def test_sticker_sheet_tiles_with_transparent_gutters(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_export_cmd("in.png", "out.png", "sticker_a4")
    vf = cmd[cmd.index("-vf") + 1]
    c = dzn.sheet_cell("sticker_a4")
    # one copy contain-fitted into a square cell, then tiled 3×4
    assert f"scale={c['cell']}:{c['cell']}:force_original_aspect_ratio=decrease" in vf
    assert f"tile=3x4:margin={dzn.SHEET_MARGIN}:padding={dzn.SHEET_GUTTER}" in vf
    # gaps and background stay transparent so a cutter can kiss-cut each copy
    assert "#00000000" in vf and "crop=" not in vf
    assert cmd[cmd.index("-pix_fmt") + 1] == "rgba"
    assert cmd[cmd.index("-dpi") + 1] == "300"
    assert "-loop" in cmd  # single still fed to the tile filter


def test_sticker_sheet_fits_inside_the_a4_page():
    for preset in dzn.STICKER_EXPORTS:
        p = dzn.EXPORT_PRESETS[preset]
        c = dzn.sheet_cell(preset)
        used_w = dzn.SHEET_MARGIN * 2 + c["cell"] * c["cols"] + dzn.SHEET_GUTTER * (c["cols"] - 1)
        used_h = dzn.SHEET_MARGIN * 2 + c["cell"] * c["rows"] + dzn.SHEET_GUTTER * (c["rows"] - 1)
        assert used_w <= p.trim_w, preset
        assert used_h <= p.trim_h, preset
        assert c["cell"] >= 400, preset  # ≥3.4 cm — still a usable sticker


def test_sticker_sheets_only_offered_for_cutout_kinds():
    for k in ("logo", "sticker"):
        assert set(dzn.STICKER_EXPORTS) <= set(dzn.exports_for_kind(k)), k
    for k in ("flyer", "banner"):
        assert not set(dzn.STICKER_EXPORTS) & set(dzn.exports_for_kind(k)), k
        assert "a4_bleed" in dzn.exports_for_kind(k)


def test_paper_exports_flatten_but_social_keeps_no_alpha(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    for preset in ("a4_bleed", "wa_status", "ig_square"):
        cmd = dzn.build_export_cmd("in.png", "out.png", preset)
        assert cmd[cmd.index("-pix_fmt") + 1] == "rgb24", preset


def test_export_files_stay_private():
    name = dzn.export_filename("a" * 32, "wa_status")
    assert name == "a" * 32 + "_x_wa_status.png"
    assert not SERVED_NAME_RE.match(name)
    assert not soundtrack.MEDIA_NAME_RE.match(name)
    assert not soundtrack.MEDIA_POSTER_RE.match(name)


# ------------------------------------------------------------------ branding
def test_brand_icon_cmd_drawtext(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    monkeypatch.setattr(dzn, "brand_font", lambda: "/f/DejaVuSans-Bold.ttf")
    cmd = dzn.build_brand_icon_cmd(512, "#0A66C2", "m", "#FFFFFF", "out.png")
    joined = " ".join(cmd)
    assert "color=c=#0A66C2:s=512x512" in joined
    assert "drawtext" in joined and "text='M'" in joined
    assert "fontcolor=#FFFFFF" in joined and "fontsize=266" in joined
    assert cmd[cmd.index("-f") + 1] == "lavfi"


def test_logo_stamp_cmd(monkeypatch):
    monkeypatch.setattr(dzn, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = dzn.build_logo_stamp_cmd("bg.jpg", "logo.png", "out.jpg", 120, 22)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "scale=120:-1" in fc and "overlay=W-w-22:H-h-22" in fc


# ----------------------------------------------------------------- i2v
def test_video_payload_text_only_vs_i2v():
    opts = VideoOptions(duration=6, aspect_ratio="16:9", quality="720p", style="cinematic")
    p = build_video_payload("grok-video", "a cat", opts)
    assert "image" not in p and p["aspect_ratio"] == "16:9" and p["resolution"] == "720p"
    p2 = build_video_payload("grok-video", "a cat", opts, image={"url": "data:image/png;base64,AA=="})
    assert p2["image"]["url"].startswith("data:image/png;base64,")
    assert p2["duration"] == 6


# ------------------------------------------------------------- agent tool
def test_design_create_is_staged_write_tool():
    assert "design_create" in ptools.WRITE_TOOLS
    names = [t["function"]["name"] for t in ptools.BUILTIN_TOOLS]
    assert "design_create" in names
    schema = next(t for t in ptools.BUILTIN_TOOLS if t["function"]["name"] == "design_create")
    params = schema["function"]["parameters"]["properties"]
    assert set(params["kind"]["enum"]) == {"flyer", "logo", "banner"}
    assert "idea" in schema["function"]["parameters"]["required"]


def test_design_label_registered():
    from app.api.routes import plugins as proutes
    assert proutes._TOOL_LABELS["design_create"] == ("🎨", "Create a design")
