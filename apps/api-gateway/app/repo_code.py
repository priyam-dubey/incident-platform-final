"""GitHub installations, repositories, scans and findings. Every query is workspace-scoped."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

SEV_ORDER = "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END"
SORTS = {"severity": f"{SEV_ORDER}, f.updated_at DESC", "recent": "f.updated_at DESC", "file": "f.file_path, f.start_line"}


class CodeMixin:
    # ---------------- install flow ----------------
    def create_install_state(self, workspace_id, user_id, ttl_seconds: int = 600) -> str:
        state = secrets.token_urlsafe(32)
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM github_install_states WHERE expires_at < now()")
            conn.execute("INSERT INTO github_install_states (state_hash,workspace_id,user_id,expires_at) VALUES (%s,%s,%s,%s)",
                         (hashlib.sha256(state.encode()).hexdigest(), workspace_id, user_id, datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)))
        return state

    def consume_install_state(self, state: str) -> dict | None:
        """Single use: a replayed or expired state returns None."""
        with self.pool.connection() as conn:
            return conn.execute("DELETE FROM github_install_states WHERE state_hash=%s AND expires_at > now() RETURNING workspace_id, user_id",
                                (hashlib.sha256(state.encode()).hexdigest(),)).fetchone()

    def upsert_installation(self, workspace_id, installation_id: int, login: str, account_type: str | None, user_id) -> dict | None:
        """An installation belongs to exactly one workspace; a different workspace cannot claim it."""
        with self.pool.connection() as conn, conn.transaction():
            cur = conn.execute("SELECT * FROM github_installations WHERE installation_id=%s", (installation_id,)).fetchone()
            if cur and cur["workspace_id"] != workspace_id:
                return None
            if cur:
                return conn.execute("UPDATE github_installations SET account_login=%s, suspended_at=NULL WHERE installation_id=%s RETURNING *",
                                    (login, installation_id)).fetchone()
            return conn.execute("INSERT INTO github_installations (workspace_id,installation_id,account_login,account_type,created_by) "
                                "VALUES (%s,%s,%s,%s,%s) RETURNING *", (workspace_id, installation_id, login, account_type, user_id)).fetchone()

    def list_installations(self, workspace_id) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute("SELECT * FROM github_installations WHERE workspace_id=%s ORDER BY created_at", (workspace_id,)).fetchall()

    def get_installation_by_id(self, installation_id: int) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute("SELECT * FROM github_installations WHERE installation_id=%s", (installation_id,)).fetchone()

    def delete_installation(self, installation_id: int) -> None:
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM github_installations WHERE installation_id=%s", (installation_id,))

    def set_installation_suspended(self, installation_id: int, suspended: bool) -> None:
        with self.pool.connection() as conn:
            conn.execute("UPDATE github_installations SET suspended_at = CASE WHEN %s THEN now() ELSE NULL END WHERE installation_id=%s", (suspended, installation_id))

    def record_delivery(self, delivery_id: str, event: str) -> bool:
        """True the first time a delivery id is seen; False for GitHub retries/replays."""
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM github_webhook_deliveries WHERE received_at < now() - interval '14 days'")
            return conn.execute("INSERT INTO github_webhook_deliveries (delivery_id,event) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                                (delivery_id, event)).rowcount == 1

    # ---------------- repositories ----------------
    def sync_repositories(self, workspace_id, installation_id: int, repos: list[dict]) -> int:
        with self.pool.connection() as conn, conn.transaction():
            for r in repos:
                conn.execute(
                    "INSERT INTO repositories (workspace_id,installation_id,github_repo_id,full_name,default_branch,is_private) VALUES (%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (workspace_id, full_name) DO UPDATE SET installation_id=EXCLUDED.installation_id, github_repo_id=EXCLUDED.github_repo_id, "
                    "default_branch=EXCLUDED.default_branch, is_private=EXCLUDED.is_private",
                    (workspace_id, installation_id, r.get("id"), r["full_name"], r.get("default_branch") or "main", bool(r.get("private", True))))
        return len(repos)

    def remove_repositories(self, installation_id: int, full_names: list[str]) -> None:
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM repositories WHERE installation_id=%s AND full_name = ANY(%s)", (installation_id, full_names))

    def list_repositories(self, workspace_id) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT r.*, (SELECT count(*) FROM findings f WHERE f.repository_id=r.id AND f.status='open') AS open_findings, "
                "(SELECT json_object_agg(severity, n) FROM (SELECT severity, count(*) n FROM findings f WHERE f.repository_id=r.id AND f.status='open' GROUP BY severity) s) AS by_severity "
                "FROM repositories r WHERE r.workspace_id=%s ORDER BY r.connected DESC, r.full_name", (workspace_id,)).fetchall()

    def get_repository(self, workspace_id, repository_id) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute("SELECT * FROM repositories WHERE workspace_id=%s AND id=%s", (workspace_id, repository_id)).fetchone()

    def get_repository_by_name(self, installation_id: int, full_name: str) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute("SELECT * FROM repositories WHERE installation_id=%s AND full_name=%s", (installation_id, full_name)).fetchone()

    def set_repository_connected(self, workspace_id, repository_id, connected: bool) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute("UPDATE repositories SET connected=%s WHERE workspace_id=%s AND id=%s RETURNING *", (connected, workspace_id, repository_id)).fetchone()

    # ---------------- scans ----------------
    def enqueue_scan(self, workspace_id, repository_id, commit_sha: str, ref: str | None, trigger: str, pr_number: int | None = None,
                     head_branch: str | None = None, user_id=None) -> tuple[dict, bool]:
        with self.pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO scans (workspace_id,repository_id,commit_sha,ref,trigger,pr_number,head_branch,requested_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (repository_id, commit_sha, trigger) WHERE status IN ('queued','running') DO NOTHING RETURNING *",
                (workspace_id, repository_id, commit_sha, ref, trigger, pr_number, head_branch, user_id)).fetchone()
            if row:
                return row, True
            return conn.execute("SELECT * FROM scans WHERE repository_id=%s AND commit_sha=%s AND trigger=%s AND status IN ('queued','running')",
                                (repository_id, commit_sha, trigger)).fetchone(), False

    def claim_scan(self) -> dict | None:
        """Atomically take the oldest queued scan (also recovers scans whose worker died > 15 minutes ago)."""
        with self.pool.connection() as conn, conn.transaction():
            conn.execute("UPDATE scans SET status='queued', locked_at=NULL WHERE status='running' AND locked_at < now() - interval '15 minutes'")
            row = conn.execute("SELECT id FROM scans WHERE status='queued' ORDER BY queued_at LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
            if not row:
                return None
            return conn.execute("UPDATE scans SET status='running', started_at=COALESCE(started_at, now()), locked_at=now() WHERE id=%s RETURNING *", (row["id"],)).fetchone()

    def fail_scan(self, scan_id, error: str) -> None:
        with self.pool.connection() as conn:
            conn.execute("UPDATE scans SET status='failed', error=%s, finished_at=now() WHERE id=%s", (error[:500], scan_id))

    def list_scans(self, workspace_id, repository_id, limit: int = 30) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute("SELECT * FROM scans WHERE workspace_id=%s AND repository_id=%s ORDER BY queued_at DESC LIMIT %s",
                                (workspace_id, repository_id, min(limit, 100))).fetchall()

    def get_scan(self, workspace_id, scan_id) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute("SELECT s.*, r.full_name FROM scans s JOIN repositories r ON r.id=s.repository_id WHERE s.workspace_id=%s AND s.id=%s",
                                (workspace_id, scan_id)).fetchone()

    def complete_scan(self, scan: dict, raw_findings: list, tool_reports: list[dict], languages: dict, default_branch_scan: bool) -> dict:
        """Persist results. Default-branch scans drive the finding lifecycle (new/unchanged/fixed/reintroduced);
        PR/branch scans only record what they found, so they never mark main's findings as fixed."""
        ok_tools = {t["tool"] for t in tool_reports if t["status"] == "ok"}
        counts = {"new": 0, "unchanged": 0, "fixed": 0, "reintroduced": 0, "suppressed": 0, "total": len(raw_findings)}
        result: dict = {}
        with self.pool.connection() as conn, conn.transaction():
            if not default_branch_scan:
                known = {r["fingerprint"]: r["status"] for r in conn.execute(
                    "SELECT fingerprint, status FROM findings WHERE repository_id=%s", (scan["repository_id"],)).fetchall()}
                new = [f for f in raw_findings if known.get(f.fingerprint) in (None, "fixed")]
                counts["new"], counts["unchanged"] = len(new), len(raw_findings) - len(new)
                result = {"new_findings": [{"tool": f.tool, "rule_id": f.rule_id, "severity": f.severity, "title": f.title, "file_path": f.file_path,
                                            "start_line": f.start_line} for f in new[:200]]}
            else:
                seen = set()
                for f in raw_findings:
                    seen.add(f.fingerprint)
                    row = conn.execute("SELECT id, status FROM findings WHERE repository_id=%s AND fingerprint=%s", (scan["repository_id"], f.fingerprint)).fetchone()
                    if row is None:
                        conn.execute(
                            "INSERT INTO findings (workspace_id,repository_id,fingerprint,tool,rule_id,category,severity,title,message,file_path,start_line,end_line,code_snippet,"
                            "cwe,package_name,package_version,fixed_version,first_seen_scan,last_seen_scan,first_seen_commit,last_seen_commit) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (scan["workspace_id"], scan["repository_id"], f.fingerprint, f.tool, f.rule_id, f.category, f.severity, f.title, f.message, f.file_path,
                             f.start_line, f.end_line, f.snippet, f.cwe, f.package_name, f.package_version, f.fixed_version, scan["id"], scan["id"], scan["commit_sha"], scan["commit_sha"]))
                        counts["new"] += 1
                        continue
                    base = ("UPDATE findings SET last_seen_scan=%s, last_seen_commit=%s, start_line=%s, end_line=%s, severity=%s, updated_at=now()")
                    if row["status"] == "fixed":
                        conn.execute(base + ", status='open', fixed_at=NULL, reintroduced_count=reintroduced_count+1 WHERE id=%s",
                                     (scan["id"], scan["commit_sha"], f.start_line, f.end_line, f.severity, row["id"]))
                        counts["reintroduced"] += 1
                    else:
                        conn.execute(base + " WHERE id=%s", (scan["id"], scan["commit_sha"], f.start_line, f.end_line, f.severity, row["id"]))
                        counts["unchanged" if row["status"] == "open" else "suppressed"] += 1
                # open findings that this scan no longer reports, for tools that actually ran, are fixed
                cur = conn.execute("UPDATE findings SET status='fixed', fixed_at=now(), updated_at=now() WHERE repository_id=%s AND status='open' AND tool = ANY(%s) "
                                   "AND NOT (fingerprint = ANY(%s))", (scan["repository_id"], sorted(ok_tools), list(seen)))
                counts["fixed"] = cur.rowcount
                conn.execute("UPDATE repositories SET last_scan_at=now(), language_summary=%s WHERE id=%s", (json.dumps(languages), scan["repository_id"]))
            return conn.execute("UPDATE scans SET status='completed', finished_at=now(), tools=%s, counts=%s, result=%s WHERE id=%s RETURNING *",
                                (json.dumps({t["tool"]: {k: v for k, v in t.items() if k != "tool"} for t in tool_reports}), json.dumps(counts),
                                 json.dumps(result), scan["id"])).fetchone()

    # ---------------- findings ----------------
    def list_findings(self, workspace_id, repository_id=None, status=None, severity=None, tool=None, category=None, q=None,
                      sort="severity", limit=50, offset=0) -> tuple[list[dict], int]:
        where, args = ["f.workspace_id=%s"], [workspace_id]
        for col, val in (("f.repository_id", repository_id), ("f.status", status), ("f.severity", severity), ("f.tool", tool), ("f.category", category)):
            if val:
                where.append(f"{col}=%s")
                args.append(val)
        if q:
            where.append("(f.title ILIKE %s OR f.file_path ILIKE %s OR f.rule_id ILIKE %s)")
            args += [f"%{q[:100]}%"] * 3
        w = " AND ".join(where)
        with self.pool.connection() as conn:
            total = conn.execute(f"SELECT count(*) AS n FROM findings f WHERE {w}", args).fetchone()["n"]
            rows = conn.execute(f"SELECT f.*, r.full_name AS repository FROM findings f JOIN repositories r ON r.id=f.repository_id WHERE {w} "
                                f"ORDER BY {SORTS.get(sort, SORTS['severity'])} LIMIT %s OFFSET %s", [*args, min(limit, 200), max(offset, 0)]).fetchall()
        return rows, total

    def get_finding(self, workspace_id, finding_id) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute("SELECT f.*, r.full_name AS repository FROM findings f JOIN repositories r ON r.id=f.repository_id WHERE f.workspace_id=%s AND f.id=%s",
                                (workspace_id, finding_id)).fetchone()

    def triage_finding(self, workspace_id, finding_id, status: str, note: str | None, user_id) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute("UPDATE findings SET status=%s, triage_note=%s, triaged_by=%s, updated_at=now() WHERE workspace_id=%s AND id=%s RETURNING *",
                                (status, note, user_id, workspace_id, finding_id)).fetchone()

    def save_explanation(self, workspace_id, finding_id, explanation: dict) -> None:
        with self.pool.connection() as conn:
            conn.execute("UPDATE findings SET explanation=%s WHERE workspace_id=%s AND id=%s", (json.dumps(explanation), workspace_id, finding_id))

    def repository_summary(self, workspace_id, repository_id) -> dict:
        with self.pool.connection() as conn:
            sev = conn.execute("SELECT severity, count(*) AS n FROM findings WHERE workspace_id=%s AND repository_id=%s AND status='open' GROUP BY severity", (workspace_id, repository_id)).fetchall()
            tool = conn.execute("SELECT tool, count(*) AS n FROM findings WHERE workspace_id=%s AND repository_id=%s AND status='open' GROUP BY tool", (workspace_id, repository_id)).fetchall()
            st = conn.execute("SELECT status, count(*) AS n FROM findings WHERE workspace_id=%s AND repository_id=%s GROUP BY status", (workspace_id, repository_id)).fetchall()
            trend = conn.execute("SELECT queued_at, commit_sha, counts FROM scans WHERE workspace_id=%s AND repository_id=%s AND status='completed' AND trigger<>'pull_request' "
                                 "ORDER BY queued_at DESC LIMIT 20", (workspace_id, repository_id)).fetchall()
        return {"by_severity": {r["severity"]: r["n"] for r in sev}, "by_tool": {r["tool"]: r["n"] for r in tool},
                "by_status": {r["status"]: r["n"] for r in st}, "history": [{"at": t["queued_at"].isoformat(), "commit": t["commit_sha"], "counts": t["counts"]} for t in reversed(trend)]}
