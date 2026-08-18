import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import Conversation, Message, SharedLink, User
from ...db.session import get_db
from ...schemas import ConversationCreate, ConversationUpdate, FeedbackRequest
from ...services.recall import delete_chat_memory
from ..deps import get_current_user

router = APIRouter()


def conv_out(c: Conversation) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "project_id": c.project_id,
        "gpt_id": getattr(c, "gpt_id", None),
        "pinned": bool(getattr(c, "pinned", False)),
        "temporary": bool(getattr(c, "temporary", False)),
        "archived": bool(getattr(c, "archived", False)),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def msg_out(m: Message) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "user_id": m.user_id,  # author (team chats)
        "meta": m.meta or {},
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("")
async def list_conversations(
    archived: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Conversation).where(Conversation.user_id == user.id, Conversation.temporary.is_(False))
    # 📦 Archived chats live in their own list; the live sidebar never mixes them.
    q = q.where(Conversation.archived.is_(True) if archived else Conversation.archived.is_(False))
    rows = (
        await db.execute(
            q.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc())
        )
    ).scalars().all()
    return [conv_out(c) for c in rows]


def _like_escape(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/search")
async def search_conversations(
    q: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Full-text search across titles and message bodies (ChatGPT sidebar search)."""
    needle = q.strip()
    if len(needle) < 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Query too short")
    pattern = f"%{_like_escape(needle)}%"
    rows = (
        await db.execute(
            select(Conversation, Message)
            .outerjoin(Message, Message.conversation_id == Conversation.id)
            .where(
                Conversation.user_id == user.id,
                Conversation.temporary.is_(False),
                or_(
                    Conversation.title.ilike(pattern),
                    Message.content.ilike(pattern),
                ),
            )
            .order_by(Conversation.updated_at.desc())
            .limit(limit * 4)
        )
    ).all()
    seen: set[str] = set()
    out: list[dict] = []
    low = needle.lower()
    for conv, msg in rows:
        if conv.id in seen:
            continue
        seen.add(conv.id)
        body = (msg.content if msg is not None else "") or ""
        idx = body.lower().find(low)
        if idx < 0:
            snippet = (conv.title or "")[:160]
        else:
            start = max(0, idx - 40)
            snippet = ("…" if start else "") + body[start : start + 160]
        out.append({**conv_out(conv), "snippet": snippet})
        if len(out) >= limit:
            break
    return {"q": needle, "results": out}


@router.post("", status_code=201)
async def create_conversation(
    req: ConversationCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    conv = Conversation(user_id=user.id, title=(req.title or "New chat")[:200])
    db.add(conv)
    await db.commit()
    return conv_out(conv)


async def _get_owned(db: AsyncSession, user: User, cid: str) -> Conversation:
    conv = await db.get(Conversation, cid)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


async def _can_read(db: AsyncSession, user: User, cid: str) -> Conversation:
    """Owner, or any member when the conversation is shared in a workspace."""
    conv = await db.get(Conversation, cid)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    if conv.user_id == user.id:
        return conv
    if conv.workspace_id:
        from .workspaces import membership_of

        if await membership_of(db, conv.workspace_id, user.id):
            return conv
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")


@router.get("/{cid}")
async def get_conversation(cid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    conv = await _can_read(db, user, cid)
    rows = (
        await db.execute(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.asc())
        )
    ).scalars().all()
    # author label map for team conversations (user messages carry user_id)
    authors: dict[str, str] = {}
    if conv.workspace_id:
        for uid_ in {m.user_id for m in rows if m.user_id}:
            u = await db.get(User, uid_)
            if u:
                authors[uid_] = u.display_name or u.email.split("@")[0]
    return {**conv_out(conv), "workspace_id": conv.workspace_id, "authors": authors, "messages": [msg_out(m) for m in rows]}


@router.patch("/{cid}")
async def update_conversation(
    cid: str, req: ConversationUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    if req.title is None and req.pinned is None and req.archived is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
    conv = await _get_owned(db, user, cid)
    if req.title is not None:
        conv.title = req.title[:200]
    if req.pinned is not None:
        conv.pinned = bool(req.pinned)
    if req.archived is not None:
        conv.archived = bool(req.archived)
        if conv.archived:
            conv.pinned = False
    await db.commit()
    await db.refresh(conv)
    return conv_out(conv)


@router.delete("/{cid}", status_code=204)
async def delete_conversation(
    cid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    conv = await _get_owned(db, user, cid)
    await db.delete(conv)
    await db.commit()
    await delete_chat_memory(user.id, cid)  # forget this chat everywhere (best-effort)
    return Response(status_code=204)


@router.post("/{cid}/share", status_code=201)
async def share_conversation(
    cid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Create (or return the existing) public read-only link for a conversation."""
    conv = await _get_owned(db, user, cid)
    link = await db.scalar(select(SharedLink).where(SharedLink.conversation_id == conv.id))
    if not link:
        link = SharedLink(token=secrets.token_urlsafe(12), conversation_id=conv.id, user_id=user.id)
        db.add(link)
        await db.commit()
    return {"token": link.token, "path": f"/shared/{link.token}"}


@router.delete("/{cid}/share")
async def unshare_conversation(
    cid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    conv = await _get_owned(db, user, cid)
    link = await db.scalar(select(SharedLink).where(SharedLink.conversation_id == conv.id))
    if link:
        await db.delete(link)
        await db.commit()
    return {"revoked": True}


@router.post("/{cid}/duplicate", status_code=201)
async def duplicate_conversation(
    cid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Fork a thread — copy messages into a new chat (ChatGPT 'open in new chat')."""
    src = await _get_owned(db, user, cid)
    rows = (
        await db.execute(
            select(Message).where(Message.conversation_id == src.id).order_by(Message.created_at.asc())
        )
    ).scalars().all()
    copy = Conversation(
        user_id=user.id,
        title=((src.title or "Chat") + " (copy)")[:200],
        project_id=src.project_id,
        gpt_id=getattr(src, "gpt_id", None),
        workspace_id=None,  # forks stay personal even if the source was a team thread
        pinned=False,
        temporary=False,
        archived=False,
    )
    db.add(copy)
    await db.flush()
    for m in rows:
        if m.role not in ("user", "assistant"):
            continue
        db.add(
            Message(
                conversation_id=copy.id,
                user_id=m.user_id if m.role == "user" else None,
                role=m.role,
                content=m.content,
                meta=dict(m.meta or {}),
            )
        )
    await db.commit()
    await db.refresh(copy)
    return conv_out(copy)


@router.get("/{cid}/export")
async def export_conversation(
    cid: str,
    format: str = Query(default="json", pattern="^(json|md)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _can_read(db, user, cid)
    rows = (
        await db.execute(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.asc())
        )
    ).scalars().all()
    msgs = [m for m in rows if m.role in ("user", "assistant")]
    if format == "md":
        lines = [f"# {conv.title or 'Chat'}", "", f"_Exported from ChatMood · {datetime.now(timezone.utc).date()}_", ""]
        for m in msgs:
            lines += ["## 🧑 You" if m.role == "user" else "## ✦ ChatMood", "", m.content or "", ""]
        return PlainTextResponse("\n".join(lines), media_type="text/markdown; charset=utf-8")
    return {
        **conv_out(conv),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ],
    }


@router.post("/{cid}/messages/{mid}/feedback")
async def rate_message(
    cid: str,
    mid: str,
    req: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """👍👎 ChatGPT-style rating on an assistant turn. `rating=null` clears it."""
    conv = await _get_owned(db, user, cid)
    msg = await db.get(Message, mid)
    if not msg or msg.conversation_id != conv.id or msg.role != "assistant":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    meta = dict(msg.meta or {})
    if req.rating is None:
        meta.pop("feedback", None)
    else:
        meta["feedback"] = {
            "rating": req.rating,
            "note": (req.note or "").strip()[:500] or None,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    msg.meta = meta
    await db.commit()
    return {"ok": True, "feedback": meta.get("feedback")}
