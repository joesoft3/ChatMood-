import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .api.deps import get_redis
from .api.routes import admin, admin_payments, agents, apikeys, auth, billing, chat, conversations, deepsearch, designer, devices, domains, files, media, memory, payments, plugins, projects, public_api, reels, share, tasks, usage, voice, voice_ws, workspaces
from .config import settings
from .core.metrics import REQ_COUNT, REQ_LAT, metrics_response
from .db.session import engine, init_db
from .services.bootstrap import bootstrap_admin, seed_app_password_from_env
from .services.domain_stats import record_request
from .services.domains import expiry_watchdog
from .services.memory import init_memory_collection, qdrant
from .services.rag import init_doc_collection
from .telemetry import setup_tracing

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    if settings.AUTO_CREATE_TABLES:
        await init_db()  # dev convenience; production uses `alembic upgrade head`
    try:
        await init_memory_collection()
        await init_doc_collection()
    except Exception as e:  # Qdrant still starting — memory/RAG activate on next request cycle
        log.warning("Qdrant not ready yet (%s) — memory/RAG features will retry lazily", e)
    await bootstrap_admin()             # env-defined owner account (create/promote)
    await seed_app_password_from_env()  # optional sign-up access code seed
    watchdog = asyncio.create_task(expiry_watchdog())  # keeps registrar expiry dates fresh
    from .services.keepwarm import start_keep_warm, stop_keep_warm

    start_keep_warm()  # 💓 keep the Neon compute hot (idle wake-ups measured at 4-15s)
    from .services.scheduler import start_scheduler, stop_scheduler

    start_scheduler()  # ⏰ run users' scheduled tasks unattended
    from .services.payment_sweep import start_payment_sweep, stop_payment_sweep

    start_payment_sweep()  # 💳 downgrade manual plans whose paid period lapsed
    try:
        yield
    finally:
        watchdog.cancel()
        await stop_keep_warm()
        await stop_scheduler()
        await stop_payment_sweep()


app = FastAPI(title="MoodAI API", version="1.9.8", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional OpenTelemetry tracing (no-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set)
setup_tracing(app)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """Request-id propagation, access logging, Prometheus request metrics."""
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    start = time.perf_counter()
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        status = 500
        log.exception("rid=%s %s %s → unhandled error", request_id, request.method, request.url.path)
        raise
    duration = time.perf_counter() - start

    if request.url.path != "/metrics":  # avoid scrape noise
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        REQ_COUNT.labels(method=request.method, path=path, status=str(status)).inc()
        REQ_LAT.labels(method=request.method, path=path).observe(duration)
        log.info("rid=%s %s %s → %s (%.3fs)", request_id, request.method, path, status, duration)

    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def domain_stats_middleware(request: Request, call_next):
    """Best-effort per-custom-domain analytics (fire-and-forget, never blocks)."""
    response = await call_next(request)
    try:
        host = request.headers.get("x-mood-host") or request.headers.get("host", "")
        asyncio.get_running_loop().create_task(
            record_request(host, request.headers.get("authorization", ""))
        )
    except Exception:
        pass
    return response


app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["conversations"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["chat"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(deepsearch.router, prefix="/api/v1/deepsearch", tags=["deepsearch"])
app.include_router(files.router, prefix="/api/v1/files", tags=["files"])
app.include_router(voice.router, prefix="/api/v1/voice", tags=["voice"])
app.include_router(memory.router, prefix="/api/v1/memory", tags=["memory"])
app.include_router(billing.router, prefix="/api/v1/billing", tags=["billing"])
app.include_router(usage.router, prefix="/api/v1/usage", tags=["usage"])
app.include_router(plugins.router, prefix="/api/v1/plugins", tags=["plugins"])
app.include_router(devices.router, prefix="/api/v1/devices", tags=["devices"])
app.include_router(share.router, prefix="/api/v1/share", tags=["share"])
app.include_router(media.router, prefix="/api/v1/media", tags=["media"])
app.include_router(designer.router, prefix="/api/v1/media", tags=["media"])
app.include_router(reels.router, prefix="/api/v1/reels", tags=["reels"])
app.include_router(voice_ws.router, prefix="/api/v1/voice", tags=["voice-ws"])
app.include_router(workspaces.router, prefix="/api/v1/workspaces", tags=["workspaces"])
app.include_router(domains.router, prefix="/api/v1/domains", tags=["domains"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(payments.router, prefix="/api/v1/payments", tags=["payments"])
app.include_router(admin_payments.router, prefix="/api/v1/admin/payments", tags=["admin-payments"])
app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["tasks"])
app.include_router(apikeys.router, prefix="/api/v1/keys", tags=["api-keys"])
app.include_router(public_api.router, prefix="/api/v1/public", tags=["public-api"])


@app.get("/healthz")
async def healthz():
    """Liveness probe + operator-visible heartbeat state (version, DB keep-warm)."""
    from .services.keepwarm import keep_warm_status
    from .services.payment_sweep import sweep_status
    from .services.scheduler import scheduler_status

    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": app.version,
        "keep_warm": keep_warm_status(),
        "scheduler": scheduler_status(),
        "payment_sweep": sweep_status(),
    }


@app.get("/readyz")
async def readyz():
    """Readiness probe: are the dependencies this deployment *needs* reachable?

    Returns structured JSON with per-service status + latency in ms so ops
    tooling can pinpoint which dependency is slow or down.

    Only the dependencies named in `READINESS_REQUIRED` (default: postgres) can
    drive the 503. Redis and the vector store are reported but marked optional,
    because the app is explicitly built to survive losing them: the rate limiter
    fails open and memory/RAG degrade to "no recall" rather than erroring. A
    machine with no Redis still serves every request correctly, so failing its
    health check would take down a healthy deployment — which is exactly what
    happens on Fly, where REDIS_URL is never set.

    Statuses:
      ok       — every probe passed
      degraded — an OPTIONAL dependency is down; still 200, still serving
      unready  — a REQUIRED dependency is down; 503, pull me from the pool
    """
    required = settings.readiness_required_set
    checks: dict[str, dict[str, str]] = {}
    ready = True      # required deps all healthy?
    degraded = False  # any optional dep down?

    async def _probe(name: str, factory):
        nonlocal ready, degraded
        is_required = name in required
        t0 = time.perf_counter()
        try:
            await factory()
            ms = round((time.perf_counter() - t0) * 1000, 1)
            checks[name] = {"status": "ok", "ms": str(ms), "required": str(is_required).lower()}
        except Exception as e:
            ms = round((time.perf_counter() - t0) * 1000, 1)
            checks[name] = {
                "status": "fail",
                "error": str(e)[:200],
                "ms": str(ms),
                "required": str(is_required).lower(),
            }
            if is_required:
                ready = False
            else:
                degraded = True

    await _probe("postgres", lambda: _pg_ping())
    await _probe("redis", lambda: _redis_ping())
    await _probe("qdrant", lambda: qdrant().get_collections())

    payload = {
        "status": "ok" if ready and not degraded else ("degraded" if ready else "unready"),
        "ready": ready,
        "version": app.version,
        "checks": checks,
        "timestamp": time.time(),
    }
    return JSONResponse(payload, status_code=200 if ready else 503)


async def _pg_ping():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _redis_ping():
    r = await get_redis()
    await r.ping()


@app.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus scrape endpoint."""
    return metrics_response()
