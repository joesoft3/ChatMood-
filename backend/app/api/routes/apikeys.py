"""🔑 API key management (session-authenticated).

    GET    /keys           list your keys (never the secrets — they don't exist here)
    POST   /keys           mint a key; the plaintext is in THIS response and nowhere else
    DELETE /keys/{kid}     revoke

Revocation is a soft flag rather than a row delete: the key stops working
immediately, and the row survives so "who called us 40k times last month" stays
answerable after the key is turned off.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import ApiKey, User
from ...db.session import get_db
from ...services.apikeys import DEFAULT_SCOPES, VALID_SCOPES, clean_scopes, generate_key
from ..deps import get_current_user

router = APIRouter()


class KeyCreate(BaseModel):
    name: str = Field(default="API key", min_length=1, max_length=80)
    scopes: list[str] = Field(default_factory=lambda: DEFAULT_SCOPES.split(","))


def key_out(k: ApiKey) -> dict:
    return {
        "id": k.id,
        "name": k.name,
        "prefix": k.prefix,
        "scopes": [s for s in (k.scopes or "").split(",") if s],
        "calls": k.calls or 0,
        "revoked": bool(k.revoked),
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    }


def _require_enabled() -> None:
    if not settings.PUBLIC_API_ENABLED:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Public API is disabled on this deployment")


@router.get("")
async def list_keys(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    _require_enabled()
    rows = (
        await db.execute(
            select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
        )
    ).scalars().all()
    return {
        "keys": [key_out(k) for k in rows],
        "limit": settings.API_KEY_MAX_PER_USER,
        "valid_scopes": list(VALID_SCOPES),
        "base_url": f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/api/v1/public",
        "rate_per_min": settings.API_KEY_RATE_PER_MIN,
    }


@router.post("", status_code=201)
async def create_key(
    req: KeyCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    _require_enabled()
    active = int(
        (
            await db.scalar(
                select(func.count(ApiKey.id)).where(ApiKey.user_id == user.id, ApiKey.revoked.is_(False))
            )
        )
        or 0
    )
    if active >= settings.API_KEY_MAX_PER_USER:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"You already have {settings.API_KEY_MAX_PER_USER} active API keys — revoke one first.",
        )
    secret, prefix, key_hash = generate_key()
    row = ApiKey(
        user_id=user.id,
        name=req.name.strip(),
        prefix=prefix,
        key_hash=key_hash,
        scopes=clean_scopes(req.scopes),
    )
    db.add(row)
    await db.commit()
    # `key` appears exactly once, right here. There is no endpoint that can show
    # it again — only the hash was stored.
    return {**key_out(row), "key": secret, "warning": "Copy this key now — it will never be shown again."}


@router.delete("/{kid}")
async def revoke_key(kid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    _require_enabled()
    row = await db.get(ApiKey, kid)
    if not row or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    row.revoked = True
    await db.commit()
    return {"ok": True, "revoked": True}
