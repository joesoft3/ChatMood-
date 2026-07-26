"""⏰ Task scheduler — runs saved prompts unattended, on a schedule.

Design notes worth knowing before you change this:

* **Single loop, atomic claim.** The loop wakes every SCHEDULER_TICK_S, selects
  due tasks and *claims* each one with a conditional UPDATE (`last_status !=
  'running'`). Two app instances (Fly runs several machines) therefore cannot
  double-run a task: exactly one UPDATE reports a matched row.

* **Advance the clock before the work, not after.** `next_run_at` is moved
  forward at claim time. If the process dies mid-run, the task resumes on its
  next slot instead of hot-looping on a permanently-overdue row.

* **Runs are cheap and bounded.** Each execution is capped by
  SCHEDULER_RUN_TIMEOUT_S and metered like any other user action, so a runaway
  prompt can't drain an account overnight.

* **Fail-open, always.** A failing task records `last_status='failed'` with the
  error and keeps its schedule; it never kills the loop or blocks its siblings.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import delete, select, update

from ..config import settings
from ..db.models import Conversation, Message, ScheduledTask, TaskRun, User
from ..db.session import SessionLocal
from .schedule import next_run_at

log = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_ticks = 0
_runs = 0
_last_tick: str | None = None

# Answers are trimmed before they become a run summary (the full text lives in
# the conversation) — the Tasks page only ever renders a preview.
SUMMARY_CHARS = 600


def scheduler_enabled() -> bool:
    return bool(settings.TASKS_ENABLED and settings.SCHEDULER_ENABLED)


def scheduler_status() -> dict:
    """Surfaced on /healthz so operators can verify the loop without log access."""
    return {
        "enabled": scheduler_enabled(),
        "running": _task is not None,
        "tick_s": settings.SCHEDULER_TICK_S,
        "ticks": _ticks,
        "runs": _runs,
        "last_tick": _last_tick,
    }


async def _ensure_conversation(db, task: ScheduledTask, user: User) -> Conversation:
    """The thread a task appends into — one per task, created lazily.

    Reusing a single conversation is what makes a recurring task read like a
    briefing thread ("every morning, another entry") instead of littering the
    sidebar with a new chat per run.
    """
    if task.conversation_id:
        conv = await db.get(Conversation, task.conversation_id)
        if conv:
            return conv
    conv = Conversation(
        user_id=user.id,
        title=f"⏰ {task.title}"[:200],
        project_id=task.project_id,
    )
    db.add(conv)
    await db.flush()
    task.conversation_id = conv.id
    return conv


async def _answer(task: ScheduledTask, user: User, conv_id: str, usage: dict) -> str:
    """Produce the task's answer through the mode it was saved with."""
    mode = (task.mode or "chat").lower()

    if mode == "deepsearch":
        from .deepsearch import build_synthesis_messages, decompose, research_query
        from .llm import llm

        questions = (await decompose(task.prompt, 3))[:3]
        findings: list[tuple[str, str]] = []
        sources: list[str] = []
        results = await asyncio.gather(
            *(research_query(q) for q in questions), return_exceptions=True
        )
        for question, res in zip(questions, results):
            if isinstance(res, Exception):
                continue
            text, cites = res
            findings.append((question, text))
            sources += cites
        uniq = list(dict.fromkeys(sources))
        messages = build_synthesis_messages(task.prompt, findings, uniq)
        return await llm.complete(messages, model=settings.MODEL_CHAT, temperature=0.4, usage_out=usage)

    if mode == "agent":
        from .agents import plan, run_agent

        steps = (await plan(task.prompt))[:3]
        prior: list[tuple[str, str, str]] = []
        for step in steps[:-1]:
            try:
                out, _ = await run_agent(step["agent"], step["task"], task.prompt, [], usage_out=usage)
                prior.append((step["agent"], step["task"], out))
            except Exception as e:
                log.warning("task %s agent step failed: %s", task.id, e)
        final = steps[-1] if steps else {"agent": "writer", "task": task.prompt}
        out, _ = await run_agent("writer", final["task"], task.prompt, prior, usage_out=usage)
        return out

    # default: a normal grounded chat turn, with the user's full context stack
    from ..api.routes.chat import build_messages
    from .llm import llm

    async with SessionLocal() as s:
        fresh_user = await s.get(User, user.id)
        messages, model, live_search = await build_messages(
            s, fresh_user or user, conv_id, task.prompt, [], bool(task.search), created=False
        )
        if task.project_id:
            from .projects import context_messages

            for i, block in enumerate(await context_messages(s, fresh_user or user, task.project_id)):
                messages.insert(1 + i, block)

    if live_search:
        text, cites = await llm.complete_with_search(messages, model=model, usage_out=usage)
        if cites:
            uniq = list(dict.fromkeys(cites))
            text += "\n\n**Sources**\n" + "\n".join(f"- [{i + 1}]({u})" for i, u in enumerate(uniq))
        return text
    return await llm.complete(messages, model=model, temperature=0.6, usage_out=usage)


async def run_task(task_id: str) -> dict:
    """Execute one task end-to-end. Safe to call directly (the "Run now" button does)."""
    global _runs
    started = time.perf_counter()
    usage: dict = {}
    status, answer, error = "ok", "", ""

    async with SessionLocal() as db:
        task = await db.get(ScheduledTask, task_id)
        if not task:
            return {"ok": False, "error": "Task not found"}
        user = await db.get(User, task.user_id)
        if not user:
            return {"ok": False, "error": "Owner not found"}

        conv = await _ensure_conversation(db, task, user)
        conv_id = conv.id
        db.add(
            Message(
                conversation_id=conv_id,
                user_id=user.id,
                role="user",
                content=task.prompt,
                meta={"mode": "task", "task_id": task.id, "task_title": task.title},
            )
        )
        await db.commit()

        try:
            answer = await asyncio.wait_for(
                _answer(task, user, conv_id, usage),
                timeout=settings.SCHEDULER_RUN_TIMEOUT_S,
            )
            answer = (answer or "").strip() or "(no response)"
        except asyncio.TimeoutError:
            status, error = "failed", f"Timed out after {settings.SCHEDULER_RUN_TIMEOUT_S}s"
        except Exception as e:
            status, error = "failed", str(e)[:500]

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        tokens_in = int(usage.get("prompt_tokens", 0))
        tokens_out = int(usage.get("completion_tokens", 0))

        # Persist the outcome: message (on success) + audit row + task state
        task = await db.get(ScheduledTask, task_id)  # re-read: the run took a while
        if task:
            if status == "ok":
                db.add(
                    Message(
                        conversation_id=conv_id,
                        role="assistant",
                        content=answer,
                        meta={"mode": "task", "task_id": task.id, "task_title": task.title},
                    )
                )
                conv = await db.get(Conversation, conv_id)
                if conv:
                    conv.updated_at = datetime.now(timezone.utc)
            db.add(
                TaskRun(
                    task_id=task.id,
                    user_id=task.user_id,
                    status=status,
                    summary=answer[:SUMMARY_CHARS],
                    error=error,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    duration_ms=elapsed_ms,
                )
            )
            await _prune_runs(db, task.id)
            task.last_run_at = datetime.now(timezone.utc)
            task.last_status = status
            task.last_error = error
            task.run_count = (task.run_count or 0) + 1
            # "once" is spent after a successful run
            if task.schedule_kind == "once" and status == "ok":
                task.enabled = False
                task.next_run_at = None
            await db.commit()

    # Metering + push happen outside the transaction so neither can hold it open.
    try:
        from .metering import estimate_tokens, record_usage

        counts = (
            {"tokens_in": tokens_in, "tokens_out": tokens_out, "estimated": False}
            if (tokens_in or tokens_out)
            else estimate_tokens(task_id, answer)
        )
        await record_usage(user.id, "task", model=None, **counts)
    except Exception as e:
        log.warning("task metering failed: %s", e)

    if status == "ok":
        _runs += 1
        try:
            from .notify import push_later

            async with SessionLocal() as s:
                t = await s.get(ScheduledTask, task_id)
                if t and t.notify:
                    push_later(
                        t.user_id,
                        "task",
                        f"⏰ {t.title}",
                        answer[:140],
                        {"conversation_id": conv_id, "task_id": t.id},
                    )
        except Exception as e:
            log.warning("task push failed: %s", e)

    return {
        "ok": status == "ok",
        "status": status,
        "error": error,
        "answer": answer,
        "conversation_id": conv_id,
        "duration_ms": elapsed_ms,
    }


async def _prune_runs(db, task_id: str) -> None:
    """Keep only the newest TASK_RUNS_KEEP audit rows for a task.

    A daily task left alone for a year would otherwise accumulate 365 rows
    nobody will read; the Tasks page only ever shows the last 20.
    """
    keep = max(1, int(settings.TASK_RUNS_KEEP))
    try:
        stale = (
            await db.execute(
                select(TaskRun.id)
                .where(TaskRun.task_id == task_id)
                .order_by(TaskRun.created_at.desc())
                .offset(keep)
            )
        ).scalars().all()
        if stale:
            await db.execute(delete(TaskRun).where(TaskRun.id.in_(stale)))
    except Exception as e:  # trimming history must never fail a run
        log.warning("task run pruning failed for %s: %s", task_id, e)


async def _claim_due(limit: int) -> list[str]:
    """Atomically claim due tasks; returns the ids this process owns.

    The conditional UPDATE is the whole concurrency story: `last_status !=
    'running'` means a second instance racing on the same row updates zero rows
    and simply skips it.
    """
    now = datetime.now(timezone.utc)
    claimed: list[str] = []
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(ScheduledTask)
                .where(
                    ScheduledTask.enabled.is_(True),
                    ScheduledTask.next_run_at.is_not(None),
                    ScheduledTask.next_run_at <= now,
                )
                .order_by(ScheduledTask.next_run_at)
                .limit(limit)
            )
        ).scalars().all()

        for task in rows:
            upcoming = next_run_at(
                task.schedule_kind, task.hour_utc, task.minute_utc, task.weekdays, after=now
            )
            res = await db.execute(
                update(ScheduledTask)
                .where(ScheduledTask.id == task.id, ScheduledTask.last_status != "running")
                .values(last_status="running", next_run_at=upcoming)
            )
            if res.rowcount:
                claimed.append(task.id)
        await db.commit()
    return claimed


async def _loop() -> None:
    global _ticks, _last_tick
    interval = max(20.0, float(settings.SCHEDULER_TICK_S))
    while True:
        await asyncio.sleep(interval)
        _ticks += 1
        _last_tick = datetime.now(timezone.utc).isoformat()
        try:
            ids = await _claim_due(settings.SCHEDULER_BATCH)
            if ids:
                log.info("⏰ scheduler running %d due task(s)", len(ids))
                await asyncio.gather(*(run_task(i) for i in ids), return_exceptions=True)
        except Exception as e:  # a bad tick must never kill the loop
            log.warning("scheduler tick failed: %s", e)


def start_scheduler() -> None:
    """Idempotent starter — called once from the app lifespan."""
    global _task
    if not scheduler_enabled() or _task is not None:
        return
    _task = asyncio.create_task(_loop())
    log.info("⏰ task scheduler started (tick every %ss)", settings.SCHEDULER_TICK_S)


async def stop_scheduler() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):
        pass
    _task = None
