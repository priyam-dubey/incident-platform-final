import uuid

from app.rate_limit import SlidingWindowLimiter
from app.security import (
    create_access_token, decode_access_token, generate_ingestion_key, hash_password,
    parse_ingestion_key, sha256_hex, verify_password,
)


def test_password_hash_roundtrip_and_not_plaintext():
    h = hash_password("correct-horse-9")
    assert "correct-horse" not in h and verify_password("correct-horse-9", h)
    assert not verify_password("wrong", h)


def test_access_token_roundtrip_and_tamper_and_expiry():
    uid = uuid.uuid4()
    tok = create_access_token(uid, "s" * 40, 60)
    assert decode_access_token(tok, "s" * 40) == uid
    assert decode_access_token(tok, "x" * 40) is None
    assert decode_access_token(create_access_token(uid, "s" * 40, -5), "s" * 40) is None
    assert decode_access_token("garbage", "s" * 40) is None


def test_ingestion_key_format_and_hash():
    full, prefix, h = generate_ingestion_key()
    assert full.startswith("ipk_") and parse_ingestion_key(full) == prefix
    assert h == sha256_hex(full) and prefix not in h
    assert parse_ingestion_key("nonsense") is None
    assert parse_ingestion_key("ipk_short_x") is None


def test_rate_limiter_window():
    t = [0.0]
    lim = SlidingWindowLimiter(2, 60, clock=lambda: t[0])
    assert lim.allow("a") and lim.allow("a") and not lim.allow("a")
    assert lim.allow("b")
    t[0] = 61
    assert lim.allow("a")
