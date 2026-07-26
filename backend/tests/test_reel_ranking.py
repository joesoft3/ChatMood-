"""🏆 For You ranking, follow graph, watch telemetry and comments.

The point of these tests is behavioural, not arithmetic: a reel people finish
and share should out-rank a newer one nobody watched, following a creator should
change what you see, and one prolific author must not be able to wall off the
feed. Those are the properties that separate a ranked feed from a list.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import Base, Reel
from app.db.session import get_db
from app.main import app
from app.services import reel_rank, soundtrack

PW = "Reel-Rank-2026!"
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


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _me(c, t):
    return (await c.get("/auth/me", headers=_h(t))).json()["id"]


async def _post(c, tok, caption):
    r = await c.post(
        "/reels/upload", headers=_h(tok),
        files={"file": ("v.mp4", MP4, "video/mp4")}, data={"caption": caption},
    )
    assert r.status_code == 201, r.text
    return r.json()["reel"]["id"]


# ───────────────────────────────────────────────────── pure scoring model
def test_engagement_weights_rank_intent_above_volume():
    """A share is worth more than a view — a thousand passive views must not
    beat a handful of people who actively put their name on the reel."""
    passive = reel_rank.engagement_score(views=1000)
    endorsed = reel_rank.engagement_score(views=10, shares=15, saves=10)
    assert endorsed > passive


def test_completion_multiplies_the_score():
    """Same interactions, different completion → the finished reel wins."""
    bail = reel_rank.engagement_score(views=100, likes=10, completion=0.05)
    finish = reel_rank.engagement_score(views=100, likes=10, completion=0.95)
    assert finish > bail * 2


def test_completion_is_clamped_against_a_hostile_client():
    """A client reporting completion=50 must not be able to buy the top slot."""
    sane = reel_rank.engagement_score(likes=1, completion=1.0)
    absurd = reel_rank.engagement_score(likes=1, completion=50.0)
    assert absurd == sane


def test_time_decay_is_monotonic_and_normalized():
    assert reel_rank.time_decay(0) == pytest.approx(1.0)
    assert reel_rank.time_decay(1) > reel_rank.time_decay(10) > reel_rank.time_decay(100)
    assert reel_rank.time_decay(10_000) > 0  # never negative, never zero-divides


def test_quality_beats_freshness_but_not_forever():
    """The core tradeoff: a great 12-hour-old reel outranks a new empty one,
    yet a week later freshness has won — otherwise the feed calcifies."""
    now = datetime.now(timezone.utc)
    great_12h = reel_rank.hot_score(
        created_at=now - timedelta(hours=12),
        views=5000, likes=800, shares=200, saves=150, completion=0.9, now=now,
    )
    empty_new = reel_rank.hot_score(created_at=now, now=now)
    assert great_12h > empty_new

    great_7d = reel_rank.hot_score(
        created_at=now - timedelta(days=7),
        views=5000, likes=800, shares=200, saves=150, completion=0.9, now=now,
    )
    assert great_7d < empty_new


def test_new_reels_get_an_exploration_floor():
    """A brand-new reel with zero engagement still scores > 0, or nothing new
    would ever collect the impressions it needs to prove itself."""
    now = datetime.now(timezone.utc)
    assert reel_rank.hot_score(created_at=now, now=now) > 0


def test_following_outranks_a_stranger_at_equal_engagement():
    base = 10.0
    assert reel_rank.personalize(base, is_following=True) > reel_rank.personalize(base)
    assert (
        reel_rank.personalize(base, has_affinity=True) > reel_rank.personalize(base)
    )
    # your own reel is damped in your own For You
    assert reel_rank.personalize(base, is_own=True) < base


def test_diversify_breaks_up_a_single_author_run():
    """Six reels from one creator must not hold the whole feed."""
    scored = [(f"r{i}", 100.0 - i, "hog") for i in range(5)]
    scored.append(("guest", 60.0, "other"))
    out = reel_rank.diversify(scored)
    authors = [a for _, _, a in out]
    # the guest is lifted out of last place by the damping
    assert authors.index("other") < 5
    assert out == sorted(out, key=lambda t: t[1], reverse=True)


def test_mean_completion_guards_division_by_zero():
    assert reel_rank.mean_completion(0.0, 0) == 0.0
    assert reel_rank.mean_completion(1.5, 2) == 0.75


# ─────────────────────────────────────────────────────────── ranked feed
def test_foryou_ranks_the_engaging_reel_above_the_newer_empty_one(env):
    """End-to-end: the ranked default reorders, `sort=new` still doesn't."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "ranker-a@moodaiapp.com")
            b = await _token(c, "ranker-b@moodaiapp.com")
            good = await _post(c, a, "the good one")
            await asyncio.sleep(0.01)
            await _post(c, b, "the newer empty one")

            # give the older reel real engagement from another viewer
            await c.post(f"/reels/{good}/like", headers=_h(b))
            await c.post(f"/reels/{good}/save", headers=_h(b))
            for _ in range(3):
                await c.post(f"/reels/{good}/share", headers=_h(b))
            await c.post(f"/reels/{good}/watch", headers=_h(b),
                         json={"watched_ms": 9500, "duration_s": 10})

            foryou = (await c.get("/reels", headers=_h(b))).json()
            assert foryou["sort"] == "foryou"
            assert foryou["reels"][0]["caption"] == "the good one"
            # score is exposed so the UI can explain the ordering
            assert foryou["reels"][0]["score"] > foryou["reels"][1]["score"]

            chrono = (await c.get("/reels?sort=new", headers=_h(b))).json()
            assert chrono["reels"][0]["caption"] == "the newer empty one"

    run(_t())


def test_foryou_paginates_without_repeating_or_dropping(env):
    """Ranked pagination must still cover every reel exactly once."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "pager@moodaiapp.com")
            for i in range(25):
                await _post(c, a, f"clip {i}")

            first = (await c.get("/reels", headers=_h(a))).json()
            assert len(first["reels"]) == 20
            assert first["total"] == 25
            second = (
                await c.get(f"/reels?offset={first['next_offset']}", headers=_h(a))
            ).json()
            ids = [r["id"] for r in first["reels"]] + [r["id"] for r in second["reels"]]
            assert len(ids) == 25
            assert len(set(ids)) == 25          # no duplicates across pages
            assert second["next_offset"] is None

    run(_t())


def test_hidden_reels_never_enter_the_ranked_feed(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "hider@moodaiapp.com")
            b = await _token(c, "looker@moodaiapp.com")
            rid = await _post(c, a, "soon hidden")
            await c.post(f"/reels/{rid}/visibility", headers=_h(a), json={"live": False})
            feed = (await c.get("/reels", headers=_h(b))).json()
            assert feed["reels"] == []
            assert feed["total"] == 0

    run(_t())


# ───────────────────────────────────────────────────────────── follow graph
def test_follow_is_persisted_and_drives_the_following_feed(env):
    """Follow used to be localStorage — it must now survive on the server and
    actually filter a feed."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "star@moodaiapp.com")
            b = await _token(c, "fan@moodaiapp.com")
            other = await _token(c, "stranger@moodaiapp.com")
            star_id = await _me(c, a)

            await _post(c, a, "from the star")
            await _post(c, other, "from a stranger")

            # nothing followed yet → the Following feed is empty, not "everything"
            empty = (await c.get("/reels?following=true", headers=_h(b))).json()
            assert empty["reels"] == [] and empty["total"] == 0

            r = await c.post(f"/reels/authors/{star_id}/follow", headers=_h(b))
            assert r.status_code == 200
            assert r.json() == {"following": True, "followers": 1, "author_id": star_id}

            feed = (await c.get("/reels?following=true", headers=_h(b))).json()
            assert [x["caption"] for x in feed["reels"]] == ["from the star"]
            assert feed["reels"][0]["following"] is True

            # the flag is reflected on the main feed too, so the badge is right
            foryou = (await c.get("/reels", headers=_h(b))).json()
            flags = {x["caption"]: x["following"] for x in foryou["reels"]}
            assert flags == {"from the star": True, "from a stranger": False}

            # idempotent toggle back off
            r = await c.post(f"/reels/authors/{star_id}/follow", headers=_h(b))
            assert r.json()["following"] is False
            assert (await c.get("/reels?following=true", headers=_h(b))).json()["total"] == 0

    run(_t())


def test_you_cannot_follow_yourself_or_a_ghost(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "solo@moodaiapp.com")
            me = await _me(c, a)
            assert (await c.post(f"/reels/authors/{me}/follow", headers=_h(a))).status_code == 422
            r = await c.post("/reels/authors/does-not-exist/follow", headers=_h(a))
            assert r.status_code == 404

    run(_t())


def test_following_boosts_that_creator_in_for_you(env):
    """Same-age reels: the followed creator's should surface first."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "followed@moodaiapp.com")
            b = await _token(c, "ignored@moodaiapp.com")
            v = await _token(c, "viewer2@moodaiapp.com")
            a_id = await _me(c, a)

            await _post(c, a, "followed creator")
            await asyncio.sleep(0.01)
            await _post(c, b, "unfollowed creator")   # newer, so chronology favours it

            await c.post(f"/reels/authors/{a_id}/follow", headers=_h(v))
            feed = (await c.get("/reels", headers=_h(v))).json()
            assert feed["reels"][0]["caption"] == "followed creator"

    run(_t())


# ────────────────────────────────────────────────────────── watch telemetry
def test_watch_reports_accumulate_and_surface_completion(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "watched@moodaiapp.com")
            b = await _token(c, "watcher@moodaiapp.com")
            rid = await _post(c, a, "watch me")

            r = await c.post(f"/reels/{rid}/watch", headers=_h(b),
                             json={"watched_ms": 5000, "duration_s": 10})
            assert r.status_code == 200
            assert r.json()["completion"] == pytest.approx(0.5)

            # the same viewer re-watching to the end refines (not duplicates) it
            r = await c.post(f"/reels/{rid}/watch", headers=_h(b),
                             json={"watched_ms": 10000, "duration_s": 10, "replays": 1})
            assert r.json()["completion"] == pytest.approx(1.0)

            feed = (await c.get("/reels?sort=new", headers=_h(b))).json()
            card = feed["reels"][0]
            assert card["completion"] == pytest.approx(1.0)
            assert card["duration_s"] == pytest.approx(10.0)

    run(_t())


def test_watch_report_is_clamped_and_validated(env):
    """Absurd or malformed reports are neutralised, never 500."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "clamp@moodaiapp.com")
            b = await _token(c, "clamper@moodaiapp.com")
            rid = await _post(c, a, "clamp me")

            # watched far longer than the duration → completion caps at 1.0
            r = await c.post(f"/reels/{rid}/watch", headers=_h(b),
                             json={"watched_ms": 999_999_999, "duration_s": 5})
            assert r.status_code == 200
            assert r.json()["completion"] == pytest.approx(1.0)

            r = await c.post(f"/reels/{rid}/watch", headers=_h(b),
                             json={"watched_ms": "banana", "duration_s": 5})
            assert r.status_code == 422

            r = await c.post("/reels/nope/watch", headers=_h(b),
                             json={"watched_ms": 100, "duration_s": 5})
            assert r.status_code == 404

    run(_t())


def test_negative_watch_values_cannot_reduce_the_aggregate(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "neg@moodaiapp.com")
            b = await _token(c, "negger@moodaiapp.com")
            rid = await _post(c, a, "negative")
            r = await c.post(f"/reels/{rid}/watch", headers=_h(b),
                             json={"watched_ms": -5000, "duration_s": -10})
            assert r.status_code == 200
            assert r.json()["completion"] == 0.0

    run(_t())


# ──────────────────────────────────────────────────────────────── comments
def test_comment_lifecycle_and_counter(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "poster@moodaiapp.com")
            b = await _token(c, "commenter@moodaiapp.com")
            rid = await _post(c, a, "say something")

            r = await c.post(f"/reels/{rid}/comments", headers=_h(b), json={"body": "🔥 unreal"})
            assert r.status_code == 201
            cid = r.json()["comment"]["id"]
            assert r.json()["comments"] == 1
            assert r.json()["comment"]["mine"] is True

            listing = (await c.get(f"/reels/{rid}/comments", headers=_h(a))).json()
            assert [x["body"] for x in listing["comments"]] == ["🔥 unreal"]
            assert listing["comments"][0]["mine"] is False   # author of the reel, not the comment

            # the count rides on the feed card so the UI needs no extra call
            card = (await c.get("/reels?sort=new", headers=_h(a))).json()["reels"][0]
            assert card["comments"] == 1

            # commenter deletes their own
            assert (await c.delete(f"/reels/{rid}/comments/{cid}", headers=_h(b))).status_code == 204
            card = (await c.get("/reels?sort=new", headers=_h(a))).json()["reels"][0]
            assert card["comments"] == 0

    run(_t())


def test_reel_author_can_moderate_but_strangers_cannot(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "owner@moodaiapp.com")
            b = await _token(c, "rude@moodaiapp.com")
            d = await _token(c, "nosy@moodaiapp.com")
            rid = await _post(c, a, "my reel")
            cid = (
                await c.post(f"/reels/{rid}/comments", headers=_h(b), json={"body": "spam"})
            ).json()["comment"]["id"]

            # an unrelated user cannot delete it
            assert (await c.delete(f"/reels/{rid}/comments/{cid}", headers=_h(d))).status_code == 404
            # the reel's author can (moderation on their own post)
            assert (await c.delete(f"/reels/{rid}/comments/{cid}", headers=_h(a))).status_code == 204

    run(_t())


def test_comment_validation(env):
    async def _t():
        async with await _client() as c:
            a = await _token(c, "val@moodaiapp.com")
            rid = await _post(c, a, "validate")
            assert (await c.post(f"/reels/{rid}/comments", headers=_h(a),
                                 json={"body": "   "})).status_code == 422
            assert (await c.post(f"/reels/{rid}/comments", headers=_h(a),
                                 json={"body": "x" * 501})).status_code == 422
            assert (await c.post("/reels/ghost/comments", headers=_h(a),
                                 json={"body": "hi"})).status_code == 404

    run(_t())


def test_profile_stats_report_followers_comments_and_completion(env):
    """The profile strip needs more than vanity tallies: followers prove the
    graph is real, and mean completion is what predicts reach."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "creator@moodaiapp.com")
            b = await _token(c, "audience@moodaiapp.com")
            a_id = await _me(c, a)
            rid = await _post(c, a, "measured")

            await c.post(f"/reels/authors/{a_id}/follow", headers=_h(b))
            await c.post(f"/reels/{rid}/comments", headers=_h(b), json={"body": "great"})
            await c.post(f"/reels/{rid}/watch", headers=_h(b),
                         json={"watched_ms": 8000, "duration_s": 10})

            s = (await c.get("/reels/stats", headers=_h(a))).json()
            assert s["followers"] == 1
            assert s["following"] == 0
            assert s["comments"] == 1
            assert s["completion"] == pytest.approx(0.8)

            # and the follower's own view of the same numbers
            s2 = (await c.get("/reels/stats", headers=_h(b))).json()
            assert s2["following"] == 1 and s2["followers"] == 0

    run(_t())


def test_deleting_a_reel_takes_its_comments_and_watch_rows_with_it(env):
    """SQLite doesn't enforce ON DELETE CASCADE by default — orphan comments or
    watch rows would resurface against a recycled id and keep feeding the
    ranker signal for a reel nobody can watch. Assert on the TABLES, not just
    the 404: the endpoint would 404 anyway once the reel row is gone."""
    async def _t():
        async with await _client() as c:
            a = await _token(c, "cleanup@moodaiapp.com")
            b = await _token(c, "chatty@moodaiapp.com")
            rid = await _post(c, a, "temporary")
            await c.post(f"/reels/{rid}/comments", headers=_h(b), json={"body": "bye"})
            await c.post(f"/reels/{rid}/watch", headers=_h(b),
                         json={"watched_ms": 3000, "duration_s": 5})
            assert (await c.delete(f"/reels/{rid}", headers=_h(a))).status_code == 204
            assert (await c.get(f"/reels/{rid}/comments", headers=_h(a))).status_code == 404

        # nothing left behind in either child table
        async with env() as s:
            from sqlalchemy import func as f, select as sel
            from app.db.models import ReelComment, ReelWatch
            assert int(await s.scalar(
                sel(f.count(ReelComment.id)).where(ReelComment.reel_id == rid)) or 0) == 0
            assert int(await s.scalar(
                sel(f.count()).select_from(ReelWatch).where(ReelWatch.reel_id == rid)) or 0) == 0

    run(_t())
