"""Deployments, incidents, evidence, hypotheses, notes. Every query is workspace-scoped."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from psycopg.rows import dict_row  # noqa: F401  (pool rows are already dicts)


class IncidentMixin:
    # ---------------- deployments ----------------
    def create_deployment(self, workspace_id, application_id, environment, version, commit_sha, branch, repository,
                          deployed_by, source, deployed_at: datetime | None, metadata: dict) -> dict:
        with self.pool.connection() as conn:
            return conn.execute(
                "INSERT INTO deployments (workspace_id,application_id,environment,version,commit_sha,branch,repository_full_name,"
                "deployed_by,source,deployed_at,metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,COALESCE(%s, now()),%s) RETURNING *",
                (workspace_id, application_id, environment, version, commit_sha, branch, repository, deployed_by, source,
                 deployed_at, json.dumps(metadata)),
            ).fetchone()

    def list_deployments(self, workspace_id, application_id=None, limit: int = 50) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT d.*, a.name AS application_name FROM deployments d JOIN applications a ON a.id=d.application_id "
                "WHERE d.workspace_id=%s AND (%s::uuid IS NULL OR d.application_id=%s) ORDER BY d.deployed_at DESC LIMIT %s",
                (workspace_id, application_id, application_id, min(limit, 200)),
            ).fetchall()

    def deployments_between(self, workspace_id, application_id, t0: datetime, t1: datetime) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT * FROM deployments WHERE workspace_id=%s AND application_id=%s AND deployed_at BETWEEN %s AND %s "
                "ORDER BY deployed_at DESC LIMIT 10", (workspace_id, application_id, t0, t1)).fetchall()

    # ---------------- incidents ----------------
    def upsert_incident(self, workspace_id, application: dict, det, started_at: datetime) -> tuple[dict, bool]:
        """One open incident per (application, fingerprint): re-detections refresh details instead of duplicating."""
        with self.pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO incidents (workspace_id,application_id,title,status,severity,started_at,fingerprint,detector,details,is_synthetic) "
                "VALUES (%s,%s,%s,'candidate',%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (application_id, fingerprint) WHERE application_id IS NOT NULL AND status NOT IN ('dismissed','resolved') "
                "DO UPDATE SET details=incidents.details || EXCLUDED.details, severity=EXCLUDED.severity, title=EXCLUDED.title, updated_at=now() "
                "RETURNING *, (xmax = 0) AS created",
                (workspace_id, application["id"], det.title, det.severity, started_at, det.fingerprint, det.detector,
                 json.dumps(det.details), application["is_synthetic"]),
            ).fetchone()
        return row, row.pop("created")

    def add_evidence(self, incident_id, items: list[dict]) -> list[dict]:
        out = []
        with self.pool.connection() as conn, conn.transaction():
            if conn.execute("SELECT 1 FROM ai_hypotheses WHERE incident_id=%s LIMIT 1", (incident_id,)).fetchone():
                return self.list_evidence(incident_id)        # evidence is frozen once hypotheses cite it
            conn.execute("DELETE FROM incident_evidence WHERE incident_id=%s", (incident_id,))
            for it in items:
                out.append(conn.execute(
                    "INSERT INTO incident_evidence (incident_id,source_type,source_ref,snippet,relevance_score,occurred_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                    (incident_id, it["source_type"], it["source_ref"], it["snippet"][:600], it.get("relevance", 0.5), it["occurred_at"]),
                ).fetchone())
        return out

    def list_evidence(self, incident_id) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute("SELECT * FROM incident_evidence WHERE incident_id=%s ORDER BY relevance_score DESC, occurred_at",
                                (incident_id,)).fetchall()

    def list_incidents(self, workspace_id, status=None, application_id=None, limit=50, offset=0) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT i.*, a.name AS application_name FROM incidents i LEFT JOIN applications a ON a.id=i.application_id "
                "WHERE i.workspace_id=%s AND (%s::text IS NULL OR i.status::text=%s) AND (%s::uuid IS NULL OR i.application_id=%s) "
                "ORDER BY i.started_at DESC LIMIT %s OFFSET %s",
                (workspace_id, status, status, application_id, application_id, min(limit, 200), max(offset, 0))).fetchall()

    def get_incident(self, workspace_id, incident_id) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT i.*, a.name AS application_name FROM incidents i LEFT JOIN applications a ON a.id=i.application_id "
                "WHERE i.workspace_id=%s AND i.id=%s", (workspace_id, incident_id)).fetchone()

    def list_hypotheses(self, incident_id) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute("SELECT * FROM ai_hypotheses WHERE incident_id=%s ORDER BY rank", (incident_id,)).fetchall()

    def save_hypotheses(self, incident_id, items: list[dict], prompt_version: str, model: str) -> None:
        with self.pool.connection() as conn, conn.transaction():
            conn.execute("DELETE FROM ai_hypotheses WHERE incident_id=%s AND human_verdict IS NULL", (incident_id,))
            for rank, it in enumerate(items, start=1):
                conn.execute(
                    "INSERT INTO ai_hypotheses (incident_id,rank,hypothesis,confidence,cited_evidence_ids,prompt_version,model_name) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (incident_id, rank, it["hypothesis"], it["confidence"], it["cited_evidence_ids"], prompt_version, model))
            conn.execute("UPDATE incidents SET status='pending_review', updated_at=now() WHERE id=%s AND status IN ('candidate','analyzing')",
                         (incident_id,))

    def set_incident_details(self, incident_id, patch: dict) -> None:
        with self.pool.connection() as conn:
            conn.execute("UPDATE incidents SET details = details || %s::jsonb, updated_at=now() WHERE id=%s", (json.dumps(patch), incident_id))

    def review_hypothesis(self, workspace_id, incident_id, hypothesis_id, verdict: str, notes: str | None,
                          edited_text: str | None, reviewer_email: str) -> dict | None:
        with self.pool.connection() as conn, conn.transaction():
            h = conn.execute(
                "UPDATE ai_hypotheses h SET human_verdict=%s, verdict_notes=%s, edited_text=%s, reviewed_by=%s, reviewed_at=now() "
                "FROM incidents i WHERE h.id=%s AND h.incident_id=i.id AND i.id=%s AND i.workspace_id=%s RETURNING h.*",
                (verdict, notes, edited_text, reviewer_email, hypothesis_id, incident_id, workspace_id)).fetchone()
            if h is None:
                return None
            conn.execute("INSERT INTO eval_examples (hypothesis_id,label) VALUES (%s,%s)", (hypothesis_id, verdict))
            if verdict in ("accepted", "edited"):
                conn.execute("UPDATE incidents SET status='published', updated_at=now() WHERE id=%s AND status='pending_review'", (incident_id,))
            return h

    def transition_incident(self, workspace_id, incident_id, new_status: str, user_id) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute(
                "UPDATE incidents SET status=%s::incident_status, updated_at=now(), "
                "resolved_at = CASE WHEN %s IN ('resolved','dismissed') THEN now() ELSE NULL END, "
                "resolved_by = CASE WHEN %s IN ('resolved','dismissed') THEN %s ELSE NULL END "
                "WHERE id=%s AND workspace_id=%s RETURNING *",
                (new_status, new_status, new_status, user_id, incident_id, workspace_id)).fetchone()

    def add_note(self, workspace_id, incident_id, user_id, body: str) -> dict | None:
        with self.pool.connection() as conn:
            if not conn.execute("SELECT 1 FROM incidents WHERE id=%s AND workspace_id=%s", (incident_id, workspace_id)).fetchone():
                return None
            return conn.execute("INSERT INTO incident_notes (incident_id,workspace_id,user_id,body) VALUES (%s,%s,%s,%s) RETURNING *",
                                (incident_id, workspace_id, user_id, body)).fetchone()

    def list_notes(self, workspace_id, incident_id) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT n.id, n.body, n.created_at, u.email AS author_email FROM incident_notes n LEFT JOIN users u ON u.id=n.user_id "
                "WHERE n.incident_id=%s AND n.workspace_id=%s ORDER BY n.created_at", (incident_id, workspace_id)).fetchall()

    def record_notification(self, workspace_id, incident_id, channel: str, status: str, error: str | None) -> None:
        with self.pool.connection() as conn:
            conn.execute("INSERT INTO notification_deliveries (workspace_id,incident_id,channel,status,error) VALUES (%s,%s,%s,%s,%s)",
                         (workspace_id, incident_id, channel, status, (error or "")[:300] or None))

    def list_notifications(self, workspace_id, incident_id) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute("SELECT channel,status,error,created_at FROM notification_deliveries WHERE workspace_id=%s AND incident_id=%s "
                                "ORDER BY created_at", (workspace_id, incident_id)).fetchall()

    def monitored_applications(self) -> list[dict]:
        """Live, non-revoked apps with recent telemetry (used by the detection loop)."""
        with self.pool.connection() as conn:
            return conn.execute("SELECT * FROM applications WHERE revoked_at IS NULL AND last_telemetry_at > now() - interval '1 day'").fetchall()
