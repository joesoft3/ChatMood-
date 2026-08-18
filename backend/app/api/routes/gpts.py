"""🤖 Custom GPTs — ChatGPT-style reusable assistants.

    GET    /gpts                 catalog + the user's own GPTs
    POST   /gpts                 create
    GET    /gpts/{gid}           detail (catalog or owned)
    PATCH  /gpts/{gid}           edit (owned only)
    DELETE /gpts/{gid}           delete (owned only; chats survive)
    POST   /gpts/{gid}/files/{fid}   pin a knowledge file
    DELETE /gpts/{gid}/files/{fid}   unpin
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import CustomGpt, FileAsset, User
from ...db.session import get_db
from ...schemas import GptCreate, GptUpdate
from ...services.gpts import CATALOG, catalog_by_id, catalog_out, gpt_out, list_mine, resolve_gpt
from ..deps import get_current_user

router = APIRouter()


def _clean_starters(raw: list[str] | None) -> list[str]:
    out: list[str] = []
    for s in raw or []:
        t = str(s).strip()[:120]
        if t and t not in out:
            out.append(t)
        if len(out) >= 4:
            break
    return out


def _clean_files(raw: list[str] | None) -> list[str]:
    out: list[str] = []
    for fid in raw or []:
        t = str(fid).strip()
        if t and t not in out:
            out.append(t)
        if len(out) >= 12:
            break
    return out


async def _owned(db: AsyncSession, user: User, gid: str) -> CustomGpt:
    row = await db.get(CustomGpt, gid)
    if not row or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "GPT not found")
    return row


@router.get("")
async def list_gpts(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    mine = await list_mine(db, user)
    return {
        "catalog": [catalog_out(g) for g in CATALOG],
        "mine": [gpt_out(g) for g in mine],
        "limit": settings.GPT_MAX_PER_USER,
        "used": len(mine),
    }


@router.post("", status_code=201)
async def create_gpt(
    req: GptCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    used = int(
        (await db.scalar(select(func.count(CustomGpt.id)).where(CustomGpt.user_id == user.id))) or 0
    )
    if used >= settings.GPT_MAX_PER_USER:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"GPT limit reached ({settings.GPT_MAX_PER_USER}). Delete one first.",
        )
    row = CustomGpt(
        user_id=user.id,
        name=req.name.strip()[:80],
        description=(req.description or "").strip()[:400],
        instructions=(req.instructions or "").strip()[:8_000],
        emoji=(req.emoji or "🤖")[:8],
        starters=_clean_starters(req.starters),
        file_ids=_clean_files(req.file_ids),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return gpt_out(row)


@router.get("/{gid}")
async def get_gpt(gid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    found = await resolve_gpt(db, user, gid)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "GPT not found")
    return found


@router.patch("/{gid}")
async def update_gpt(
    gid: str, req: GptUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    if catalog_by_id(gid):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Catalog GPTs can't be edited — duplicate one instead")
    row = await _owned(db, user, gid)
    if req.name is not None:
        row.name = req.name.strip()[:80]
    if req.description is not None:
        row.description = req.description.strip()[:400]
    if req.instructions is not None:
        row.instructions = req.instructions.strip()[:8_000]
    if req.emoji is not None:
        row.emoji = (req.emoji or "🤖")[:8]
    if req.starters is not None:
        row.starters = _clean_starters(req.starters)
    if req.file_ids is not None:
        row.file_ids = _clean_files(req.file_ids)
    await db.commit()
    await db.refresh(row)
    return gpt_out(row)


@router.delete("/{gid}", status_code=204)
async def delete_gpt(gid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if catalog_by_id(gid):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Catalog GPTs can't be deleted")
    row = await _owned(db, user, gid)
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


@router.post("/{gid}/files/{fid}", status_code=201)
async def pin_knowledge(
    gid: str, fid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    if catalog_by_id(gid):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Catalog GPTs have no knowledge files")
    row = await _owned(db, user, gid)
    asset = await db.get(FileAsset, fid)
    if not asset or asset.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    files = _clean_files(list(row.file_ids or []))
    if fid in files:
        return {"ok": True, "file_id": fid, "already_pinned": True}
    if len(files) >= 12:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This GPT already has 12 knowledge files")
    files.append(fid)
    row.file_ids = files
    await db.commit()
    return {"ok": True, "file_id": fid}


@router.delete("/{gid}/files/{fid}")
async def unpin_knowledge(
    gid: str, fid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    if catalog_by_id(gid):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Catalog GPTs have no knowledge files")
    row = await _owned(db, user, gid)
    row.file_ids = [x for x in (row.file_ids or []) if x != fid]
    await db.commit()
    return {"ok": True}
