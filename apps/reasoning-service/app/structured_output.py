"""
The structured-output contract for the reasoning model. This is what gets
forced as a tool-call schema (see llm_client.py) - the model cannot return
free text, only an object matching HypothesisSetDraft. `cited_evidence_ids`
is deliberately required and non-empty per hypothesis: a root-cause claim
with zero citations is exactly the failure mode this pipeline exists to
prevent, so the schema itself makes an uncited hypothesis structurally
invalid rather than relying on the model to remember to cite.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field


class HypothesisDraft(BaseModel):
    hypothesis: Annotated[str, Field(min_length=10, max_length=1000)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    cited_evidence_ids: Annotated[list[UUID], Field(min_length=1, max_length=20)]


class HypothesisSetDraft(BaseModel):
    hypotheses: Annotated[list[HypothesisDraft], Field(min_length=1, max_length=5)]
    # The model's own assessment of whether the provided evidence was
    # sufficient at all - distinct from per-hypothesis confidence, this is
    # "should a human trust *any* of the above", used to trigger abstention.
    evidence_sufficient: bool
