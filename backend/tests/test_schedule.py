"""⏰ Schedule arithmetic — the pure core behind Scheduled Tasks.

These are the tests that matter most for tasks: every bug here is invisible
until 3am, when a job either fires twice or never fires at all.
"""

from datetime import datetime, timedelta, timezone

from app.services.schedule import (
    SCHEDULE_KINDS,
    describe,
    format_weekdays,
    is_due,
    next_run_at,
    parse_weekdays,
)


def at(y=2026, mo=7, d=26, h=12, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


# ---------- weekday parsing ----------

def test_parse_weekdays_sorts_dedupes_and_drops_junk():
    assert parse_weekdays("4,0,2,0") == [0, 2, 4]
    assert parse_weekdays("") == []
    assert parse_weekdays(None) == []
    # out of range and non-numeric entries are dropped, not fatal
    assert parse_weekdays("9,-1,abc,3") == [3]


def test_format_weekdays_roundtrips_canonically():
    assert format_weekdays([5, 1, 1]) == "1,5"
    assert format_weekdays([]) == ""


# ---------- daily ----------

def test_daily_picks_today_when_slot_is_still_ahead():
    nxt = next_run_at("daily", 18, 30, after=at(h=12))
    assert nxt == at(h=18, mi=30)


def test_daily_rolls_to_tomorrow_once_the_slot_has_passed():
    nxt = next_run_at("daily", 8, 0, after=at(h=12))
    assert nxt == at(d=27, h=8, mi=0)


def test_slot_exactly_now_moves_to_the_next_day_not_immediately():
    """Strict `>` is what stops a finished run from re-firing its own slot."""
    now = at(h=9, mi=0)
    assert next_run_at("daily", 9, 0, after=now) == now + timedelta(days=1)


# ---------- hourly ----------

def test_hourly_uses_the_next_matching_minute():
    assert next_run_at("hourly", 0, 45, after=at(h=12, mi=10)) == at(h=12, mi=45)
    # past this hour's minute → next hour
    assert next_run_at("hourly", 0, 5, after=at(h=12, mi=10)) == at(h=13, mi=5)


# ---------- weekly ----------

def test_weekly_advances_to_the_next_selected_weekday():
    # 2026-07-26 is a Sunday (weekday 6); ask for Tuesday (1)
    nxt = next_run_at("weekly", 7, 0, "1", after=at(h=12))
    assert nxt.weekday() == 1
    assert nxt == at(d=28, h=7, mi=0)


def test_weekly_with_empty_mask_degrades_to_daily_rather_than_never():
    nxt = next_run_at("weekly", 7, 0, "", after=at(h=12))
    assert nxt == at(d=27, h=7, mi=0)


def test_weekly_weekday_mask_skips_the_weekend():
    # Friday 2026-07-31 12:00, weekdays Mon-Fri → next is Monday 2026-08-03
    nxt = next_run_at("weekly", 7, 0, "0,1,2,3,4", after=at(d=31, h=12))
    assert nxt.weekday() == 0
    assert nxt.date() == datetime(2026, 8, 3).date()


# ---------- robustness ----------

def test_unknown_kind_returns_none_so_a_bad_row_never_busy_loops():
    assert next_run_at("fortnightly", 7, 0) is None


def test_out_of_range_time_is_clamped_not_crashed():
    nxt = next_run_at("daily", 99, 99, after=at(h=1))
    assert nxt is not None and nxt.hour == 23 and nxt.minute == 59


def test_every_declared_kind_produces_a_future_time():
    now = at()
    for kind in SCHEDULE_KINDS:
        nxt = next_run_at(kind, 6, 15, "0,3", after=now)
        assert nxt is not None and nxt > now, kind


# ---------- due check ----------

def test_is_due_handles_none_and_naive_datetimes():
    now = at()
    assert is_due(None, now=now) is False
    assert is_due(now - timedelta(minutes=1), now=now) is True
    assert is_due(now + timedelta(minutes=1), now=now) is False
    # sqlite hands back naive datetimes — read as UTC instead of raising
    naive = (now - timedelta(minutes=5)).replace(tzinfo=None)
    assert is_due(naive, now=now) is True


# ---------- human labels ----------

def test_describe_reads_naturally_for_common_cadences():
    assert describe("daily", 7, 30) == "Every day at 07:30 UTC"
    assert describe("weekly", 7, 0, "0,1,2,3,4") == "Weekdays at 07:00 UTC"
    assert describe("weekly", 9, 0, "5,6") == "Weekends at 09:00 UTC"
    assert describe("hourly", 0, 5) == "Every hour at :05"
    assert describe("once", 22, 0) == "Once at 22:00 UTC"
    assert "Mon" in describe("weekly", 8, 0, "0,2")
