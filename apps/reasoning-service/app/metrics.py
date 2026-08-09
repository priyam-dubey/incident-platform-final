"""Prometheus metrics for the reasoning service. Same pattern as the other
services - see apps/ingestion-service/app/metrics.py. The retry counter is
the single most operationally important metric this service exposes: a
rising hallucination-retry rate is the earliest signal that a prompt or
model change has degraded citation grounding, well before it would show up
in human verdict data (which lags by however long incidents take to review).
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from starlette.responses import Response

HYPOTHESES_ACCEPTED_TOTAL = Counter(
    "hypotheses_accepted_total", "Hypotheses that passed citation validation"
)
HYPOTHESES_REJECTED_TOTAL = Counter(
    "hypotheses_rejected_total", "Hypotheses rejected for citing fabricated evidence"
)
CANDIDATES_WITH_NO_VALID_HYPOTHESIS_TOTAL = Counter(
    "candidates_with_no_valid_hypothesis_total",
    "Incident candidates where every hypothesis failed citation validation after retries",
)


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
