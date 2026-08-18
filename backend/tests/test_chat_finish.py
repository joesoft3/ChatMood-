"""Finish the chat: 📌 pin, ✏️ edit-and-resend, 💬 follow-ups, file_id on the wire."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes import chat as chatmod
from app.db.models import Base, Conversation, Message
from app.db.session import get_db
from app.main import app

EMAIL = "finisher-chat@moodaiapp.com"
PW = "Finish-2026!"
OTHER = "other@moodaiapp.com"


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
    r = await c.post("/api/v1/auth/register", json={"email": email, "password": PW, "display_name": "Fin"})
    if r.status_code == 400:
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": PW})
    assert r.status_code in (200, 201), r.text
    return r.json()["access_token"]


def _auth(tk):
    return {"Authorization": f"Bearer {tk}"}


async def _post_chat(c, tk, payload):
    r = await c.post("/api/v1/chat/stream", json=payload, headers=_auth(tk))
    assert r.status_code == 200, r.text
    return _parse_sse(r.text)


# ---------------------------------------------------------------- pin


def test_pin_sorts_to_top_and_is_idempotent(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            older = (
                await c.post("/api/v1/conversations", json={"title": "oldest"}, headers=_auth(tk))
            ).json()["id"]
            newer = (
                await c.post("/api/v1/conversations", json={"title": "newest"}, headers=_auth(tk))
            ).json()["id"]
            # sqlite timestamps are 1s resolution — stamp explicitly so recency is real
            async with env() as s:
                o = await s.get(Conversation, older)
                n = await s.get(Conversation, newer)
                now = datetime.now(timezone.utc)
                o.updated_at = now - timedelta(minutes=5)
                n.updated_at = now
                await s.commit()

            listed = (await c.get("/api/v1/conversations", headers=_auth(tk))).json()
            assert [x["id"] for x in listed] == [newer, older]
            assert all(x["pinned"] is False for x in listed)

            r = await c.patch(f"/api/v1/conversations/{older}", json={"pinned": True}, headers=_auth(tk))
            assert r.status_code == 200 and r.json()["pinned"] is True

            listed = (await c.get("/api/v1/conversations", headers=_auth(tk))).json()
            assert [x["id"] for x in listed] == [older, newer]
            assert listed[0]["pinned"] is True and listed[1]["pinned"] is False

            # unpin drops the flag; the row stays. (touching the row may bump
            # updated_at, so we don't assert recency after an unpin.)
            r = await c.patch(f"/api/v1/conversations/{older}", json={"pinned": False}, headers=_auth(tk))
            assert r.json()["pinned"] is False
            listed = (await c.get("/api/v1/conversations", headers=_auth(tk))).json()
            assert {x["id"] for x in listed} == {newer, older}
            assert next(x for x in listed if x["id"] == older)["pinned"] is False

            # empty PATCH is a 400, not a silent no-op
            bad = await c.patch(f"/api/v1/conversations/{older}", json={}, headers=_auth(tk))
            assert bad.status_code == 400

            # rename still works (the original contract)
            r = await c.patch(
                f"/api/v1/conversations/{older}", json={"title": "Pinned brief"}, headers=_auth(tk)
            )
            assert r.status_code == 200 and r.json()["title"] == "Pinned brief"

    run(_t())


def test_pin_is_owner_only(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            cid = (
                await c.post("/api/v1/conversations", json={"title": "mine"}, headers=_auth(tk))
            ).json()["id"]
            other = await _token(c, OTHER)
            r = await c.patch(f"/api/v1/conversations/{cid}", json={"pinned": True}, headers=_auth(other))
            assert r.status_code == 404

    run(_t())


# ---------------------------------------------------------------- edit


def test_edit_from_truncates_and_resends(env, monkeypatch):
    replies = iter(["first answer", "edited answer"])

    async def fake_stream(*a, **k):
        yield {"type": "delta", "text": next(replies)}

    monkeypatch.setattr(chatmod.llm, "stream_chat", fake_stream)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            first = await _post_chat(c, tk, {"message": "original question", "files": [], "search": False})
            cid = next(e for e in first if e["type"] == "meta")["conversation_id"]
            uid = next(e for e in first if e["type"] == "meta")["user_message_id"]
            assert uid

            evs = await _post_chat(
                c,
                tk,
                {
                    "conversation_id": cid,
                    "message": "better question",
                    "files": [],
                    "search": False,
                    "edit_from": uid,
                },
            )
            assert any(e.get("text") == "edited answer" for e in evs), evs

            thread = (await c.get(f"/api/v1/conversations/{cid}", headers=_auth(tk))).json()
            contents = [(m["role"], m["content"]) for m in thread["messages"]]
            assert contents == [("user", "better question"), ("assistant", "edited answer")], contents
            # the original user turn is gone
            assert uid not in {m["id"] for m in thread["messages"]}

    run(_t())


def test_edit_from_rejects_missing_or_assistant(env, monkeypatch):
    async def fake_stream(*a, **k):
        yield {"type": "delta", "text": "ok"}

    monkeypatch.setattr(chatmod.llm, "stream_chat", fake_stream)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            evs = await _post_chat(c, tk, {"message": "hello", "files": [], "search": False})
            cid = next(e for e in evs if e["type"] == "meta")["conversation_id"]
            thread = (await c.get(f"/api/v1/conversations/{cid}", headers=_auth(tk))).json()
            assistant_id = next(m["id"] for m in thread["messages"] if m["role"] == "assistant")

            missing = await c.post(
                "/api/v1/chat/stream",
                json={"conversation_id": cid, "message": "x", "files": [], "edit_from": "no-such"},
                headers=_auth(tk),
            )
            assert missing.status_code == 404

            asst = await c.post(
                "/api/v1/chat/stream",
                json={"conversation_id": cid, "message": "x", "files": [], "edit_from": assistant_id},
                headers=_auth(tk),
            )
            assert asst.status_code == 404

            other = await _token(c, OTHER)
            stolen = await c.post(
                "/api/v1/chat/stream",
                json={
                    "conversation_id": cid,
                    "message": "x",
                    "files": [],
                    "edit_from": thread["messages"][0]["id"],
                },
                headers=_auth(other),
            )
            assert stolen.status_code == 404

    run(_t())


# ---------------------------------------------------------------- suggestions


def test_suggestions_emit_three_chips(env, monkeypatch):
    async def fake_stream(*a, **k):
        yield {"type": "delta", "text": "Accra is the capital of Ghana."}

    async def fake_complete(messages, model=None, max_tokens=None, **kw):
        return "How big is Accra?\nBest time to visit?\nWhat language is spoken?"

    monkeypatch.setattr(chatmod.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chatmod.llm, "complete", fake_complete)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            evs = await _post_chat(c, tk, {"message": "capital of Ghana?", "files": [], "search": False})
            sug = next((e for e in evs if e["type"] == "suggestions"), None)
            assert sug is not None, evs
            assert sug["suggestions"] == [
                "How big is Accra?",
                "Best time to visit?",
                "What language is spoken?",
            ]
            assert evs[-1]["type"] == "done"

    run(_t())


def test_suggestions_fail_open(env, monkeypatch):
    async def fake_stream(*a, **k):
        yield {"type": "delta", "text": "hello"}

    async def boom(*a, **k):
        raise RuntimeError("quota storm")

    monkeypatch.setattr(chatmod.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(chatmod.llm, "complete", boom)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            evs = await _post_chat(c, tk, {"message": "hi", "files": [], "search": False})
            assert not any(e["type"] == "suggestions" for e in evs)
            assert evs[-1]["type"] == "done"
            assert any(e.get("text") == "hello" for e in evs)

    run(_t())


def test_user_message_id_is_on_meta(env, monkeypatch):
    async def fake_stream(*a, **k):
        yield {"type": "delta", "text": "ok"}

    monkeypatch.setattr(chatmod.llm, "stream_chat", fake_stream)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            evs = await _post_chat(c, tk, {"message": "ping", "files": [], "search": False})
            meta = next(e for e in evs if e["type"] == "meta")
            assert meta["user_message_id"]
            async with env() as s:
                row = await s.get(Message, meta["user_message_id"])
                assert row is not None and row.role == "user" and row.content == "ping"

    run(_t())
