"""⏰ Scheduled Tasks — CRUD, plan caps, the atomic claim, and unattended runs."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import Base, Message, ScheduledTask, TaskRun
from app.db.session import get_db
from app.main import app

PW = "Tasks-2026!"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def env(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
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
    monkeypatch.setattr(settings, "TASKS_ENABLED", True)
    # the scheduler LOOP stays off in tests; we drive run_task/_claim_due directly
    monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)

    # the task runner writes through SessionLocal, not the request dependency,
    # so point that at the same in-memory database
    import app.services.scheduler as sched

    monkeypatch.setattr(sched, "SessionLocal", factory)
    yield factory
    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


async def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1", timeout=30
    )


async def _token(c, email):
    await c.post("/auth/register", json={"email": email, "password": PW})
    r = await c.post("/auth/login", json={"email": email, "password": PW})
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


TASK = {
    "title": "Morning AI brief",
    "prompt": "What happened in AI in the last 24 hours?",
    "mode": "chat",
    "schedule_kind": "daily",
    "hour_utc": 7,
    "minute_utc": 30,
}


# ---------- CRUD ----------

def test_create_task_computes_next_run_and_label(env):
    async def go():
        async with await _client() as c:
            tok = await _token(c, "t1@test.io")
            r = await c.post("/tasks", json=TASK, headers=_h(tok))
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["schedule_label"] == "Every day at 07:30 UTC"
            assert body["next_run_at"] is not None
            assert datetime.fromisoformat(body["next_run_at"]) > datetime.now(timezone.utc)
            assert body["enabled"] is True and body["run_count"] == 0

            listing = (await c.get("/tasks", headers=_h(tok))).json()
            assert listing["used"] == 1 and listing["limit"] == settings.TASK_MAX_PER_USER_FREE

    run(go())


def test_weekly_task_stores_and_returns_its_weekday_mask(env):
    async def go():
        async with await _client() as c:
            tok = await _token(c, "t2@test.io")
            r = await c.post(
                "/tasks",
                json={**TASK, "schedule_kind": "weekly", "weekdays": [4, 0, 0, 2]},
                headers=_h(tok),
            )
            assert r.json()["weekdays"] == [0, 2, 4]  # sorted + deduped
            assert "Mon" in r.json()["schedule_label"]

    run(go())


def test_pausing_clears_next_run_and_resuming_schedules_the_future(env):
    async def go():
        async with await _client() as c:
            tok = await _token(c, "t3@test.io")
            tid = (await c.post("/tasks", json=TASK, headers=_h(tok))).json()["id"]

            r = await c.patch(f"/tasks/{tid}", json={"enabled": False}, headers=_h(tok))
            assert r.json()["enabled"] is False and r.json()["next_run_at"] is None

            r = await c.patch(f"/tasks/{tid}", json={"enabled": True}, headers=_h(tok))
            assert r.json()["enabled"] is True
            # a resumed task must schedule forward, never fire an overdue backlog
            assert datetime.fromisoformat(r.json()["next_run_at"]) > datetime.now(timezone.utc)

    run(go())


def test_editing_the_schedule_recomputes_the_next_slot(env):
    async def go():
        async with await _client() as c:
            tok = await _token(c, "t4@test.io")
            tid = (await c.post("/tasks", json=TASK, headers=_h(tok))).json()["id"]
            r = await c.patch(
                f"/tasks/{tid}", json={"schedule_kind": "hourly", "minute_utc": 15}, headers=_h(tok)
            )
            assert r.json()["schedule_label"] == "Every hour at :15"
            assert datetime.fromisoformat(r.json()["next_run_at"]).minute == 15

    run(go())


def test_tasks_are_private_and_deletable(env):
    async def go():
        factory = env
        async with await _client() as c:
            a = await _token(c, "own-t@test.io")
            b = await _token(c, "other-t@test.io")
            tid = (await c.post("/tasks", json=TASK, headers=_h(a))).json()["id"]

            assert (await c.get(f"/tasks/{tid}", headers=_h(b))).status_code == 404
            assert (await c.patch(f"/tasks/{tid}", json={"enabled": False}, headers=_h(b))).status_code == 404
            assert (await c.delete(f"/tasks/{tid}", headers=_h(b))).status_code == 404
            assert (await c.post(f"/tasks/{tid}/run", headers=_h(b))).status_code == 404

            assert (await c.delete(f"/tasks/{tid}", headers=_h(a))).status_code == 204
            async with factory() as s:
                assert await s.get(ScheduledTask, tid) is None

    run(go())


def test_free_plan_task_cap_points_at_the_upgrade(env, monkeypatch):
    monkeypatch.setattr(settings, "TASK_MAX_PER_USER_FREE", 1)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "cap@test.io")
            assert (await c.post("/tasks", json=TASK, headers=_h(tok))).status_code == 201
            r = await c.post("/tasks", json={**TASK, "title": "Second"}, headers=_h(tok))
            assert r.status_code == 400
            detail = r.json()["detail"]
            assert "limit reached" in detail.lower() and "Pro" in detail

    run(go())


def test_task_cannot_be_attached_to_another_users_project(env):
    async def go():
        async with await _client() as c:
            a = await _token(c, "pa@test.io")
            b = await _token(c, "pb@test.io")
            pid = (await c.post("/projects", json={"name": "A's"}, headers=_h(a))).json()["id"]
            r = await c.post("/tasks", json={**TASK, "project_id": pid}, headers=_h(b))
            assert r.status_code == 404

    run(go())


# ---------- running ----------

def _stub_llm(monkeypatch, text="Here is your briefing.", usage=None):
    """Replace the model call with a deterministic answer."""
    from app.services import llm as llm_mod

    async def fake_complete(messages, model=None, temperature=0.3, max_tokens=None, usage_out=None, provider=None):
        if usage_out is not None and usage:
            usage_out.update(usage)
        return text

    async def fake_search(messages, model=None, temperature=0.4, usage_out=None, provider=None):
        if usage_out is not None and usage:
            usage_out.update(usage)
        return text, ["https://example.com/a"]

    monkeypatch.setattr(llm_mod.llm, "complete", fake_complete)
    monkeypatch.setattr(llm_mod.llm, "complete_with_search", fake_search)


def test_run_now_appends_the_answer_and_records_a_run(env, monkeypatch):
    _stub_llm(monkeypatch, "AI news: models got faster.", {"prompt_tokens": 11, "completion_tokens": 7})

    async def go():
        factory = env
        async with await _client() as c:
            tok = await _token(c, "run1@test.io")
            tid = (await c.post("/tasks", json={**TASK, "search": False}, headers=_h(tok))).json()["id"]

            r = await c.post(f"/tasks/{tid}/run", headers=_h(tok))
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["ok"] is True and "AI news" in body["answer"]
            cid = body["conversation_id"]

            detail = (await c.get(f"/tasks/{tid}", headers=_h(tok))).json()
            assert detail["run_count"] == 1 and detail["last_status"] == "ok"
            assert len(detail["runs"]) == 1
            assert detail["runs"][0]["tokens_in"] == 11 and detail["runs"][0]["tokens_out"] == 7

            # the result lives in a real conversation the user can open
            convo = (await c.get(f"/conversations/{cid}", headers=_h(tok))).json()
            roles = [m["role"] for m in convo["messages"]]
            assert roles == ["user", "assistant"]
            assert "AI news" in convo["messages"][1]["content"]
            assert convo["messages"][1]["meta"]["task_id"] == tid

    run(go())


def test_repeat_runs_append_to_the_same_thread(env, monkeypatch):
    """A recurring task should read as one growing briefing thread."""
    _stub_llm(monkeypatch, "entry")

    async def go():
        async with await _client() as c:
            tok = await _token(c, "run2@test.io")
            tid = (await c.post("/tasks", json={**TASK, "search": False}, headers=_h(tok))).json()["id"]
            first = (await c.post(f"/tasks/{tid}/run", headers=_h(tok))).json()["conversation_id"]
            second = (await c.post(f"/tasks/{tid}/run", headers=_h(tok))).json()["conversation_id"]
            assert first == second

            convo = (await c.get(f"/conversations/{first}", headers=_h(tok))).json()
            assert len(convo["messages"]) == 4  # two user/assistant pairs

    run(go())


def test_run_now_does_not_consume_the_scheduled_slot(env, monkeypatch):
    _stub_llm(monkeypatch)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "run3@test.io")
            created = (await c.post("/tasks", json={**TASK, "search": False}, headers=_h(tok))).json()
            tid, before = created["id"], created["next_run_at"]
            await c.post(f"/tasks/{tid}/run", headers=_h(tok))
            after = (await c.get(f"/tasks/{tid}", headers=_h(tok))).json()["next_run_at"]

            # Compare instants, not strings: sqlite round-trips drop tzinfo, so the
            # re-read value is naive UTC while the freshly-computed one is aware.
            def instant(s: str) -> datetime:
                d = datetime.fromisoformat(s)
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

            assert instant(after) == instant(before)  # testing a task must not skip its next run

    run(go())


def test_a_failing_run_is_recorded_without_killing_the_task(env, monkeypatch):
    from app.services import llm as llm_mod

    async def boom(*a, **k):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(llm_mod.llm, "complete", boom)
    monkeypatch.setattr(llm_mod.llm, "complete_with_search", boom)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "fail@test.io")
            tid = (await c.post("/tasks", json={**TASK, "search": False}, headers=_h(tok))).json()["id"]
            r = await c.post(f"/tasks/{tid}/run", headers=_h(tok))
            assert r.status_code == 502

            detail = (await c.get(f"/tasks/{tid}", headers=_h(tok))).json()
            assert detail["last_status"] == "failed"
            assert "provider exploded" in detail["last_error"]
            # the task keeps its schedule and stays enabled
            assert detail["enabled"] is True and detail["next_run_at"] is not None
            assert detail["runs"][0]["status"] == "failed"

    run(go())


def test_a_once_task_disables_itself_after_a_successful_run(env, monkeypatch):
    _stub_llm(monkeypatch)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "once@test.io")
            tid = (
                await c.post(
                    "/tasks", json={**TASK, "schedule_kind": "once", "search": False}, headers=_h(tok)
                )
            ).json()["id"]
            await c.post(f"/tasks/{tid}/run", headers=_h(tok))
            detail = (await c.get(f"/tasks/{tid}", headers=_h(tok))).json()
            assert detail["enabled"] is False and detail["next_run_at"] is None

    run(go())


def test_a_task_run_is_metered_like_any_other_action(env, monkeypatch):
    _stub_llm(monkeypatch, "x", {"prompt_tokens": 5, "completion_tokens": 9})
    seen: list[tuple] = []

    async def fake_record(user_id, kind, model=None, **kw):
        seen.append((kind, kw.get("tokens_in"), kw.get("tokens_out")))

    import app.services.metering as metering

    monkeypatch.setattr(metering, "record_usage", fake_record)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "meter@test.io")
            tid = (await c.post("/tasks", json={**TASK, "search": False}, headers=_h(tok))).json()["id"]
            await c.post(f"/tasks/{tid}/run", headers=_h(tok))

    run(go())
    assert seen and seen[0][0] == "task"
    assert seen[0][1] == 5 and seen[0][2] == 9


# ---------- the scheduler's atomic claim ----------

def test_claim_due_only_takes_overdue_enabled_tasks_and_advances_the_clock(env, monkeypatch):
    from app.services import scheduler as sched

    async def go():
        factory = env
        async with await _client() as c:
            tok = await _token(c, "claim@test.io")
            due = (await c.post("/tasks", json=TASK, headers=_h(tok))).json()["id"]
            future = (await c.post("/tasks", json={**TASK, "title": "Later"}, headers=_h(tok))).json()["id"]
            paused = (await c.post("/tasks", json={**TASK, "title": "Off"}, headers=_h(tok))).json()["id"]
            await c.patch(f"/tasks/{paused}", json={"enabled": False}, headers=_h(tok))

            past = datetime.now(timezone.utc) - timedelta(minutes=5)
            async with factory() as s:
                t = await s.get(ScheduledTask, due)
                t.next_run_at = past
                p = await s.get(ScheduledTask, paused)
                p.next_run_at = past  # overdue BUT disabled → must not be claimed
                await s.commit()

            claimed = await sched._claim_due(10)
            assert claimed == [due]
            assert future not in claimed and paused not in claimed

            async with factory() as s:
                t = await s.get(ScheduledTask, due)
                assert t.last_status == "running"
                # the clock is advanced at claim time, so a crash can't hot-loop
                nxt = t.next_run_at
                if nxt.tzinfo is None:
                    nxt = nxt.replace(tzinfo=timezone.utc)
                assert nxt > datetime.now(timezone.utc)

            # a second pass finds nothing left to claim
            assert await sched._claim_due(10) == []

    run(go())


def test_a_claimed_task_is_not_double_claimed_by_a_second_worker(env):
    """Two app instances racing the same row: exactly one may win."""
    from app.services import scheduler as sched

    async def go():
        factory = env
        async with await _client() as c:
            tok = await _token(c, "race@test.io")
            tid = (await c.post("/tasks", json=TASK, headers=_h(tok))).json()["id"]
            async with factory() as s:
                t = await s.get(ScheduledTask, tid)
                t.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
                await s.commit()

            first = await sched._claim_due(10)
            second = await sched._claim_due(10)
            assert first == [tid] and second == []

    run(go())


def test_tasks_can_be_disabled_by_config(env, monkeypatch):
    monkeypatch.setattr(settings, "TASKS_ENABLED", False)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "toff@test.io")
            r = await c.get("/tasks", headers=_h(tok))
            assert r.status_code == 503 and "disabled" in r.json()["detail"].lower()

    run(go())


def test_scheduler_status_is_reported_for_operators(env):
    from app.services.scheduler import scheduler_status

    st = scheduler_status()
    assert set(st) >= {"enabled", "running", "tick_s", "ticks", "runs", "last_tick"}


def test_run_history_is_trimmed_to_the_retention_limit(env, monkeypatch):
    """A daily task left alone for a year must not accumulate unbounded audit rows."""
    monkeypatch.setattr(settings, "TASK_RUNS_KEEP", 3)
    _stub_llm(monkeypatch, "x")

    async def go():
        factory = env
        async with await _client() as c:
            tok = await _token(c, "prune@test.io")
            tid = (await c.post("/tasks", json={**TASK, "search": False}, headers=_h(tok))).json()["id"]
            for _ in range(5):
                await c.post(f"/tasks/{tid}/run", headers=_h(tok))

            async with factory() as s:
                from sqlalchemy import func, select as sel

                n = await s.scalar(sel(func.count(TaskRun.id)).where(TaskRun.task_id == tid))
                assert n == 3  # newest three kept

            # the task's own counter still reflects every run that happened
            assert (await c.get(f"/tasks/{tid}", headers=_h(tok))).json()["run_count"] == 5

    run(go())
