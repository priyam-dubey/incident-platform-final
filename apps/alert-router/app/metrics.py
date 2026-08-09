"""Prometheus metrics for the alert router. Same pattern as the other
services. The verdict counter is the one that ultimately closes the loop
described throughout this platform: it's a direct measure of how often
humans agree with the AI, split by verdict, which is the leading indicator
long before a full offline eval run aggregates the same eval_examples data.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
VERDICTS_SUBMITTED_TOTAL = Counter(
    "verdicts_submitted_total", "Human verdicts submitted on AI hypotheses", ["verdict"]
)
ALERTS_DISPATCHED_TOTAL = Counter(
    "alerts_dispatched_total", "Alert dispatch attempts by channel and outcome", ["channel", "outcome"]
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        route = request.scope.get("route")
        path_label = route.path if route is not None else request.url.path
        HTTP_REQUESTS_TOTAL.labels(request.method, path_label, response.status_code).inc()
        return response


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
