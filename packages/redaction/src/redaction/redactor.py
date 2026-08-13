"""
Redacts secrets and PII from telemetry snippets before they can reach the
reasoning service. This runs in the correlation engine's evidence buffer -
the boundary where raw log/trace content is about to become "evidence" a
model will read - not at ingestion (where the raw form is still needed for
ClickHouse's durable telemetry record) and not in the reasoning service
(too late; by then the string has already been assembled into a prompt).

Deliberately regex-based rather than an ML/NER-based redactor: for the
specific, structurally-recognizable categories below (API keys, JWTs, emails,
credit card numbers, IPv4 addresses, AWS-style access keys), pattern
matching is both fast enough to run on every buffered log line and precise
enough - the risk profile of an NER model (probabilistic, occasionally
misses an entity, needs its own eval suite) is worse than a slightly
over-eager regex for this specific job. This is not a claim that regex
redaction catches every possible secret shape; it is a documented,
narrow set of high-confidence, high-frequency patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    # Generic bearer/API-key-shaped tokens: a labeled prefix followed by a
    # long opaque alphanumeric string - covers "api_key=...", "token: ...",
    # "Bearer ...", "Authorization: ..." across most REST/log conventions.
    "api_key": re.compile(
        r"(?i)\b(api[_-]?key|token|secret|bearer|authorization)\b\s*[:=]?\s*['\"]?"
        r"([A-Za-z0-9_\-\.]{20,})['\"]?"
    ),
    "aws_access_key": re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    # Credit card numbers: either grouped with separators (the overwhelmingly
    # common way humans and systems format/log them, e.g. "4111-1111-1111-1111"
    # or "4111 1111 1111 1111"), or exactly 16 continuous digits (the
    # standard unformatted card-number length). Deliberately NOT "13-19
    # continuous digits with no separator required" - that shape collides
    # constantly with epoch millisecond timestamps (13 digits), some trace/
    # request ids, and other ordinary numeric telemetry, which would make
    # every log line containing a timestamp get needlessly mangled.
    "credit_card": re.compile(r"\b\d{3,4}(?:[ -]\d{3,4}){3,}\b|\b\d{16}\b"),
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "phone": re.compile(r"\b(?:\+?\d{1,2}[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b"),
}

# ipv4 and phone are opt-in (see redact()'s `categories` param): internal
# service IPs (10.0.x.x, 127.0.0.1, container addresses) appear constantly
# in legitimate, non-sensitive infrastructure logs, and redacting every IP
# by default would gut the evidence's usefulness for exactly the kind of
# "which service talked to which" reasoning the platform exists to support.
# Phone-number-shaped strings collide heavily with order ids, ports, and
# other numeric telemetry. Both are available for callers with a specific
# compliance need, but neither is in the default set.
DEFAULT_CATEGORIES = frozenset({"email", "api_key", "aws_access_key", "jwt", "credit_card"})


@dataclass(frozen=True)
class RedactionResult:
    text: str
    redacted_categories: list[str]

    @property
    def was_modified(self) -> bool:
        return len(self.redacted_categories) > 0


def redact(text: str, categories: frozenset[str] = DEFAULT_CATEGORIES) -> RedactionResult:
    result = text
    hit_categories: list[str] = []

    for category in categories:
        pattern = _PATTERNS.get(category)
        if pattern is None:
            raise ValueError(f"unknown redaction category: {category!r}")

        def _replace(match: re.Match[str], cat: str = category) -> str:
            return f"[REDACTED:{cat.upper()}]"

        new_result, count = pattern.subn(_replace, result)
        if count > 0:
            hit_categories.append(category)
            result = new_result

    return RedactionResult(text=result, redacted_categories=hit_categories)
