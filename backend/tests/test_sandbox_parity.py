"""🧪 Parity between the module engine and every *other* engine/session.

Three live faults surfaced only under an authenticated runtime sweep, because
each depends on which engine or session happens to serve the request:

1. `date_trunc` was registered on `engine.sync_engine` alone, so the three admin
   endpoints raised "no such function" on any other sqlite engine.
2. `GET /media/films/resumable` took a `db` dependency and then ignored it,
   opening `SessionLocal()` and dialling the globally-configured database.
3. The pgvector store ran Postgres-only DDL on sqlite, retried it, and logged a
   syntax error that reads like a broken deployment.
"""

import asyncio

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Film, User
from app.db.session import get_db
from app.main import app

PW = "Sandbox-Parity-2026!"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def api():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    async def _make():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_make())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    yield factory
    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


async def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1", timeout=60
    )


async def _token(client, email):
    await client.post("/auth/register", json={"email": email, "password": PW})
    res = await client.post("/auth/login", json={"email": email, "password": PW})
    return res.json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


# ────────────────────────────── 1. date_trunc on every engine

def test_date_trunc_is_registered_on_engines_other_than_the_module_one():
    """The shim bound to `engine.sync_engine`, so nothing else had it."""

    async def go():
        other = create_async_engine(
            "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        try:
            async with other.connect() as conn:
                got = (
                    await conn.execute(
                        sa.text("SELECT date_trunc('month', '2026-07-26 10:00:00')")
                    )
                ).scalar()
            assert got == "2026-07-01 00:00:00", got
        finally:
            await other.dispose()

    run(go())


@pytest.mark.parametrize("path", ["/admin/overview", "/admin/users", "/admin/analytics"])
def test_admin_pages_work_on_a_sqlite_deployment(api, path):
    """Each of these calls date_trunc — all three 500'd through a test engine."""

    async def go():
        async with await _client() as client:
            token = await _token(client, "parity-admin@test.io")
            async with api() as session:
                user = (
                    await session.execute(sa.select(User).where(User.email == "parity-admin@test.io"))
                ).scalar_one()
                user.is_admin = True
                await session.commit()
            res = await client.get(path, headers=_h(token))
            assert res.status_code == 200, f"{path} -> {res.status_code} {res.text[:200]}"

    run(go())


# ────────────────────────────── 2. the route must use the session it was given

def test_resumable_films_reads_the_request_session_not_the_global_engine(api):
    """It took `db` as a dependency and then ignored it.

    A film written through the overridden session must be visible to the
    endpoint; if it reopens `SessionLocal()` it queries a different database and
    either errors or returns nothing.
    """

    async def go():
        async with await _client() as client:
            token = await _token(client, "parity-films@test.io")
            async with api() as session:
                user = (
                    await session.execute(sa.select(User).where(User.email == "parity-films@test.io"))
                ).scalar_one()
                session.add(
                    Film(id="film-parity-1", user_id=user.id, status="rendering", prompt="Stuck")
                )
                await session.commit()

            res = await client.get("/media/films/resumable", headers=_h(token))
            assert res.status_code == 200, f"{res.status_code} {res.text[:200]}"
            body = res.json()
            assert body["count"] == 1, body
            assert body["resumable"][0]["id"] == "film-parity-1", body

    run(go())


def test_resumable_films_does_not_leak_other_users_renders(api):
    """Ownership still filters once the session is honoured."""

    async def go():
        async with await _client() as client:
            mine = await _token(client, "parity-mine@test.io")
            await _token(client, "parity-other@test.io")
            async with api() as session:
                other = (
                    await session.execute(sa.select(User).where(User.email == "parity-other@test.io"))
                ).scalar_one()
                session.add(
                    Film(id="film-parity-2", user_id=other.id, status="rendering", prompt="Theirs")
                )
                await session.commit()

            res = await client.get("/media/films/resumable", headers=_h(mine))
            assert res.status_code == 200, res.text
            assert res.json()["count"] == 0, res.json()

    run(go())


# ────────────────────────────── 3. pgvector says why, instead of a DDL syntax error

def test_pgvector_reports_a_clear_reason_on_non_postgres(monkeypatch):
    """It used to attempt CREATE EXTENSION on sqlite, twice, then surface a
    "syntax error near EXTENSION" that reads like a broken deployment.

    The engine is pinned to sqlite here rather than relying on the ambient
    DATABASE_URL: the settings default is Postgres, so a bare `pytest` run would
    otherwise skip the guard entirely and this test would silently prove
    nothing.
    """
    from app.services import vectorstore
    from app.services.vectorstore import PgVectorStore

    sqlite_engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    monkeypatch.setattr(vectorstore, "engine", sqlite_engine)

    async def go():
        try:
            with pytest.raises(RuntimeError) as excinfo:
                await PgVectorStore()._ensure()
            message = str(excinfo.value)
            assert "PostgreSQL" in message, message
            assert "EXTENSION" not in message.upper(), f"leaked raw DDL error: {message}"
        finally:
            await sqlite_engine.dispose()

    run(go())


def test_pgvector_still_proceeds_on_postgres(monkeypatch):
    """The guard must not disable pgvector on the deployments that support it."""
    from app.services import vectorstore
    from app.services.vectorstore import PgVectorStore

    pg_engine = create_async_engine(
        "postgresql+asyncpg://mood:mood@localhost:5432/mood", poolclass=StaticPool
    )
    monkeypatch.setattr(vectorstore, "engine", pg_engine)
    reached = {"ddl": False}

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, sql, params=None):
            if "CREATE EXTENSION" in str(sql):
                reached["ddl"] = True
            raise AssertionError("stop-after-probe")

        async def commit(self):
            pass

    monkeypatch.setattr(vectorstore, "SessionLocal", lambda: _Session())

    async def go():
        try:
            with pytest.raises(Exception):
                await PgVectorStore()._ensure()
            assert reached["ddl"], "Postgres must still reach the pgvector DDL"
        finally:
            await pg_engine.dispose()

    run(go())
