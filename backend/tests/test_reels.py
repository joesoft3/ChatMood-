"""📺 Creator Reel — feed, upload, share, likes, visibility, janitor safety."""

import asyncio
import os

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes import reels as reelmod
from app.api.routes.media import SERVED_NAME_RE
from app.config import settings
from app.db.models import Base, Film
from app.db.session import get_db
from app.main import app
from app.services import soundtrack

PW = "Reel-Creator-2026!"


def run(coro):
    return asyncio.run(coro)


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
    # posters need ffmpeg; unit tests run without it (upload must still succeed)
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
    r = await c.post("/auth/login", json={"email": email, "password": PW})
    return r.json()["access_token"]


def _h(tk):
    return {"Authorization": f"Bearer {tk}"}


MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096


# ------------------------------------------------------------- name safety
def test_reel_media_is_never_swept_by_the_media_janitor():
    """The 24h janitor purges <hex32>.mp4/_e.mp4/_p.jpg. Reel posts are
    keepsakes — their names must fall outside every sweep pattern."""
    h = "a" * 32
    for name in (f"{h}_r.mp4", f"{h}_rp.jpg"):
        assert not soundtrack.MEDIA_NAME_RE.match(name), name
        assert not soundtrack.MEDIA_POSTER_RE.match(name), name


def test_reel_names_match_only_their_own_route():
    h = "b" * 32
    assert reelmod.REEL_NAME_RE.match(f"{h}_r.mp4")
    assert reelmod.REEL_POSTER_RE.match(f"{h}_rp.jpg")
    # traversal / foreign names are rejected outright
    for bad in ("../../etc/passwd", f"{h}.mp4", f"{h}_e.mp4", "evil_r.mp4", f"{h}_p.jpg"):
        assert not reelmod.REEL_NAME_RE.match(bad), bad
        assert not reelmod.REEL_POSTER_RE.match(bad), bad
    # and the films route must not serve reel media either (separate namespaces)
    assert not SERVED_NAME_RE.match(f"{h}_r.mp4")


# ------------------------------------------------------------------ upload
def test_upload_creates_live_post_and_serves_the_file(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "poster@moodaiapp.com")
            r = await c.post(
                "/reels/upload",
                headers=_h(tk),
                files={"file": ("clip.mp4", MP4, "video/mp4")},
                data={"caption": "Accra sunrise timelapse"},
            )
            assert r.status_code == 201, r.text
            reel = r.json()["reel"]
            assert reel["caption"] == "Accra sunrise timelapse"
            assert reel["source"] == "upload" and reel["status"] == "live"
            assert reel["mine"] is True and reel["likes"] == 0
            assert reel["url"].endswith("_r.mp4")
            assert reel["author"] == "poster"  # local-part, never the full email

            name = reel["url"].rsplit("/", 1)[-1]
            assert os.path.exists(os.path.join(settings.MEDIA_DIR, name))
            got = await c.get(f"/reels/files/{name}")
            assert got.status_code == 200 and got.content == MP4

    run(_t())


def test_upload_rejects_wrong_mime_and_oversize(env, monkeypatch):
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "badup@moodaiapp.com")
            r = await c.post("/reels/upload", headers=_h(tk),
                             files={"file": ("x.txt", b"hello", "text/plain")})
            assert r.status_code == 415

            # The upload cap is now plan-aware (services/reel_premium), so the
            # free-tier ceiling is what this exercises.
            from app.services import reel_premium as premium

            monkeypatch.setattr(premium, "FREE_MAX_MB", 0.0001)  # ~100 bytes
            r2 = await c.post("/reels/upload", headers=_h(tk),
                              files={"file": ("big.mp4", b"x" * 500, "video/mp4")})
            assert r2.status_code == 413

    run(_t())


def test_serve_rejects_unknown_and_traversal_names(env):
    async def _t():
        async with await _client() as c:
            for bad in ("nope.mp4", "a" * 32 + ".mp4", "a" * 32 + "_e.mp4", "%2e%2e%2fsecret.mp4"):
                assert (await c.get(f"/reels/files/{bad}")).status_code == 404, bad
            # a literal ../ never even reaches the handler — the router
            # normalizes the path away from /reels/files/ (405, not a file read)
            assert (await c.get("/reels/files/../secret.mp4")).status_code in (404, 405)

    run(_t())


# ------------------------------------------------------------------- share
def test_share_a_finished_film_points_at_existing_media(env):
    async def _t():
        factory = env
        async with await _client() as c:
            tk = await _token(c, "filmmaker@moodaiapp.com")
            me = (await c.get("/auth/me", headers=_h(tk))).json()
            async with factory() as s:
                s.add(Film(id="f" * 32, user_id=me["id"], prompt="Volta at dawn",
                           status="done", filename="c" * 32 + ".mp4", poster="c" * 32 + "_p.jpg"))
                await s.commit()

            r = await c.post("/reels/share", headers=_h(tk), json={"film_id": "f" * 32})
            assert r.status_code == 201, r.text
            reel = r.json()["reel"]
            assert reel["source"] == "film"
            # no bytes copied — it points back at the film's own media route
            assert "/api/v1/media/files/" in reel["url"]
            assert reel["poster"].endswith("_p.jpg")
            assert reel["caption"] == "Volta at dawn"  # falls back to the prompt

            # same film twice → conflict, not a duplicated feed entry
            again = await c.post("/reels/share", headers=_h(tk), json={"film_id": "f" * 32})
            assert again.status_code == 409

    run(_t())


def test_share_rejects_unfinished_or_foreign_films(env):
    async def _t():
        factory = env
        async with await _client() as c:
            tk = await _token(c, "owner@moodaiapp.com")
            other = await _token(c, "stranger@moodaiapp.com")
            me = (await c.get("/auth/me", headers=_h(tk))).json()
            async with factory() as s:
                s.add(Film(id="r" * 32, user_id=me["id"], prompt="wip", status="rendering"))
                await s.commit()

            assert (await c.post("/reels/share", headers=_h(tk),
                                 json={"film_id": "r" * 32})).status_code == 409
            # someone else's film is simply not found
            assert (await c.post("/reels/share", headers=_h(other),
                                 json={"film_id": "r" * 32})).status_code == 404

    run(_t())


def test_share_url_must_be_media_this_deployment_serves(env):
    """No arbitrary hotlinks — the feed only carries media Mood made."""
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "hotlink@moodaiapp.com")
            bad = await c.post("/reels/share", headers=_h(tk),
                               json={"url": "https://evil.example/porn.mp4"})
            assert bad.status_code == 422

            ok = await c.post("/reels/share", headers=_h(tk), json={
                "url": "https://api.test/api/v1/media/files/" + "d" * 32 + ".mp4",
                "caption": "made in chat"})
            assert ok.status_code == 201
            assert ok.json()["reel"]["source"] == "chat"

            assert (await c.post("/reels/share", headers=_h(tk), json={})).status_code == 422

    run(_t())


# -------------------------------------------------------------------- feed
def test_feed_is_shared_across_creators_newest_first(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "ama@moodaiapp.com")
            b = await _token(c, "kofi@moodaiapp.com")
            await c.post("/reels/upload", headers=_h(a),
                         files={"file": ("1.mp4", MP4, "video/mp4")}, data={"caption": "first"})
            await c.post("/reels/upload", headers=_h(b),
                         files={"file": ("2.mp4", MP4, "video/mp4")}, data={"caption": "second"})

            # Kofi sees BOTH posts — it is one shared creator feed
            feed = (await c.get("/reels", headers=_h(b))).json()
            assert feed["total"] == 2
            captions = [r["caption"] for r in feed["reels"]]
            assert set(captions) == {"first", "second"}
            # newest first — timestamps carry sub-second precision so two posts
            # made in the same second still order correctly (regression guard:
            # SQLite CURRENT_TIMESTAMP alone is 1-second resolution)
            stamps = [r["created_at"] for r in feed["reels"]]
            assert stamps == sorted(stamps, reverse=True)
            assert captions == ["second", "first"]
            mine = {r["caption"]: r["mine"] for r in feed["reels"]}
            assert mine == {"second": True, "first": False}  # ownership is per-viewer

            # ?mine=true narrows to your own posts
            just_ama = (await c.get("/reels?mine=true", headers=_h(a))).json()
            assert [r["caption"] for r in just_ama["reels"]] == ["first"]

    run(_t())


def test_unposting_hides_from_the_feed_but_keeps_it_for_the_author(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "shy@moodaiapp.com")
            b = await _token(c, "viewer@moodaiapp.com")
            rid = (await c.post("/reels/upload", headers=_h(a),
                                files={"file": ("x.mp4", MP4, "video/mp4")},
                                data={"caption": "oops"})).json()["reel"]["id"]

            await c.post(f"/reels/{rid}/visibility", headers=_h(a), json={"live": False})
            assert (await c.get("/reels", headers=_h(b))).json()["total"] == 0
            own = (await c.get("/reels?mine=true", headers=_h(a))).json()
            assert own["reels"][0]["status"] == "hidden"

            await c.post(f"/reels/{rid}/visibility", headers=_h(a), json={"live": True})
            assert (await c.get("/reels", headers=_h(b))).json()["total"] == 1

    run(_t())


# ------------------------------------------------------------------- likes
def test_like_is_a_toggle_and_idempotent_per_user(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "author2@moodaiapp.com")
            b = await _token(c, "fan@moodaiapp.com")
            rid = (await c.post("/reels/upload", headers=_h(a),
                                files={"file": ("x.mp4", MP4, "video/mp4")})).json()["reel"]["id"]

            first = (await c.post(f"/reels/{rid}/like", headers=_h(b))).json()
            assert first == {"liked": True, "likes": 1}
            # double-tap unlikes rather than double-counting
            second = (await c.post(f"/reels/{rid}/like", headers=_h(b))).json()
            assert second == {"liked": False, "likes": 0}

            await c.post(f"/reels/{rid}/like", headers=_h(b))
            await c.post(f"/reels/{rid}/like", headers=_h(a))
            feed = (await c.get("/reels", headers=_h(b))).json()["reels"][0]
            assert feed["likes"] == 2 and feed["liked"] is True   # viewer-specific flag

    run(_t())


def test_view_counter_increments(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "watched@moodaiapp.com")
            rid = (await c.post("/reels/upload", headers=_h(tk),
                                files={"file": ("x.mp4", MP4, "video/mp4")})).json()["reel"]["id"]
            assert (await c.post(f"/reels/{rid}/view", headers=_h(tk))).json()["views"] == 1
            assert (await c.post(f"/reels/{rid}/view", headers=_h(tk))).json()["views"] == 2

    run(_t())


# ------------------------------------------------------------------ delete
def test_delete_removes_row_and_uploaded_bytes(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "deleter@moodaiapp.com")
            reel = (await c.post("/reels/upload", headers=_h(tk),
                                 files={"file": ("x.mp4", MP4, "video/mp4")})).json()["reel"]
            name = reel["url"].rsplit("/", 1)[-1]
            path = os.path.join(settings.MEDIA_DIR, name)
            assert os.path.exists(path)

            assert (await c.delete(f"/reels/{reel['id']}", headers=_h(tk))).status_code == 204
            assert not os.path.exists(path)          # bytes cleaned up too
            assert (await c.get("/reels", headers=_h(tk))).json()["total"] == 0

    run(_t())


def test_only_the_author_can_unpost_or_delete(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "mine2@moodaiapp.com")
            b = await _token(c, "nosy@moodaiapp.com")
            rid = (await c.post("/reels/upload", headers=_h(a),
                                files={"file": ("x.mp4", MP4, "video/mp4")})).json()["reel"]["id"]

            assert (await c.delete(f"/reels/{rid}", headers=_h(b))).status_code == 404
            assert (await c.post(f"/reels/{rid}/visibility", headers=_h(b),
                                 json={"live": False})).status_code == 404
            # still live for everyone
            assert (await c.get("/reels", headers=_h(b))).json()["total"] == 1

    run(_t())


def test_feed_requires_auth(env):
    async def _t():
        async with await _client() as c:
            assert (await c.get("/reels")).status_code in (401, 403)

    run(_t())
