"""🚦 Readiness contract — /readyz and the probes that consume it.

The bug this guards against, in full:

`/readyz` pinged postgres, redis AND qdrant and 503'd if *any* failed. Meanwhile
every deployment probe (fly.toml, render.yaml, docker-compose) pointed at
`/healthz`, which returns 200 whenever the process is alive. So the checks were
inverted from what anyone wanted:

  - A machine whose Postgres was unreachable kept a GREEN health check while
    serving 500s to users.
  - And you could not simply repoint the probe at /readyz, because Fly never
    sets REDIS_URL — REDIS_URL defaults to redis://localhost:6379/0, nothing
    listens there, so /readyz was a PERMANENT 503 in production. Repointing
    naively would have failed every machine's health check and taken the API
    down on the next deploy.

The resolution is the `READINESS_REQUIRED` contract: Postgres is required, Redis
and Qdrant are optional-by-design (the rate limiter fails open; memory/RAG
degrade to "no recall"), so losing them reports `degraded` at 200 instead of
pulling a healthy machine out of the pool.
"""

import asyncio
import re
from pathlib import Path

import httpx
import pytest

from app.config import Settings, settings

REPO = Path(__file__).resolve().parent.parent.parent


# ─────────────────────────── the endpoint's behaviour ────────────────────────

def _readyz(monkeypatch, *, pg_ok=True, redis_ok=True, qdrant_ok=True, required=None):
    """Drive /readyz with each dependency forced up or down."""
    import app.main as m

    async def _pg():
        if not pg_ok:
            raise RuntimeError("postgres down")

    async def _redis():
        if not redis_ok:
            raise RuntimeError("redis down")

    class _Q:
        async def get_collections(self):
            if not qdrant_ok:
                raise RuntimeError("qdrant down")
            return []

    monkeypatch.setattr(m, "_pg_ping", _pg)
    monkeypatch.setattr(m, "_redis_ping", _redis)
    monkeypatch.setattr(m, "qdrant", lambda: _Q())
    if required is not None:
        monkeypatch.setattr(settings, "READINESS_REQUIRED", required)

    async def go():
        # No lifespan: app startup dials Redis/Qdrant for real, and the suite's
        # other tests mutate that global state.
        transport = httpx.ASGITransport(app=m.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return await c.get("/readyz")

    # asyncio.run (not get_event_loop) — matches the rest of the suite and stays
    # correct after another test closes the ambient loop.
    return asyncio.run(go())


def test_all_dependencies_up_is_200_ok(monkeypatch):
    res = _readyz(monkeypatch)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["ready"] is True


def test_redis_down_stays_200_because_the_app_serves_without_it(monkeypatch):
    """THE REGRESSION. Fly has no Redis; this must not fail the health check.

    The rate limiter explicitly fails open (api/deps.py), so a machine with no
    Redis serves every request correctly. Reporting it as unready would have
    taken production down the moment the probe moved to /readyz.
    """
    res = _readyz(monkeypatch, redis_ok=False)
    assert res.status_code == 200, "a dead OPTIONAL dep must never fail the probe"
    body = res.json()
    assert body["status"] == "degraded"
    assert body["ready"] is True
    assert body["checks"]["redis"]["status"] == "fail"
    assert body["checks"]["redis"]["required"] == "false"


def test_qdrant_down_stays_200(monkeypatch):
    res = _readyz(monkeypatch, qdrant_ok=False)
    assert res.status_code == 200
    assert res.json()["status"] == "degraded"


def test_postgres_down_is_503_unready(monkeypatch):
    """Postgres is the one hard requirement — this is the case worth catching."""
    res = _readyz(monkeypatch, pg_ok=False)
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "unready"
    assert body["ready"] is False
    assert body["checks"]["postgres"]["required"] == "true"


def test_optional_failure_does_not_mask_a_required_one(monkeypatch):
    res = _readyz(monkeypatch, pg_ok=False, redis_ok=False)
    assert res.status_code == 503
    assert res.json()["status"] == "unready"


def test_required_set_is_configurable(monkeypatch):
    """Stacks that DO provision Redis (docker-compose) can gate on it."""
    res = _readyz(monkeypatch, redis_ok=False, required="postgres,redis,qdrant")
    assert res.status_code == 503
    assert res.json()["checks"]["redis"]["required"] == "true"


def test_every_probe_is_reported_even_when_optional(monkeypatch):
    """Operators need to SEE the degraded dep, not just a green light."""
    body = _readyz(monkeypatch, redis_ok=False).json()
    assert set(body["checks"]) == {"postgres", "redis", "qdrant"}
    for name, c in body["checks"].items():
        assert "ms" in c, f"{name} lost its latency reading"
        assert c["required"] in ("true", "false")


def test_default_required_set_is_just_postgres():
    assert Settings().readiness_required_set == {"postgres"}


def test_required_set_parsing_is_whitespace_and_case_tolerant(monkeypatch):
    s = Settings(READINESS_REQUIRED=" Postgres , REDIS ")
    assert s.readiness_required_set == {"postgres", "redis"}


# ──────────────────── the deployment probes that consume it ──────────────────
# The endpoint being correct is only half the fix: the original bug was that
# every probe pointed at the WRONG endpoint. Assert the wiring too.

def test_fly_health_check_uses_readyz():
    toml = (REPO / "fly.toml").read_text(encoding="utf-8")
    checks = toml.split("[[http_service.checks]]", 1)
    assert len(checks) == 2, "fly.toml lost its http_service check block"
    assert re.search(r'^\s*path\s*=\s*"/readyz"', checks[1], re.M), (
        "Fly's health check must gate on readiness — /healthz is 200 even when "
        "Postgres is unreachable, which is how a broken deploy stayed green."
    )


def test_render_health_check_uses_readyz():
    y = (REPO / "render.yaml").read_text(encoding="utf-8")
    assert re.search(r"^\s*healthCheckPath:\s*/readyz\s*$", y, re.M)


def test_compose_backend_healthcheck_uses_readyz_and_gates_all_three():
    y = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert "/readyz" in y, "compose backend healthcheck should use /readyz"
    # compose provisions redis + qdrant and `frontend` waits on this healthcheck,
    # so the strict gate belongs here.
    assert re.search(r"READINESS_REQUIRED:\s*postgres,redis,qdrant", y)


def test_fly_check_timeout_survives_a_waking_database():
    """A DB round-trip needs more headroom than the old 5s liveness budget.

    Neon idles to sleep; a cold compute takes 4-15s to wake (documented in the
    keep-warm service). Too tight a timeout turns a slow wake into a failed
    health check — the same self-inflicted outage from the other direction.
    """
    toml = (REPO / "fly.toml").read_text(encoding="utf-8")
    block = toml.split("[[http_service.checks]]", 1)[1]
    m = re.search(r'timeout\s*=\s*"(\d+)s"', block)
    assert m and int(m.group(1)) >= 10, "give the DB probe >= 10s"


@pytest.mark.parametrize("script", ["smoke.sh", "live-smoke.sh"])
def test_smoke_scripts_accept_a_degraded_but_serving_deployment(script):
    """`degraded` is a 200 — the smoke tests must not report it as failure."""
    src = (REPO / "scripts" / script).read_text(encoding="utf-8")
    assert "degraded" in src, f"{script} still treats /readyz as pass/fail only"
