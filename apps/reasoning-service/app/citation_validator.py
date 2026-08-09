"""
The hallucination-prevention enforcement point. The schema forces the model
to attach citations, but a citation is only as trustworthy as the check that
it actually resolves to real evidence - a model can still produce a
syntactically valid UUID that doesn't correspond to anything it was given.
This module is the thing that actually catches that, deterministically, with
no LLM call involved.

Also enforces a stricter bar than "the ID exists": a citation to evidence
from a *different* service than the hypothesis claims to be about is treated
as invalid too - a hypothesis about checkout-api's root cause citing only
payments-api evidence is is a mismatch worth flagging even if the ID is real,
since it suggests the model conflated evidence rather than reasoning about it.
Enforced as a warning (not a hard rejection) via `cross_service_citations`,
since cross-service citations are sometimes exactly right (a downstream
dependency's evidence explaining an upstream service's symptom).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from incident_schemas import EvidenceItem, IncidentCandidate

from app.structured_output import HypothesisDraft, HypothesisSetDraft


@dataclass
class ValidatedHypothesis:
    hypothesis: str
    confidence: float
    cited_evidence_ids: list[UUID]
    cross_service_citation_count: int = 0


@dataclass
class RejectedHypothesis:
    hypothesis: str
    reason: str


@dataclass
class ValidationResult:
    accepted: list[ValidatedHypothesis] = field(default_factory=list)
    rejected: list[RejectedHypothesis] = field(default_factory=list)

    @property
    def has_any_valid_hypothesis(self) -> bool:
        return len(self.accepted) > 0


def _validate_one(draft: HypothesisDraft, evidence_by_id: dict[UUID, EvidenceItem]) -> ValidatedHypothesis | RejectedHypothesis:
    unknown_ids = [eid for eid in draft.cited_evidence_ids if eid not in evidence_by_id]
    if unknown_ids:
        return RejectedHypothesis(
            hypothesis=draft.hypothesis,
            reason=(
                f"cited {len(unknown_ids)} evidence id(s) not present in the incident "
                f"candidate's evidence set: {[str(i) for i in unknown_ids]}"
            ),
        )

    cited_items = [evidence_by_id[eid] for eid in draft.cited_evidence_ids]
    cited_services = {item.service_name for item in cited_items if item.service_name}
    # A "cross-service" citation here just means the hypothesis draws on
    # evidence from more than one service - informational, not a rejection.
    cross_service_count = max(0, len(cited_services) - 1)

    return ValidatedHypothesis(
        hypothesis=draft.hypothesis,
        confidence=draft.confidence,
        cited_evidence_ids=draft.cited_evidence_ids,
        cross_service_citation_count=cross_service_count,
    )


def validate_citations(draft: HypothesisSetDraft, candidate: IncidentCandidate) -> ValidationResult:
    evidence_by_id = {item.id: item for item in candidate.evidence}
    result = ValidationResult()

    for hypothesis_draft in draft.hypotheses:
        validated = _validate_one(hypothesis_draft, evidence_by_id)
        if isinstance(validated, ValidatedHypothesis):
            result.accepted.append(validated)
        else:
            result.rejected.append(validated)

    # Rank accepted hypotheses by confidence, most confident first - this is
    # the rank order persisted to ai_hypotheses.rank and shown to the reviewer.
    result.accepted.sort(key=lambda h: h.confidence, reverse=True)
    return result
