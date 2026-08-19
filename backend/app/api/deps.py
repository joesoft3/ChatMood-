from datetime import datetime, timezone

import redis.asyncio as redis
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.security import decode_token
from ..db.models import ApiKey, User
from ..db.session import get_db

# auto_error=False so a missing header is 401 (not FastAPI's default 403
# "Not authenticated") — same status the clients already treat as "sign in".
bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None or not (creds.credentials or "").strip():
        raise _unauthorized("Not authenticated")
    try:
        payload = decode_token(creds.credentials)
        uid = payload.get("sub")
    except JWTError:
        raise _unauthorized("Invalid or expired token")
    user = await db.get(User, str(uid)) if uid else None
    if not user:
        raise _unauthorized("User not found")
    return user


async def resolve_api_key(db: AsyncSession, secret: str) -> tuple[User, ApiKey] | None:
    """Authenticate an `mk_live_…` secret → (user, key), or None if it isn't valid.

    Lookup is a single indexed hit on the stored SHA-256 (see services/apikeys.py
    for why a fast hash is the right call for high-entropy keys). Usage counters
    are bumped in a separate UPDATE that deliberately does NOT block the request:
    a stats write failing must never cost a caller their API call.
    """
    from ..services.apikeys import hash_key, looks_like_key

    if not looks_like_key(secret):
        return None
    row = await db.scalar(
        select(ApiKey).where(ApiKey.key_hash == hash_key(secret), ApiKey.revoked.is_(False))
    )
    if not row:
        return None
    user = await db.get(User, row.user_id)
    if not user:
        return None
    try:
        await db.execute(
            update(ApiKey)
            .where(ApiKey.id == row.id)
            .values(calls=ApiKey.calls + 1, last_used_at=datetime.now(timezone.utc))
        )
        await db.commit()
    except Exception:
        await db.rollback()  # stats are best-effort; the call itself still stands
    return user, row


async def get_api_caller(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, ApiKey]:
    """Auth for the public developer API (/api/v1/public/*) — API keys ONLY.

    Session JWTs are rejected here on purpose: browser tokens live in
    localStorage and are handed to far more code than a deliberately-minted,
    revocable, scoped key. Keeping the surfaces separate means revoking a key
    actually revokes that integration's access.
    """
    if not settings.PUBLIC_API_ENABLED:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Public API is disabled on this deployment")
    secret = (creds.credentials if creds else "") or ""
    resolved = await resolve_api_key(db, secret)
    if not resolved:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or revoked API key — create one in Settings → API keys.",
        )
    return resolved


def require_scope(key: ApiKey, scope: str) -> None:
    from ..services.apikeys import has_scope

    if not has_scope(key.scopes, scope):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"This API key lacks the '{scope}' scope (it has: {key.scopes or 'none'}).",
        )


def is_effective_admin(user: User) -> bool:
    """DB flag OR owner email listed in ADMIN_EMAILS env."""
    return bool(user.is_admin or user.email.lower() in settings.admin_email_set)


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not is_effective_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


_redis: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


_RL_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local cur = redis.call('INCR', key)
if cur == 1 then
    redis.call('EXPIRE', key, ttl)
end
if cur > limit then
    return 0
end
return 1
"""
_rl_script = None


async def enforce_rate_limit(bucket: str, per_minute: int) -> None:
    """Atomic per-user token bucket (Lua script — no race between INCR & EXPIRE).

    Fails open if Redis is unavailable so a down cache never blocks real users.
    """
    global _rl_script
    try:
        r = await get_redis()
        if _rl_script is None:
            _rl_script = r.register_script(_RL_LUA)
        allowed = await _rl_script(keys=[f"rl:{bucket}"], args=[per_minute, 60])
        if not int(allowed):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded — slow down.")
    except HTTPException:
        raise
    except Exception:
        pass  # fail-open
