"""📺 Creator Reel — the shared public feed of creator videos.

Two ways in:
  • **Upload** — a creator posts their own clip (`POST /reels/upload`, multipart).
  • **Share**  — a creator posts something Mood already generated: a storyboard
    film or an in-chat video (`POST /reels/share`, JSON). Nothing is copied;
    the row points at the media that already exists.

Feed reads are open to any signed-in user; writes are always scoped to the
author. Reel media uses the `_r.mp4` / `_rp.jpg` suffixes precisely so the 24h
media janitor (which only matches `<hex32>.mp4` / `_e.mp4` / `_p.jpg`) leaves
posted reels alone — a feed whose videos evaporate overnight is not a feed.
"""

import logging
import os
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import Film, Reel, ReelLike, ReelSave, User
from ...db.session import get_db
from ...services import soundtrack
from ...services.metering import plan_rate_mult, record_usage
from ..deps import enforce_rate_limit, get_current_user

log = logging.getLogger(__name__)
router = APIRouter()

# Reel media names: <hex32>_r.mp4 (clip) and <hex32>_rp.jpg (cover frame).
# Deliberately outside soundtrack.MEDIA_NAME_RE / MEDIA_POSTER_RE so the
# ephemeral-media janitor never sweeps a posted reel.
REEL_NAME_RE = re.compile(r"^[a-f0-9]{32}_r\.mp4$")
REEL_POSTER_RE = re.compile(r"^[a-f0-9]{32}_rp\.jpg$")

REEL_MIMES = {"video/mp4": "mp4", "video/quicktime": "mp4", "video/webm": "mp4"}
REEL_MAX_BYTES = 100 * 1024 * 1024
CAPTION_MAX = 300
FEED_PAGE = 20


def _author_label(u: User) -> str:
    """Display name for the feed — never leak the full email address."""
    name = (getattr(u, "display_name", "") or "").strip()
    if name:
        return name[:80]
    email = (u.email or "").strip()
    return (email.split("@")[0] or "creator")[:80]


def _media_url(name: str) -> str:
    return f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/api/v1/reels/files/{name}"


def _reel_out(r: Reel, *, liked: bool = False, saved: bool = False, mine: bool = False) -> dict:
    """Serialize a reel for the feed.

    Defensive about filenames for the same reason the films gallery is: one
    malformed row must never break the whole feed render.
    """
    url = ""
    if r.filename and REEL_NAME_RE.match(r.filename):
        url = _media_url(r.filename)
    elif r.source_url:
        url = r.source_url

    poster = ""
    if r.poster and REEL_POSTER_RE.match(r.poster):
        poster = _media_url(r.poster)

    return {
        "id": r.id,
        "author": r.author_name or "creator",
        "caption": r.caption or "",
        "source": r.source,
        "url": url,
        "poster": poster,
        "views": r.views or 0,
        "likes": r.likes or 0,
        "shares": r.shares or 0,
        "saves": r.saves or 0,
        "liked": liked,
        "saved": saved,
        "mine": mine,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


async def _liked_ids(db: AsyncSession, user_id: str, reel_ids: list[str]) -> set[str]:
    """Which of these reels the viewer already liked (one query, not N)."""
    if not reel_ids:
        return set()
    rows = (
        await db.execute(
            select(ReelLike.reel_id).where(
                ReelLike.user_id == user_id, ReelLike.reel_id.in_(reel_ids)
            )
        )
    ).scalars().all()
    return set(rows)


async def _saved_ids(db: AsyncSession, user_id: str, reel_ids: list[str]) -> set[str]:
    """Which of these reels the viewer has bookmarked (one query, not N)."""
    if not reel_ids:
        return set()
    rows = (
        await db.execute(
            select(ReelSave.reel_id).where(
                ReelSave.user_id == user_id, ReelSave.reel_id.in_(reel_ids)
            )
        )
    ).scalars().all()
    return set(rows)


# --------------------------------------------------------------------- feed
@router.get("")
async def list_reels(
    mine: bool = False,
    saved: bool = False,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The shared creator feed, newest first.

    `mine=true`  → only your posts (including unposted ones, so you can
                   restore them from your profile).
    `saved=true` → only reels you bookmarked, newest *save* first (not newest
                   post — a save is its own event with its own timestamp).
    """
    offset = max(0, min(offset, 5000))

    if saved:
        # Join through the bookmark table and sort by when it was saved.
        q = (
            select(Reel)
            .join(ReelSave, ReelSave.reel_id == Reel.id)
            .where(ReelSave.user_id == user.id, Reel.status == "live")
            .order_by(ReelSave.created_at.desc(), Reel.id.desc())
        )
        count_q = (
            select(func.count(Reel.id))
            .select_from(Reel)
            .join(ReelSave, ReelSave.reel_id == Reel.id)
            .where(ReelSave.user_id == user.id, Reel.status == "live")
        )
    else:
        q = select(Reel)
        if mine:
            q = q.where(Reel.user_id == user.id)
            count_q = select(func.count(Reel.id)).where(Reel.user_id == user.id)
        else:
            q = q.where(Reel.status == "live")
            count_q = select(func.count(Reel.id)).where(Reel.status == "live")
        # `id` breaks ties deterministically: without it, posts sharing a
        # timestamp could shuffle between pages and the reader would skip or
        # re-see one.
        q = q.order_by(Reel.created_at.desc(), Reel.id.desc())

    rows = (await db.execute(q.offset(offset).limit(FEED_PAGE))).scalars().all()

    ids = [r.id for r in rows]
    liked = await _liked_ids(db, user.id, ids)
    saved_set = await _saved_ids(db, user.id, ids)
    total = int(await db.scalar(count_q) or 0)
    return {
        "reels": [
            _reel_out(r, liked=r.id in liked, saved=r.id in saved_set, mine=r.user_id == user.id)
            for r in rows
        ],
        "total": total,
        "next_offset": offset + len(rows) if offset + len(rows) < total else None,
    }


async def _own_reel(db: AsyncSession, user: User, reel_id: str) -> Reel:
    r = await db.get(Reel, reel_id)
    if not r or r.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reel not found")
    return r


# ------------------------------------------------------------------- upload
@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_reel(
    file: UploadFile = File(...),
    caption: str = Form(default="", max_length=CAPTION_MAX),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """🎥 Post your own clip to the creator feed."""
    await enforce_rate_limit(f"reelup:{user.id}", 4 * plan_rate_mult(user.plan))

    mime = (file.content_type or "").lower()
    if mime not in REEL_MIMES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload an MP4, MOV or WebM video"
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That file is empty")
    if len(raw) > REEL_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Reels must be ≤ {REEL_MAX_BYTES // (1024 * 1024)} MB",
        )

    uid = uuid.uuid4().hex
    name = f"{uid}_r.mp4"
    os.makedirs(settings.MEDIA_DIR, exist_ok=True)
    path = os.path.join(settings.MEDIA_DIR, name)
    with open(path, "wb") as fh:
        fh.write(raw)

    # Cover frame — best effort: a reel without a poster still plays fine.
    poster = ""
    try:
        ffbin = soundtrack.ffmpeg_path()
        if ffbin:
            got = await soundtrack.extract_poster(ffbin, path, settings.MEDIA_DIR, f"{uid}_r.mp4", 6.0)
            # extract_poster writes <base>_p.jpg → rename into the reel namespace
            if got:
                src = os.path.join(settings.MEDIA_DIR, got)
                dst_name = f"{uid}_rp.jpg"
                os.replace(src, os.path.join(settings.MEDIA_DIR, dst_name))
                poster = dst_name
    except Exception:  # noqa: BLE001 — cover frames are cosmetic, never fatal
        log.info("reel poster extraction skipped", exc_info=True)

    row = Reel(
        id=uid,
        user_id=user.id,
        author_name=_author_label(user),
        caption=caption.strip()[:CAPTION_MAX],
        source="upload",
        filename=name,
        poster=poster,
    )
    db.add(row)
    await db.commit()
    await record_usage(user.id, "reel", "upload")
    return {"reel": _reel_out(row, mine=True)}


# -------------------------------------------------------------------- share
@router.post("/share", status_code=status.HTTP_201_CREATED)
async def share_to_reel(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """♻️ Post a video Mood already made — a film, or an in-chat generation.

    Body: `{film_id}` **or** `{url}`, plus an optional `caption`.
    Nothing is copied: the reel points at media that already exists.
    """
    await enforce_rate_limit(f"reelshare:{user.id}", 8 * plan_rate_mult(user.plan))
    caption = str(body.get("caption") or "").strip()[:CAPTION_MAX]
    film_id = str(body.get("film_id") or "").strip()
    url = str(body.get("url") or "").strip()

    if film_id:
        film = await db.get(Film, film_id)
        if not film or film.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Film not found")
        if film.status != "done":
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"That film is still {film.status} — wait for it to finish"
            )
        dupe = await db.scalar(
            select(Reel.id).where(
                Reel.user_id == user.id, Reel.film_id == film_id, Reel.status == "live"
            )
        )
        if dupe:
            raise HTTPException(status.HTTP_409_CONFLICT, "That film is already on your reel")

        src = ""
        if film.filename:
            src = f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/api/v1/media/files/{film.filename}"
        elif film.fallback_url:
            src = film.fallback_url
        if not src:
            raise HTTPException(status.HTTP_409_CONFLICT, "That film has no playable file")

        poster_url = ""
        if film.poster:
            poster_url = f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/api/v1/media/files/{film.poster}"

        row = Reel(
            id=uuid.uuid4().hex,
            user_id=user.id,
            author_name=_author_label(user),
            caption=caption or (film.prompt or "")[:CAPTION_MAX],
            source="film",
            film_id=film_id,
            source_url=src,
            # films keep their poster on the media route; store the absolute URL
            poster="",
        )
        db.add(row)
        await db.commit()
        out = _reel_out(row, mine=True)
        out["poster"] = poster_url  # film posters live under /media/files
        await record_usage(user.id, "reel", "film")
        return {"reel": out}

    if not url:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Pass a film_id or a url to share"
        )
    # Only accept media this deployment actually serves — no arbitrary hotlinks.
    base = settings.BACKEND_PUBLIC_URL.rstrip("/")
    if not (url.startswith(f"{base}/api/v1/media/files/") or url.startswith(f"{base}/api/v1/reels/files/")):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Only videos generated in Mood can be shared to the reel",
        )

    row = Reel(
        id=uuid.uuid4().hex,
        user_id=user.id,
        author_name=_author_label(user),
        caption=caption,
        source="chat",
        source_url=url,
    )
    db.add(row)
    await db.commit()
    await record_usage(user.id, "reel", "chat")
    return {"reel": _reel_out(row, mine=True)}


# ------------------------------------------------------------ engage/manage
@router.post("/{reel_id}/like")
async def toggle_like(
    reel_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """❤️ Idempotent like toggle — the (reel, user) PK makes double-taps safe."""
    r = await db.get(Reel, reel_id)
    if not r or r.status != "live":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reel not found")
    existing = await db.get(ReelLike, {"reel_id": reel_id, "user_id": user.id})
    if existing:
        await db.delete(existing)
        r.likes = max(0, (r.likes or 0) - 1)
        liked = False
    else:
        db.add(ReelLike(reel_id=reel_id, user_id=user.id))
        r.likes = (r.likes or 0) + 1
        liked = True
    await db.commit()
    return {"liked": liked, "likes": r.likes}


@router.post("/{reel_id}/save")
async def toggle_save(
    reel_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """🔖 Idempotent bookmark toggle — saves land in your private Saved tab.

    You can save your own reel: creators bookmark their own work as a shortlist,
    and blocking it would be a surprising rule with no upside.
    """
    r = await db.get(Reel, reel_id)
    if not r or r.status != "live":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reel not found")
    existing = await db.get(ReelSave, {"reel_id": reel_id, "user_id": user.id})
    if existing:
        await db.delete(existing)
        r.saves = max(0, (r.saves or 0) - 1)
        saved = False
    else:
        db.add(ReelSave(reel_id=reel_id, user_id=user.id))
        r.saves = (r.saves or 0) + 1
        saved = True
    await db.commit()
    return {"saved": saved, "saves": r.saves}


@router.post("/{reel_id}/share")
async def count_share(
    reel_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """🔗 Record that a viewer shared this reel, and hand back the link to copy.

    Unlike likes/saves this is a pure tally, not a per-user toggle: sharing the
    same reel twice really is two shares.
    """
    r = await db.get(Reel, reel_id)
    if not r or r.status != "live":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reel not found")
    await enforce_rate_limit(f"reelshr:{user.id}", 30 * plan_rate_mult(user.plan))
    r.shares = (r.shares or 0) + 1
    await db.commit()
    return {"shares": r.shares, "url": _reel_out(r)["url"]}


@router.get("/stats")
async def my_stats(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """📊 Totals across everything you've posted — the profile header numbers."""
    row = (
        await db.execute(
            select(
                func.count(Reel.id),
                func.coalesce(func.sum(Reel.views), 0),
                func.coalesce(func.sum(Reel.likes), 0),
                func.coalesce(func.sum(Reel.shares), 0),
                func.coalesce(func.sum(Reel.saves), 0),
            ).where(Reel.user_id == user.id)
        )
    ).one()
    live = int(
        await db.scalar(
            select(func.count(Reel.id)).where(Reel.user_id == user.id, Reel.status == "live")
        )
        or 0
    )
    saved_count = int(
        await db.scalar(select(func.count(ReelSave.reel_id)).where(ReelSave.user_id == user.id))
        or 0
    )
    return {
        "posts": int(row[0] or 0),
        "live": live,
        "views": int(row[1] or 0),
        "likes": int(row[2] or 0),
        "shares": int(row[3] or 0),
        "saves": int(row[4] or 0),
        "saved_by_me": saved_count,
    }


@router.post("/{reel_id}/view")
async def count_view(
    reel_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """👁 Bump the view counter (fire-and-forget from the player)."""
    r = await db.get(Reel, reel_id)
    if not r or r.status != "live":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reel not found")
    r.views = (r.views or 0) + 1
    await db.commit()
    return {"views": r.views}


@router.post("/{reel_id}/visibility")
async def set_visibility(
    reel_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Unpost (`{"live": false}`) or re-post your own reel."""
    r = await _own_reel(db, user, reel_id)
    r.status = "live" if bool(body.get("live", True)) else "hidden"
    await db.commit()
    return {"reel": _reel_out(r, mine=True)}


@router.delete("/{reel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reel(
    reel_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Delete your post — and its uploaded bytes (shares leave the original alone)."""
    r = await _own_reel(db, user, reel_id)
    for name in (r.filename, r.poster):
        if not name:
            continue
        if not (REEL_NAME_RE.match(name) or REEL_POSTER_RE.match(name)):
            continue  # never unlink anything outside the reel namespace
        try:
            os.remove(os.path.join(settings.MEDIA_DIR, name))
        except OSError:
            pass
    # Clear both join tables explicitly: SQLite doesn't enforce ON DELETE
    # CASCADE unless PRAGMA foreign_keys is on, so a deleted reel could
    # otherwise leave orphan likes/saves that break other users' Saved tabs.
    await db.execute(delete(ReelLike).where(ReelLike.reel_id == r.id))
    await db.execute(delete(ReelSave).where(ReelSave.reel_id == r.id))
    await db.delete(r)
    await db.commit()


# --------------------------------------------------------------------- file
@router.get("/files/{name}")
async def serve_reel_file(name: str):
    """Stream reel media. Public like /media/files so <video> tags and mobile
    players work without auth headers; names are 128-bit random hex."""
    if not (REEL_NAME_RE.match(name) or REEL_POSTER_RE.match(name)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    path = os.path.join(settings.MEDIA_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That reel is no longer available")
    media_type = "image/jpeg" if name.endswith("_rp.jpg") else "video/mp4"
    return FileResponse(path, media_type=media_type)
