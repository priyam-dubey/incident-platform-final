"""Scan worker: claims queued scans, snapshots the commit from GitHub, analyses it statically in a temp dir.

Run in-process (SCAN_WORKER_ENABLED=true) or as its own process: `python -m app.scan_worker`.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time

from incident_scanner import scan_directory

from app.config import Settings, get_settings
from app.github_app import GitHubClient, GitHubError, GitHubNotConfigured, UnsafeArchive

logger = logging.getLogger("scan-worker")


def process_one(repo, settings: Settings, client: GitHubClient | None = None, scanner=scan_directory) -> bool:
    scan = repo.claim_scan()
    if scan is None:
        return False
    own = client is None
    workdir = tempfile.mkdtemp(prefix="scan-")
    try:
        r = repo.get_repository(scan["workspace_id"], scan["repository_id"])
        if r is None or not r["connected"]:
            repo.fail_scan(scan["id"], "Repository is not connected")
            return True
        client = client or GitHubClient(settings)
        client.download_snapshot(r["installation_id"], r["full_name"], scan["commit_sha"], workdir)
        tools = tuple(t.strip() for t in settings.scan_enabled_tools.split(",") if t.strip())
        result = scanner(workdir, tools)
        reports = [{"tool": t.tool, "status": t.status, "detail": t.detail, "findings": t.findings, "seconds": t.seconds} for t in result.reports]
        is_default = scan["trigger"] in ("manual", "schedule") or scan["ref"] == f"refs/heads/{r['default_branch']}"
        repo.complete_scan(scan, result.findings, reports, result.languages, is_default)
        logger.info("scan_completed scan=%s findings=%d", scan["id"], len(result.findings))
    except GitHubNotConfigured:
        repo.fail_scan(scan["id"], "GitHub App is not configured")
    except (GitHubError, UnsafeArchive) as exc:
        repo.fail_scan(scan["id"], str(exc))
    except Exception:
        logger.exception("scan_crashed scan=%s", scan["id"])
        repo.fail_scan(scan["id"], "Internal error while scanning")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        if own and client is not None:
            client.close()
    return True


def run_forever(repo, stop: threading.Event, interval: float = 5.0) -> None:
    settings = get_settings()
    while not stop.is_set():
        try:
            if not process_one(repo, settings):
                stop.wait(interval)
        except Exception:
            logger.exception("scan_worker_loop_error")
            stop.wait(interval)


if __name__ == "__main__":      # pragma: no cover
    from app.db import make_pool
    from app.repository import Repository

    logging.basicConfig(level="INFO")
    run_forever(Repository(make_pool(get_settings().database_url)), threading.Event())
