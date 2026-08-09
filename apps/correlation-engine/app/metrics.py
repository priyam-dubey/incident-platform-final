"""Prometheus metrics for the correlation engine. Same pattern as the
ingestion service's app/metrics.py - see that file's docstring for the
rationale. Domain counters here track the pipeline's actual job (anomalies
detected, candidates emitted) rather than just HTTP traffic, since this
service's real work happens in the Kafka consume/tick loop, not its (mostly
health-check-only) HTTP surface.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from starlette.responses import Response

ANOMALIES_DETECTED_TOTAL = Counter(
    "anomalies_detected_total", "Anomalies detected by the anomaly detector", ["service_name"]
)
INCIDENT_CANDIDATES_EMITTED_TOTAL = Counter(
    "incident_candidates_emitted_total", "Incident candidates emitted after clustering"
)


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
