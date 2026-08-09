"""
Prometheus metrics. Two kinds: generic HTTP metrics (via middleware, applies
to every route automatically) and domain-specific counters that matter more
than "how many requests" - here, that's events actually published to each
sink, since a healthy request count can coexist with a Kafka publish that's
silently failing for every event in the batch (see the partial-failure
behavior documented in the ingestion service README).
"""

from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds", "HTTP request duration", ["method", "path"]
)

EVENTS_INGESTED_TOTAL = Counter(
    "events_ingested_total", "Telemetry events accepted into the ingestion pipeline", ["kind"]
)
EVENTS_PUBLISH_FAILURES_TOTAL = Counter(
    "events_publish_failures_total", "Events that failed to publish to a sink", ["sink"]
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response: Response = await call_next(request)
        duration = time.perf_counter() - start

        # request.url.path, not the raw path with resolved path params, would
        # explode cardinality (one label series per unique incident id, etc.)
        # - the route template (request.scope["route"].path) is stable.
        route = request.scope.get("route")
        path_label = route.path if route is not None else request.url.path

        HTTP_REQUESTS_TOTAL.labels(request.method, path_label, response.status_code).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(request.method, path_label).observe(duration)
        return response


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
