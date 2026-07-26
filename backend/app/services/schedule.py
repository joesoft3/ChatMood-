"""⏰ Schedule arithmetic for Scheduled Tasks — pure functions, no I/O.

Deliberately cron-free. A cron parser is a dependency plus a support burden
("why didn't `*/5 9-17 * * 1-5` fire?"), and the product only needs four shapes:

    once    → run one time at the next occurrence of hour:minute, then disable
    hourly  → every hour at :minute
    daily   → every day at hour:minute UTC
    weekly  → the same, but only on the selected weekdays (Mon=0 … Sun=6)

Everything is computed in UTC; the UI converts for display. Keeping this module
pure is what makes the scheduler unit-testable without a clock or a database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

SCHEDULE_KINDS = ("once", "hourly", "daily", "weekly")

# Guard rails shared by the API layer and the scheduler.
MIN_INTERVAL_MINUTES = 60  # the tightest cadence we will ever run a task at


def parse_weekdays(raw: str | None) -> list[int]:
    """"0,2,4" → [0, 2, 4]. Invalid entries are dropped, result is sorted/deduped.

    An empty result means "every day", which is what `daily` implies and what a
    `weekly` task falls back to when its mask is empty or entirely invalid.
    """
    if not raw:
        return []
    out: set[int] = set()
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            day = int(part)
        except ValueError:
            continue
        if 0 <= day <= 6:
            out.add(day)
    return sorted(out)


def format_weekdays(days: list[int] | None) -> str:
    """Inverse of parse_weekdays — the canonical stored form."""
    return ",".join(str(d) for d in parse_weekdays(",".join(str(d) for d in (days or []))))


def next_run_at(
    kind: str,
    hour: int,
    minute: int,
    weekdays: str | None = None,
    *,
    after: datetime | None = None,
) -> datetime | None:
    """The next UTC datetime this schedule should fire, strictly after `after`.

    Returns None only for an unknown kind, so a corrupt row can never wedge the
    scheduler into a busy loop — it simply never becomes due.

    The `> after` strictness matters: the scheduler calls this with the run it
    just completed, and a non-strict comparison would re-fire the same slot
    forever whenever a run finished inside the same minute it started.
    """
    kind = (kind or "").lower()
    if kind not in SCHEDULE_KINDS:
        return None

    now = (after or datetime.now(timezone.utc)).astimezone(timezone.utc)
    hour = max(0, min(23, int(hour)))
    minute = max(0, min(59, int(minute)))

    if kind == "hourly":
        candidate = now.replace(minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(hours=1)
        return candidate

    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)

    if kind in ("once", "daily"):
        return candidate

    # weekly: walk forward to the next selected weekday (≤ 7 hops by construction)
    days = parse_weekdays(weekdays)
    if not days:
        return candidate  # empty mask degrades to daily rather than never running
    for _ in range(8):
        if candidate.weekday() in days:
            return candidate
        candidate += timedelta(days=1)
    return candidate


def describe(kind: str, hour: int, minute: int, weekdays: str | None = None) -> str:
    """Human-readable cadence for the API/UI ("Weekdays at 07:30 UTC")."""
    kind = (kind or "").lower()
    stamp = f"{max(0, min(23, int(hour))):02d}:{max(0, min(59, int(minute))):02d} UTC"
    if kind == "hourly":
        return f"Every hour at :{max(0, min(59, int(minute))):02d}"
    if kind == "once":
        return f"Once at {stamp}"
    if kind == "daily":
        return f"Every day at {stamp}"
    if kind == "weekly":
        days = parse_weekdays(weekdays)
        if not days:
            return f"Every day at {stamp}"
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        if days == [0, 1, 2, 3, 4]:
            return f"Weekdays at {stamp}"
        if days == [5, 6]:
            return f"Weekends at {stamp}"
        return f"{', '.join(names[d] for d in days)} at {stamp}"
    return stamp


def is_due(next_run: datetime | None, *, now: datetime | None = None) -> bool:
    """True when a task's next_run_at has arrived. Naive datetimes (sqlite round-trips
    drop tzinfo) are read as UTC rather than crashing the comparison."""
    if next_run is None:
        return False
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=timezone.utc)
    return next_run <= now
