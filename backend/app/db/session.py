from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import settings
from . import models  # noqa: F401  (registers models on Base.metadata)
from .base import Base


def engine_connect_args(url: str) -> dict:
    """asyncpg through a shared connection pooler (Supabase Pooler / PgBouncer in
    transaction mode, typically port 6543) must not cache prepared statements:
    a cached statement references plan state of a *specific* server connection,
    and the pooler hands you a different one per transaction. Detect the pooler
    from the URL (host/port hint) and disable the cache; direct connections
    (5432) keep full performance."""
    if not url.startswith("postgresql+asyncpg://"):
        return {}
    pooled = "pooler.supabase.com" in url or ":6543" in url or "pgbouncer" in url
    return {"statement_cache_size": 0} if pooled else {}


def _sqlite_date_trunc(unit, ts) -> str:
    """date_trunc(unit, ts) for sqlite — same truncation semantics as Postgres,
    so self-hosters on a sqlite DATABASE_URL get working admin/analytics pages."""
    from datetime import datetime, timedelta

    s = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts)
    dt = datetime.fromisoformat(s.replace("T", " ").split(".")[0][:19])
    u = (unit or "").lower()
    if u.startswith("year"):
        dt = dt.replace(month=1, day=1, hour=0, minute=0, second=0)
    elif u.startswith("month"):
        dt = dt.replace(day=1, hour=0, minute=0, second=0)
    elif u.startswith("week"):
        dt = (dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0)
    elif u.startswith("day"):
        dt = dt.replace(hour=0, minute=0, second=0)
    elif u.startswith("hour"):
        dt = dt.replace(minute=0, second=0)
    elif u.startswith("minute"):
        dt = dt.replace(second=0)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@event.listens_for(Engine, "connect")
def _register_sqlite_compat(dbapi_conn, connection_record):
    """Attach the Postgres-compatibility shims to **every** sqlite connection.

    This used to bind to `engine.sync_engine` only, so the shim existed on the
    one module-level engine and nowhere else. Any other engine — every test
    fixture, any tool or script that builds its own — silently lost
    `date_trunc`, and the admin/analytics endpoints blew up with
    "no such function" the moment they were exercised through one. Listening on
    the `Engine` class covers all of them; the dialect check keeps it inert for
    Postgres.
    """
    # aiosqlite hands back an AsyncAdapt_* wrapper, not a raw sqlite3 module
    # object, so sniffing the connection's module misses the async driver
    # entirely. Duck-type on `create_function` instead: sqlite exposes it and
    # asyncpg/psycopg do not.
    create_function = getattr(dbapi_conn, "create_function", None)
    if create_function is None:
        return
    create_function("date_trunc", 2, _sqlite_date_trunc)


engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG,
    connect_args=engine_connect_args(settings.DATABASE_URL),
)


SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Dev convenience: create tables if missing. Adopt Alembic before production."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
