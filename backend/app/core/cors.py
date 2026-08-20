"""CORS that stays valid on custom / Cloudflare domains.

Starlette's CORSMiddleware snapshots `allow_origins` at construction and cannot
ask the DB. A visitor on an active white-label host then gets a browser
TypeError (\"Failed to fetch\") which the web app surfaces as \"Can't reach the
ChatMood server\" — the same symptom as Cloudflare 522.

This subclass keeps the stock ASGI CORS implementation (safe for SSE) and
adds:
  * live `CORS_ORIGINS` + `FRONTEND_URL` (and its www twin)
  * a process-local set of active custom-domain hosts, refreshed at boot and
    whenever a domain is verified.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from starlette.middleware.cors import CORSMiddleware

from ..config import settings

log = logging.getLogger(__name__)

_extra_hosts: set[str] = set()


def host_aliases(host: str) -> set[str]:
    h = (host or "").strip().lower().split(":")[0].rstrip(".")
    if not h:
        return set()
    if h.startswith("www."):
        return {h, h[4:]}
    return {h, f"www.{h}"}


def remember_cors_host(domain: str) -> None:
    _extra_hosts.update(host_aliases(domain))


def forget_cors_host(domain: str) -> None:
    _extra_hosts.difference_update(host_aliases(domain))


def reset_cors_hosts(hosts: set[str] | None = None) -> None:
    _extra_hosts.clear()
    if hosts:
        for h in hosts:
            remember_cors_host(h)


def extra_cors_hosts() -> set[str]:
    return set(_extra_hosts)


def _origin_host(origin: str) -> str:
    try:
        return (urlparse(origin).hostname or "").lower()
    except Exception:
        return ""


def origin_allowed(origin: str) -> bool:
    if not origin:
        return False
    listed = [o.strip() for o in settings.cors_origin_list]
    if "*" in listed:
        return True
    stripped = origin.rstrip("/")
    if origin in listed or stripped in listed:
        return True
    fe = (settings.FRONTEND_URL or "").rstrip("/")
    if fe and stripped == fe:
        return True
    host = _origin_host(origin)
    if not host:
        return False
    if host in _extra_hosts:
        return True
    # FRONTEND_URL www twin (https://5boost.me ↔ https://www.5boost.me)
    if fe:
        fe_host = _origin_host(fe)
        if host in host_aliases(fe_host):
            return True
    return False


async def refresh_cors_hosts_from_db() -> int:
    """Load active custom domains into the CORS allow-list. Fail-open (keep last)."""
    try:
        from sqlalchemy import select

        from ..db.models import Domain
        from ..db.session import SessionLocal

        async with SessionLocal() as s:
            rows = (await s.execute(select(Domain.domain).where(Domain.status == "active"))).scalars().all()
        reset_cors_hosts({str(d) for d in rows if d})
        return len(_extra_hosts)
    except Exception as e:
        log.warning("cors host refresh skipped: %s", e)
        return 0


class ChatMoodCORS(CORSMiddleware):
    """Stock CORS + live FRONTEND_URL + active custom-domain hosts."""

    def is_allowed_origin(self, origin: str) -> bool:
        if super().is_allowed_origin(origin):
            return True
        return origin_allowed(origin)
