"""
Persists the outcome of the reasoning pipeline: accepted hypotheses go into
`ai_hypotheses` with rank order, the parent `incidents` row moves to
'pending_review' (accepted) or stays flagged for manual triage (nothing
accepted after retries), ready for a human to accept/reject/edit via the
dashboard (Phase 6) - which is what ultimately produces the eval_examples
row via a trigger-equivalent write in the review endpoint (Phase 5/6), not
here.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol

import psycopg

from app.citation_validator import ValidationResult


class HypothesisWriter(Protocol):
    async def write(
        self, incident_id: uuid.UUID, result: ValidationResult, prompt_version: str, model_name: str
    ) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class PostgresHypothesisWriter:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._conn: psycopg.Connection | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._conn = await loop.run_in_executor(
            None, lambda: psycopg.connect(self._database_url, autocommit=True)
        )

    async def stop(self) -> None:
        if self._conn is not None:
            self._conn.close()

    async def write(
        self, incident_id: uuid.UUID, result: ValidationResult, prompt_version: str, model_name: str
    ) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._write_sync, incident_id, result, prompt_version, model_name)

    def _write_sync(
        self, incident_id: uuid.UUID, result: ValidationResult, prompt_version: str, model_name: str
    ) -> None:
        assert self._conn is not None
        with self._conn.cursor() as cur:
            for rank, hypothesis in enumerate(result.accepted, start=1):
                cur.execute(
                    """
                    INSERT INTO ai_hypotheses
                        (incident_id, rank, hypothesis, confidence, cited_evidence_ids,
                         prompt_version, model_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(incident_id),
                        rank,
                        hypothesis.hypothesis,
                        hypothesis.confidence,
                        [str(i) for i in hypothesis.cited_evidence_ids],
                        prompt_version,
                        model_name,
                    ),
                )

            new_status = "pending_review" if result.accepted else "analyzing"
            cur.execute(
                "UPDATE incidents SET status = %s, updated_at = now() WHERE id = %s",
                (new_status, str(incident_id)),
            )
