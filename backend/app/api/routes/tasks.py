"""⏰ Scheduled Tasks API — saved prompts ChatMood runs unattended.

    GET    /tasks              list (with cadence descriptions + next run)
    POST   /tasks              create
    GET    /tasks/{tid}        detail + recent run history
    PATCH  /tasks/{tid}        edit / pause / resume (recomputes next_run_at)
    DELETE /tasks/{tid}        delete
    POST   /tasks/{tid}/run    run right now (rate-limited; doesn't disturb the schedule)

Plan caps live here rather than in the scheduler: an unattended job that quietly
outgrew its plan should fail at the moment the user creates it, with a message
that says what to do, not silently at 3am.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import Project, ScheduledTask, TaskRun, User
from ...db.session import get_db
from ...services.metering import plan_rate_mult
from ...services.schedule import SCHEDULE_KINDS, describe, format_weekdays, next_run_at, parse_weekdays
from ...services.scheduler import run_task
from ..deps import enforce_rate_limit, get_current_user

router = APIRouter()
log = logging.getLogger(__name__)

TASK_MODES = ("chat", "deepsearch", "agent")


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=3, max_length=4_000)
    mode: str = Field(default="chat", pattern="^(chat|deepsearch|agent)$")
    search: bool = True
    schedule_kind: str = Field(default="daily", pattern="^(once|hourly|daily|weekly)$")
    hour_utc: int = Field(default=8, ge=0, le=23)
    minute_utc: int = Field(default=0, ge=0, le=59)
    weekdays: list[int] = Field(default_factory=list)  # Mon=0 … Sun=6 (weekly only)
    enabled: bool = True
    notify: bool = True
    project_id: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    prompt: str | None = Field(default=None, min_length=3, max_length=4_000)
    mode: str | None = Field(default=None, pattern="^(chat|deepsearch|agent)$")
    search: bool | None = None
    schedule_kind: str | None = Field(default=None, pattern="^(once|hourly|daily|weekly)$")
    hour_utc: int | None = Field(default=None, ge=0, le=23)
    minute_utc: int | None = Field(default=None, ge=0, le=59)
    weekdays: list[int] | None = None
    enabled: bool | None = None
    notify: bool | None = None
    project_id: str | None = None


def task_out(t: ScheduledTask) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "prompt": t.prompt,
        "mode": t.mode,
        "search": bool(t.search),
        "schedule_kind": t.schedule_kind,
        "hour_utc": t.hour_utc,
        "minute_utc": t.minute_utc,
        "weekdays": parse_weekdays(t.weekdays),
        "schedule_label": describe(t.schedule_kind, t.hour_utc, t.minute_utc, t.weekdays),
        "enabled": bool(t.enabled),
        "notify": bool(t.notify),
        "project_id": t.project_id,
        "conversation_id": t.conversation_id,
        "next_run_at": t.next_run_at.isoformat() if t.next_run_at else None,
        "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
        "last_status": t.last_status or "",
        "last_error": t.last_error or "",
        "run_count": t.run_count or 0,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def run_out(r: TaskRun) -> dict:
    return {
        "id": r.id,
        "status": r.status,
        "summary": r.summary or "",
        "error": r.error or "",
        "tokens_in": r.tokens_in,
        "tokens_out": r.tokens_out,
        "duration_ms": r.duration_ms,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _require_enabled() -> None:
    if not settings.TASKS_ENABLED:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Tasks are disabled on this deployment")


def task_cap(plan: str) -> int:
    return settings.TASK_MAX_PER_USER_PRO if plan == "pro" else settings.TASK_MAX_PER_USER_FREE


async def _owned(db: AsyncSession, user: User, tid: str) -> ScheduledTask:
    task = await db.get(ScheduledTask, tid)
    if not task or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


async def _check_project(db: AsyncSession, user: User, project_id: str | None) -> str | None:
    if not project_id:
        return None
    project = await db.get(Project, project_id)
    if not project or project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project.id


@router.get("")
async def list_tasks(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    _require_enabled()
    rows = (
        await db.execute(
            select(ScheduledTask)
            .where(ScheduledTask.user_id == user.id)
            .order_by(ScheduledTask.enabled.desc(), ScheduledTask.next_run_at.asc().nulls_last())
        )
    ).scalars().all()
    cap = task_cap(user.plan)
    return {
        "tasks": [task_out(t) for t in rows],
        "limit": cap,
        "used": len(rows),
        "plan": user.plan,
        "scheduler": settings.SCHEDULER_ENABLED,
    }


@router.post("", status_code=201)
async def create_task(
    req: TaskCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    _require_enabled()
    used = int(
        (await db.scalar(select(func.count(ScheduledTask.id)).where(ScheduledTask.user_id == user.id)))
        or 0
    )
    cap = task_cap(user.plan)
    if used >= cap:
        msg = f"⏰ Task limit reached — the {user.plan} plan allows {cap} scheduled task{'s' if cap != 1 else ''}."
        if user.plan != "pro":
            msg += f" Upgrade to Pro for {settings.TASK_MAX_PER_USER_PRO}."
        raise HTTPException(status.HTTP_400_BAD_REQUEST, msg)

    project_id = await _check_project(db, user, req.project_id)
    weekdays = format_weekdays(req.weekdays)
    task = ScheduledTask(
        user_id=user.id,
        project_id=project_id,
        title=req.title.strip(),
        prompt=req.prompt.strip(),
        mode=req.mode,
        search=req.search,
        schedule_kind=req.schedule_kind,
        hour_utc=req.hour_utc,
        minute_utc=req.minute_utc,
        weekdays=weekdays,
        enabled=req.enabled,
        notify=req.notify,
    )
    task.next_run_at = (
        next_run_at(req.schedule_kind, req.hour_utc, req.minute_utc, weekdays) if req.enabled else None
    )
    db.add(task)
    await db.commit()
    return task_out(task)


@router.get("/{tid}")
async def get_task(tid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    _require_enabled()
    task = await _owned(db, user, tid)
    runs = (
        await db.execute(
            select(TaskRun)
            .where(TaskRun.task_id == task.id)
            .order_by(TaskRun.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return {**task_out(task), "runs": [run_out(r) for r in runs]}


@router.patch("/{tid}")
async def update_task(
    tid: str, req: TaskUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    _require_enabled()
    task = await _owned(db, user, tid)

    if req.title is not None:
        task.title = req.title.strip()
    if req.prompt is not None:
        task.prompt = req.prompt.strip()
    if req.mode is not None:
        task.mode = req.mode
    if req.search is not None:
        task.search = req.search
    if req.schedule_kind is not None:
        task.schedule_kind = req.schedule_kind
    if req.hour_utc is not None:
        task.hour_utc = req.hour_utc
    if req.minute_utc is not None:
        task.minute_utc = req.minute_utc
    if req.weekdays is not None:
        task.weekdays = format_weekdays(req.weekdays)
    if req.notify is not None:
        task.notify = req.notify
    if req.project_id is not None:
        task.project_id = await _check_project(db, user, req.project_id) if req.project_id else None
    if req.enabled is not None:
        task.enabled = req.enabled

    # Any schedule/enablement edit re-derives the next slot, so a paused task
    # resumes into the FUTURE rather than instantly firing an overdue run.
    task.next_run_at = (
        next_run_at(task.schedule_kind, task.hour_utc, task.minute_utc, task.weekdays)
        if task.enabled
        else None
    )
    if task.last_status == "running":
        task.last_status = ""  # an edit clears a stuck claim from a crashed run
    await db.commit()
    return task_out(task)


@router.delete("/{tid}", status_code=204)
async def delete_task(tid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    _require_enabled()
    task = await _owned(db, user, tid)
    await db.execute(delete(TaskRun).where(TaskRun.task_id == task.id))
    await db.delete(task)
    await db.commit()
    return Response(status_code=204)


@router.post("/{tid}/run")
async def run_now(tid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Run a task immediately. The schedule is untouched — this is a preview/test
    button, so trying a task must not consume its next scheduled slot."""
    _require_enabled()
    task = await _owned(db, user, tid)
    await enforce_rate_limit(f"task-run:{user.id}", 6 * plan_rate_mult(user.plan))
    result = await run_task(task.id)
    if not result.get("ok"):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, result.get("error") or "Task run failed"
        )
    return result
