import redis.asyncio as redis
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.security import decode_token
from ..db.models import User
from ..db.session import get_db

bearer = HTTPBearer()


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = decode_token(creds.credentials)
        uid = payload.get("sub")
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = await db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


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
