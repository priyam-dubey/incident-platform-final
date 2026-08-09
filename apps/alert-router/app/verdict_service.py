"""
The business logic behind a human's accept/reject/edit action on an AI
hypothesis. Every verdict does two things: (1) updates the hypothesis's own
review state, and (2) writes an `eval_examples` row - this is the mechanism
by which "an engineer looked at this and said yes/no" becomes training/eval
data for the offline eval harness (Phase 7) to score future prompt or model
changes against, without any separate labeling effort.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.repository import HypothesisRecord, IncidentRepository


class HypothesisNotFoundError(Exception):
    pass


@dataclass
class VerdictOutcome:
    hypothesis: HypothesisRecord
    incident_status: str


async def apply_verdict(
    repo: IncidentRepository,
    hypothesis_id: uuid.UUID,
    verdict: str,
    notes: str | None,
    reviewed_by: str,
) -> VerdictOutcome:
    if verdict not in {"accepted", "rejected", "edited"}:
        raise ValueError(f"invalid verdict: {verdict!r}")

    updated = await repo.record_verdict(hypothesis_id, verdict, notes, reviewed_by)
    if updated is None:
        raise HypothesisNotFoundError(f"no hypothesis with id={hypothesis_id}")

    await repo.record_eval_example(hypothesis_id, verdict)

    new_status = await _resolve_incident_status(repo, updated.incident_id, verdict)
    if new_status is not None:
        await repo.mark_incident_status(updated.incident_id, new_status)

    return VerdictOutcome(hypothesis=updated, incident_status=new_status or "pending_review")


async def _resolve_incident_status(
    repo: IncidentRepository, incident_id: uuid.UUID, just_applied_verdict: str
) -> str | None:
    if just_applied_verdict in {"accepted", "edited"}:
        # A human endorsed a root cause - the incident's story is settled,
        # regardless of what verdict any other hypothesis for it ends up with.
        return "published"

    # A rejection: only escalate to "dismissed" once every hypothesis for
    # this incident has been reviewed and none were accepted/edited - a
    # single rejected hypothesis doesn't mean the incident itself is noise,
    # there may be other candidate hypotheses still awaiting review.
    detail = await repo.get_incident_detail(incident_id)
    if detail is None:
        return None

    all_reviewed = all(h.human_verdict is not None for h in detail.hypotheses)
    any_endorsed = any(h.human_verdict in {"accepted", "edited"} for h in detail.hypotheses)

    if all_reviewed and not any_endorsed:
        return "dismissed"
    return None
