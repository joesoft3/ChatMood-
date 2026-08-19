from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from ..config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# Floor so a mis-set ACCESS_TOKEN_EXPIRE_MINUTES=0 cannot mint already-expired
# tokens (that surfaces in chat as "Invalid or expired token" on every send).
_MIN_TTL_MINUTES = 15
# Clock skew between the API host and the client / a sibling machine.
_DECODE_LEEWAY_S = 60


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(subject: str) -> str:
    minutes = max(int(settings.ACCESS_TOKEN_EXPIRE_MINUTES or 0), _MIN_TTL_MINUTES)
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    # `exp` MUST be a numeric Unix timestamp. Passing a datetime can encode as
    # an ISO string on some python-jose versions, which then fails decode as
    # "invalid" on the very next request.
    return jwt.encode(
        {"sub": str(subject), "exp": int(expire.timestamp())},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALG,
    )


def decode_token(token: str) -> dict:
    """Raises jose.JWTError on invalid/expired tokens."""
    return jwt.decode(
        (token or "").strip(),
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALG],
        options={"leeway": _DECODE_LEEWAY_S},
    )
