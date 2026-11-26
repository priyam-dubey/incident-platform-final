"""
All SQL lives here. Every query touching tenant data takes workspace_id and
filters on it in the WHERE clause, so tenant isolation is enforced in the data
layer, not by callers remembering to check.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from psycopg.errors import UniqueViolation
from psycopg_pool import ConnectionPool

ROLE_RANK = {"viewer": 1, "developer": 2, "admin": 3, "owner": 4}


class DuplicateError(Exception):
    pass


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workspace"
    return base[:40]


from app.repo_code import CodeMixin  # noqa: E402
from app.repo_incidents import IncidentMixin  # noqa: E402


class Repository(IncidentMixin, CodeMixin):
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    # ---------------- users / sessions ----------------
    def create_user(self, email: str, password_hash: str, display_name: str) -> dict:
        try:
            with self.pool.connection() as conn:
                return conn.execute(
                    "INSERT INTO users (email, password_hash, display_name) VALUES (%s,%s,%s) "
                    "RETURNING id, email, display_name, email_verified, created_at",
                    (email.strip(), password_hash, display_name),
                ).fetchone()
        except UniqueViolation:
            raise DuplicateError("email") from None

    def get_user_by_email(self, email: str) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute("SELECT * FROM users WHERE lower(email)=lower(%s)", (email.strip(),)).fetchone()

    def get_user(self, user_id: uuid.UUID) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT id, email, display_name, email_verified, created_at FROM users WHERE id=%s", (user_id,)
            ).fetchone()

    def update_user_profile(self, user_id: uuid.UUID, display_name: str) -> dict:
        with self.pool.connection() as conn:
            return conn.execute(
                "UPDATE users SET display_name=%s WHERE id=%s "
                "RETURNING id, email, display_name, email_verified, created_at", (display_name, user_id)
            ).fetchone()

    def create_session(self, user_id, token_hash: str, ttl_seconds: int, user_agent: str | None) -> None:
        exp = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO sessions (user_id, refresh_token_hash, expires_at, user_agent) VALUES (%s,%s,%s,%s)",
                (user_id, token_hash, exp, (user_agent or "")[:300]),
            )

    def rotate_session(self, old_hash: str, new_hash: str, ttl_seconds: int) -> uuid.UUID | None:
        """Atomically revoke the presented refresh token and issue a new one. Returns user_id."""
        exp = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        with self.pool.connection() as conn:
            row = conn.execute(
                "UPDATE sessions SET revoked_at=now() WHERE refresh_token_hash=%s "
                "AND revoked_at IS NULL AND expires_at > now() RETURNING user_id, user_agent",
                (old_hash,),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "INSERT INTO sessions (user_id, refresh_token_hash, expires_at, user_agent) VALUES (%s,%s,%s,%s)",
                (row["user_id"], new_hash, exp, row["user_agent"]),
            )
            return row["user_id"]

    def revoke_session(self, token_hash: str) -> None:
        with self.pool.connection() as conn:
            conn.execute("UPDATE sessions SET revoked_at=now() WHERE refresh_token_hash=%s AND revoked_at IS NULL", (token_hash,))

    def revoke_all_sessions(self, user_id) -> None:
        with self.pool.connection() as conn:
            conn.execute("UPDATE sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", (user_id,))

    # ---------------- password reset ----------------
    def create_reset_token(self, user_id, token_hash: str, ttl_seconds: int) -> None:
        exp = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        with self.pool.connection() as conn:
            conn.execute("INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (%s,%s,%s)", (user_id, token_hash, exp))

    def consume_reset_token(self, token_hash: str) -> uuid.UUID | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "UPDATE password_reset_tokens SET used_at=now() WHERE token_hash=%s AND used_at IS NULL "
                "AND expires_at > now() RETURNING user_id", (token_hash,),
            ).fetchone()
            return row["user_id"] if row else None

    def set_password(self, user_id, password_hash: str) -> None:
        with self.pool.connection() as conn:
            conn.execute("UPDATE users SET password_hash=%s WHERE id=%s", (password_hash, user_id))

    # ---------------- workspaces / membership ----------------
    def create_workspace(self, owner_id, name: str) -> dict:
        base = slugify(name)
        with self.pool.connection() as conn:
            for attempt in range(5):
                slug = base if attempt == 0 else f"{base}-{uuid.uuid4().hex[:6]}"
                try:
                    with conn.transaction():
                        ws = conn.execute(
                            "INSERT INTO workspaces (name, slug) VALUES (%s,%s) RETURNING id, name, slug, is_demo, created_at",
                            (name, slug),
                        ).fetchone()
                        conn.execute("INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s,%s,'owner')", (ws["id"], owner_id))
                        return {**ws, "role": "owner"}
                except UniqueViolation:
                    continue
        raise DuplicateError("slug")

    def list_workspaces_for_user(self, user_id) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT w.id, w.name, w.slug, w.is_demo, w.created_at, m.role FROM workspaces w "
                "JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=%s ORDER BY w.created_at", (user_id,)
            ).fetchall()

    def get_membership(self, workspace_id, user_id) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT m.role, w.name, w.slug, w.is_demo FROM workspace_members m JOIN workspaces w ON w.id=m.workspace_id "
                "WHERE m.workspace_id=%s AND m.user_id=%s", (workspace_id, user_id),
            ).fetchone()

    def list_members(self, workspace_id) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT u.id AS user_id, u.email, u.display_name, m.role, m.created_at FROM workspace_members m "
                "JOIN users u ON u.id=m.user_id WHERE m.workspace_id=%s ORDER BY m.created_at", (workspace_id,)
            ).fetchall()

    def add_member_by_email(self, workspace_id, email: str, role: str) -> dict | None:
        user = self.get_user_by_email(email)
        if not user:
            return None
        try:
            with self.pool.connection() as conn:
                conn.execute("INSERT INTO workspace_members (workspace_id,user_id,role) VALUES (%s,%s,%s)", (workspace_id, user["id"], role))
        except UniqueViolation:
            raise DuplicateError("member") from None
        return {"user_id": user["id"], "email": user["email"], "role": role}

    def change_member_role(self, workspace_id, user_id, role: str) -> bool:
        with self.pool.connection() as conn:
            cur = conn.execute("UPDATE workspace_members SET role=%s WHERE workspace_id=%s AND user_id=%s", (role, workspace_id, user_id))
            return cur.rowcount > 0

    def remove_member(self, workspace_id, user_id) -> bool:
        with self.pool.connection() as conn:
            cur = conn.execute("DELETE FROM workspace_members WHERE workspace_id=%s AND user_id=%s", (workspace_id, user_id))
            return cur.rowcount > 0

    def count_owners(self, workspace_id) -> int:
        with self.pool.connection() as conn:
            return conn.execute("SELECT count(*) AS n FROM workspace_members WHERE workspace_id=%s AND role='owner'", (workspace_id,)).fetchone()["n"]

    # ---------------- applications / ingestion keys ----------------
    def create_application(self, workspace_id, user_id, name, environment, framework, backend_url, is_synthetic,
                           key_prefix: str, key_hash: str) -> dict:
        try:
            with self.pool.connection() as conn, conn.transaction():
                app = conn.execute(
                    "INSERT INTO applications (workspace_id,name,environment,framework,backend_url,is_synthetic,created_by) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                    (workspace_id, name, environment, framework, backend_url, is_synthetic, user_id),
                ).fetchone()
                conn.execute(
                    "INSERT INTO ingestion_keys (application_id, workspace_id, key_prefix, key_hash) VALUES (%s,%s,%s,%s)",
                    (app["id"], workspace_id, key_prefix, key_hash),
                )
                return app
        except UniqueViolation:
            raise DuplicateError("application") from None

    def list_applications(self, workspace_id) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT a.*, (SELECT key_prefix FROM ingestion_keys k WHERE k.application_id=a.id AND k.revoked_at IS NULL "
                "ORDER BY created_at DESC LIMIT 1) AS active_key_prefix FROM applications a "
                "WHERE a.workspace_id=%s AND a.revoked_at IS NULL ORDER BY a.created_at DESC", (workspace_id,)
            ).fetchall()

    def get_application(self, workspace_id, application_id) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT a.*, (SELECT key_prefix FROM ingestion_keys k WHERE k.application_id=a.id AND k.revoked_at IS NULL "
                "ORDER BY created_at DESC LIMIT 1) AS active_key_prefix FROM applications a "
                "WHERE a.workspace_id=%s AND a.id=%s AND a.revoked_at IS NULL", (workspace_id, application_id)
            ).fetchone()

    def rotate_ingestion_key(self, workspace_id, application_id, key_prefix, key_hash) -> bool:
        with self.pool.connection() as conn, conn.transaction():
            app = conn.execute("SELECT id FROM applications WHERE id=%s AND workspace_id=%s AND revoked_at IS NULL",
                               (application_id, workspace_id)).fetchone()
            if not app:
                return False
            conn.execute("UPDATE ingestion_keys SET revoked_at=now() WHERE application_id=%s AND workspace_id=%s AND revoked_at IS NULL",
                         (application_id, workspace_id))
            conn.execute("INSERT INTO ingestion_keys (application_id, workspace_id, key_prefix, key_hash) VALUES (%s,%s,%s,%s)",
                         (application_id, workspace_id, key_prefix, key_hash))
            return True

    def revoke_application(self, workspace_id, application_id) -> bool:
        with self.pool.connection() as conn, conn.transaction():
            cur = conn.execute("UPDATE applications SET revoked_at=now() WHERE id=%s AND workspace_id=%s AND revoked_at IS NULL",
                               (application_id, workspace_id))
            if cur.rowcount == 0:
                return False
            conn.execute("UPDATE ingestion_keys SET revoked_at=now() WHERE application_id=%s AND workspace_id=%s AND revoked_at IS NULL",
                         (application_id, workspace_id))
            return True

    def lookup_ingestion_key(self, key_prefix: str) -> dict | None:
        """Used by the ingestion edge. Returns key row + app info only for live keys on live apps."""
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT k.id AS key_id, k.key_hash, k.workspace_id, k.application_id, a.name AS application_name, "
                "a.environment, a.is_synthetic FROM ingestion_keys k JOIN applications a ON a.id=k.application_id "
                "WHERE k.key_prefix=%s AND k.revoked_at IS NULL AND a.revoked_at IS NULL", (key_prefix,)
            ).fetchone()

    def touch_key(self, key_id, application_id) -> None:
        with self.pool.connection() as conn:
            conn.execute("UPDATE ingestion_keys SET last_used_at=now() WHERE id=%s", (key_id,))

    def mark_telemetry_received(self, application_id) -> None:
        with self.pool.connection() as conn:
            conn.execute("UPDATE applications SET last_telemetry_at=now() WHERE id=%s", (application_id,))

    # ---------------- audit ----------------
    def audit(self, workspace_id, user_id, action: str, resource_type: str | None = None,
              resource_id: str | None = None, metadata: dict | None = None) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO audit_logs (workspace_id,user_id,action,resource_type,resource_id,metadata) VALUES (%s,%s,%s,%s,%s,%s)",
                (workspace_id, user_id, action, resource_type, resource_id, json.dumps(metadata or {})),
            )

    def list_audit(self, workspace_id, limit: int = 100) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT a.id, a.action, a.resource_type, a.resource_id, a.metadata, a.created_at, u.email AS actor_email "
                "FROM audit_logs a LEFT JOIN users u ON u.id=a.user_id WHERE a.workspace_id=%s "
                "ORDER BY a.created_at DESC LIMIT %s", (workspace_id, min(limit, 500))
            ).fetchall()
