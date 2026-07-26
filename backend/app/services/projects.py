"""🗂 Projects — durable containers for related chats, files and standing instructions.

The whole point of a project is that its brief is *ambient*: every chat filed
under it starts with the project's instructions already in the system prompt and
can reach its pinned documents without the user re-attaching anything.

This module owns the read side of that (context assembly + access checks) so the
chat orchestrator stays a thin caller. Everything here is fail-open: a project
lookup that errors must degrade to a normal, unfiled chat rather than break the
conversation.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import FileAsset, Project, ProjectFile

log = logging.getLogger(__name__)

# How much pinned-document text a project may inject. Projects are long-lived
# and accumulate files, so an unbounded splice would silently push the real
# conversation out of the context window.
MAX_PINNED_FILES = 6
MAX_CHARS_PER_FILE = 4_000
MAX_INSTRUCTION_CHARS = 4_000


async def get_readable(db: AsyncSession, user, project_id: str) -> Project | None:
    """The project, if this user may read it (owner, or a member of its workspace)."""
    if not project_id:
        return None
    project = await db.get(Project, project_id)
    if not project:
        return None
    if project.user_id == user.id:
        return project
    if project.workspace_id:
        from ..api.routes.workspaces import membership_of

        if await membership_of(db, project.workspace_id, user.id):
            return project
    return None


async def pinned_files(db: AsyncSession, project_id: str, limit: int = MAX_PINNED_FILES) -> list[FileAsset]:
    """Files pinned to the project, newest first, that still carry extracted text."""
    rows = (
        await db.execute(
            select(FileAsset)
            .join(ProjectFile, ProjectFile.file_id == FileAsset.id)
            .where(ProjectFile.project_id == project_id)
            .order_by(ProjectFile.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


def build_instruction_block(project: Project) -> str:
    """The standing brief injected as a system message for every chat in the project."""
    lines = [f'You are working inside the user\'s project "{project.name}".']
    if project.description:
        lines.append(f"Project description: {project.description.strip()[:600]}")
    if project.instructions:
        lines.append(
            "Standing instructions for this project — follow them for every reply in this "
            "chat unless they conflict with being truthful and safe:\n"
            + project.instructions.strip()[:MAX_INSTRUCTION_CHARS]
        )
    return "\n\n".join(lines)


async def context_messages(db: AsyncSession, user, project_id: str | None) -> list[dict]:
    """System messages contributed by a project: its brief, then its pinned docs.

    Returns [] for no/unreadable/failing project — a project must never be able
    to take a conversation down with it.
    """
    if not project_id:
        return []
    try:
        project = await get_readable(db, user, project_id)
        if not project:
            return []
        msgs = [{"role": "system", "content": build_instruction_block(project)}]

        files = await pinned_files(db, project.id)
        blocks = [
            f'<project-file name="{f.filename}" type="{f.mime}">\n'
            f"{(f.extracted_text or '')[:MAX_CHARS_PER_FILE]}\n</project-file>"
            for f in files
            if f.extracted_text
        ]
        if blocks:
            msgs.append(
                {
                    "role": "system",
                    "content": (
                        "Reference documents pinned to this project (cite the filename when "
                        "you use one):\n" + "\n\n".join(blocks)
                    ),
                }
            )
        return msgs
    except Exception as e:  # never break a chat over project context
        log.warning("project context failed for %s: %s", project_id, e)
        return []
