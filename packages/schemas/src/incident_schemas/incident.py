"""
Incident-candidate contracts.

This is the object that crosses the boundary from the (deterministic)
correlation engine into the (AI) reasoning service. It is the enforcement
point for the platform's core design rule: the model never sees raw
telemetry, only this bounded, pre-validated evidence structure.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class IncidentSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ServiceAnomaly(BaseModel):
    """One service's contribution to a correlated incident cluster."""

    service_id: UUID
    service_name: str
    anomaly_score: Annotated[float, Field(ge=0)]
    metric_name: str
    observed_value: float
    baseline_mean: float
    baseline_stddev: Annotated[float, Field(ge=0)]


class EvidenceItem(BaseModel):
    """
    A single, bounded piece of evidence. `snippet` is what the model actually
    reads - it must already be redacted and length-capped by the time it
    reaches here (see packages/redaction, Phase 7). `source_ref` is what lets
    the citation-validation step in the reasoning service confirm a claim is
    real by resolving it back to ClickHouse rather than trusting the model's
    word for it.
    """

    id: UUID
    source_type: Annotated[str, Field(pattern="^(log|metric|trace|deploy)$")]
    source_ref: Annotated[str, Field(min_length=1)]
    service_name: str | None = None
    snippet: Annotated[str, Field(min_length=1, max_length=2000)]
    relevance_score: Annotated[float, Field(ge=0, le=1)]
    occurred_at: datetime


class IncidentCandidate(BaseModel):
    """
    Emitted by the correlation engine once enough simultaneous anomalies
    cluster together to look like one real incident rather than noise.
    Consumed by the reasoning service as the entire universe of evidence it
    is permitted to reason over.
    """

    id: UUID
    workspace_id: UUID
    detected_at: datetime
    window_start: datetime
    window_end: datetime
    affected_services: Annotated[list[ServiceAnomaly], Field(min_length=1)]
    evidence: Annotated[list[EvidenceItem], Field(min_length=1, max_length=200)]
    suggested_severity: IncidentSeverity

    @model_validator(mode="after")
    def _window_must_be_ordered(self) -> "IncidentCandidate":
        # Must run before _evidence_must_fall_within_window: an inverted window
        # makes every evidence-window check below meaningless, and reporting
        # "evidence out of range" for an internally-inconsistent window would
        # send the caller chasing the wrong bug.
        if self.window_end < self.window_start:
            raise ValueError("window_end must not be before window_start")
        return self

    @model_validator(mode="after")
    def _evidence_must_fall_within_window(self) -> "IncidentCandidate":
        # A small grace period accounts for clock skew between services emitting
        # telemetry and the correlation engine's own window boundaries.
        grace = 5.0  # seconds
        for item in self.evidence:
            lower = self.window_start.timestamp() - grace
            upper = self.window_end.timestamp() + grace
            if not (lower <= item.occurred_at.timestamp() <= upper):
                raise ValueError(
                    f"evidence {item.id} occurred at {item.occurred_at}, "
                    f"outside incident window [{self.window_start}, {self.window_end}]"
                )
        return self
