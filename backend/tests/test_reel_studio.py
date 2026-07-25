"""🎬 Reel Studio — duet layouts, effects, caption burn-in, repost lineage."""

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

PW = "Reel-Studio-2026!"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048


def run(coro):
    return asyncio.run(coro)


# ============================================================ pure builders
def test_effect_table_pairs_every_look_with_a_css_preview():
    """The browser previews effects with CSS while editing; the server burns
    the ffmpeg chain in on post. A look with no CSS twin would render a preview
    that lies about the result."""
    assert "none" in studio.EFFECTS
    for key, e in studio.EFFECTS.items():
        assert e.label and e.emoji, key
        assert e.css, key                       # every look is previewable
        if key != "none":
            assert e.vf, key                    # ...and every look really renders
    cat = studio.effect_catalog()
    assert {c["id"] for c in cat} == set(studio.EFFECTS)
    assert all({"id", "label", "emoji", "css"} <= set(c) for c in cat)


@pytest.mark.parametrize("layout", ["side", "top", "green"])
def test_duet_builder_targets_the_reel_canvas(monkeypatch, layout):
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = studio.build_duet_cmd("mine.mp4", "theirs.mp4", "out.mp4", layout=layout)
    chain = cmd[cmd.index("-filter_complex") + 1]
    # theirs is input 0, mine is input 1 — the duet reads left/top = original
    assert cmd.index("theirs.mp4") < cmd.index("mine.mp4")
    if layout == "side":
        assert "hstack" in chain and f"scale={studio.REEL_W // 2}:{studio.REEL_H}" in chain
    elif layout == "top":
        assert "vstack" in chain and f"scale={studio.REEL_W}:{studio.REEL_H // 2}" in chain
    else:
        assert "overlay=" in chain and "hstack" not in chain
    assert cmd[-1] == "out.mp4"


def test_duet_audio_routing(monkeypatch):
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    both = studio.build_duet_cmd("m.mp4", "t.mp4", "o.mp4", audio="both")
    assert "amix=inputs=2" in both[both.index("-filter_complex") + 1]
    mine = studio.build_duet_cmd("m.mp4", "t.mp4", "o.mp4", audio="mine")
    assert "[1:a]" in mine[mine.index("-filter_complex") + 1] and "amix" not in mine[mine.index("-filter_complex") + 1]
    theirs = studio.build_duet_cmd("m.mp4", "t.mp4", "o.mp4", audio="theirs")
    assert "[0:a]" in theirs[theirs.index("-filter_complex") + 1]


def test_duet_degrades_when_a_side_has_no_audio(monkeypatch):
    """Referencing [0:a] on a silent clip makes ffmpeg fail the WHOLE graph
    with "Stream specifier ':a' matches no streams" — caught live on a
    render. A silent side must fall back, never kill the duet."""
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")

    # theirs silent, mine has sound → only [1:a] may be referenced
    c = studio.build_duet_cmd("m.mp4", "t.mp4", "o.mp4", audio="both",
                              mine_has_audio=True, theirs_has_audio=False)
    chain = c[c.index("-filter_complex") + 1]
    assert "[0:a]" not in chain and "[1:a]" in chain and "amix" not in chain
    assert "-an" not in c

    # mine silent, theirs has sound → mirror case
    c2 = studio.build_duet_cmd("m.mp4", "t.mp4", "o.mp4", audio="both",
                               mine_has_audio=False, theirs_has_audio=True)
    chain2 = c2[c2.index("-filter_complex") + 1]
    assert "[1:a]" not in chain2 and "[0:a]" in chain2

    # both silent → a clean silent duet, no audio mapping at all
    c3 = studio.build_duet_cmd("m.mp4", "t.mp4", "o.mp4",
                               mine_has_audio=False, theirs_has_audio=False)
    assert "-an" in c3 and "[aout]" not in " ".join(c3)

    # asking for a side that is silent must not reference it either
    c4 = studio.build_duet_cmd("m.mp4", "t.mp4", "o.mp4", audio="theirs",
                               theirs_has_audio=False, mine_has_audio=True)
    assert "-an" in c4


def test_probe_has_audio_does_not_depend_on_ffprobe(monkeypatch):
    """imageio-ffmpeg ships NO ffprobe binary, so audio detection has to read
    `ffmpeg -i` stderr. Caught live: the ffprobe-based helper silently returned
    its optimistic default and every duet with a silent clip 502'd."""
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")

    class R:
        def __init__(self, err):
            self.stderr = err

    monkeypatch.setattr(studio.subprocess, "run",
                        lambda *a, **k: R("Stream #0:0: Video: h264\n  Stream #0:1: Audio: aac"))
    assert studio.probe_has_audio("x.mp4") is True

    monkeypatch.setattr(studio.subprocess, "run", lambda *a, **k: R("Stream #0:0: Video: h264"))
    assert studio.probe_has_audio("x.mp4") is False

    # a probe must never raise into the render path
    def boom(*a, **k):
        raise OSError("no binary")

    monkeypatch.setattr(studio.subprocess, "run", boom)
    assert studio.probe_has_audio("x.mp4") is False
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: None)
    assert studio.probe_has_audio("x.mp4") is False


def test_duet_rejects_unknown_layout(monkeypatch):
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    with pytest.raises(studio.StudioError):
        studio.build_duet_cmd("m.mp4", "t.mp4", "o.mp4", layout="diagonal")


def test_effect_builder_normalises_and_clamps_speed(monkeypatch):
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = studio.build_effect_cmd("in.mp4", "out.mp4", effect="vivid", speed=1.5)
    vf = cmd[cmd.index("-vf") + 1]
    assert f"crop={studio.REEL_W}:{studio.REEL_H}" in vf
    assert studio.EFFECTS["vivid"].vf in vf
    assert "setpts=0.6667*PTS" in vf
    assert cmd[cmd.index("-filter:a") + 1] == "atempo=1.5000"

    # atempo only accepts 0.5–2.0; anything wilder must be clamped, not passed
    fast = studio.build_effect_cmd("in.mp4", "out.mp4", speed=9.0)
    assert fast[fast.index("-filter:a") + 1] == "atempo=2.0000"
    slow = studio.build_effect_cmd("in.mp4", "out.mp4", speed=0.01)
    assert slow[slow.index("-filter:a") + 1] == "atempo=0.5000"

    # no speed change → audio is copied rather than re-encoded
    plain = studio.build_effect_cmd("in.mp4", "out.mp4", effect="mono")
    assert "-filter:a" not in plain and plain[plain.index("-c:a") + 1] == "copy"


def test_effect_builder_rejects_unknown_look(monkeypatch):
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    with pytest.raises(studio.StudioError):
        studio.build_effect_cmd("in.mp4", "out.mp4", effect="sparkles")


def test_captions_use_libass_because_drawtext_is_unavailable(monkeypatch):
    """This ffmpeg build ships without `drawtext` — captions MUST go through
    the subtitles/libass filter or every caption render fails at runtime."""
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = studio.build_caption_cmd("in.mp4", "out.mp4", "/tmp/s.srt", style="bold")
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("subtitles=") and "drawtext" not in vf
    assert studio.CAPTION_STYLES["bold"] in vf
    assert cmd[cmd.index("-c:a") + 1] == "copy"       # captions never touch audio


def test_caption_path_is_escaped_for_the_filter_parser(monkeypatch):
    monkeypatch.setattr(studio, "ffmpeg_path", lambda: "/bin/ffmpeg")
    cmd = studio.build_caption_cmd("in.mp4", "out.mp4", r"C:\tmp\my subs.srt")
    vf = cmd[cmd.index("-vf") + 1]
    # a raw ':' would split the filter option in the wrong place
    assert r"C\:" in vf or r"\:" in vf


def test_srt_to_text_flattens_cues():
    srt = (
        "1\n00:00:00,000 --> 00:00:02,000\nHello from Accra\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\nSecond line\n"
    )
    assert studio.srt_to_text(srt) == "Hello from Accra Second line"
    assert studio.srt_to_text("") == ""
    assert len(studio.srt_to_text("1\n00:00:00,000 --> 00:00:02,000\n" + "x" * 900)) <= 300


# ================================================================== routes
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


async def _post(c, tk, caption="clip"):
    r = await c.post("/reels/upload", headers=_h(tk),
                     files={"file": ("c.mp4", MP4, "video/mp4")}, data={"caption": caption})
    return r.json()["reel"]


def test_effects_catalog_endpoint(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "fx@moodaiapp.com")
            j = (await c.get("/reels/effects", headers=_h(tk))).json()
            assert len(j["effects"]) == len(studio.EFFECTS)
            assert j["duet_layouts"] == list(studio.DUET_LAYOUTS)
            assert "clean" in j["caption_styles"] and "1x" in j["speeds"]

    run(_t())


def test_duet_needs_a_local_upload_to_stack_against(env):
    """Shared film/chat reels have no local bytes on this host, so they can't
    be dueted — that must be a clean 409, not a render crash."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "sharer2@moodaiapp.com")
            b = await _token(c, "duetter@moodaiapp.com")
            shared = (await c.post("/reels/share", headers=_h(a), json={
                "url": "https://api.test/api/v1/media/files/" + "d" * 32 + ".mp4"})).json()["reel"]
            r = await c.post(f"/reels/{shared['id']}/duet", headers=_h(b),
                             files={"file": ("m.mp4", MP4, "video/mp4")})
            assert r.status_code == 409
            assert "duet" in r.json()["detail"].lower()

    run(_t())


def test_duet_validates_layout_audio_and_target(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "orig@moodaiapp.com")
            b = await _token(c, "partner@moodaiapp.com")
            rid = (await _post(c, a))["id"]
            f = {"file": ("m.mp4", MP4, "video/mp4")}
            assert (await c.post(f"/reels/{rid}/duet", headers=_h(b), files=f,
                                 data={"layout": "diagonal"})).status_code == 422
            assert (await c.post(f"/reels/{rid}/duet", headers=_h(b), files=f,
                                 data={"audio": "loud"})).status_code == 422
            assert (await c.post("/reels/missing/duet", headers=_h(b), files=f)).status_code == 404

    run(_t())


def test_duet_reports_cleanly_when_the_renderer_is_missing(env):
    """No ffmpeg on this host → 503, never a 500 traceback."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "norender@moodaiapp.com")
            b = await _token(c, "norender2@moodaiapp.com")
            rid = (await _post(c, a))["id"]
            r = await c.post(f"/reels/{rid}/duet", headers=_h(b),
                             files={"file": ("m.mp4", MP4, "video/mp4")})
            assert r.status_code == 503

    run(_t())


# ------------------------------------------------------------------ repost
def test_repost_credits_the_original_and_shares_its_media(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "author9@moodaiapp.com")
            b = await _token(c, "reposter@moodaiapp.com")
            orig = await _post(c, a, "original work")

            j = (await c.post(f"/reels/{orig['id']}/repost", headers=_h(b), json={})).json()
            rp = j["reel"]
            assert rp["source"] == "repost"
            assert rp["parent_id"] == orig["id"]
            assert rp["parent_author"] == orig["author"]
            assert rp["url"] == orig["url"]      # same media, no copy
            assert j["reposts"] == 1

            # the counter shows on the original in the feed
            feed = (await c.get("/reels", headers=_h(a))).json()["reels"]
            original = next(r for r in feed if r["id"] == orig["id"])
            assert original["reposts"] == 1

    run(_t())


def test_cannot_repost_your_own_reel_or_repost_twice(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "self@moodaiapp.com")
            b = await _token(c, "dbl@moodaiapp.com")
            orig = await _post(c, a)
            assert (await c.post(f"/reels/{orig['id']}/repost", headers=_h(a),
                                 json={})).status_code == 409
            assert (await c.post(f"/reels/{orig['id']}/repost", headers=_h(b),
                                 json={})).status_code == 201
            assert (await c.post(f"/reels/{orig['id']}/repost", headers=_h(b),
                                 json={})).status_code == 409

    run(_t())


def test_reposting_a_repost_credits_the_root_author(env):
    """A chain must not credit the middle-man — attribution follows the root."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "root@moodaiapp.com")
            b = await _token(c, "mid@moodaiapp.com")
            d = await _token(c, "last@moodaiapp.com")
            orig = await _post(c, a, "the original")
            first = (await c.post(f"/reels/{orig['id']}/repost", headers=_h(b),
                                  json={})).json()["reel"]
            second = (await c.post(f"/reels/{first['id']}/repost", headers=_h(d),
                                   json={})).json()
            assert second["reel"]["parent_id"] == orig["id"]
            assert second["reel"]["parent_author"] == orig["author"]
            assert second["reposts"] == 2      # both counted on the root

    run(_t())


def test_deleting_a_repost_leaves_the_originals_media_intact(env):
    """Reposts share the original's file — deleting one must not unlink bytes
    the original still plays."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "keepme@moodaiapp.com")
            b = await _token(c, "dropme@moodaiapp.com")
            orig = await _post(c, a)
            name = orig["url"].rsplit("/", 1)[-1]
            path = os.path.join(settings.MEDIA_DIR, name)
            assert os.path.exists(path)

            rp = (await c.post(f"/reels/{orig['id']}/repost", headers=_h(b),
                               json={})).json()["reel"]
            assert (await c.delete(f"/reels/{rp['id']}", headers=_h(b))).status_code == 204
            assert os.path.exists(path), "the original's video was deleted with the repost"

            # ...and the repost counter came back down
            feed = (await c.get("/reels", headers=_h(a))).json()["reels"]
            assert next(r for r in feed if r["id"] == orig["id"])["reposts"] == 0

            # deleting the original now DOES remove the file (nothing else uses it)
            assert (await c.delete(f"/reels/{orig['id']}", headers=_h(a))).status_code == 204
            assert not os.path.exists(path)

    run(_t())


def test_upload_accepts_studio_options_without_a_renderer(env):
    """Effects/captions fail OPEN — with no ffmpeg the post still succeeds,
    just without the burn-in."""
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "failopen@moodaiapp.com")
            r = await c.post("/reels/upload", headers=_h(tk),
                             files={"file": ("c.mp4", MP4, "video/mp4")},
                             data={"caption": "with fx", "effect": "vivid",
                                   "speed": "1.5", "captions": "true"})
            assert r.status_code == 201
            reel = r.json()["reel"]
            assert reel["caption"] == "with fx"
            assert reel["effect"] == "" and reel["captioned"] is False

    run(_t())
