"""
Bounded, per-service ring buffer of recent log and trace events.

The cluster engine tells us *which services* and *what time window* an
incident candidate spans, but the anomaly signal itself (a metric z-score)
isn't evidence a human or an LLM can read and understand - "error_rate was
4.2 standard deviations above baseline" doesn't explain *why*. This buffer
retains the raw log lines and trace spans emitted around the same time, so
when a cluster fires we can pull the actual "connection timeout after
30000ms" log line that the metric spike corresponds to.

Log message content is passed through `redaction.redact()` before being
buffered - this is the enforcement point for keeping secrets/PII out of
anything that could eventually reach an LLM (the reasoning service, Phase 4)
or a human reviewer (the dashboard, Phase 6). Redacting here rather than at
ingestion or in the reasoning service means the raw, unredacted form is
still available in ClickHouse for engineers with direct telemetry access,
while nothing downstream of this buffer ever sees it.

Bounded per service (not globally) so one noisy service can't crowd out
evidence retention for every other service in memory.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from redaction import redact

from incident_schemas import LogEvent, TraceSpanEvent


@dataclass(frozen=True)
class BufferedEvidence:
    source_type: str  # "log" | "trace"
    service_name: str
    snippet: str
    occurred_at: datetime
    trace_id: str | None
    # A stable reference the citation-validation step (Phase 4) can resolve
    # back to the durable ClickHouse record - not fabricated per-event here,
    # deliberately a placeholder key derived from content the ingestion
    # service can look up, since this in-memory buffer is not itself durable.
    source_ref: str


MAX_SNIPPET_LENGTH = 2000  # matches EvidenceItem.snippet's max_length in incident_schemas


class EvidenceBuffer:
    def __init__(self, retention: timedelta = timedelta(minutes=15), max_per_service: int = 500) -> None:
        self._retention = retention
        self._max_per_service = max_per_service
        self._by_service: dict[str, deque[BufferedEvidence]] = defaultdict(
            lambda: deque(maxlen=max_per_service)
        )

    def add_log(self, event: LogEvent) -> None:
        if event.severity.value not in {"warn", "error", "fatal"}:
            return  # info/debug/trace-level logs are rarely useful incident evidence and just add noise
        redaction_result = redact(event.message)
        snippet = redaction_result.text[:MAX_SNIPPET_LENGTH]
        self._by_service[event.service_name].append(
            BufferedEvidence(
                source_type="log",
                service_name=event.service_name,
                snippet=snippet,
                occurred_at=event.timestamp,
                trace_id=event.trace_id,
                source_ref=f"log:{event.service_name}:{event.timestamp.isoformat()}",
            )
        )

    def add_trace(self, event: TraceSpanEvent) -> None:
        if event.status != "error" and event.duration_ms < 1000:
            return  # only retain error spans or notably slow spans as evidence
        snippet = f"{event.operation_name} took {event.duration_ms:.0f}ms, status={event.status}"
        self._by_service[event.service_name].append(
            BufferedEvidence(
                source_type="trace",
                service_name=event.service_name,
                snippet=snippet[:MAX_SNIPPET_LENGTH],
                occurred_at=event.timestamp,
                trace_id=event.trace_id,
                source_ref=f"trace:{event.trace_id}:{event.span_id}",
            )
        )

    def trace_links_since(self, cutoff: datetime) -> dict[str, set[str]]:
        """trace_id -> set of service_names that trace touched, for the cluster engine."""
        links: dict[str, set[str]] = defaultdict(set)
        for service_name, buf in self._by_service.items():
            for item in buf:
                if item.trace_id and item.occurred_at >= cutoff:
                    links[item.trace_id].add(service_name)
        return dict(links)

    def evidence_for(
        self, service_name: str, window_start: datetime, window_end: datetime, limit: int = 20
    ) -> list[BufferedEvidence]:
        grace = timedelta(seconds=5)
        matches = [
            item
            for item in self._by_service.get(service_name, ())
            if window_start - grace <= item.occurred_at <= window_end + grace
        ]
        # Most recent first - if a service produced more evidence than the
        # limit, the freshest signal is the most likely to still be relevant.
        matches.sort(key=lambda i: i.occurred_at, reverse=True)
        return matches[:limit]

    def prune(self, now: datetime) -> None:
        cutoff = now - self._retention
        for service_name in list(self._by_service.keys()):
            buf = self._by_service[service_name]
            while buf and buf[0].occurred_at < cutoff:
                buf.popleft()
