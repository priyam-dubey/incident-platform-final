"""Ingestion-time safety: drop sensitive attributes, redact secrets/PII in strings, bound sizes."""

from __future__ import annotations

from redaction import redact

SENSITIVE_KEY_PARTS = (
    "authorization", "cookie", "password", "passwd", "secret", "token", "api_key", "apikey",
    "set-cookie", "credit", "card", "cvv", "ssn", "x-api-key", "private_key",
)
MAX_ATTR_VALUE = 1024
MAX_ATTRS = 64


def is_sensitive_key(key: str) -> bool:
    k = key.lower()
    return any(p in k for p in SENSITIVE_KEY_PARTS)


def clean_text(value: str, limit: int, enabled: bool = True) -> str:
    if enabled:
        value = redact(value).text
    return value if len(value) <= limit else value[:limit] + "…[truncated]"


def clean_attributes(attrs: dict, enabled: bool = True) -> dict:
    out: dict = {}
    for k, v in list(attrs.items())[:MAX_ATTRS]:
        if is_sensitive_key(k):
            out[k] = "[REDACTED:KEY]"
        elif isinstance(v, str):
            out[k] = clean_text(v, MAX_ATTR_VALUE, enabled)
        else:
            out[k] = v
    return out
