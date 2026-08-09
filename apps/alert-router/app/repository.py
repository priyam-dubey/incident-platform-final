"""
Data access layer for the alert-router's HTTP API (incident detail, hypothesis
verdicts) and its Kafka-triggered escalation path (fetching on-call info).
Behind a Protocol so route handlers and the escalation consumer are testable
without a live Postgres instance - `PostgresIncidentRepository` is the real
implementation, tests use an in-memory fake (tests/conftest.py).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class HypothesisRecord:
    id: uuid.UUID
    incident_id: uuid.UUID
    rank: int
    hypothesis: str
    confidence: float
    cited_evidence_ids: list[uuid.UUID]
    human_verdict: str | None
    reviewed_by: str | None


@dataclass
class EvidenceRecord:
    id: uuid.UUID
    source_type: str
    source_ref: str
    snippet: str
    relevance_score: float
    occurred_at: datetime


@dataclass
class IncidentRecord:
    id: uuid.UUID
    workspace_id: uuid.UUID
    status: str
    severity: str
    started_at: datetime
    resolved_at: datetime | None


@dataclass
class IncidentDetail:
    incident: IncidentRecord
    evidence: list[EvidenceRecord]
    hypotheses: list[HypothesisRecord]


class IncidentRepository(Protocol):
    async def list_incidents(
        self, workspace_id: uuid.UUID, status: str | None, limit: int
    ) -> list[IncidentRecord]: ...

    async def get_incident_detail(self, incident_id: uuid.UUID) -> IncidentDetail | None: ...

    async def record_verdict(
        self,
        hypothesis_id: uuid.UUID,
        verdict: str,
        notes: str | None,
        reviewed_by: str,
    ) -> HypothesisRecord | None: ...

    async def mark_incident_status(self, incident_id: uuid.UUID, status: str) -> None: ...

    async def record_eval_example(self, hypothesis_id: uuid.UUID, label: str) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class PostgresIncidentRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._conn = None

    async def start(self) -> None:
        import psycopg

        loop = asyncio.get_running_loop()
        self._conn = await loop.run_in_executor(
            None, lambda: psycopg.connect(self._database_url, autocommit=True)
        )

    async def stop(self) -> None:
        if self._conn is not None:
            self._conn.close()

    async def list_incidents(
        self, workspace_id: uuid.UUID, status: str | None, limit: int
    ) -> list[IncidentRecord]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._list_incidents_sync, workspace_id, status, limit)

    def _list_incidents_sync(self, workspace_id, status, limit) -> list[IncidentRecord]:
        assert self._conn is not None
        with self._conn.cursor() as cur:
            if status:
                cur.execute(
                    """
                    SELECT id, workspace_id, status, severity, started_at, resolved_at
                    FROM incidents WHERE workspace_id = %s AND status = %s
                    ORDER BY started_at DESC LIMIT %s
                    """,
                    (str(workspace_id), status, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, workspace_id, status, severity, started_at, resolved_at
                    FROM incidents WHERE workspace_id = %s
                    ORDER BY started_at DESC LIMIT %s
                    """,
                    (str(workspace_id), limit),
                )
            return [
                IncidentRecord(
                    id=row[0], workspace_id=row[1], status=row[2], severity=row[3],
                    started_at=row[4], resolved_at=row[5],
                )
                for row in cur.fetchall()
            ]

    async def get_incident_detail(self, incident_id: uuid.UUID) -> IncidentDetail | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_incident_detail_sync, incident_id)

    def _get_incident_detail_sync(self, incident_id: uuid.UUID) -> IncidentDetail | None:
        assert self._conn is not None
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT id, workspace_id, status, severity, started_at, resolved_at "
                "FROM incidents WHERE id = %s",
                (str(incident_id),),
            )
            row = cur.fetchone()
            if row is None:
                return None
            incident = IncidentRecord(
                id=row[0], workspace_id=row[1], status=row[2], severity=row[3],
                started_at=row[4], resolved_at=row[5],
            )

            cur.execute(
                "SELECT id, source_type, source_ref, snippet, relevance_score, occurred_at "
                "FROM incident_evidence WHERE incident_id = %s ORDER BY occurred_at",
                (str(incident_id),),
            )
            evidence = [
                EvidenceRecord(id=r[0], source_type=r[1], source_ref=r[2], snippet=r[3], relevance_score=r[4], occurred_at=r[5])
                for r in cur.fetchall()
            ]

            cur.execute(
                "SELECT id, incident_id, rank, hypothesis, confidence, cited_evidence_ids, "
                "human_verdict, reviewed_by FROM ai_hypotheses WHERE incident_id = %s ORDER BY rank",
                (str(incident_id),),
            )
            hypotheses = [
                HypothesisRecord(
                    id=r[0], incident_id=r[1], rank=r[2], hypothesis=r[3], confidence=r[4],
                    cited_evidence_ids=[uuid.UUID(str(x)) for x in (r[5] or [])],
                    human_verdict=r[6], reviewed_by=r[7],
                )
                for r in cur.fetchall()
            ]

            return IncidentDetail(incident=incident, evidence=evidence, hypotheses=hypotheses)

    async def record_verdict(
        self, hypothesis_id: uuid.UUID, verdict: str, notes: str | None, reviewed_by: str
    ) -> HypothesisRecord | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._record_verdict_sync, hypothesis_id, verdict, notes, reviewed_by
        )

    def _record_verdict_sync(self, hypothesis_id, verdict, notes, reviewed_by) -> HypothesisRecord | None:
        assert self._conn is not None
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_hypotheses
                SET human_verdict = %s, verdict_notes = %s, reviewed_by = %s, reviewed_at = now()
                WHERE id = %s
                RETURNING id, incident_id, rank, hypothesis, confidence, cited_evidence_ids,
                          human_verdict, reviewed_by
                """,
                (verdict, notes, reviewed_by, str(hypothesis_id)),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return HypothesisRecord(
                id=row[0], incident_id=row[1], rank=row[2], hypothesis=row[3], confidence=row[4],
                cited_evidence_ids=[uuid.UUID(str(x)) for x in (row[5] or [])],
                human_verdict=row[6], reviewed_by=row[7],
            )

    async def mark_incident_status(self, incident_id: uuid.UUID, status: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._mark_incident_status_sync, incident_id, status)

    def _mark_incident_status_sync(self, incident_id: uuid.UUID, status: str) -> None:
        assert self._conn is not None
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE incidents SET status = %s, updated_at = now() WHERE id = %s",
                (status, str(incident_id)),
            )

    async def record_eval_example(self, hypothesis_id: uuid.UUID, label: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._record_eval_example_sync, hypothesis_id, label)

    def _record_eval_example_sync(self, hypothesis_id: uuid.UUID, label: str) -> None:
        assert self._conn is not None
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO eval_examples (hypothesis_id, label) VALUES (%s, %s)",
                (str(hypothesis_id), label),
            )
