"""
Orchestrates the deterministic correlation pipeline end to end.

Deliberately tick-based (batch-process everything accumulated since the last
tick, on a fixed interval) rather than emitting a candidate immediately on
every single new anomaly. A per-event emission strategy would either flap
(re-emitting a growing cluster as each new service joins it within the same
real incident) or require nontrivial debouncing/dedup logic to avoid that.
Ticking every `correlation_window_seconds` means a cluster is built once,
from the complete picture of everything anomalous in that window - simpler,
and matches how the windowed-aggregation pattern is described in the overall
platform architecture.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from incident_schemas import IncidentCandidate, LogEvent, MetricEvent, TraceSpanEvent

from app.anomaly_detector import AnomalyDetector, AnomalyResult
from app.candidate_builder import build_incident_candidate
from app.cluster_engine import ClusterEngine
from app.evidence_buffer import EvidenceBuffer
from app.incident_writer import IncidentCandidateSink
from app.service_registry import ServiceRegistry

logger = logging.getLogger(__name__)


class CorrelationPipeline:
    def __init__(
        self,
        anomaly_detector: AnomalyDetector,
        cluster_engine: ClusterEngine,
        evidence_buffer: EvidenceBuffer,
        service_registry: ServiceRegistry,
        candidate_sink: IncidentCandidateSink,
        correlation_window_seconds: float,
    ) -> None:
        self._anomaly_detector = anomaly_detector
        self._cluster_engine = cluster_engine
        self._evidence_buffer = evidence_buffer
        self._service_registry = service_registry
        self._candidate_sink = candidate_sink
        self._window = timedelta(seconds=correlation_window_seconds)

        # workspace_id -> anomalies observed since the last successful tick
        self._pending: dict[uuid.UUID, list[AnomalyResult]] = defaultdict(list)

    async def handle_log_event(self, event: LogEvent) -> None:
        self._evidence_buffer.add_log(event)

    async def handle_trace_event(self, event: TraceSpanEvent) -> None:
        self._evidence_buffer.add_trace(event)

    async def handle_metric_event(self, event: MetricEvent) -> None:
        anomaly = self._anomaly_detector.observe(
            event.service_name, event.metric_name, event.value, event.timestamp
        )
        if anomaly is not None:
            self._pending[event.workspace_id].append(anomaly)
            logger.info(
                "anomaly_detected",
                extra={
                    "workspace_id": str(event.workspace_id),
                    "service_name": anomaly.service_name,
                    "metric_name": anomaly.metric_name,
                    "zscore": anomaly.zscore,
                },
            )

    async def tick(self, now: datetime) -> list[IncidentCandidate]:
        emitted: list[IncidentCandidate] = []

        for workspace_id, anomalies in list(self._pending.items()):
            if not anomalies:
                continue

            trace_links = self._evidence_buffer.trace_links_since(now - self._window)
            clusters = self._cluster_engine.cluster(anomalies, trace_links=trace_links)

            for cluster in clusters:
                service_ids = {
                    name: await self._service_registry.resolve(workspace_id, name)
                    for name in cluster.service_names
                }
                candidate = build_incident_candidate(
                    workspace_id=workspace_id,
                    cluster=cluster,
                    evidence_buffer=self._evidence_buffer,
                    service_ids=service_ids,
                    detected_at=now,
                )
                await self._candidate_sink.publish(candidate)
                emitted.append(candidate)

            self._pending[workspace_id] = []

        self._evidence_buffer.prune(now)
        return emitted
