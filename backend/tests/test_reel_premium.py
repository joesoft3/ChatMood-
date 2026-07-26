"""⭐🔴 Reel premium gates + Go Live broadcasts.

Two things must never break here: a paying creator being wrongly blocked (a
support ticket), and a free creator slipping past a paid gate (lost revenue).
Both directions are pinned, plus the security rule that a stream KEY — a write
credential — never reaches the public feed payload.
"""

import asyncio

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import Base, Reel, User
from app.db.session import get_db
from app.main import app
from app.services import live_stream, reel_premium as premium

PW = "ReelPro-2026!"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096


def run(coro):
    return asyncio.run(coro)


class FakeUser:
    def __init__(self, plan="free", is_admin=False, email="c@test.io"):
        self.plan, self.is_admin, self.email = plan, is_admin, email


# ═════════════════════════════════════════════ entitlement predicate

def test_free_creator_is_not_premium():
    assert premium.is_premium(FakeUser(plan="free")) is False


def test_pro_creator_is_premium():
    assert premium.is_premium(FakeUser(plan="pro")) is True


def test_future_tiers_are_premium_by_default():
    """A new tier must not silently lose its perks."""
    for plan in ("heavy", "enterprise", "PRO"):
        assert premium.is_premium(FakeUser(plan=plan)) is True, plan


def test_admins_are_premium_even_on_free(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
    assert premium.is_premium(FakeUser(plan="free", is_admin=True)) is True


def test_anonymous_is_not_premium():
    assert premium.is_premium(None) is False


# ═════════════════════════════════════════════════════ caps & perks

def test_pro_gets_bigger_and_longer_clips():
    free, pro = FakeUser(), FakeUser(plan="pro")
    assert premium.max_bytes(pro) > premium.max_bytes(free)
    assert premium.max_seconds(pro) == premium.PRO_MAX_SECONDS
    assert premium.max_seconds(free) == premium.FREE_MAX_SECONDS


def test_premium_effects_are_gated_but_basics_are_free():
    free, pro = FakeUser(), FakeUser(plan="pro")
    for locked in premium.PREMIUM_EFFECTS:
        assert premium.effect_allowed(free, locked) is False, locked
        assert premium.effect_allowed(pro, locked) is True, locked
    for open_fx in ("none", "warm", "cool", "vivid", "mono"):
        assert premium.effect_allowed(free, open_fx) is True, open_fx


def test_entitlements_shape_drives_the_paywall_ui():
    e = premium.entitlements(FakeUser())
    assert e["premium"] is False and e["watermark"] is True
    assert e["resolution"] == "720x1280"
    ids = {p["id"] for p in e["perks"]}
    assert {"no_watermark", "premium_effects", "go_live", "hd_export"} <= ids
    # free perks stay unlocked so the paywall isn't a wall of padlocks
    unlocked = {p["id"] for p in e["perks"] if p["unlocked"]}
    assert "post" in unlocked and "duet" in unlocked
    assert "go_live" not in unlocked


def test_pro_entitlements_unlock_everything():
    e = premium.entitlements(FakeUser(plan="pro"))
    assert e["premium"] is True and e["watermark"] is False
    assert e["resolution"] == "1080x1920"
    assert all(p["unlocked"] for p in e["perks"])


def test_upgrade_message_is_actionable():
    msg = premium.upgrade_message("Go Live")
    assert "Go Live" in msg and "Upgrade" in msg


# ══════════════════════════════════════════════ live provider config

def test_go_live_is_unavailable_without_a_provider(monkeypatch):
    monkeypatch.setattr(settings, "LIVE_PROVIDER", "")
    assert premium.live_configured() is False
    # ...and a Pro creator still can't go live — infra, not entitlement
    assert premium.entitlements(FakeUser(plan="pro"))["go_live"] is False


def test_provider_needs_both_halves_of_its_credentials(monkeypatch):
    monkeypatch.setattr(settings, "LIVE_PROVIDER", "mux")
    monkeypatch.setattr(settings, "MUX_TOKEN_ID", "id")
    monkeypatch.setattr(settings, "MUX_TOKEN_SECRET", "")
    assert premium.live_configured() is False
    monkeypatch.setattr(settings, "MUX_TOKEN_SECRET", "secret")
    assert premium.live_configured() is True
    assert premium.entitlements(FakeUser(plan="pro"))["go_live"] is True


def test_unknown_provider_reports_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "LIVE_PROVIDER", "myspace_tv")
    assert premium.live_configured() is False


def test_provider_listing_is_honest(monkeypatch):
    monkeypatch.setattr(settings, "MUX_TOKEN_ID", "")
    by_id = {p["id"]: p for p in premium.live_providers()}
    assert set(by_id) == {"mux", "cloudflare", "livekit"}
    assert by_id["mux"]["configured"] is False
    assert "MUX_TOKEN_ID" in by_id["mux"]["env"]   # tells you exactly what's missing


def test_create_stream_refuses_rather_than_faking_a_url(monkeypatch):
    monkeypatch.setattr(settings, "LIVE_PROVIDER", "")
    with pytest.raises(live_stream.LiveNotConfigured):
        run(live_stream.create_stream())


def test_viewer_payload_never_carries_the_stream_key():
    """The key is a WRITE credential — anyone holding it can broadcast as you."""
    t = live_stream.LiveTarget(
        provider="mux", stream_id="s1", ingest_url="rtmps://x",
        stream_key="SUPER-SECRET", playback_url="https://p/x.m3u8",
    )
    viewer = t.as_viewer_dict()
    assert "SUPER-SECRET" not in str(viewer)
    assert "stream_key" not in viewer
    assert viewer["playback_url"] == "https://p/x.m3u8"
    assert t.as_owner_dict()["stream_key"] == "SUPER-SECRET"  # owner still gets it


def test_destroy_stream_never_raises():
    """A finished broadcast must be markable as ended even if teardown fails."""
    assert run(live_stream.destroy_stream("mux", "")) is False
    assert run(live_stream.destroy_stream("nonsense", "abc")) is False


# ═══════════════════════════════════════════════════════ API tests

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
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
    monkeypatch.setattr(settings, "LIVE_PROVIDER", "")
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


async def _upgrade(factory, email):
    async with factory() as s:
        u = (await s.execute(select(User).where(User.email == email))).scalar_one()
        u.plan = "pro"
        await s.commit()


def _fake_live(monkeypatch):
    """Stand in for the provider so no network call happens in tests."""
    async def fake_create(*, room_hint=""):
        return live_stream.LiveTarget(
            provider="mux", stream_id="stream-123",
            ingest_url="rtmps://global-live.mux.com:443/app",
            stream_key="KEY-DO-NOT-LEAK",
            playback_url="https://stream.mux.com/abc.m3u8",
        )

    async def fake_destroy(provider, stream_id):
        return True

    import app.services.live_stream as ls

    monkeypatch.setattr(ls, "create_stream", fake_create)
    monkeypatch.setattr(ls, "destroy_stream", fake_destroy)
    monkeypatch.setattr(settings, "LIVE_PROVIDER", "mux")
    monkeypatch.setattr(settings, "MUX_TOKEN_ID", "id")
    monkeypatch.setattr(settings, "MUX_TOKEN_SECRET", "sec")


# ─────────────────────────────────────────────── premium endpoint

def test_premium_endpoint_reports_locks_for_free_creators(api):
    async def go():
        async with await _client() as c:
            tok = await _token(c, "freebie@test.io")
            j = (await c.get("/reels/premium", headers=_h(tok))).json()
            assert j["premium"] is False and j["watermark"] is True
            assert j["go_live"] is False
            assert j["upgrade_path"] == "/upgrade"
            assert any(p["id"] == "go_live" and not p["unlocked"] for p in j["perks"])

    run(go())


def test_premium_endpoint_unlocks_for_pro(api, monkeypatch):
    _fake_live(monkeypatch)

    async def go():
        factory = api
        async with await _client() as c:
            tok = await _token(c, "prochap@test.io")
            await _upgrade(factory, "prochap@test.io")
            j = (await c.get("/reels/premium", headers=_h(tok))).json()
            assert j["premium"] is True and j["watermark"] is False
            assert j["go_live"] is True and j["resolution"] == "1080x1920"

    run(go())


# ────────────────────────────────────────────────── effect gating

def test_free_creator_is_blocked_from_premium_effects(api):
    async def go():
        async with await _client() as c:
            tok = await _token(c, "fx-free@test.io")
            r = await c.post(
                "/reels/upload",
                files={"file": ("c.mp4", MP4, "video/mp4")},
                data={"caption": "hi", "effect": "noir"},
                headers=_h(tok),
            )
            assert r.status_code == 402                 # payment required
            assert "Pro feature" in r.json()["detail"]

    run(go())


def test_pro_creator_may_use_premium_effects(api):
    async def go():
        factory = api
        async with await _client() as c:
            tok = await _token(c, "fx-pro@test.io")
            await _upgrade(factory, "fx-pro@test.io")
            r = await c.post(
                "/reels/upload",
                files={"file": ("c.mp4", MP4, "video/mp4")},
                data={"caption": "hi", "effect": "noir"},
                headers=_h(tok),
            )
            assert r.status_code == 201

    run(go())


def test_free_effects_stay_open(api):
    async def go():
        async with await _client() as c:
            tok = await _token(c, "fx-warm@test.io")
            r = await c.post(
                "/reels/upload",
                files={"file": ("c.mp4", MP4, "video/mp4")},
                data={"caption": "hi", "effect": "warm"},
                headers=_h(tok),
            )
            assert r.status_code == 201

    run(go())


def test_free_upload_over_the_free_cap_is_rejected_with_the_upsell(api, monkeypatch):
    monkeypatch.setattr(premium, "FREE_MAX_MB", 1)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "big@test.io")
            r = await c.post(
                "/reels/upload",
                files={"file": ("big.mp4", b"\x00" * (2 * 1024 * 1024), "video/mp4")},
                data={"caption": "big"},
                headers=_h(tok),
            )
            assert r.status_code == 413
            assert "Pro raises it" in r.json()["detail"]

    run(go())


# ──────────────────────────────────────────────────── Go Live API

def test_free_creator_cannot_go_live(api, monkeypatch):
    _fake_live(monkeypatch)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "nolive@test.io")
            r = await c.post("/reels/live/start", data={"caption": "hey"}, headers=_h(tok))
            assert r.status_code == 402 and "Go Live" in r.json()["detail"]

    run(go())


def test_go_live_503s_when_no_provider_is_configured(api, monkeypatch):
    """Pro entitlement isn't enough — the infra has to exist."""
    monkeypatch.setattr(settings, "LIVE_PROVIDER", "")

    async def go():
        factory = api
        async with await _client() as c:
            tok = await _token(c, "noinfra@test.io")
            await _upgrade(factory, "noinfra@test.io")
            r = await c.post("/reels/live/start", data={"caption": "hey"}, headers=_h(tok))
            assert r.status_code == 503 and "isn't configured" in r.json()["detail"]

    run(go())


def test_pro_creator_goes_live_and_gets_the_ingest_key(api, monkeypatch):
    _fake_live(monkeypatch)

    async def go():
        factory = api
        async with await _client() as c:
            tok = await _token(c, "golive@test.io")
            await _upgrade(factory, "golive@test.io")
            r = await c.post("/reels/live/start", data={"caption": "live now"}, headers=_h(tok))
            assert r.status_code == 201, r.text
            body = r.json()
            # the owner DOES get the key — they need it to broadcast
            assert body["stream"]["stream_key"] == "KEY-DO-NOT-LEAK"
            assert body["stream"]["ingest_url"].startswith("rtmps://")
            assert body["reel"]["kind"] == "live" and body["reel"]["live_state"] == "live"

    run(go())


def test_the_public_feed_never_leaks_a_stream_key(api, monkeypatch):
    """The single most important security property of Go Live."""
    _fake_live(monkeypatch)

    async def go():
        factory = api
        async with await _client() as c:
            host = await _token(c, "host@test.io")
            await _upgrade(factory, "host@test.io")
            await c.post("/reels/live/start", data={"caption": "live"}, headers=_h(host))

            viewer = await _token(c, "viewer@test.io")
            feed = await c.get("/reels", headers=_h(viewer))
            assert "KEY-DO-NOT-LEAK" not in feed.text
            card = feed.json()["reels"][0]
            assert card["live_state"] == "live"
            assert card["live_playback_url"] == "https://stream.mux.com/abc.m3u8"
            assert "stream_key" not in card

    run(go())


def test_live_broadcasts_float_to_the_top_of_the_feed(api, monkeypatch):
    _fake_live(monkeypatch)

    async def go():
        factory = api
        async with await _client() as c:
            other = await _token(c, "clipper@test.io")
            await c.post("/reels/upload", files={"file": ("c.mp4", MP4, "video/mp4")},
                         data={"caption": "a clip"}, headers=_h(other))

            host = await _token(c, "toplive@test.io")
            await _upgrade(factory, "toplive@test.io")
            await c.post("/reels/live/start", data={"caption": "LIVE"}, headers=_h(host))

            # the clip is NEWER, but a stream is only watchable while it runs
            feed = (await c.get("/reels", headers=_h(other))).json()["reels"]
            assert feed[0]["live_state"] == "live"

    run(go())


def test_only_one_broadcast_at_a_time(api, monkeypatch):
    _fake_live(monkeypatch)

    async def go():
        factory = api
        async with await _client() as c:
            tok = await _token(c, "twice@test.io")
            await _upgrade(factory, "twice@test.io")
            assert (await c.post("/reels/live/start", data={}, headers=_h(tok))).status_code == 201
            r = await c.post("/reels/live/start", data={}, headers=_h(tok))
            assert r.status_code == 409 and "already live" in r.json()["detail"]

    run(go())


def test_ending_a_broadcast_keeps_it_in_the_feed_as_a_replay(api, monkeypatch):
    _fake_live(monkeypatch)

    async def go():
        factory = api
        async with await _client() as c:
            tok = await _token(c, "ender@test.io")
            await _upgrade(factory, "ender@test.io")
            rid = (await c.post("/reels/live/start", data={"caption": "bye"},
                                headers=_h(tok))).json()["reel"]["id"]

            r = await c.post(f"/reels/live/{rid}/end", headers=_h(tok))
            assert r.status_code == 200 and r.json()["reel"]["live_state"] == "ended"

            # the post survives — viewers keep what they were watching
            feed = (await c.get("/reels", headers=_h(tok))).json()["reels"]
            assert any(x["id"] == rid for x in feed)
            # ending twice is a no-op, not an error
            assert (await c.post(f"/reels/live/{rid}/end", headers=_h(tok))).json()["already"] is True

    run(go())


def test_only_the_owner_can_end_a_broadcast(api, monkeypatch):
    _fake_live(monkeypatch)

    async def go():
        factory = api
        async with await _client() as c:
            host = await _token(c, "owner-live@test.io")
            await _upgrade(factory, "owner-live@test.io")
            rid = (await c.post("/reels/live/start", data={}, headers=_h(host))).json()["reel"]["id"]

            stranger = await _token(c, "stranger-live@test.io")
            assert (await c.post(f"/reels/live/{rid}/end", headers=_h(stranger))).status_code == 404

    run(go())


def test_viewer_counter_tracks_peak_and_never_goes_negative(api, monkeypatch):
    _fake_live(monkeypatch)

    async def go():
        factory = api
        async with await _client() as c:
            host = await _token(c, "counter@test.io")
            await _upgrade(factory, "counter@test.io")
            rid = (await c.post("/reels/live/start", data={}, headers=_h(host))).json()["reel"]["id"]
            v = await _token(c, "watcher@test.io")

            for _ in range(3):
                await c.post(f"/reels/live/{rid}/heartbeat", data={"joining": "true"}, headers=_h(v))
            # 3 joined, 1 left → 2 watching, peak stays at the high-water mark
            j = (await c.post(f"/reels/live/{rid}/heartbeat", data={"joining": "false"},
                              headers=_h(v))).json()
            assert j["viewers"] == 2 and j["peak"] == 3

            # a flurry of leaves must not drive the badge negative
            for _ in range(10):
                j = (await c.post(f"/reels/live/{rid}/heartbeat", data={"joining": "false"},
                                  headers=_h(v))).json()
            assert j["viewers"] == 0 and j["peak"] == 3

    run(go())


def test_heartbeat_on_an_ended_stream_reports_not_live(api, monkeypatch):
    _fake_live(monkeypatch)

    async def go():
        factory = api
        async with await _client() as c:
            host = await _token(c, "hb-end@test.io")
            await _upgrade(factory, "hb-end@test.io")
            rid = (await c.post("/reels/live/start", data={}, headers=_h(host))).json()["reel"]["id"]
            await c.post(f"/reels/live/{rid}/end", headers=_h(host))
            j = (await c.post(f"/reels/live/{rid}/heartbeat", data={"joining": "true"},
                              headers=_h(host))).json()
            assert j["live"] is False and j["viewers"] == 0

    run(go())


def test_ending_resets_the_live_viewer_count(api, monkeypatch):
    _fake_live(monkeypatch)

    async def go():
        factory = api
        async with await _client() as c:
            host = await _token(c, "reset@test.io")
            await _upgrade(factory, "reset@test.io")
            rid = (await c.post("/reels/live/start", data={}, headers=_h(host))).json()["reel"]["id"]
            await c.post(f"/reels/live/{rid}/heartbeat", data={"joining": "true"}, headers=_h(host))
            await c.post(f"/reels/live/{rid}/end", headers=_h(host))
            async with factory() as s:
                row = await s.get(Reel, rid)
                assert row.live_viewers == 0 and row.live_peak_viewers >= 1

    run(go())
