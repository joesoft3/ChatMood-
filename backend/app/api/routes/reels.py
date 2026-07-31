"""📺 Creator Reel — the shared public feed of creator videos.

Two ways in:
  • **Upload** — a creator posts their own clip (`POST /reels/upload`, multipart).
  • **Share**  — a creator posts something MoodAI already generated: a storyboard
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
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import Film, Reel, ReelLike, ReelSave, User
from ...db.session import get_db
from ...services import reel_premium as premium, reel_studio as studio, soundtrack
from ...services.editor import transcribe_srt
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
# Camera captures arrive as webm from MediaRecorder; audio adds are music beds
# or voiceovers recorded in-browser.
# Browsers disagree on audio MIME strings for the SAME file: Chrome reports
# .m4a as audio/x-m4a, Python's mimetypes says audio/mp4, Safari sends
# audio/aac. Accept every spelling or the picker rejects valid tracks.
REEL_AUDIO_MIMES = {
    "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/x-mpeg": "mp3",
    "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/m4a": "m4a", "audio/aac": "m4a",
    "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/vnd.wave": "wav",
    "audio/webm": "webm", "audio/ogg": "ogg", "audio/vorbis": "ogg", "audio/opus": "ogg",
    "audio/flac": "flac", "audio/x-flac": "flac",
}
REEL_MAX_BYTES = 100 * 1024 * 1024
REEL_AUDIO_MAX_BYTES = 25 * 1024 * 1024
# Draft assets staged in MEDIA_DIR before publish. `_ra` keeps them outside the
# reel-serving namespace so a half-finished edit is never publicly playable.
DRAFT_RE = re.compile(r"^[a-f0-9]{32}_ra\.(mp4|webm|mov|mp3|m4a|wav|ogg|flac)$")
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
        "reposts": r.reposts or 0,
        "parent_id": r.parent_id or "",
        "parent_author": r.parent_author or "",
        "effect": r.effect or "",
        "captioned": bool(r.captioned),
        "liked": liked,
        "saved": saved,
        "mine": mine,
        "status": r.status,
        "watermarked": bool(getattr(r, "watermarked", False)),
        # 🔴 Live broadcast surface. `live_playback_url` is viewer-safe; the
        # stream KEY is a write credential and is never serialized here.
        "kind": getattr(r, "kind", "clip") or "clip",
        "live_state": getattr(r, "live_state", "") or "",
        "live_playback_url": getattr(r, "live_playback_url", "") or "",
        "live_viewers": getattr(r, "live_viewers", 0) or 0,
        "live_peak_viewers": getattr(r, "live_peak_viewers", 0) or 0,
        "live_started_at": (
            r.live_started_at.isoformat() if getattr(r, "live_started_at", None) else None
        ),
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
        # 🔴 Live broadcasts float to the top of the main feed: a stream is only
        # watchable WHILE it runs, so burying it under newer clips wastes it.
        # Ordering (not filtering) keeps pagination stable — a stream that ends
        # mid-scroll simply falls back into chronological place.
        # `id` breaks ties deterministically: without it, posts sharing a
        # timestamp could shuffle between pages and the reader would skip or
        # re-see one.
        live_first = case((Reel.live_state == "live", 0), else_=1)
        q = q.order_by(live_first, Reel.created_at.desc(), Reel.id.desc())

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


# ------------------------------------------------------- studio helpers
async def _make_poster(path: str, uid: str) -> str:
    """Cover frame — best effort: a reel without a poster still plays fine."""
    try:
        ffbin = soundtrack.ffmpeg_path()
        if not ffbin:
            return ""
        got = await soundtrack.extract_poster(ffbin, path, settings.MEDIA_DIR, f"{uid}_r.mp4", 6.0)
        if got:
            # extract_poster writes <base>_p.jpg → move into the reel namespace
            src = os.path.join(settings.MEDIA_DIR, got)
            dst_name = f"{uid}_rp.jpg"
            os.replace(src, os.path.join(settings.MEDIA_DIR, dst_name))
            return dst_name
    except Exception:  # noqa: BLE001 — cover frames are cosmetic, never fatal
        log.info("reel poster extraction skipped", exc_info=True)
    return ""


async def _apply_effect(path: str, uid: str, effect: str, speed: float) -> str:
    """Burn a look/speed into the clip IN PLACE. Returns the effect actually
    applied ("" when it was skipped) — never raises: a failed grade must not
    cost the creator their upload."""
    if effect not in studio.EFFECTS:
        effect = "none"
    tmp = os.path.join(settings.MEDIA_DIR, f"{uid}_fx.mp4")
    try:
        studio.run(studio.build_effect_cmd(path, tmp, effect=effect, speed=speed))
        os.replace(tmp, path)
        return effect if effect != "none" else ""
    except Exception:  # noqa: BLE001
        log.info("reel effect skipped (%s)", effect, exc_info=True)
        _unlink(tmp)
        return ""


async def _apply_captions(path: str, uid: str, style: str) -> bool:
    """Auto-transcribe with Whisper and burn the captions in (fail-open).

    Reuses editor.transcribe_srt so there is exactly one transcription path in
    the codebase. Burning uses libass — this ffmpeg build has no `drawtext`.
    """
    work = Path(settings.MEDIA_DIR) / f"{uid}_cap"
    tmp = os.path.join(settings.MEDIA_DIR, f"{uid}_cp.mp4")
    try:
        work.mkdir(parents=True, exist_ok=True)
        srt = await transcribe_srt(Path(path), work)
        if not srt or not srt.exists() or not srt.read_text(encoding="utf-8").strip():
            return False
        studio.run(studio.build_caption_cmd(
            path, tmp, str(srt), style=style, fontsdir=settings.REEL_FONTS_DIR or None))
        os.replace(tmp, path)
        return True
    except Exception:  # noqa: BLE001
        log.info("reel captions skipped", exc_info=True)
        _unlink(tmp)
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _unlink(p: str) -> None:
    try:
        os.remove(p)
    except OSError:
        pass


# ------------------------------------------------------------------- upload
@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_reel(
    file: UploadFile = File(...),
    caption: str = Form(default="", max_length=CAPTION_MAX),
    effect: str = Form(default="none"),
    speed: float = Form(default=1.0),
    captions: bool = Form(default=False),
    caption_style: str = Form(default="clean"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """🎥 Post your own clip — optionally with an effect, speed change and
    auto-generated burned-in captions."""
    await enforce_rate_limit(f"reelup:{user.id}", 4 * plan_rate_mult(user.plan))

    mime = (file.content_type or "").lower()
    if mime not in REEL_MIMES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload an MP4, MOV or WebM video"
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That file is empty")
    # ⭐ Plan-aware ceiling — Pro posts longer/bigger clips.
    cap = premium.max_bytes(user)
    if len(raw) > cap:
        msg = f"Reels must be ≤ {cap // (1024 * 1024)} MB"
        if not premium.is_premium(user):
            msg += f" on the free plan — Pro raises it to {premium.PRO_MAX_MB} MB."
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, msg)
    # ⭐ Cinematic effects are a Pro perk — 402 tells the client to show the paywall.
    if not premium.effect_allowed(user, effect):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            premium.upgrade_message(f"The {effect.title()} effect"),
        )

    uid = uuid.uuid4().hex
    name = f"{uid}_r.mp4"
    os.makedirs(settings.MEDIA_DIR, exist_ok=True)
    path = os.path.join(settings.MEDIA_DIR, name)
    with open(path, "wb") as fh:
        fh.write(raw)

    # 🎬 Studio pass — effect/speed burn-in, then captions. Both fail OPEN: a
    # look that won't render must never cost the creator their upload.
    applied_effect, captioned = "", False
    if effect and effect != "none" or (speed and float(speed) != 1.0):
        applied_effect = await _apply_effect(path, uid, effect, float(speed or 1.0))
    if captions:
        captioned = await _apply_captions(path, uid, caption_style)

    # 🏷 Free tier: badge the posted clip. Same fail-open contract as the rest
    # of the studio pass — a badge failure never costs the creator their upload.
    stamped = False
    if premium.entitlements(user)["watermark"]:
        from ...services.watermark import apply_to_file

        stamped = await apply_to_file(Path(path), video=True)

    poster = await _make_poster(path, uid)

    row = Reel(
        id=uid,
        user_id=user.id,
        author_name=_author_label(user),
        caption=caption.strip()[:CAPTION_MAX],
        source="upload",
        filename=name,
        poster=poster,
        effect=applied_effect,
        captioned=captioned,
        watermarked=stamped,
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
    """♻️ Post a video MoodAI already made — a film, or an in-chat generation.

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
            "Only videos generated in MoodAI can be shared to the reel",
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


# ------------------------------------------------------------ 🎞 editor
@router.post("/assets", status_code=status.HTTP_201_CREATED)
async def upload_asset(
    file: UploadFile = File(...),
    kind: str = Form(default="video"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """📥 Stage one clip (camera capture or file) or audio track for the editor.

    Assets live in MEDIA_DIR under `_ra` names — deliberately OUTSIDE the reel
    serving pattern, so an unpublished draft can never be played from the feed.
    They're cleaned up when the edit is published or discarded.
    """
    await enforce_rate_limit(f"reelasset:{user.id}", 20 * plan_rate_mult(user.plan))
    mime = (file.content_type or "").split(";")[0].strip().lower()
    is_audio = kind == "audio"
    table = REEL_AUDIO_MIMES if is_audio else REEL_MIMES
    cap = REEL_AUDIO_MAX_BYTES if is_audio else REEL_MAX_BYTES
    if mime not in table:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Upload an MP3, M4A, WAV or OGG track" if is_audio
            else "Upload an MP4, MOV or WebM video",
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That file is empty")
    if len(raw) > cap:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Must be ≤ {cap // (1024 * 1024)} MB")

    ext = table[mime]
    aid = uuid.uuid4().hex
    name = f"{aid}_ra.{ext}"
    os.makedirs(settings.MEDIA_DIR, exist_ok=True)
    path = os.path.join(settings.MEDIA_DIR, name)
    with open(path, "wb") as fh:
        fh.write(raw)

    return {
        "asset": {
            "id": aid,
            "name": name,
            "kind": "audio" if is_audio else "video",
            "url": _media_url(name),
            "duration": studio.probe_duration(path),
            "has_audio": True if is_audio else studio.probe_has_audio(path),
        }
    }


def _asset_path(name: str) -> str:
    """Resolve a staged asset name to a path, refusing anything else.

    Never trust a client-supplied filename: without this an attacker could
    pass `../../etc/passwd` and have ffmpeg read it into a published video.
    """
    if not name or not DRAFT_RE.match(name):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown asset: {name}")
    path = os.path.join(settings.MEDIA_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That clip is no longer staged — re-add it")
    return path


@router.post("/publish", status_code=status.HTTP_201_CREATED)
async def publish_edit(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """🚀 Render the edited timeline and publish it as a reel.

    Body:
      clips:   [{name, start, end, effect, speed, volume}]  (1..MAX_CLIPS, ordered)
      audio:   {name, volume, start}          — optional bed ("+ audio")
      overlay: {name, corner, scale, volume}  — optional picture-in-picture
      caption, captions (bool), caption_style, original_volume
    """
    await enforce_rate_limit(f"reelpub:{user.id}", 3 * plan_rate_mult(user.plan))

    # Validate the timeline BEFORE checking the renderer: a malformed request
    # deserves "your overlay corner is wrong", not a misleading 503 that sends
    # the creator hunting for an outage that isn't there.
    raw_clips = body.get("clips") or []
    if not isinstance(raw_clips, list) or not raw_clips:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Add at least one clip")
    if len(raw_clips) > studio.MAX_CLIPS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"A reel can hold at most {studio.MAX_CLIPS} clips")

    clips: list[studio.Clip] = []
    for c in raw_clips:
        if not isinstance(c, dict):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "malformed clip")
        path = _asset_path(str(c.get("name") or ""))
        end = c.get("end")
        clips.append(studio.Clip(
            path=path,
            start=max(0.0, float(c.get("start") or 0.0)),
            end=float(end) if end not in (None, "") else None,
            effect=str(c.get("effect") or "none"),
            speed=float(c.get("speed") or 1.0),
            volume=float(c.get("volume") if c.get("volume") is not None else 1.0),
            has_audio=studio.probe_has_audio(path),
        ))

    total = sum(c.duration or studio.probe_duration(c.path) for c in clips)
    if total > studio.MAX_TOTAL_SECONDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"That edit is {int(total)}s — reels are capped at {studio.MAX_TOTAL_SECONDS}s",
        )

    bed = None
    if isinstance(body.get("audio"), dict) and body["audio"].get("name"):
        a = body["audio"]
        bed = studio.AudioBed(path=_asset_path(str(a["name"])),
                              volume=float(a.get("volume", 0.8)),
                              start=max(0.0, float(a.get("start") or 0.0)))

    ov = None
    if isinstance(body.get("overlay"), dict) and body["overlay"].get("name"):
        o = body["overlay"]
        opath = _asset_path(str(o["name"]))
        corner = str(o.get("corner") or "tr")
        if corner not in studio.OVERLAY_CORNERS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"corner must be one of {', '.join(studio.OVERLAY_CORNERS)}")
        ov = studio.Overlay(path=opath, corner=corner,
                            scale=float(o.get("scale", 0.3)),
                            volume=float(o.get("volume") or 0.0),
                            has_audio=studio.probe_has_audio(opath))

    # Everything the caller sent is valid — now we need the renderer.
    if not soundtrack.ffmpeg_path():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "The video renderer is unavailable on this host")

    uid = uuid.uuid4().hex
    name = f"{uid}_r.mp4"
    out_path = os.path.join(settings.MEDIA_DIR, name)
    try:
        studio.run(studio.build_timeline_cmd(
            clips, out_path, bed=bed, overlay=ov,
            original_volume=float(body.get("original_volume", 1.0)),
        ), timeout=600)
    except studio.StudioError as e:
        _unlink(out_path)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)[:200])

    captioned = False
    if bool(body.get("captions")):
        captioned = await _apply_captions(out_path, uid, str(body.get("caption_style") or "clean"))
    poster = await _make_poster(out_path, uid)

    # The edit is rendered — staged assets have served their purpose.
    for c in raw_clips:
        _unlink(os.path.join(settings.MEDIA_DIR, str(c.get("name") or "")))
    for key in ("audio", "overlay"):
        blob = body.get(key)
        if isinstance(blob, dict) and blob.get("name"):
            _unlink(os.path.join(settings.MEDIA_DIR, str(blob["name"])))

    row = Reel(
        id=uid,
        user_id=user.id,
        author_name=_author_label(user),
        caption=str(body.get("caption") or "").strip()[:CAPTION_MAX],
        source="upload",
        filename=name,
        poster=poster,
        effect=(clips[0].effect if clips[0].effect != "none" else ""),
        captioned=captioned,
    )
    db.add(row)
    await db.commit()
    await record_usage(user.id, "reel", "publish")
    return {"reel": _reel_out(row, mine=True)}


@router.delete("/assets/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_asset(name: str, user: User = Depends(get_current_user)):
    """🗑 Drop a staged asset when the creator removes it from the timeline."""
    if not DRAFT_RE.match(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    _unlink(os.path.join(settings.MEDIA_DIR, name))


# --------------------------------------------------------------------- duet
@router.get("/effects")
async def list_effects(user: User = Depends(get_current_user)):
    """🎨 Effect catalog — the studio renders its chips straight from this, and
    each entry carries the CSS equivalent so the live preview matches the burn."""
    return {
        "effects": studio.effect_catalog(),
        "speeds": studio.SPEEDS,
        "caption_styles": sorted(studio.CAPTION_STYLES),
        "duet_layouts": list(studio.DUET_LAYOUTS),
    }


@router.post("/{reel_id}/duet", status_code=status.HTTP_201_CREATED)
async def create_duet(
    reel_id: str,
    file: UploadFile = File(...),
    caption: str = Form(default="", max_length=CAPTION_MAX),
    layout: str = Form(default="side"),
    audio: str = Form(default="both"),
    effect: str = Form(default="none"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """🎭 Duet — your clip stacked with theirs in one 1080x1920 frame.

    The original stays untouched; the duet is a NEW reel that credits it via
    `parent_id` / `parent_author`, so the first creator keeps attribution.
    """
    await enforce_rate_limit(f"reelduet:{user.id}", 3 * plan_rate_mult(user.plan))
    if layout not in studio.DUET_LAYOUTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"layout must be one of {', '.join(studio.DUET_LAYOUTS)}")
    if audio not in ("both", "mine", "theirs"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "audio must be both, mine or theirs")

    parent = await db.get(Reel, reel_id)
    if not parent or parent.status != "live":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reel not found")
    # A duet needs the other side's actual bytes on this host. Shared/hotlinked
    # reels (film or chat sources) have no local file to stack against.
    if not parent.filename or not REEL_NAME_RE.match(parent.filename):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "That reel can't be dueted — it isn't a local upload")
    theirs = os.path.join(settings.MEDIA_DIR, parent.filename)
    if not os.path.exists(theirs):
        raise HTTPException(status.HTTP_409_CONFLICT, "The original video is no longer available")

    mime = (file.content_type or "").lower()
    if mime not in REEL_MIMES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            "Upload an MP4, MOV or WebM video")
    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That file is empty")
    if len(raw) > REEL_MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Reels must be ≤ {REEL_MAX_BYTES // (1024 * 1024)} MB")

    if not soundtrack.ffmpeg_path():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Duets need the video renderer, which is unavailable on this host")

    uid = uuid.uuid4().hex
    name = f"{uid}_r.mp4"
    os.makedirs(settings.MEDIA_DIR, exist_ok=True)
    mine_path = os.path.join(settings.MEDIA_DIR, f"{uid}_duetsrc.mp4")
    out_path = os.path.join(settings.MEDIA_DIR, name)
    with open(mine_path, "wb") as fh:
        fh.write(raw)
    try:
        # Probe both sides: referencing an audio stream that doesn't exist
        # fails the whole filtergraph, so a silent clip must degrade instead.
        studio.run(studio.build_duet_cmd(
            mine_path, theirs, out_path, layout=layout, audio=audio,
            mine_has_audio=studio.probe_has_audio(mine_path),
            theirs_has_audio=studio.probe_has_audio(theirs),
        ))
    except studio.StudioError as e:
        _unlink(mine_path)
        _unlink(out_path)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)[:200])
    finally:
        _unlink(mine_path)

    applied_effect = ""
    if effect and effect != "none":
        applied_effect = await _apply_effect(out_path, uid, effect, 1.0)
    poster = await _make_poster(out_path, uid)

    row = Reel(
        id=uid,
        user_id=user.id,
        author_name=_author_label(user),
        caption=caption.strip()[:CAPTION_MAX] or f"Duet with @{parent.author_name}",
        source="duet",
        filename=name,
        poster=poster,
        parent_id=parent.id,
        parent_author=parent.author_name,
        effect=applied_effect,
    )
    db.add(row)
    await db.commit()
    await record_usage(user.id, "reel", "duet")
    return {"reel": _reel_out(row, mine=True)}


@router.post("/{reel_id}/repost", status_code=status.HTTP_201_CREATED)
async def repost(
    reel_id: str,
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """🔁 Repost — surface someone else's reel on your own profile.

    No bytes are copied: the new row points at the same media and credits the
    original author. Reposting your own reel, or the same reel twice, is a
    conflict rather than a silent duplicate.
    """
    await enforce_rate_limit(f"reelrepost:{user.id}", 10 * plan_rate_mult(user.plan))
    src = await db.get(Reel, reel_id)
    if not src or src.status != "live":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reel not found")
    if src.user_id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "That's already your reel — no need to repost it")
    # The original of a repost is always the ROOT reel, so a chain of reposts
    # credits the true author instead of the last person who reposted.
    root_id = src.parent_id if src.source == "repost" and src.parent_id else src.id
    root = await db.get(Reel, root_id) if root_id != src.id else src
    if not root:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The original reel is gone")

    dupe = await db.scalar(
        select(Reel.id).where(
            Reel.user_id == user.id, Reel.parent_id == root.id,
            Reel.source == "repost", Reel.status == "live",
        )
    )
    if dupe:
        raise HTTPException(status.HTTP_409_CONFLICT, "You already reposted that reel")

    caption = str((body or {}).get("caption") or "").strip()[:CAPTION_MAX]
    row = Reel(
        id=uuid.uuid4().hex,
        user_id=user.id,
        author_name=_author_label(user),
        caption=caption or root.caption,
        source="repost",
        filename=root.filename,          # same media, no copy
        source_url=root.source_url,
        poster=root.poster,
        parent_id=root.id,
        parent_author=root.author_name,
        effect=root.effect,
    )
    root.reposts = (root.reposts or 0) + 1
    db.add(row)
    await db.commit()
    await record_usage(user.id, "reel", "repost")
    return {"reel": _reel_out(row, mine=True), "reposts": root.reposts}


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

    # 🔁 Reposts share the ORIGINAL's media file. Deleting a repost must never
    # unlink bytes another row still plays, and deleting an original that has
    # live reposts must not leave them pointing at a missing file — so only
    # unlink when no other reel references the same filename.
    others = 0
    if r.filename:
        others = int(await db.scalar(
            select(func.count(Reel.id)).where(
                Reel.filename == r.filename, Reel.id != r.id)
        ) or 0)
    if others:
        log.info("reel %s deleted but %d row(s) still use %s — keeping the file",
                 r.id, others, r.filename)
    else:
        for name in (r.filename, r.poster):
            if not name:
                continue
            if not (REEL_NAME_RE.match(name) or REEL_POSTER_RE.match(name)):
                continue  # never unlink anything outside the reel namespace
            try:
                os.remove(os.path.join(settings.MEDIA_DIR, name))
            except OSError:
                pass

    # An original going away shouldn't leave dangling "duet with @x" credits.
    if r.parent_id:
        parent = await db.get(Reel, r.parent_id)
        if parent and r.source == "repost":
            parent.reposts = max(0, (parent.reposts or 0) - 1)
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
    players work without auth headers; names are 128-bit random hex.

    Staged editor assets (`_ra`) are served too — the editor has to play back
    what you just recorded before you publish it. They stay out of the feed
    because nothing links to them: no Reel row ever references an `_ra` name.
    """
    is_draft = bool(DRAFT_RE.match(name))
    if not (REEL_NAME_RE.match(name) or REEL_POSTER_RE.match(name) or is_draft):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    path = os.path.join(settings.MEDIA_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That reel is no longer available")
    if name.endswith("_rp.jpg"):
        media_type = "image/jpeg"
    elif is_draft:
        ext = name.rsplit(".", 1)[-1]
        media_type = {
            "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
            "mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav", "ogg": "audio/ogg",
        }.get(ext, "application/octet-stream")
    else:
        media_type = "video/mp4"
    return FileResponse(path, media_type=media_type)


# ═══════════════════════════════════════════════════ ⭐ premium · 🔴 Go Live

@router.get("/premium")
async def reel_premium_status(user: User = Depends(get_current_user)):
    """Everything the Reel UI needs to draw locks, caps and the paywall.

    The UI renders its padlocks straight from this, so a lock can never claim
    something the server doesn't actually enforce.
    """
    return {
        **premium.entitlements(user),
        "live_providers": premium.live_providers(),
        "upgrade_path": "/upgrade",
    }


@router.post("/live/start", status_code=status.HTTP_201_CREATED)
async def start_live(
    caption: str = Form(default="", max_length=CAPTION_MAX),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """🔴 Go Live (Pro) — provision a broadcast and put it at the top of the feed.

    The broadcast IS a reel row (`kind="live"`), so when it ends it becomes a
    normal replay and viewers keep the post they were watching.

    The ingest URL + stream key are returned ONCE, to the owner only: the key is
    a write credential, and anyone holding it could broadcast as this creator.
    """
    if not premium.is_premium(user):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED, premium.upgrade_message("Go Live")
        )
    await enforce_rate_limit(f"reellive:{user.id}", 4 * plan_rate_mult(user.plan))

    # One broadcast at a time — a second stream would bill twice and split the
    # audience across two cards in the feed.
    existing = (
        await db.execute(
            select(Reel).where(
                Reel.user_id == user.id, Reel.kind == "live", Reel.live_state == "live"
            ).limit(1)
        )
    ).scalars().first()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You're already live — end that broadcast before starting another.",
        )

    from ...services.live_stream import LiveNotConfigured, LiveProviderError, create_stream

    try:
        target = await create_stream(room_hint=f"reel-{user.id[:8]}")
    except LiveNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    except LiveProviderError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    row = Reel(
        id=uuid.uuid4().hex,
        user_id=user.id,
        author_name=_author_label(user),
        caption=caption.strip()[:CAPTION_MAX],
        source="live",
        kind="live",
        live_state="live",
        live_provider=target.provider,
        live_stream_id=target.stream_id,
        live_playback_url=target.playback_url,
        live_started_at=datetime.now(timezone.utc),
        status="live",
    )
    db.add(row)
    await db.commit()
    await record_usage(user.id, "reel_live", target.provider)
    # `as_owner_dict()` carries the stream key — this response, and only this
    # response, is allowed to include it.
    return {"reel": _reel_out(row, mine=True), "stream": target.as_owner_dict()}


@router.post("/live/{reel_id}/end")
async def end_live(
    reel_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Stop broadcasting. The post stays in the feed as a replay."""
    row = await db.get(Reel, reel_id)
    if not row or row.user_id != user.id or row.kind != "live":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live broadcast not found")
    if row.live_state != "live":
        return {"reel": _reel_out(row, mine=True), "already": True}

    from ...services.live_stream import destroy_stream

    await destroy_stream(row.live_provider, row.live_stream_id)
    row.live_state = "ended"
    row.live_ended_at = datetime.now(timezone.utc)
    row.live_viewers = 0  # nobody is watching a finished stream
    await db.commit()
    return {"reel": _reel_out(row, mine=True)}


@router.post("/live/{reel_id}/heartbeat")
async def live_heartbeat(
    reel_id: str,
    joining: bool = Form(default=True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Concurrent-viewer ping. Clamped at zero and tracks the peak.

    Deliberately a simple counter rather than presence tracking: an exact
    concurrent count needs sticky sessions the deployment doesn't have, and a
    live badge that's off by one is fine — one stuck at -3 is not.
    """
    row = await db.get(Reel, reel_id)
    if not row or row.kind != "live":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live broadcast not found")
    if row.live_state != "live":
        return {"viewers": 0, "live": False}
    row.live_viewers = max(0, (row.live_viewers or 0) + (1 if joining else -1))
    row.live_peak_viewers = max(row.live_peak_viewers or 0, row.live_viewers)
    await db.commit()
    return {"viewers": row.live_viewers, "peak": row.live_peak_viewers, "live": True}
