"""
The final step of the deterministic pipeline: turn an AnomalyCluster (a
correlation-engine-internal concept) into an `IncidentCandidate` (the shared,
schema-validated contract defined in packages/schemas, the object that
crosses into the reasoning service). This is the enforcement point for
"the model never sees raw telemetry, only bounded evidence" - anything not
captured in the returned IncidentCandidate simply does not exist as far as
the reasoning service (Phase 4) is concerned.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from incident_schemas import EvidenceItem, IncidentCandidate, IncidentSeverity, ServiceAnomaly

from app.cluster_engine import AnomalyCluster
from app.evidence_buffer import EvidenceBuffer

MAX_EVIDENCE_PER_INCIDENT = 200
MAX_EVIDENCE_PER_SERVICE = 20


def _severity_for_score(max_score: float) -> IncidentSeverity:
    # Thresholds chosen so that "just barely anomalous" (score near the
    # detector's own trigger threshold, typically ~3.0) reads as low/medium
    # rather than immediately critical - severity should escalate with how
    # far past the trigger point the anomaly actually is.
    if max_score >= 10.0:
        return IncidentSeverity.critical
    if max_score >= 6.0:
        return IncidentSeverity.high
    if max_score >= 4.0:
        return IncidentSeverity.medium
    return IncidentSeverity.low


def build_incident_candidate(
    workspace_id: uuid.UUID,
    cluster: AnomalyCluster,
    evidence_buffer: EvidenceBuffer,
    service_ids: dict[str, uuid.UUID],
    detected_at,
) -> IncidentCandidate:
    """
    `service_ids` maps service_name -> the Postgres services.id UUID that
    name resolves to. Resolving this mapping is the caller's responsibility
    (it requires a DB lookup / cache) so this function stays pure and testable.
    """
    affected_services = [
        ServiceAnomaly(
            service_id=service_ids[a.service_name],
            service_name=a.service_name,
            anomaly_score=a.anomaly_score,
            metric_name=a.metric_name,
            observed_value=a.observed_value,
            baseline_mean=a.baseline_mean,
            baseline_stddev=a.baseline_stddev,
        )
        for a in cluster.anomalies
    ]

    evidence: list[EvidenceItem] = []
    window_start, window_end = cluster.window_start, cluster.window_end

    for service_name in cluster.service_names:
        buffered = evidence_buffer.evidence_for(
            service_name, window_start, window_end, limit=MAX_EVIDENCE_PER_SERVICE
        )
        for item in buffered:
            if len(evidence) >= MAX_EVIDENCE_PER_INCIDENT:
                break
            evidence.append(
                EvidenceItem(
                    id=uuid.uuid4(),
                    source_type=item.source_type,
                    source_ref=item.source_ref,
                    service_name=item.service_name,
                    snippet=item.snippet,
                    # Evidence directly tied to a service in the cluster starts
                    # at high relevance; a real relevance model (e.g. weighting
                    # by proximity to the anomaly's exact timestamp) is a
                    # documented future improvement, not implemented here to
                    # avoid a second undertested heuristic layered on the first.
                    relevance_score=0.75,
                    occurred_at=item.occurred_at,
                )
            )

    if not evidence:
        # IncidentCandidate requires at least one evidence item (schema
        # constraint) - if the anomaly fired but no log/trace evidence was
        # buffered for it (e.g. a metric-only anomaly with no correlated
        # error logs), synthesize a minimal evidence item from the anomaly
        # itself rather than silently dropping a real incident candidate.
        anomaly = max(cluster.anomalies, key=lambda a: a.anomaly_score)
        evidence.append(
            EvidenceItem(
                id=uuid.uuid4(),
                source_type="metric",
                source_ref=f"metric:{anomaly.service_name}:{anomaly.metric_name}:{anomaly.occurred_at.isoformat()}",
                service_name=anomaly.service_name,
                snippet=(
                    f"{anomaly.metric_name} = {anomaly.observed_value:.2f} "
                    f"(baseline {anomaly.baseline_mean:.2f} +/- {anomaly.baseline_stddev:.2f}, "
                    f"z-score {anomaly.zscore:.2f})"
                ),
                relevance_score=1.0,
                occurred_at=anomaly.occurred_at,
            )
        )

    return IncidentCandidate(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        detected_at=detected_at,
        window_start=window_start - timedelta(seconds=5),
        window_end=window_end + timedelta(seconds=5),
        affected_services=affected_services,
        evidence=evidence,
        suggested_severity=_severity_for_score(cluster.max_anomaly_score),
    )
