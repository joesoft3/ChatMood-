"""Grok-parity pack: 😄 Fun mode, 👻 temporary chats, ✏️ editable memory, DeeperSearch."""

import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes import chat as chatmod
from app.db.models import Base, Conversation, User
from app.db.session import get_db
from app.main import app
from app.services import memory as memmod
from app.services.deepsearch import depth_config

EMAIL = "grok-parity@moodaiapp.com"
PW = "GrokParity-2026!"


def _parse_sse(body: str) -> list[dict]:
    out = []
    for chunk in body.split("\n\n"):
        line = chunk.strip()
        if line.startswith("data:"):
            try:
                out.append(json.loads(line[5:].strip()))
            except Exception:
                pass
    return out


@pytest.fixture()
def env(monkeypatch):
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
    monkeypatch.setattr(chatmod, "SessionLocal", factory)
    yield factory
    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


def run(coro):
    return asyncio.run(coro)


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _token(c, email=EMAIL):
    r = await c.post("/api/v1/auth/register", json={"email": email, "password": PW, "display_name": "Grok"})
    if r.status_code == 400:
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": PW})
    assert r.status_code in (200, 201), r.text
    return r.json()["access_token"]


def _auth(tk):
    return {"Authorization": f"Bearer {tk}"}


def test_fun_mode_persists_on_preferences(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            me = (await c.get("/api/v1/auth/me", headers=_auth(tk))).json()
            assert me["fun_mode"] is False
            r = await c.patch(
                "/api/v1/auth/preferences",
                json={"fun_mode": True},
                headers=_auth(tk),
            )
            assert r.status_code == 200, r.text
            assert r.json()["fun_mode"] is True
            me = (await c.get("/api/v1/auth/me", headers=_auth(tk))).json()
            assert me["fun_mode"] is True
            # instructions-only PATCH must not wipe Fun
            r = await c.patch(
                "/api/v1/auth/preferences",
                json={"custom_instructions": "Be brief."},
                headers=_auth(tk),
            )
            assert r.json()["fun_mode"] is True
            assert r.json()["custom_instructions"] == "Be brief."

    run(_t())


def test_temporary_chat_is_hidden_from_history_and_skips_memory(env, monkeypatch):
    calls = {"extract": 0, "summary": 0}

    async def fake_stream(*a, **k):
        yield {"type": "delta", "text": "incognito ok"}

    async def fake_extract(*a, **k):
        calls["extract"] += 1

    async def fake_summary(*a, **k):
        calls["summary"] += 1

    monkeypatch.setattr(chatmod.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chatmod, "extract_and_store", fake_extract)
    monkeypatch.setattr(chatmod, "update_conversation_summary", fake_summary)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            r = await c.post(
                "/api/v1/chat/stream",
                json={"message": "secret plan", "files": [], "search": False, "temporary": True},
                headers=_auth(tk),
            )
            assert r.status_code == 200, r.text
            evs = _parse_sse(r.text)
            cid = next(e for e in evs if e["type"] == "meta")["conversation_id"]
            listed = (await c.get("/api/v1/conversations", headers=_auth(tk))).json()
            assert cid not in {x["id"] for x in listed}
            # the thread itself is still readable this session
            thread = (await c.get(f"/api/v1/conversations/{cid}", headers=_auth(tk))).json()
            assert thread["temporary"] is True
            assert any(m["content"] == "incognito ok" for m in thread["messages"])

    run(_t())
    assert calls["extract"] == 0
    assert calls["summary"] == 0


def test_normal_chat_still_lists_and_writes_memory(env, monkeypatch):
    calls = {"extract": 0}

    async def fake_stream(*a, **k):
        yield {"type": "delta", "text": "normal ok"}

    async def fake_extract(*a, **k):
        calls["extract"] += 1

    async def fake_summary(*a, **k):
        return None

    monkeypatch.setattr(chatmod.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chatmod, "extract_and_store", fake_extract)
    monkeypatch.setattr(chatmod, "update_conversation_summary", fake_summary)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            r = await c.post(
                "/api/v1/chat/stream",
                json={"message": "hello", "files": [], "search": False},
                headers=_auth(tk),
            )
            assert r.status_code == 200, r.text
            evs = _parse_sse(r.text)
            cid = next(e for e in evs if e["type"] == "meta")["conversation_id"]
            listed = (await c.get("/api/v1/conversations", headers=_auth(tk))).json()
            assert cid in {x["id"] for x in listed}

    run(_t())
    assert calls["extract"] == 1


def test_fun_flag_reaches_build_messages(env, monkeypatch):
    seen = {"fun": None}

    async def fake_stream(*a, **k):
        yield {"type": "delta", "text": "ha"}

    orig = chatmod.build_messages

    async def wrap(*a, **k):
        seen["fun"] = k.get("fun")
        return await orig(*a, **k)

    monkeypatch.setattr(chatmod, "build_messages", wrap)
    monkeypatch.setattr(chatmod.llm, "stream_chat", fake_stream)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            r = await c.post(
                "/api/v1/chat/stream",
                json={"message": "joke?", "files": [], "search": False, "fun": True},
                headers=_auth(tk),
            )
            assert r.status_code == 200, r.text

    run(_t())
    assert seen["fun"] is True


def test_deeper_depth_config():
    assert depth_config("deep") == (2, 4)
    assert depth_config("deeper") == (3, 5)
    assert depth_config("nope") == (2, 4)


def test_update_memory_rewrites_fact_and_drops_old_id(monkeypatch):
    store: dict = {}

    class FakeQ:
        async def retrieve(self, _col, ids, with_payload=True):
            pid = ids[0]
            if pid not in store:
                return []

            class P:
                def __init__(self, i, payload):
                    self.id = i
                    self.payload = payload

            return [P(pid, store[pid])]

        async def upsert(self, _col, points):
            for p in points:
                store[str(p.id)] = p.payload

        async def delete(self, _col, points_selector):
            for pid in points_selector.points:
                store.pop(str(pid), None)

    async def fake_embed(texts):
        return [[0.1] * 8 for _ in texts]

    monkeypatch.setattr(memmod, "qdrant", lambda: FakeQ())
    monkeypatch.setattr(memmod, "embed", fake_embed)

    uid = "user-1"
    old_id = "mem-old"
    store[old_id] = {
        "user_id": uid,
        "kind": "fact",
        "fact": "likes jollof",
        "category": "preference",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    row = run(memmod.update_memory(uid, old_id, "loves waakye", "preference"))
    assert row is not None
    assert row["fact"] == "loves waakye"
    assert row["id"] != old_id
    assert old_id not in store
    assert store[row["id"]]["fact"] == "loves waakye"

    missing = run(memmod.update_memory("other", row["id"], "nope"))
    assert missing is None
