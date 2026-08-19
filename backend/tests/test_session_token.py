"""Session JWT contract: mint → /auth/me → chat auth gate.

The chat page was stuck on "Invalid or expired token" when a leftover
localStorage value (or an immediately-expired JWT) was treated as signed-in.
These tests pin the server half of that loop: a fresh login token works,
garbage/expired tokens 401 with the exact detail the clients already handle.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.core.security import create_access_token, decode_token
from app.db.models import Base
from app.db.session import get_db
from app.main import app

EMAIL = "session.token@moodaiapp.com"
PASSWORD = "SessionPass-2026!"


@pytest.fixture()
def env():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
    yield factory
    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


def _run(coro):
    return asyncio.run(coro)


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _register(c):
    r = await c.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD, "display_name": "Session"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["access_token"]
    return body["access_token"], body["user"]["id"]


def test_minted_token_round_trips(env):
    """encode → decode → /auth/me 200, and the token is a 3-part JWT."""

    async def flow():
        async with await _client() as c:
            tk, uid = await _register(c)
            assert tk.count(".") == 2
            claims = decode_token(tk)
            assert claims["sub"] == uid
            assert isinstance(claims["exp"], int)
            me = await c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tk}"})
            assert me.status_code == 200, me.text
            assert me.json()["email"] == EMAIL

    _run(flow())


def test_chat_stream_rejects_garbage_token(env):
    async def flow():
        async with await _client() as c:
            r = await c.post(
                "/api/v1/chat/stream",
                headers={"Authorization": "Bearer not-a-jwt"},
                json={"message": "hello", "files": [], "search": False},
            )
            assert r.status_code == 401
            assert r.json()["detail"] == "Invalid or expired token"

    _run(flow())


def test_chat_stream_rejects_expired_token(env):
    async def flow():
        async with await _client() as c:
            _, uid = await _register(c)
            expired = jwt.encode(
                {"sub": uid, "exp": int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())},
                settings.JWT_SECRET,
                algorithm=settings.JWT_ALG,
            )
            r = await c.post(
                "/api/v1/chat/stream",
                headers={"Authorization": f"Bearer {expired}"},
                json={"message": "hello", "files": [], "search": False},
            )
            assert r.status_code == 401
            assert r.json()["detail"] == "Invalid or expired token"

    _run(flow())


def test_missing_bearer_is_401(env):
    async def flow():
        async with await _client() as c:
            r = await c.get("/api/v1/auth/me")
            assert r.status_code == 401
            assert r.json()["detail"] == "Not authenticated"

    _run(flow())


def test_zero_ttl_still_mints_a_usable_token(env, monkeypatch):
    """ACCESS_TOKEN_EXPIRE_MINUTES=0 must not produce an already-expired JWT."""
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 0)
    tk = create_access_token("user-id-zero-ttl")
    claims = decode_token(tk)
    assert claims["sub"] == "user-id-zero-ttl"
    assert claims["exp"] > int(datetime.now(timezone.utc).timestamp()) + 60
