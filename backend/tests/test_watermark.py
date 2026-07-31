"""🏷 Output watermarking — entitlement rules, badge rendering, and wiring.

The tests that matter most are the entitlement ones: a badge leaking onto a
paying customer's export is a refund request, and a badge silently *not*
applying to free users is lost revenue. Both directions are pinned here.
"""

import asyncio
import io
from pathlib import Path

import pytest

from app.config import settings
from app.services import watermark as wm


def run(coro):
    return asyncio.run(coro)


class FakeUser:
    """Minimal stand-in — should_watermark only reads plan / is_admin / email."""

    def __init__(self, plan="free", is_admin=False, email="user@example.com"):
        self.plan = plan
        self.is_admin = is_admin
        self.email = email


@pytest.fixture(autouse=True)
def _enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", True)
    monkeypatch.setattr(settings, "WATERMARK_TEXT", "")
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
    wm._badge_cache.clear()
    yield
    wm._badge_cache.clear()


# ---------------------------------------------------------------- entitlement

def test_free_users_get_a_watermark():
    assert wm.should_watermark(FakeUser(plan="free")) is True


def test_paid_plans_are_never_watermarked():
    assert wm.should_watermark(FakeUser(plan="pro")) is False


def test_a_future_paid_tier_is_exempt_by_default():
    """New tiers must fail toward 'no badge' — stamping a paying customer is worse."""
    for plan in ("heavy", "enterprise", "team", "PRO"):
        assert wm.should_watermark(FakeUser(plan=plan)) is False, plan


def test_admins_are_never_watermarked_even_on_the_free_plan():
    """Owner demos and store screenshots must come out clean."""
    assert wm.should_watermark(FakeUser(plan="free", is_admin=True)) is False


def test_owner_email_from_env_is_exempt(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "owner@company.com , other@x.io")
    assert wm.should_watermark(FakeUser(plan="free", email="owner@company.com")) is False
    # case-insensitive, matching is_effective_admin
    assert wm.should_watermark(FakeUser(plan="free", email="OWNER@company.com")) is False
    # a non-listed free user still gets the badge
    assert wm.should_watermark(FakeUser(plan="free", email="someone@company.com")) is True


def test_anonymous_render_is_treated_as_free_tier():
    assert wm.should_watermark(None) is True


def test_the_whole_feature_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", False)
    assert wm.should_watermark(FakeUser(plan="free")) is False


def test_is_premium_plan_edges():
    assert wm.is_premium_plan("free") is False
    assert wm.is_premium_plan("") is False
    assert wm.is_premium_plan(None) is False
    assert wm.is_premium_plan("  FREE  ") is False   # normalized
    assert wm.is_premium_plan("pro") is True


def test_entitlement_is_fail_safe_when_the_admin_check_explodes(monkeypatch):
    """A broken admin lookup must not silently exempt a free user."""
    import app.api.deps as deps

    def boom(_user):
        raise RuntimeError("db gone")

    monkeypatch.setattr(deps, "is_effective_admin", boom)
    assert wm.should_watermark(FakeUser(plan="free")) is True
    # ...and a paid user is still exempt (that branch returns before the check)
    assert wm.should_watermark(FakeUser(plan="pro")) is False


# ------------------------------------------------------------------- wording

def test_badge_text_defaults_to_the_app_name(monkeypatch):
    monkeypatch.setattr(settings, "APP_NAME", "MoodAI")
    assert wm.watermark_text() == "Made with MoodAI"


def test_badge_text_is_overridable_and_bounded(monkeypatch):
    monkeypatch.setattr(settings, "WATERMARK_TEXT", "  moodai.app  ")
    assert wm.watermark_text() == "moodai.app"
    monkeypatch.setattr(settings, "WATERMARK_TEXT", "x" * 200)
    assert len(wm.watermark_text()) == 60


# ------------------------------------------------------------ badge rendering

def test_badge_renders_a_real_transparent_png(tmp_path):
    from PIL import Image

    dst = tmp_path / "badge.png"
    assert wm.render_badge("Made with MoodAI", 1280, dst) is True
    with Image.open(dst) as im:
        assert im.mode == "RGBA"
        assert im.width > 40 and im.height > 10
        # the pill must actually be drawn (some pixels opaque)
        assert im.convert("RGBA").getchannel("A").getextrema()[1] > 100


def test_badge_scales_with_output_width(tmp_path):
    from PIL import Image

    small, large = tmp_path / "s.png", tmp_path / "l.png"
    wm.render_badge("Made with MoodAI", 640, small)
    wm.render_badge("Made with MoodAI", 3000, large)
    with Image.open(small) as a, Image.open(large) as b:
        # a print-tier export gets a proportionally bigger badge, not a speck
        assert b.width > a.width


def test_badges_are_cached_per_width_bucket(tmp_path):
    first = wm._badge_for(1280)
    second = wm._badge_for(1280)
    assert first and first == second  # same path reused, not re-rasterized


# -------------------------------------------------------------- argv builders

def test_overlay_cmd_places_the_badge_bottom_right():
    cmd = wm.build_overlay_cmd("in.png", "b.png", "out.png", video=False)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert graph == "[0:v][1:v]overlay=W-w-24:H-h-24"
    assert cmd[-1] == "out.png"
    assert "-frames:v" in cmd  # single frame for stills


def test_overlay_cmd_for_video_reencodes_video_but_copies_audio():
    cmd = wm.build_overlay_cmd("in.mp4", "b.png", "out.mp4", video=True)
    assert "libx264" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "copy"   # never re-encode the audio
    assert "+faststart" in cmd                     # keep web playback progressive
    assert "-frames:v" not in cmd


# --------------------------------------------------------------- bytes path

def _png_bytes(w=800, h=600):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 90, 160)).save(buf, "PNG")
    return buf.getvalue()


def test_apply_to_bytes_stamps_and_keeps_a_valid_image():
    from PIL import Image

    original = _png_bytes()
    out = wm.apply_to_bytes(original, suffix=".png")
    assert out != original
    with Image.open(io.BytesIO(out)) as im:
        assert im.size == (800, 600)  # dimensions preserved


def test_apply_to_bytes_returns_jpeg_for_jpeg_targets():
    from PIL import Image

    out = wm.apply_to_bytes(_png_bytes(), suffix=".jpg")
    with Image.open(io.BytesIO(out)) as im:
        assert im.format == "JPEG"  # RGBA would crash a naive JPEG save


def test_apply_to_bytes_returns_the_original_on_garbage_input():
    """Fail-open: a render is never destroyed by the badge step."""
    junk = b"this is not an image"
    assert wm.apply_to_bytes(junk) == junk


# ---------------------------------------------------------------- file path

def test_apply_to_file_noops_without_ffmpeg(monkeypatch, tmp_path):
    import app.services.soundtrack as st

    monkeypatch.setattr(st, "ffmpeg_path", lambda: None)
    p = tmp_path / "x.png"
    p.write_bytes(_png_bytes())
    before = p.read_bytes()
    assert run(wm.apply_to_file(p, video=False, width=800)) is False
    assert p.read_bytes() == before  # untouched


def test_apply_to_file_noops_on_missing_file(tmp_path):
    assert run(wm.apply_to_file(tmp_path / "nope.png", video=False)) is False


def test_apply_to_file_leaves_the_original_when_ffmpeg_fails(monkeypatch, tmp_path):
    """A failed stamp must not truncate or delete the user's render."""
    import app.services.soundtrack as st

    monkeypatch.setattr(st, "ffmpeg_path", lambda: "/bin/false")
    p = tmp_path / "x.png"
    p.write_bytes(_png_bytes())
    before = p.read_bytes()
    assert run(wm.apply_to_file(p, video=False, width=800)) is False
    assert p.exists() and p.read_bytes() == before
    # and no scratch file is left behind
    assert not (tmp_path / "x_wm.png").exists()


def test_video_detection_from_extension(monkeypatch, tmp_path):
    """`video=None` infers from the suffix — the flag drives re-encode vs single frame."""
    seen: dict = {}

    def fake_builder(src, badge, dst, *, video, pad=24):
        seen["video"] = video
        return ["/bin/false"]

    monkeypatch.setattr(wm, "build_overlay_cmd", fake_builder)
    monkeypatch.setattr(wm, "_badge_for", lambda w: str(tmp_path / "b.png"))
    import app.services.soundtrack as st

    monkeypatch.setattr(st, "ffmpeg_path", lambda: "/bin/false")

    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"x" * 64)
    run(wm.apply_to_file(mp4))
    assert seen["video"] is True

    png = tmp_path / "still.png"
    png.write_bytes(_png_bytes())
    run(wm.apply_to_file(png))
    assert seen["video"] is False


# =====================================================================
# Wiring: the entitlement actually reaches each render pipeline.
# =====================================================================

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Design, Film, User
from app.db.session import get_db
from app.main import app

PW = "Watermark-2026!"


@pytest.fixture()
def api(monkeypatch, tmp_path):
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    async def _make():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_make())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    yield factory
    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


async def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1", timeout=30
    )


async def _token(c, email):
    await c.post("/auth/register", json={"email": email, "password": PW})
    r = await c.post("/auth/login", json={"email": email, "password": PW})
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _set_plan(factory, email, plan=None, admin=None):
    from sqlalchemy import select as sel

    async with factory() as s:
        u = (await s.execute(sel(User).where(User.email == email))).scalar_one()
        if plan is not None:
            u.plan = plan
        if admin is not None:
            u.is_admin = admin
        await s.commit()
        return u.id


def _stub_design(monkeypatch, seen: dict):
    """Capture the watermark flag the route hands the design pipeline."""
    import app.services.designer as dzn

    async def fake_generate(idea, kind, **kw):
        seen["watermark"] = kw.get("watermark")
        return {
            "id": "d" * 32, "file": "x_d.png", "print_file": "x_dp.png",
            "width": 1080, "height": 1350, "print_width": 2480, "print_height": 3508,
            "print_dpi": 300, "fit": "cover", "alpha": False, "prompt": "p", "brief": "b",
            "note": None, "native": True, "branded": False,
            "watermarked": bool(kw.get("watermark")),
        }

    monkeypatch.setattr(dzn, "generate_design", fake_generate)


def test_design_route_watermarks_free_users(api, monkeypatch):
    seen: dict = {}
    _stub_design(monkeypatch, seen)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "free-d@test.io")
            r = await c.post("/media/designs", json={"idea": "a poster", "kind": "flyer"}, headers=_h(tok))
            assert r.status_code == 201, r.text
            assert r.json()["watermarked"] is True

    run(go())
    assert seen["watermark"] is True


def test_design_route_does_not_watermark_pro_users(api, monkeypatch):
    seen: dict = {}
    _stub_design(monkeypatch, seen)

    async def go():
        factory = api
        async with await _client() as c:
            tok = await _token(c, "pro-d@test.io")
            await _set_plan(factory, "pro-d@test.io", plan="pro")
            r = await c.post("/media/designs", json={"idea": "a poster", "kind": "flyer"}, headers=_h(tok))
            assert r.status_code == 201
            assert r.json()["watermarked"] is False

    run(go())
    assert seen["watermark"] is False


def test_design_route_does_not_watermark_admins(api, monkeypatch):
    seen: dict = {}
    _stub_design(monkeypatch, seen)

    async def go():
        factory = api
        async with await _client() as c:
            tok = await _token(c, "admin-d@test.io")
            await _set_plan(factory, "admin-d@test.io", admin=True)
            r = await c.post("/media/designs", json={"idea": "a poster", "kind": "flyer"}, headers=_h(tok))
            assert r.status_code == 201
            assert r.json()["watermarked"] is False

    run(go())
    assert seen["watermark"] is False


def test_film_persists_the_flag_so_resume_reapplies_it(api, monkeypatch):
    """A restart mid-render must not produce a half-badged film."""
    launched: dict = {}

    import app.api.routes.media as media_routes

    monkeypatch.setattr(
        media_routes.film_jobs, "launch", lambda fid, kw: launched.update({fid: kw})
    )

    async def go():
        factory = api
        async with await _client() as c:
            tok = await _token(c, "film@test.io")
            r = await c.post(
                "/media/videos/storyboard",
                json={"prompt": "a short film about the sea", "scenes": 2, "audio": "none"},
                headers=_h(tok),
            )
            assert r.status_code == 202, r.text
            fid = r.json()["film"]["id"]
            assert r.json()["film"]["watermarked"] is True
            assert launched[fid]["watermark"] is True

            # the row remembers the decision …
            async with factory() as s:
                assert (await s.get(Film, fid)).watermarked is True

            # … and the resume path rebuilds it from the row, not from a fresh
            # entitlement lookup (user could have upgraded mid-render)
            from app.api.routes.media import _film_kwargs

            async with factory() as s:
                film = await s.get(Film, fid)
                assert _film_kwargs(film)["watermark"] is True

    run(go())


def test_film_is_clean_for_pro(api, monkeypatch):
    launched: dict = {}
    import app.api.routes.media as media_routes

    monkeypatch.setattr(
        media_routes.film_jobs, "launch", lambda fid, kw: launched.update({fid: kw})
    )

    async def go():
        factory = api
        async with await _client() as c:
            tok = await _token(c, "film-pro@test.io")
            await _set_plan(factory, "film-pro@test.io", plan="pro")
            r = await c.post(
                "/media/videos/storyboard",
                json={"prompt": "a short film about the sea", "scenes": 2, "audio": "none"},
                headers=_h(tok),
            )
            assert r.status_code == 202
            fid = r.json()["film"]["id"]
            assert r.json()["film"]["watermarked"] is False
            assert launched[fid]["watermark"] is False

    run(go())


def test_in_chat_image_bytes_are_stamped_only_for_free_users(api, monkeypatch):
    """_persist_generated_media is the single chokepoint for in-chat creations."""
    from app.api.routes.chat import _persist_generated_media

    calls: list = []
    monkeypatch.setattr(
        "app.services.watermark.apply_to_bytes",
        lambda data, suffix=".png": (calls.append(suffix) or b"STAMPED" + data),
    )

    async def fake_put(user_id, filename, data):
        calls.append(("stored", data[:7]))
        return f"/tmp/{filename}"

    monkeypatch.setattr("app.services.storage.put_upload", fake_put)
    monkeypatch.setattr("app.services.storage.presigned_url", lambda *a, **k: _none())
    monkeypatch.setattr("app.services.storage.is_remote", lambda p: False)

    async def _none():
        return None

    import base64

    tiny = base64.b64encode(_png_bytes(8, 8)).decode()
    data_url = f"data:image/png;base64,{tiny}"

    async def go():
        factory = api
        async with await _client() as c:
            await _token(c, "chatimg@test.io")
            await _token(c, "chatimg-pro@test.io")
            await _set_plan(factory, "chatimg-pro@test.io", plan="pro")

            from sqlalchemy import select as sel

            async with factory() as s:
                free_u = (await s.execute(sel(User).where(User.email == "chatimg@test.io"))).scalar_one()
                pro_u = (await s.execute(sel(User).where(User.email == "chatimg-pro@test.io"))).scalar_one()

                calls.clear()
                await _persist_generated_media(s, free_u, data_url, "image")
                assert any(c == ".png" for c in calls), "free user's image was not stamped"

                calls.clear()
                await _persist_generated_media(s, pro_u, data_url, "image")
                assert not any(c == ".png" for c in calls), "pro user's image WAS stamped"

    run(go())
