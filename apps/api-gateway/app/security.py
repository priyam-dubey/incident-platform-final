"""Password hashing, JWT access tokens, opaque refresh tokens, ingestion keys."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()
ALGORITHM = "HS256"
KEY_PREFIX_LABEL = "ipk"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_opaque_token() -> tuple[str, str]:
    """Returns (raw_token, sha256_hash). Only the hash is persisted."""
    raw = secrets.token_urlsafe(48)
    return raw, sha256_hex(raw)


def create_access_token(user_id: uuid.UUID, secret: str, ttl_seconds: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + ttl_seconds, "typ": "access"},
        secret, algorithm=ALGORITHM,
    )


def decode_access_token(token: str, secret: str) -> uuid.UUID | None:
    try:
        claims = jwt.decode(token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None
    if claims.get("typ") != "access":
        return None
    try:
        return uuid.UUID(claims["sub"])
    except ValueError:
        return None


def generate_ingestion_key() -> tuple[str, str, str]:
    """Returns (full_key, prefix, sha256_hash). The full key is shown once, never stored."""
    prefix = secrets.token_hex(5)
    secret = secrets.token_urlsafe(32)
    full = f"{KEY_PREFIX_LABEL}_{prefix}_{secret}"
    return full, prefix, sha256_hex(full)


def parse_ingestion_key(key: str) -> str | None:
    """Extract the lookup prefix from a presented key, or None if malformed."""
    parts = key.split("_", 2)
    if len(parts) != 3 or parts[0] != KEY_PREFIX_LABEL or len(parts[1]) != 10 or not parts[2]:
        return None
    return parts[1]


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
