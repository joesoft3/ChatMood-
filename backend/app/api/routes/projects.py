"""🗂 Projects API — durable containers for chats, files and standing instructions.

    GET    /projects                      list (with chat/file counts)
    POST   /projects                      create
    GET    /projects/{pid}                detail + conversations + pinned files
    PATCH  /projects/{pid}                rename / re-brief / archive
    DELETE /projects/{pid}                delete (chats survive, they just unfile)
    POST   /projects/{pid}/files/{fid}    pin an uploaded file
    DELETE /projects/{pid}/files/{fid}    unpin (the upload itself is untouched)
    POST   /projects/{pid}/conversations/{cid}   file a chat under the project
    DELETE /projects/{pid}/conversations/{cid}   unfile it

Ownership rule: only the owner may mutate; workspace members may read, so a team
can share a project brief without anyone silently rewriting it.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import Conversation, FileAsset, Project, ProjectFile, ScheduledTask, User
from ...db.session import get_db
from ...services.projects import get_readable, pinned_files
from ..deps import get_current_user

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2_000)
    instructions: str = Field(default="", max_length=8_000)
    emoji: str = Field(default="🗂", max_length=8)
    accent: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    workspace_id: str | None = None


class ProjectUpdate(BaseModel):
    """PATCH semantics: a field left absent/None stays unchanged; "" clears it."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2_000)
    instructions: str | None = Field(default=None, max_length=8_000)
    emoji: str | None = Field(default=None, max_length=8)
    accent: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    archived: bool | None = None
    workspace_id: str | None = None


def project_out(p: Project, chats: int = 0, files: int = 0, tasks: int = 0) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description or "",
        "instructions": p.instructions or "",
        "emoji": p.emoji or "🗂",
        "accent": p.accent,
        "archived": bool(p.archived),
        "workspace_id": p.workspace_id,
        "chats": chats,
        "files": files,
        "tasks": tasks,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _require_enabled() -> None:
    if not settings.PROJECTS_ENABLED:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Projects are disabled on this deployment")


async def _owned(db: AsyncSession, user: User, pid: str) -> Project:
    """Mutations require ownership (workspace members get read-only access)."""
    project = await db.get(Project, pid)
    if not project or project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


@router.get("")
async def list_projects(
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_enabled()
    q = select(Project).where(Project.user_id == user.id)
    if not include_archived:
        q = q.where(Project.archived.is_(False))
    rows = (await db.execute(q.order_by(Project.updated_at.desc()))).scalars().all()

    # Counts in three grouped queries rather than N per project.
    ids = [p.id for p in rows]
    chats: dict[str, int] = {}
    files: dict[str, int] = {}
    tasks: dict[str, int] = {}
    if ids:
        chats = {
            k: int(v)
            for k, v in (
                await db.execute(
                    select(Conversation.project_id, func.count(Conversation.id))
                    .where(Conversation.project_id.in_(ids))
                    .group_by(Conversation.project_id)
                )
            ).all()
        }
        files = {
            k: int(v)
            for k, v in (
                await db.execute(
                    select(ProjectFile.project_id, func.count(ProjectFile.file_id))
                    .where(ProjectFile.project_id.in_(ids))
                    .group_by(ProjectFile.project_id)
                )
            ).all()
        }
        tasks = {
            k: int(v)
            for k, v in (
                await db.execute(
                    select(ScheduledTask.project_id, func.count(ScheduledTask.id))
                    .where(ScheduledTask.project_id.in_(ids))
                    .group_by(ScheduledTask.project_id)
                )
            ).all()
        }
    return [
        project_out(p, chats.get(p.id, 0), files.get(p.id, 0), tasks.get(p.id, 0)) for p in rows
    ]


@router.post("", status_code=201)
async def create_project(
    req: ProjectCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    _require_enabled()
    count = int(
        (await db.scalar(select(func.count(Project.id)).where(Project.user_id == user.id))) or 0
    )
    if count >= settings.PROJECT_MAX_PER_USER:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Project limit reached ({settings.PROJECT_MAX_PER_USER}). Delete or archive one first.",
        )
    if req.workspace_id:
        from .workspaces import require_member

        await require_member(db, req.workspace_id, user.id)
    project = Project(
        user_id=user.id,
        workspace_id=req.workspace_id,
        name=req.name.strip(),
        description=req.description.strip(),
        instructions=req.instructions.strip(),
        emoji=req.emoji or "🗂",
        accent=req.accent,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)  # load server-side created_at/updated_at before serializing
    return project_out(project)


@router.get("/{pid}")
async def get_project(pid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    _require_enabled()
    project = await get_readable(db, user, pid)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    convs = (
        await db.execute(
            select(Conversation)
            .where(Conversation.project_id == project.id)
            .order_by(Conversation.updated_at.desc())
            .limit(100)
        )
    ).scalars().all()
    files = await pinned_files(db, project.id, limit=settings.PROJECT_MAX_FILES)
    task_rows = (
        await db.execute(
            select(ScheduledTask)
            .where(ScheduledTask.project_id == project.id)
            .order_by(ScheduledTask.created_at.desc())
            .limit(50)
        )
    ).scalars().all()

    return {
        **project_out(project, len(convs), len(files), len(task_rows)),
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in convs
        ],
        "pinned_files": [
            {
                "id": f.id,
                "filename": f.filename,
                "mime": f.mime,
                "size_bytes": f.size_bytes,
                "indexed": bool(f.extracted_text),
            }
            for f in files
        ],
        "tasks": [
            {"id": t.id, "title": t.title, "enabled": bool(t.enabled), "mode": t.mode}
            for t in task_rows
        ],
    }


@router.patch("/{pid}")
async def update_project(
    pid: str, req: ProjectUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    _require_enabled()
    project = await _owned(db, user, pid)
    if req.name is not None:
        project.name = req.name.strip()
    if req.description is not None:
        project.description = req.description.strip()
    if req.instructions is not None:
        project.instructions = req.instructions.strip()
    if req.emoji is not None:
        project.emoji = req.emoji or "🗂"
    if req.accent is not None:
        project.accent = req.accent
    if req.archived is not None:
        project.archived = req.archived
    if req.workspace_id is not None:
        if req.workspace_id:
            from .workspaces import require_member

            await require_member(db, req.workspace_id, user.id)
            project.workspace_id = req.workspace_id
        else:
            project.workspace_id = None
    await db.commit()
    await db.refresh(project)  # updated_at is computed server-side by onupdate
    return project_out(project)


@router.delete("/{pid}", status_code=204)
async def delete_project(pid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Delete a project. Its conversations and uploads SURVIVE — they simply
    become unfiled. Deleting an organizational container must never be a
    destructive act on the user's actual content."""
    _require_enabled()
    project = await _owned(db, user, pid)
    await db.execute(
        Conversation.__table__.update()
        .where(Conversation.project_id == project.id)
        .values(project_id=None)
    )
    await db.execute(delete(ProjectFile).where(ProjectFile.project_id == project.id))
    await db.delete(project)
    await db.commit()
    return Response(status_code=204)


@router.post("/{pid}/files/{fid}", status_code=201)
async def pin_file(
    pid: str, fid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    _require_enabled()
    project = await _owned(db, user, pid)
    asset = await db.get(FileAsset, fid)
    if not asset or asset.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    exists = await db.get(ProjectFile, {"project_id": project.id, "file_id": fid})
    if exists:
        return {"ok": True, "project_id": project.id, "file_id": fid, "already_pinned": True}
    count = int(
        (await db.scalar(select(func.count(ProjectFile.file_id)).where(ProjectFile.project_id == project.id)))
        or 0
    )
    if count >= settings.PROJECT_MAX_FILES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"This project already has the maximum {settings.PROJECT_MAX_FILES} pinned files.",
        )
    db.add(ProjectFile(project_id=project.id, file_id=fid))
    await db.commit()
    return {"ok": True, "project_id": project.id, "file_id": fid}


@router.delete("/{pid}/files/{fid}")
async def unpin_file(
    pid: str, fid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    _require_enabled()
    project = await _owned(db, user, pid)
    await db.execute(
        delete(ProjectFile).where(ProjectFile.project_id == project.id, ProjectFile.file_id == fid)
    )
    await db.commit()
    return {"ok": True}


@router.post("/{pid}/conversations/{cid}")
async def file_conversation(
    pid: str, cid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    _require_enabled()
    project = await _owned(db, user, pid)
    conv = await db.get(Conversation, cid)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    conv.project_id = project.id
    await db.commit()
    return {"ok": True, "conversation_id": cid, "project_id": project.id}


@router.delete("/{pid}/conversations/{cid}")
async def unfile_conversation(
    pid: str, cid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    _require_enabled()
    await _owned(db, user, pid)
    conv = await db.get(Conversation, cid)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    conv.project_id = None
    await db.commit()
    return {"ok": True}
