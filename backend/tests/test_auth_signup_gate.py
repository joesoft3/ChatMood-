"""Signup-gate contract: deployments with an app access code must still be joinable."""

import asyncio

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.models import Base
from app.db.session import get_db
from app.main import app
from app.services.platform_settings import KEY_APP_PASSWORD, KEY_SIGNUP_OPEN, set_setting


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


def test_register_accepts_owner_app_access_code(env):
    async def flow():
        async with env() as db:
            await set_setting(db, KEY_APP_PASSWORD, {"hash": hash_password("join-mood-2026")})

        async with await _client() as client:
            no_code = await client.post(
                "/api/v1/auth/register",
                json={"email": "gate@moodaiapp.com", "password": "password123"},
            )
            assert no_code.status_code == 403
            assert "access code" in no_code.json()["detail"]

            wrong_code = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "gate@moodaiapp.com",
                    "password": "password123",
                    "app_password": "wrong-code",
                },
            )
            assert wrong_code.status_code == 403

            ok = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "Gate@Moodaiapp.com",
                    "password": "password123",
                    "display_name": "Gate User",
                    "app_password": "join-mood-2026",
                },
            )
            assert ok.status_code == 201, ok.text
            body = ok.json()
            assert body["access_token"]
            assert body["user"]["email"] == "gate@moodaiapp.com"
            assert body["user"]["display_name"] == "Gate User"

    _run(flow())


def test_register_still_respects_closed_signups(env):
    async def flow():
        async with env() as db:
            await set_setting(db, KEY_SIGNUP_OPEN, {"open": False})
            await set_setting(db, KEY_APP_PASSWORD, {"hash": hash_password("join-mood-2026")})

        async with await _client() as client:
            r = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "closed@moodaiapp.com",
                    "password": "password123",
                    "app_password": "join-mood-2026",
                },
            )
            assert r.status_code == 403
            assert "Signups are closed" in r.json()["detail"]

    _run(flow())
