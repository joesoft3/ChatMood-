"""ChatGPT-parity pack: Study, Custom GPTs, archive, search, feedback, continue."""

import asyncio
import json

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes import chat as chatmod
from app.db.models import Base, Conversation, Message
from app.db.session import get_db
from app.main import app
from app.services.gpts import CATALOG, catalog_by_id

EMAIL = "chatgpt-parity@moodaiapp.com"
PW = "ChatGptParity-2026!"


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
    r = await c.post("/api/v1/auth/register", json={"email": email, "password": PW, "display_name": "Ada"})
    if r.status_code == 400:
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": PW})
    assert r.status_code in (200, 201), r.text
    return r.json()["access_token"]


def _auth(tk):
    return {"Authorization": f"Bearer {tk}"}


def test_study_mode_persists_without_wiping_fun(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            me = (await c.get("/api/v1/auth/me", headers=_auth(tk))).json()
            assert me["study_mode"] is False
            r = await c.patch(
                "/api/v1/auth/preferences",
                json={"study_mode": True, "fun_mode": True},
                headers=_auth(tk),
            )
            assert r.status_code == 200, r.text
            assert r.json()["study_mode"] is True
            assert r.json()["fun_mode"] is True
            r = await c.patch(
                "/api/v1/auth/preferences",
                json={"custom_instructions": "Be brief."},
                headers=_auth(tk),
            )
            assert r.json()["study_mode"] is True
            assert r.json()["fun_mode"] is True

    run(_t())


def test_study_flag_reaches_build_messages(env, monkeypatch):
    seen = {"study": None}

    async def fake_stream(*a, **k):
        yield {"type": "delta", "text": "hint first"}

    orig = chatmod.build_messages

    async def wrap(*a, **k):
        seen["study"] = k.get("study")
        return await orig(*a, **k)

    monkeypatch.setattr(chatmod, "build_messages", wrap)
    monkeypatch.setattr(chatmod.llm, "stream_chat", fake_stream)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            r = await c.post(
                "/api/v1/chat/stream",
                json={"message": "teach me photosynthesis", "files": [], "search": False, "study": True},
                headers=_auth(tk),
            )
            assert r.status_code == 200, r.text

    run(_t())
    assert seen["study"] is True


def test_catalog_and_custom_gpt_crud(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            listed = (await c.get("/api/v1/gpts", headers=_auth(tk))).json()
            assert any(g["id"] == "catalog:writing-coach" for g in listed["catalog"])
            assert listed["mine"] == []
            r = await c.post(
                "/api/v1/gpts",
                json={
                    "name": "Brand voice",
                    "emoji": "🎯",
                    "instructions": "Always write like a calm Accra radio host.",
                    "starters": ["Draft a launch post", "Soften this"],
                },
                headers=_auth(tk),
            )
            assert r.status_code == 201, r.text
            gid = r.json()["id"]
            assert r.json()["name"] == "Brand voice"
            got = (await c.get(f"/api/v1/gpts/{gid}", headers=_auth(tk))).json()
            assert "Accra" in got["instructions"]
            cat = (await c.get("/api/v1/gpts/catalog:code-reviewer", headers=_auth(tk))).json()
            assert cat["catalog"] is True
            bad = await c.patch(
                "/api/v1/gpts/catalog:code-reviewer",
                json={"name": "hacked"},
                headers=_auth(tk),
            )
            assert bad.status_code == 400
            r = await c.patch(
                f"/api/v1/gpts/{gid}",
                json={"name": "Brand voice v2"},
                headers=_auth(tk),
            )
            assert r.json()["name"] == "Brand voice v2"
            # other user cannot read it
            other = await _token(c, "other-gpt@moodaiapp.com")
            hidden = await c.get(f"/api/v1/gpts/{gid}", headers=_auth(other))
            assert hidden.status_code == 404
            gone = await c.delete(f"/api/v1/gpts/{gid}", headers=_auth(tk))
            assert gone.status_code == 204
            assert (await c.get(f"/api/v1/gpts/{gid}", headers=_auth(tk))).status_code == 404

    run(_t())


def test_chat_with_catalog_gpt_injects_instructions(env, monkeypatch):
    seen = {"gpt": None}

    async def fake_stream(*a, **k):
        yield {"type": "delta", "text": "coach reply"}

    orig = chatmod.build_messages

    async def wrap(*a, **k):
        seen["gpt"] = k.get("gpt_id")
        msgs, model, live = await orig(*a, **k)
        joined = " ".join(str(m.get("content")) for m in msgs if m.get("role") == "system")
        seen["brief"] = joined
        return msgs, model, live

    monkeypatch.setattr(chatmod, "build_messages", wrap)
    monkeypatch.setattr(chatmod.llm, "stream_chat", fake_stream)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            r = await c.post(
                "/api/v1/chat/stream",
                json={
                    "message": "Tighten this: we help teams ship.",
                    "files": [],
                    "search": False,
                    "gpt_id": "catalog:writing-coach",
                },
                headers=_auth(tk),
            )
            assert r.status_code == 200, r.text
            evs = _parse_sse(r.text)
            cid = next(e for e in evs if e["type"] == "meta")["conversation_id"]
            thread = (await c.get(f"/api/v1/conversations/{cid}", headers=_auth(tk))).json()
            assert thread["gpt_id"] == "catalog:writing-coach"

    run(_t())
    assert seen["gpt"] == "catalog:writing-coach"
    assert "Writing Coach" in seen["brief"]


def test_archive_hides_from_live_list(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            created = await c.post("/api/v1/conversations", json={"title": "Keep me"}, headers=_auth(tk))
            cid = created.json()["id"]
            live = (await c.get("/api/v1/conversations", headers=_auth(tk))).json()
            assert cid in {x["id"] for x in live}
            r = await c.patch(f"/api/v1/conversations/{cid}", json={"archived": True}, headers=_auth(tk))
            assert r.status_code == 200 and r.json()["archived"] is True
            live = (await c.get("/api/v1/conversations", headers=_auth(tk))).json()
            assert cid not in {x["id"] for x in live}
            boxed = (await c.get("/api/v1/conversations?archived=true", headers=_auth(tk))).json()
            assert cid in {x["id"] for x in boxed}
            # still readable
            assert (await c.get(f"/api/v1/conversations/{cid}", headers=_auth(tk))).status_code == 200

    run(_t())


def test_search_finds_message_body(env):
    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            created = await c.post("/api/v1/conversations", json={"title": "Groceries"}, headers=_auth(tk))
            cid = created.json()["id"]
            async with env() as s:
                s.add(Message(conversation_id=cid, role="user", content="Remember the waakye stall on Oxford Street"))
                s.add(Message(conversation_id=cid, role="assistant", content="Got it — Oxford Street waakye."))
                await s.commit()
            r = await c.get("/api/v1/conversations/search?q=waakye", headers=_auth(tk))
            assert r.status_code == 200, r.text
            hits = r.json()["results"]
            assert any(h["id"] == cid for h in hits)
            assert any("waakye" in (h.get("snippet") or "").lower() for h in hits)
            miss = await c.get("/api/v1/conversations/search?q=zzzznope", headers=_auth(tk))
            assert miss.json()["results"] == []

    run(_t())


def test_feedback_duplicate_export_and_continue(env, monkeypatch):
    async def fake_stream(*a, **k):
        yield {"type": "delta", "text": "first half"}

    monkeypatch.setattr(chatmod.llm, "stream_chat", fake_stream)

    async def _t():
        async with await _client() as c:
            tk = await _token(c)
            r = await c.post(
                "/api/v1/chat/stream",
                json={"message": "Write a long essay", "files": [], "search": False},
                headers=_auth(tk),
            )
            evs = _parse_sse(r.text)
            cid = next(e for e in evs if e["type"] == "meta")["conversation_id"]
            thread = (await c.get(f"/api/v1/conversations/{cid}", headers=_auth(tk))).json()
            aid = next(m["id"] for m in thread["messages"] if m["role"] == "assistant")
            fb = await c.post(
                f"/api/v1/conversations/{cid}/messages/{aid}/feedback",
                json={"rating": "up", "note": "clear"},
                headers=_auth(tk),
            )
            assert fb.status_code == 200 and fb.json()["feedback"]["rating"] == "up"
            thread = (await c.get(f"/api/v1/conversations/{cid}", headers=_auth(tk))).json()
            assert thread["messages"][-1]["meta"]["feedback"]["rating"] == "up"

            dup = await c.post(f"/api/v1/conversations/{cid}/duplicate", headers=_auth(tk))
            assert dup.status_code == 201, dup.text
            copy_id = dup.json()["id"]
            assert copy_id != cid
            copied = (await c.get(f"/api/v1/conversations/{copy_id}", headers=_auth(tk))).json()
            assert "(copy)" in copied["title"]
            assert any(m["content"] == "first half" for m in copied["messages"])

            exported = await c.get(f"/api/v1/conversations/{cid}/export", headers=_auth(tk))
            assert exported.status_code == 200
            assert any(m["content"] == "first half" for m in exported.json()["messages"])
            md = await c.get(f"/api/v1/conversations/{cid}/export?format=md", headers=_auth(tk))
            assert md.status_code == 200
            assert "first half" in md.text

            async def more(*a, **k):
                yield {"type": "delta", "text": " and the rest"}

            monkeypatch.setattr(chatmod.llm, "stream_chat", more)
            cont = await c.post(
                "/api/v1/chat/stream",
                json={"conversation_id": cid, "continue_gen": True, "files": [], "search": False},
                headers=_auth(tk),
            )
            assert cont.status_code == 200, cont.text
            thread = (await c.get(f"/api/v1/conversations/{cid}", headers=_auth(tk))).json()
            assistants = [m for m in thread["messages"] if m["role"] == "assistant"]
            assert len(assistants) == 1
            assert assistants[0]["content"] == "first half and the rest"
            users = [m for m in thread["messages"] if m["role"] == "user"]
            assert len(users) == 1  # continue must not add a user turn

    run(_t())


def test_catalog_has_pulse_and_study_tutor():
    assert catalog_by_id("catalog:pulse")["pulse"] is True
    assert any(g["id"] == "catalog:study-tutor" for g in CATALOG)
    assert catalog_by_id("catalog:nope") is None
