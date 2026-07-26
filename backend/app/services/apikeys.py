"""🔑 Developer API keys — mint, hash, verify.

Threat model, stated plainly: the database stores only `sha256(secret)`. A
dump of the `api_keys` table therefore yields nothing usable, and the plaintext
key exists exactly once — in the HTTP response that created it.

Why plain SHA-256 rather than bcrypt/argon2 (which we DO use for passwords):
an API key is 32 bytes of `secrets.token_urlsafe` entropy, not a human-chosen
password, so it is not brute-forcible and there is nothing for a slow KDF to
protect. Fast hashing is also what lets us authenticate a key with a single
indexed lookup on every API request instead of a per-request KDF.
"""

from __future__ import annotations

import hashlib
import secrets

KEY_PREFIX = "mk_live_"
PREFIX_LABEL_LEN = 11  # "mk_live_" + 3 chars — enough to recognize, useless to an attacker

# Scopes gate what a key may call. Kept small and additive on purpose.
VALID_SCOPES = ("chat", "search", "images")
DEFAULT_SCOPES = "chat,search"


def generate_key() -> tuple[str, str, str]:
    """Mint a key. Returns (plaintext, prefix_label, sha256_hex).

    The plaintext is returned to the caller ONCE and never persisted.
    """
    secret = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return secret, secret[:PREFIX_LABEL_LEN], hash_key(secret)


def hash_key(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def looks_like_key(value: str | None) -> bool:
    """Cheap shape check so obviously-not-a-key bearer tokens (our JWTs) skip the
    database lookup entirely and fall through to normal JWT auth."""
    return bool(value) and value.startswith(KEY_PREFIX) and len(value) >= 24


def clean_scopes(raw: str | list[str] | None) -> str:
    """Normalize requested scopes to a sorted, deduped CSV of KNOWN scopes.

    Unknown scopes are dropped rather than rejected: a client asking for a scope
    a future version defines should get a working key with what exists today.
    An empty result falls back to DEFAULT_SCOPES so a key is never inert.
    """
    if isinstance(raw, str):
        parts = [p.strip().lower() for p in raw.split(",")]
    else:
        parts = [str(p).strip().lower() for p in (raw or [])]
    keep = sorted({p for p in parts if p in VALID_SCOPES})
    return ",".join(keep) if keep else DEFAULT_SCOPES


def has_scope(scopes: str | None, needed: str) -> bool:
    return needed in {s.strip() for s in (scopes or "").split(",") if s.strip()}
