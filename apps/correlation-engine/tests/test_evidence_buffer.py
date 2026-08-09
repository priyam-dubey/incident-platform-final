import uuid
from datetime import datetime, timezone

from app.evidence_buffer import EvidenceBuffer
from incident_schemas import LogEvent

WORKSPACE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
T0 = datetime(2026, 8, 5, 10, 0, 0, tzinfo=timezone.utc)


def _log(message: str, severity: str = "error") -> LogEvent:
    return LogEvent(
        workspace_id=WORKSPACE_ID,
        service_name="checkout-api",
        timestamp=T0.isoformat(),
        severity=severity,
        message=message,
    )


def test_secrets_in_log_messages_are_redacted_before_buffering() -> None:
    buffer = EvidenceBuffer()
    buffer.add_log(_log("auth failed for alice@company.com with api_key=sk_live_abcdef1234567890XYZ"))

    stored = buffer.evidence_for("checkout-api", T0, T0)
    assert len(stored) == 1
    assert "alice@company.com" not in stored[0].snippet
    assert "sk_live_abcdef1234567890XYZ" not in stored[0].snippet
    assert "[REDACTED:EMAIL]" in stored[0].snippet
    assert "[REDACTED:API_KEY]" in stored[0].snippet


def test_clean_log_messages_pass_through_unmodified() -> None:
    buffer = EvidenceBuffer()
    buffer.add_log(_log("connection pool exhausted after 30000ms"))

    stored = buffer.evidence_for("checkout-api", T0, T0)
    assert stored[0].snippet == "connection pool exhausted after 30000ms"
