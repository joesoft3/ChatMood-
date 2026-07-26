"""🗂 Projects — containers with standing instructions + pinned files.

Covers the two promises that make a project more than a folder:
  1. its brief reaches the model on every turn of every chat inside it, and
  2. deleting the container never destroys the user's chats or uploads.
"""

import asyncio

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import Base, Conversation, FileAsset
from app.db.session import get_db
from app.main import app

PW = "Projects-2026!"


def run(coro):
    return asyncio.run(coro)


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
    monkeypatch.setattr(settings, "PROJECTS_ENABLED", True)
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


# ---------- CRUD ----------

def test_create_list_and_update_project(env):
    async def go():
        async with await _client() as c:
            tok = await _token(c, "proj1@test.io")
            r = await c.post(
                "/projects",
                json={
                    "name": "Q3 Launch",
                    "description": "Go-to-market",
                    "instructions": "Always answer in British English.",
                    "emoji": "🚀",
                    "accent": "#7c9bff",
                },
                headers=_h(tok),
            )
            assert r.status_code == 201, r.text
            pid = r.json()["id"]
            assert r.json()["emoji"] == "🚀"

            r = await c.get("/projects", headers=_h(tok))
            assert r.status_code == 200
            assert [p["name"] for p in r.json()] == ["Q3 Launch"]
            assert r.json()[0]["chats"] == 0 and r.json()[0]["files"] == 0

            r = await c.patch(f"/projects/{pid}", json={"name": "Q4 Launch"}, headers=_h(tok))
            assert r.json()["name"] == "Q4 Launch"
            # instructions were not sent → unchanged (PATCH semantics)
            assert r.json()["instructions"] == "Always answer in British English."

            # archived projects drop out of the default list but survive
            await c.patch(f"/projects/{pid}", json={"archived": True}, headers=_h(tok))
            assert (await c.get("/projects", headers=_h(tok))).json() == []
            r = await c.get("/projects?include_archived=true", headers=_h(tok))
            assert len(r.json()) == 1

    run(go())


def test_projects_are_private_to_their_owner(env):
    async def go():
        async with await _client() as c:
            a = await _token(c, "owner@test.io")
            b = await _token(c, "stranger@test.io")
            pid = (await c.post("/projects", json={"name": "Secret"}, headers=_h(a))).json()["id"]

            assert (await c.get(f"/projects/{pid}", headers=_h(b))).status_code == 404
            assert (await c.patch(f"/projects/{pid}", json={"name": "hax"}, headers=_h(b))).status_code == 404
            assert (await c.delete(f"/projects/{pid}", headers=_h(b))).status_code == 404
            # ...and the owner still sees it untouched
            assert (await c.get(f"/projects/{pid}", headers=_h(a))).json()["name"] == "Secret"

    run(go())


def test_project_limit_is_enforced(env, monkeypatch):
    monkeypatch.setattr(settings, "PROJECT_MAX_PER_USER", 2)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "limit@test.io")
            for i in range(2):
                assert (await c.post("/projects", json={"name": f"P{i}"}, headers=_h(tok))).status_code == 201
            r = await c.post("/projects", json={"name": "P3"}, headers=_h(tok))
            assert r.status_code == 400
            assert "limit reached" in r.json()["detail"].lower()

    run(go())


# ---------- filing chats + pinning files ----------

def test_filing_and_unfiling_a_conversation(env):
    async def go():
        async with await _client() as c:
            tok = await _token(c, "file@test.io")
            pid = (await c.post("/projects", json={"name": "Research"}, headers=_h(tok))).json()["id"]
            cid = (await c.post("/conversations", json={"title": "Notes"}, headers=_h(tok))).json()["id"]

            assert (await c.post(f"/projects/{pid}/conversations/{cid}", headers=_h(tok))).status_code == 200
            detail = (await c.get(f"/projects/{pid}", headers=_h(tok))).json()
            assert [x["id"] for x in detail["conversations"]] == [cid]
            assert detail["chats"] == 1

            assert (await c.delete(f"/projects/{pid}/conversations/{cid}", headers=_h(tok))).status_code == 200
            assert (await c.get(f"/projects/{pid}", headers=_h(tok))).json()["conversations"] == []

    run(go())


def test_pin_and_unpin_files_and_the_pin_cap(env, monkeypatch):
    monkeypatch.setattr(settings, "PROJECT_MAX_FILES", 2)

    async def go():
        factory = env
        async with await _client() as c:
            tok = await _token(c, "pin@test.io")
            me = (await c.get("/auth/me", headers=_h(tok))).json()
            pid = (await c.post("/projects", json={"name": "Docs"}, headers=_h(tok))).json()["id"]

            ids = []
            async with factory() as s:
                for i in range(3):
                    a = FileAsset(
                        user_id=me["id"], filename=f"doc{i}.txt", mime="text/plain",
                        path=f"/tmp/doc{i}.txt", size_bytes=10, extracted_text=f"body {i}",
                    )
                    s.add(a)
                    await s.flush()
                    ids.append(a.id)
                await s.commit()

            assert (await c.post(f"/projects/{pid}/files/{ids[0]}", headers=_h(tok))).status_code == 201
            assert (await c.post(f"/projects/{pid}/files/{ids[1]}", headers=_h(tok))).status_code == 201
            # third exceeds the cap
            r = await c.post(f"/projects/{pid}/files/{ids[2]}", headers=_h(tok))
            assert r.status_code == 400 and "maximum" in r.json()["detail"].lower()

            # re-pinning an existing file is idempotent, not an error
            assert (await c.post(f"/projects/{pid}/files/{ids[0]}", headers=_h(tok))).status_code == 201
            assert (await c.get(f"/projects/{pid}", headers=_h(tok))).json()["files"] == 2

            assert (await c.delete(f"/projects/{pid}/files/{ids[0]}", headers=_h(tok))).status_code == 200
            assert (await c.get(f"/projects/{pid}", headers=_h(tok))).json()["files"] == 1

    run(go())


def test_deleting_a_project_unfiles_chats_but_keeps_them(env):
    """Deleting an organizational container must never delete real content."""

    async def go():
        factory = env
        async with await _client() as c:
            tok = await _token(c, "del@test.io")
            pid = (await c.post("/projects", json={"name": "Temp"}, headers=_h(tok))).json()["id"]
            cid = (await c.post("/conversations", json={"title": "Keep me"}, headers=_h(tok))).json()["id"]
            await c.post(f"/projects/{pid}/conversations/{cid}", headers=_h(tok))

            assert (await c.delete(f"/projects/{pid}", headers=_h(tok))).status_code == 204
            assert (await c.get(f"/projects/{pid}", headers=_h(tok))).status_code == 404

            # the conversation survived and simply became unfiled
            r = await c.get(f"/conversations/{cid}", headers=_h(tok))
            assert r.status_code == 200 and r.json()["title"] == "Keep me"
            async with factory() as s:
                assert (await s.get(Conversation, cid)).project_id is None

    run(go())


# ---------- the part that makes it a project: context injection ----------

def test_project_context_injects_brief_and_pinned_docs(env):
    from app.services.projects import context_messages

    async def go():
        factory = env
        async with await _client() as c:
            tok = await _token(c, "ctx@test.io")
            me = (await c.get("/auth/me", headers=_h(tok))).json()
            pid = (
                await c.post(
                    "/projects",
                    json={"name": "Thesis", "description": "PhD work", "instructions": "Cite APA style."},
                    headers=_h(tok),
                )
            ).json()["id"]

            async with factory() as s:
                a = FileAsset(
                    user_id=me["id"], filename="chapter1.txt", mime="text/plain",
                    path="/tmp/c1.txt", size_bytes=20, extracted_text="MAGIC_CHAPTER_TEXT",
                )
                s.add(a)
                await s.flush()
                fid = a.id
                await s.commit()
            await c.post(f"/projects/{pid}/files/{fid}", headers=_h(tok))

            async with factory() as s:
                from app.db.models import User

                user = await s.get(User, me["id"])
                msgs = await context_messages(s, user, pid)

            assert len(msgs) == 2
            assert all(m["role"] == "system" for m in msgs)
            assert "Thesis" in msgs[0]["content"] and "Cite APA style." in msgs[0]["content"]
            assert "MAGIC_CHAPTER_TEXT" in msgs[1]["content"] and "chapter1.txt" in msgs[1]["content"]

    run(go())


def test_project_context_is_fail_open(env):
    """A missing/unreadable project degrades to a normal chat, never an exception."""
    from app.services.projects import context_messages

    async def go():
        factory = env
        async with await _client() as c:
            tok = await _token(c, "failopen@test.io")
            me = (await c.get("/auth/me", headers=_h(tok))).json()
            async with factory() as s:
                from app.db.models import User

                user = await s.get(User, me["id"])
                assert await context_messages(s, user, None) == []
                assert await context_messages(s, user, "does-not-exist") == []

    run(go())


def test_chat_conversation_can_be_created_inside_a_project(env):
    """The conversation records its project, so later turns keep the brief."""

    async def go():
        factory = env
        async with await _client() as c:
            tok = await _token(c, "convproj@test.io")
            me = (await c.get("/auth/me", headers=_h(tok))).json()
            pid = (await c.post("/projects", json={"name": "Ship"}, headers=_h(tok))).json()["id"]

            async with factory() as s:
                from app.api.routes.chat import get_or_create_conversation
                from app.db.models import User

                user = await s.get(User, me["id"])
                conv, created = await get_or_create_conversation(s, user, None, "hello", None, pid)
                await s.commit()
                assert created and conv.project_id == pid

            # and it shows up in the project detail
            detail = (await c.get(f"/projects/{pid}", headers=_h(tok))).json()
            assert detail["chats"] == 1

    run(go())


def test_creating_a_chat_in_someone_elses_project_is_rejected(env):
    async def go():
        factory = env
        async with await _client() as c:
            a = await _token(c, "a-own@test.io")
            await _token(c, "b-own@test.io")
            pid = (await c.post("/projects", json={"name": "Mine"}, headers=_h(a))).json()["id"]
            b_me = (await c.get("/auth/me", headers=_h(await _token(c, "b-own@test.io")))).json()

            async with factory() as s:
                from fastapi import HTTPException

                from app.api.routes.chat import get_or_create_conversation
                from app.db.models import User

                intruder = await s.get(User, b_me["id"])
                try:
                    await get_or_create_conversation(s, intruder, None, "hi", None, pid)
                    raise AssertionError("expected the project check to reject this")
                except HTTPException as e:
                    assert e.status_code == 404

    run(go())


def test_projects_can_be_disabled_by_config(env, monkeypatch):
    monkeypatch.setattr(settings, "PROJECTS_ENABLED", False)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "off@test.io")
            r = await c.get("/projects", headers=_h(tok))
            assert r.status_code == 503 and "disabled" in r.json()["detail"].lower()

    run(go())
