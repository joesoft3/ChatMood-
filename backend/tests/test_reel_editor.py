"""🎞 Reel editor — staged assets, timeline compositing, publish."""

import asyncio
import os

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes import reels as reelmod
from app.config import settings
from app.db.models import Base
from app.db.session import get_db
from app.main import app
from app.services import reel_studio as studio
from app.services import soundtrack

PW = "Reel-Editor-2026!"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048
MP3 = b"ID3\x03\x00\x00\x00" + b"\x00" * 2048


def run(coro):
    return asyncio.run(coro)


# ======================================================== timeline builder
def test_timeline_needs_at_least_one_clip(monkeypatch):
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    with pytest.raises(studio.StudioError):
        studio.build_timeline_cmd([], "out.mp4")


def test_timeline_caps_the_clip_count(monkeypatch):
    """An unbounded filtergraph is a denial-of-service on our own renderer."""
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    too_many = [studio.Clip(f"c{i}.mp4") for i in range(studio.MAX_CLIPS + 1)]
    with pytest.raises(studio.StudioError):
        studio.build_timeline_cmd(too_many, "out.mp4")


def test_single_clip_trims_grades_and_normalises(monkeypatch):
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = studio.build_timeline_cmd(
        [studio.Clip("a.mp4", start=1.5, end=4.0, effect="vivid", volume=0.5)], "out.mp4")
    g = cmd[cmd.index("-filter_complex") + 1]
    assert "trim=start=1.500:end=4.000" in g
    assert "setpts=PTS-STARTPTS" in g                     # trimmed clips restart at 0
    assert f"crop={studio.REEL_W}:{studio.REEL_H}" in g
    assert studio.EFFECTS["vivid"].vf in g
    assert "atrim=start=1.500:end=4.000" in g             # audio trimmed to match
    assert "volume=0.500" in g
    assert "concat=" not in g                             # a single clip needs no concat


def test_silent_clip_gets_a_generated_silent_track(monkeypatch):
    """concat demands audio on EVERY segment. A silent clip without a stand-in
    fails the whole graph with "Stream specifier ':a' matches no streams" —
    the same class of bug that broke duets."""
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = studio.build_timeline_cmd(
        [studio.Clip("a.mp4", has_audio=True),
         studio.Clip("b.mp4", end=3.0, has_audio=False)], "out.mp4")
    assert "anullsrc" in " ".join(cmd)
    g = cmd[cmd.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=1" in g
    # the silent stand-in is a real input, so its audio label must be referenced
    assert g.count("[a0]") >= 1 and g.count("[a1]") >= 1


def test_clip_speed_is_clamped_to_what_atempo_accepts(monkeypatch):
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    g = studio.build_timeline_cmd([studio.Clip("a.mp4", speed=99)], "o.mp4")
    chain = g[g.index("-filter_complex") + 1]
    assert "atempo=2.0000" in chain and "atempo=99" not in chain
    slow = studio.build_timeline_cmd([studio.Clip("a.mp4", speed=0.01)], "o.mp4")
    assert "atempo=0.5000" in slow[slow.index("-filter_complex") + 1]


def test_audio_bed_mixes_under_the_timeline(monkeypatch):
    """The 'volume split': clip audio ducked, music bed raised."""
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = studio.build_timeline_cmd(
        [studio.Clip("a.mp4", volume=0.25)], "out.mp4",
        bed=studio.AudioBed("music.mp3", volume=0.9))
    g = cmd[cmd.index("-filter_complex") + 1]
    assert "volume=0.250" in g and "volume=0.900" in g
    # duration=first keeps a long bed from extending the video
    assert "amix=inputs=2:duration=first" in g
    assert cmd[cmd.index("-map") + 1].startswith("[")


def test_overlay_is_pinned_and_scaled(monkeypatch):
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    for corner, expect in (("tl", "40:40"), ("br", "W-w-40:H-h-40")):
        cmd = studio.build_timeline_cmd(
            [studio.Clip("a.mp4")], "out.mp4",
            overlay=studio.Overlay("pip.mp4", corner=corner, scale=0.25))
        g = cmd[cmd.index("-filter_complex") + 1]
        assert f"overlay={expect}" in g
        assert f"scale={int(studio.REEL_W * 0.25)}:-2" in g
        assert "shortest=0" in g      # base keeps playing after a short overlay


def test_silent_overlay_contributes_no_audio(monkeypatch):
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = studio.build_timeline_cmd(
        [studio.Clip("a.mp4")], "o.mp4",
        overlay=studio.Overlay("pip.mp4", has_audio=False, volume=0.0))
    g = cmd[cmd.index("-filter_complex") + 1]
    assert "ovla" not in g       # never reference an audio stream that isn't there


def test_overlay_scale_is_bounded(monkeypatch):
    """A 'PiP' at 95% of the frame just hides the main clip."""
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    huge = studio.build_timeline_cmd([studio.Clip("a.mp4")], "o.mp4",
                                     overlay=studio.Overlay("p.mp4", scale=9.0))
    assert f"scale={int(studio.REEL_W * 0.6)}:-2" in huge[huge.index("-filter_complex") + 1]


def test_everything_at_once_renders_one_pass(monkeypatch):
    """Multi-clip + bed + overlay must stay a SINGLE ffmpeg invocation —
    chaining passes re-encodes the footage once per operation."""
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = studio.build_timeline_cmd(
        [studio.Clip("a.mp4", effect="warm"),
         studio.Clip("b.mp4", has_audio=False, end=2.0),
         studio.Clip("a.mp4", start=1, end=3, speed=1.5)],
        "out.mp4", bed=studio.AudioBed("m.mp3"), overlay=studio.Overlay("p.mp4"))
    assert cmd.count("-filter_complex") == 1
    g = cmd[cmd.index("-filter_complex") + 1]
    assert "concat=n=3:v=1:a=1" in g and "overlay=" in g and g.count("amix") >= 1
    assert cmd[-1] == "out.mp4"


# ============================================================ route surface
@pytest.fixture()
def env(monkeypatch, tmp_path):
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
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "https://api.test")
    monkeypatch.setattr(soundtrack, "ffmpeg_path", lambda: None)
    yield factory
    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


async def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1", timeout=30
    )


async def _token(c, email):
    await c.post("/auth/register", json={"email": email, "password": PW})
    return (await c.post("/auth/login", json={"email": email, "password": PW})).json()["access_token"]


def _h(tk):
    return {"Authorization": f"Bearer {tk}"}


def test_stage_a_camera_capture_then_discard_it(env):
    """MediaRecorder hands us webm — the editor must accept it."""
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "cam@moodaiapp.com")
            r = await c.post("/reels/assets", headers=_h(tk),
                             files={"file": ("rec.webm", MP4, "video/webm")},
                             data={"kind": "video"})
            assert r.status_code == 201, r.text
            a = r.json()["asset"]
            assert a["name"].endswith("_ra.mp4") and a["kind"] == "video"
            assert os.path.exists(os.path.join(settings.MEDIA_DIR, a["name"]))

            # a staged draft is playable (the editor previews it)...
            assert (await c.get(f"/reels/files/{a['name']}")).status_code == 200
            # ...but it is NOT in anybody's feed
            assert (await c.get("/reels", headers=_h(tk))).json()["total"] == 0

            assert (await c.delete(f"/reels/assets/{a['name']}", headers=_h(tk))).status_code == 204
            assert not os.path.exists(os.path.join(settings.MEDIA_DIR, a["name"]))

    run(_t())


def test_audio_assets_are_accepted_and_video_mimes_rejected(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "aud@moodaiapp.com")
            ok = await c.post("/reels/assets", headers=_h(tk),
                              files={"file": ("m.mp3", MP3, "audio/mpeg")},
                              data={"kind": "audio"})
            assert ok.status_code == 201 and ok.json()["asset"]["kind"] == "audio"

            bad = await c.post("/reels/assets", headers=_h(tk),
                               files={"file": ("m.mp3", MP3, "audio/mpeg")},
                               data={"kind": "video"})
            assert bad.status_code == 415

    run(_t())


@pytest.mark.parametrize("mime", ["audio/mpeg", "audio/x-m4a", "audio/mp4",
                                  "audio/aac", "audio/x-wav", "audio/ogg"])
def test_audio_picker_accepts_every_browser_mime_spelling(env, mime):
    """Browsers disagree on the MIME for the SAME file — Chrome calls .m4a
    audio/x-m4a while Python's mimetypes says audio/mp4. Caught live: the
    picker 415'd a perfectly valid track."""
    async def _t():
        async with await _client() as c:
            tk = await _token(c, f"mime{abs(hash(mime)) % 9999}@moodaiapp.com")
            r = await c.post("/reels/assets", headers=_h(tk),
                             files={"file": ("t", MP3, mime)}, data={"kind": "audio"})
            assert r.status_code == 201, f"{mime} → {r.status_code}"
            assert reelmod.DRAFT_RE.match(r.json()["asset"]["name"])

    run(_t())


def test_publish_refuses_paths_outside_the_staging_area(env):
    """Client-supplied filenames are hostile input: without the DRAFT_RE guard
    a caller could make ffmpeg read any file on disk into a published video."""
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "evil@moodaiapp.com")
            for bad in ("../../etc/passwd", "/etc/passwd", "a" * 32 + "_r.mp4", "x.mp4", ""):
                r = await c.post("/reels/publish", headers=_h(tk),
                                 json={"clips": [{"name": bad}]})
                assert r.status_code in (404, 422), f"{bad} → {r.status_code}"

    run(_t())


def test_publish_validates_the_timeline_shape(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "shape@moodaiapp.com")
            assert (await c.post("/reels/publish", headers=_h(tk),
                                 json={"clips": []})).status_code == 422
            assert (await c.post("/reels/publish", headers=_h(tk),
                                 json={})).status_code == 422
            many = [{"name": "a" * 32 + "_ra.mp4"} for _ in range(studio.MAX_CLIPS + 1)]
            assert (await c.post("/reels/publish", headers=_h(tk),
                                 json={"clips": many})).status_code == 422

    run(_t())


def test_publish_rejects_a_bad_overlay_corner(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "corner@moodaiapp.com")
            a = (await c.post("/reels/assets", headers=_h(tk),
                              files={"file": ("v.mp4", MP4, "video/mp4")})).json()["asset"]
            r = await c.post("/reels/publish", headers=_h(tk), json={
                "clips": [{"name": a["name"]}],
                "overlay": {"name": a["name"], "corner": "middle"}})
            assert r.status_code == 422
            assert "corner" in r.json()["detail"]

    run(_t())


def test_publish_reports_cleanly_without_a_renderer(env):
    """No ffmpeg → 503, never a 500 traceback."""
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "norend@moodaiapp.com")
            a = (await c.post("/reels/assets", headers=_h(tk),
                              files={"file": ("v.mp4", MP4, "video/mp4")})).json()["asset"]
            r = await c.post("/reels/publish", headers=_h(tk),
                             json={"clips": [{"name": a["name"]}], "caption": "hi"})
            assert r.status_code == 503

    run(_t())


def test_staged_asset_names_never_collide_with_published_reels(env):
    """`_ra` drafts must not match the reel-serving pattern, or an unpublished
    edit could be discovered on the feed's own URL space."""
    h = "a" * 32
    assert reelmod.DRAFT_RE.match(f"{h}_ra.mp4")
    assert not reelmod.REEL_NAME_RE.match(f"{h}_ra.mp4")
    assert not reelmod.REEL_POSTER_RE.match(f"{h}_ra.mp4")
    # ...and the janitor leaves both alone
    assert not soundtrack.MEDIA_NAME_RE.match(f"{h}_ra.mp4")
