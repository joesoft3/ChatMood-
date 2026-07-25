"""📊 Reel engagement — view/like/share/save counters, Saved tab, profile stats."""

import asyncio

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import Base
from app.db.session import get_db
from app.main import app
from app.services import soundtrack

PW = "Reel-Engage-2026!"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048


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


async def _post_reel(c, tk, caption="clip"):
    r = await c.post("/reels/upload", headers=_h(tk),
                     files={"file": ("c.mp4", MP4, "video/mp4")}, data={"caption": caption})
    return r.json()["reel"]["id"]


# ------------------------------------------------------------------ counters
def test_new_reel_starts_with_zero_engagement(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "fresh@moodaiapp.com")
            r = (await c.post("/reels/upload", headers=_h(tk),
                              files={"file": ("c.mp4", MP4, "video/mp4")})).json()["reel"]
            assert (r["views"], r["likes"], r["shares"], r["saves"]) == (0, 0, 0, 0)
            assert r["liked"] is False and r["saved"] is False

    run(_t())


def test_share_count_is_a_tally_not_a_toggle(env):
    """Unlike ❤/🔖, sharing twice really is two shares — it must not toggle."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "sharer@moodaiapp.com")
            b = await _token(c, "friend@moodaiapp.com")
            rid = await _post_reel(c, a)

            first = (await c.post(f"/reels/{rid}/share", headers=_h(b))).json()
            assert first["shares"] == 1
            assert first["url"].endswith("_r.mp4")      # link handed back to copy
            assert (await c.post(f"/reels/{rid}/share", headers=_h(b))).json()["shares"] == 2
            assert (await c.post(f"/reels/{rid}/share", headers=_h(a))).json()["shares"] == 3

            feed = (await c.get("/reels", headers=_h(b))).json()["reels"][0]
            assert feed["shares"] == 3

    run(_t())


def test_save_toggles_and_is_per_viewer(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "author3@moodaiapp.com")
            b = await _token(c, "saver@moodaiapp.com")
            rid = await _post_reel(c, a)

            assert (await c.post(f"/reels/{rid}/save", headers=_h(b))).json() == {
                "saved": True, "saves": 1}
            # double-tap un-saves rather than double-counting
            assert (await c.post(f"/reels/{rid}/save", headers=_h(b))).json() == {
                "saved": False, "saves": 0}
            await c.post(f"/reels/{rid}/save", headers=_h(b))
            await c.post(f"/reels/{rid}/save", headers=_h(a))

            # counter is shared; the `saved` flag is specific to the viewer
            for tk, expect in ((b, True), (a, True)):
                card = (await c.get("/reels", headers=_h(tk))).json()["reels"][0]
                assert card["saves"] == 2 and card["saved"] is expect

    run(_t())


def test_counters_are_independent_of_each_other(env):
    """A like must not move the share/save/view numbers, and vice versa."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "indep@moodaiapp.com")
            b = await _token(c, "indep2@moodaiapp.com")
            rid = await _post_reel(c, a)

            await c.post(f"/reels/{rid}/like", headers=_h(b))
            await c.post(f"/reels/{rid}/share", headers=_h(b))
            await c.post(f"/reels/{rid}/share", headers=_h(b))
            await c.post(f"/reels/{rid}/save", headers=_h(b))
            for _ in range(3):
                await c.post(f"/reels/{rid}/view", headers=_h(b))

            card = (await c.get("/reels", headers=_h(b))).json()["reels"][0]
            assert (card["likes"], card["shares"], card["saves"], card["views"]) == (1, 2, 1, 3)

    run(_t())


# ------------------------------------------------------------------ saved tab
def test_saved_feed_lists_only_bookmarks_newest_save_first(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "poster4@moodaiapp.com")
            b = await _token(c, "collector@moodaiapp.com")
            r1 = await _post_reel(c, a, "first")
            r2 = await _post_reel(c, a, "second")
            r3 = await _post_reel(c, a, "third")

            # save the OLDEST post last — ordering must follow the save, not the post
            await c.post(f"/reels/{r2}/save", headers=_h(b))
            await c.post(f"/reels/{r1}/save", headers=_h(b))

            saved = (await c.get("/reels?saved=true", headers=_h(b))).json()
            assert saved["total"] == 2
            assert [r["caption"] for r in saved["reels"]] == ["first", "second"]
            assert all(r["saved"] for r in saved["reels"])
            assert r3 not in [r["id"] for r in saved["reels"]]

            # the other viewer's Saved tab is untouched
            assert (await c.get("/reels?saved=true", headers=_h(a))).json()["total"] == 0

    run(_t())


def test_saved_feed_hides_unposted_reels(env):
    """If an author unposts, it should drop out of everyone's Saved tab too."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "unposter@moodaiapp.com")
            b = await _token(c, "keeper@moodaiapp.com")
            rid = await _post_reel(c, a)
            await c.post(f"/reels/{rid}/save", headers=_h(b))
            assert (await c.get("/reels?saved=true", headers=_h(b))).json()["total"] == 1

            await c.post(f"/reels/{rid}/visibility", headers=_h(a), json={"live": False})
            assert (await c.get("/reels?saved=true", headers=_h(b))).json()["total"] == 0

    run(_t())


def test_deleting_a_reel_clears_it_from_other_peoples_saves(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "owner5@moodaiapp.com")
            b = await _token(c, "fan5@moodaiapp.com")
            rid = await _post_reel(c, a)
            await c.post(f"/reels/{rid}/save", headers=_h(b))
            await c.post(f"/reels/{rid}/like", headers=_h(b))

            assert (await c.delete(f"/reels/{rid}", headers=_h(a))).status_code == 204
            # no orphan rows left pointing at a reel that no longer exists
            assert (await c.get("/reels?saved=true", headers=_h(b))).json()["total"] == 0
            assert (await c.get("/reels", headers=_h(b))).json()["total"] == 0

    run(_t())


# --------------------------------------------------------------------- stats
def test_stats_totals_across_all_my_posts(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "creator6@moodaiapp.com")
            b = await _token(c, "audience6@moodaiapp.com")
            r1 = await _post_reel(c, a, "one")
            r2 = await _post_reel(c, a, "two")

            await c.post(f"/reels/{r1}/like", headers=_h(b))
            await c.post(f"/reels/{r2}/like", headers=_h(b))
            await c.post(f"/reels/{r1}/share", headers=_h(b))
            await c.post(f"/reels/{r1}/save", headers=_h(b))
            for _ in range(4):
                await c.post(f"/reels/{r2}/view", headers=_h(b))
            # something posted by someone else must NOT count toward my stats
            other = await _post_reel(c, b, "not mine")
            await c.post(f"/reels/{other}/like", headers=_h(a))

            s = (await c.get("/reels/stats", headers=_h(a))).json()
            assert s["posts"] == 2 and s["live"] == 2
            assert s["likes"] == 2 and s["shares"] == 1 and s["saves"] == 1 and s["views"] == 4

            # unposting keeps the post but drops the live count
            await c.post(f"/reels/{r1}/visibility", headers=_h(a), json={"live": False})
            s2 = (await c.get("/reels/stats", headers=_h(a))).json()
            assert s2["posts"] == 2 and s2["live"] == 1

    run(_t())


def test_stats_route_is_not_shadowed_by_the_reel_id_route(env):
    """`/reels/stats` is declared after `/reels/{reel_id}/…`; prove FastAPI
    still resolves it as the literal route and not as a reel id."""
    async def _t():
        async with await _client() as c:
            tk = await _token(c, "shadow@moodaiapp.com")
            r = await c.get("/reels/stats", headers=_h(tk))
            assert r.status_code == 200
            assert set(r.json()) >= {"posts", "views", "likes", "shares", "saves"}

    run(_t())


def test_engagement_endpoints_reject_missing_or_hidden_reels(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "gone@moodaiapp.com")
            b = await _token(c, "viewer7@moodaiapp.com")
            rid = await _post_reel(c, a)
            await c.post(f"/reels/{rid}/visibility", headers=_h(a), json={"live": False})
            for verb in ("like", "save", "share", "view"):
                assert (await c.post(f"/reels/{rid}/{verb}", headers=_h(b))).status_code == 404, verb
                assert (await c.post(f"/reels/nope/{verb}", headers=_h(b))).status_code == 404, verb

    run(_t())
