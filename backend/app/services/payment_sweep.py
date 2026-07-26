"""💳 Expiry sweep — return lapsed manual subscriptions to the free plan.

A gateway subscription tells us when it ends (Stripe fires a webhook). A manual
mobile-money payment has nobody to fire anything, so the platform has to notice
by itself — otherwise one month of MoMo would silently grant Pro forever.

Mirrors the existing keep-warm / scheduler loops: idempotent starter, cancelled
on shutdown, and a failing tick can never kill the loop.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from ..config import settings

log = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_ticks = 0
_downgraded = 0
_last_tick: str | None = None


def sweep_enabled() -> bool:
    return bool(settings.MANUAL_PAYMENTS_ENABLED and settings.PAYMENT_EXPIRY_SWEEP_HOURS > 0)


def sweep_status() -> dict:
    """Surfaced on /healthz so the loop is verifiable without log access."""
    return {
        "enabled": sweep_enabled(),
        "running": _task is not None,
        "interval_h": settings.PAYMENT_EXPIRY_SWEEP_HOURS,
        "ticks": _ticks,
        "downgraded": _downgraded,
        "last_tick": _last_tick,
    }


async def _loop() -> None:
    global _ticks, _downgraded, _last_tick
    interval = max(600.0, float(settings.PAYMENT_EXPIRY_SWEEP_HOURS) * 3600.0)
    while True:
        await asyncio.sleep(interval)
        _ticks += 1
        _last_tick = datetime.now(timezone.utc).isoformat()
        try:
            from .payments import downgrade_expired_plans

            n = await downgrade_expired_plans()
            if n:
                _downgraded += n
                log.info("💳 expiry sweep downgraded %d lapsed plan(s)", n)
        except Exception as e:  # a bad tick must never kill the loop
            log.warning("payment expiry sweep failed: %s", e)


def start_payment_sweep() -> None:
    """Idempotent starter — called once from the app lifespan."""
    global _task
    if not sweep_enabled() or _task is not None:
        return
    _task = asyncio.create_task(_loop())
    log.info("💳 payment expiry sweep started (every %sh)", settings.PAYMENT_EXPIRY_SWEEP_HOURS)


async def stop_payment_sweep() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):
        pass
    _task = None
