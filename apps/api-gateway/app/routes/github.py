"""GitHub App install flow + webhook receiver, and workspace-scoped repository / scan APIs."""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app import github_app
from app.config import Settings, get_settings
from app.deps import WorkspaceContext, get_repo, workspace_access
from app.github_app import GitHubClient, GitHubError
from app.repository import Repository

logger = logging.getLogger("github")
router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["github"])
public = APIRouter(prefix="/v1/github", tags=["github"])


def get_client(request: Request, settings: Settings = Depends(get_settings)) -> GitHubClient:
    existing = getattr(request.app.state, "github", None)       # tests inject a client with a mock transport
    if existing is not None:
        return existing
    if github_app.missing(settings):
        raise HTTPException(503, detail={"code": "github_not_configured", "message": "The GitHub App is not configured on this deployment.",
                                         "missing": github_app.missing(settings)})
    return GitHubClient(settings)


def _repo_out(r: dict) -> dict:
    return {"id": str(r["id"]), "full_name": r["full_name"], "default_branch": r["default_branch"], "private": r["is_private"], "connected": r["connected"],
            "languages": r["language_summary"], "last_scan_at": r["last_scan_at"].isoformat() if r["last_scan_at"] else None,
            "open_findings": int(r.get("open_findings") or 0), "by_severity": r.get("by_severity") or {}}


def scan_out(s: dict) -> dict:
    return {"id": str(s["id"]), "repository_id": str(s["repository_id"]), "commit_sha": s["commit_sha"], "ref": s["ref"], "trigger": s["trigger"],
            "pr_number": s["pr_number"], "status": s["status"], "error": s["error"], "tools": s["tools"], "counts": s["counts"],
            "result": s.get("result") or {}, "queued_at": s["queued_at"].isoformat(),
            "started_at": s["started_at"].isoformat() if s["started_at"] else None, "finished_at": s["finished_at"].isoformat() if s["finished_at"] else None}


@router.get("/github/status")
def github_status(ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
    return {**github_app.status(settings), "webhook_url_path": "/v1/github/webhook",
            "installations": [{"installation_id": i["installation_id"], "account": i["account_login"], "suspended": bool(i["suspended_at"])}
                              for i in repo.list_installations(ctx.workspace_id)]}


@router.post("/github/install-url")
def install_url(ctx: WorkspaceContext = Depends(workspace_access("admin")), repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
    if github_app.missing(settings):
        raise HTTPException(503, detail={"code": "github_not_configured", "message": "The GitHub App is not configured on this deployment.",
                                         "missing": github_app.missing(settings)})
    state = repo.create_install_state(ctx.workspace_id, ctx.user["id"])
    return {"url": github_app.install_url(settings, state)}


@public.get("/callback")
def callback(installation_id: int, state: str, setup_action: str | None = None, repo: Repository = Depends(get_repo),
             settings: Settings = Depends(get_settings), client: GitHubClient = Depends(get_client)):
    """GitHub redirects the browser here after install. `state` ties it to the user + workspace that started it (single use, 10 min)."""
    dash = settings.dashboard_url.rstrip("/")
    st = repo.consume_install_state(state)
    if st is None:
        return RedirectResponse(f"{dash}/repositories?github=invalid_state", status_code=303)
    try:
        info = client.installation(installation_id)      # confirms the installation really belongs to our App
    except GitHubError:
        return RedirectResponse(f"{dash}/repositories?github=verification_failed", status_code=303)
    inst = repo.upsert_installation(st["workspace_id"], installation_id, info["account"]["login"], info["account"].get("type"), st["user_id"])
    if inst is None:
        return RedirectResponse(f"{dash}/repositories?github=installation_in_use", status_code=303)
    repo.audit(st["workspace_id"], st["user_id"], "github.installed", "github_installation", str(installation_id), {"account": info["account"]["login"]})
    try:
        repo.sync_repositories(st["workspace_id"], installation_id, client.list_repositories(installation_id))
    except GitHubError:
        logger.warning("github_initial_sync_failed")
    return RedirectResponse(f"{dash}/repositories?github=connected", status_code=303)


@router.post("/github/sync")
def sync(ctx: WorkspaceContext = Depends(workspace_access("admin")), repo: Repository = Depends(get_repo), client: GitHubClient = Depends(get_client)):
    total = 0
    for inst in repo.list_installations(ctx.workspace_id):
        try:
            total += repo.sync_repositories(ctx.workspace_id, inst["installation_id"], client.list_repositories(inst["installation_id"]))
        except GitHubError as exc:
            raise HTTPException(502, f"GitHub request failed ({exc.status})") from None
    return {"synced": total}


@router.get("/repositories")
def list_repositories(ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo)):
    return [_repo_out(r) for r in repo.list_repositories(ctx.workspace_id)]


def _get_repo_or_404(repo: Repository, ctx: WorkspaceContext, repository_id: uuid.UUID) -> dict:
    r = repo.get_repository(ctx.workspace_id, repository_id)
    if r is None:
        raise HTTPException(404, "Repository not found")
    return r


@router.get("/repositories/{repository_id}")
def get_repository(repository_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo)):
    r = _get_repo_or_404(repo, ctx, repository_id)
    return {**_repo_out(r), "summary": repo.repository_summary(ctx.workspace_id, repository_id),
            "scans": [scan_out(s) for s in repo.list_scans(ctx.workspace_id, repository_id, 10)]}


@router.post("/repositories/{repository_id}/connect")
def connect(repository_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("admin")), repo: Repository = Depends(get_repo)):
    _get_repo_or_404(repo, ctx, repository_id)
    r = repo.set_repository_connected(ctx.workspace_id, repository_id, True)
    repo.audit(ctx.workspace_id, ctx.user["id"], "repository.connected", "repository", str(repository_id), {"name": r["full_name"]})
    return _repo_out(r)


@router.post("/repositories/{repository_id}/disconnect")
def disconnect(repository_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("admin")), repo: Repository = Depends(get_repo)):
    _get_repo_or_404(repo, ctx, repository_id)
    r = repo.set_repository_connected(ctx.workspace_id, repository_id, False)
    repo.audit(ctx.workspace_id, ctx.user["id"], "repository.disconnected", "repository", str(repository_id), {"name": r["full_name"]})
    return _repo_out(r)


@router.post("/repositories/{repository_id}/scans", status_code=202)
def start_scan(repository_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("developer")), repo: Repository = Depends(get_repo),
               client: GitHubClient = Depends(get_client)):
    r = _get_repo_or_404(repo, ctx, repository_id)
    if not r["connected"]:
        raise HTTPException(409, "Connect the repository before scanning")
    try:
        sha = client.head_sha(r["installation_id"], r["full_name"], r["default_branch"])
    except GitHubError as exc:
        raise HTTPException(502, f"GitHub request failed ({exc.status})") from None
    scan, created = repo.enqueue_scan(ctx.workspace_id, repository_id, sha, f"refs/heads/{r['default_branch']}", "manual", user_id=ctx.user["id"])
    if created:
        repo.audit(ctx.workspace_id, ctx.user["id"], "scan.requested", "scan", str(scan["id"]), {"commit": sha[:12]})
    return {**scan_out(scan), "already_queued": not created}


@router.get("/repositories/{repository_id}/scans")
def list_scans(repository_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo)):
    _get_repo_or_404(repo, ctx, repository_id)
    return [scan_out(s) for s in repo.list_scans(ctx.workspace_id, repository_id)]


@router.get("/scans/{scan_id}")
def get_scan(scan_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo)):
    s = repo.get_scan(ctx.workspace_id, scan_id)
    if s is None:
        raise HTTPException(404, "Scan not found")
    return {**scan_out(s), "repository": s["full_name"]}


# ----------------------------------------------------------------------------- webhook
@public.post("/webhook")
async def webhook(request: Request, x_github_event: str = Header(default=""), x_github_delivery: str = Header(default=""),
                  x_hub_signature_256: str | None = Header(default=None), repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
    body = await request.body()
    if len(body) > 5_000_000:
        raise HTTPException(413, "Payload too large")
    if not github_app.verify_webhook(settings.github_webhook_secret, body, x_hub_signature_256):
        raise HTTPException(401, "Invalid signature")
    if not x_github_delivery or not repo.record_delivery(x_github_delivery, x_github_event):
        return {"status": "duplicate"}
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(400, "Invalid JSON") from None
    return {"status": "ok", "handled": handle_event(repo, x_github_event, payload)}


def handle_event(repo: Repository, event: str, p: dict) -> str:
    inst_id = (p.get("installation") or {}).get("id")
    inst = repo.get_installation_by_id(inst_id) if inst_id else None
    if event == "ping":
        return "pong"
    if inst is None:
        return "ignored_unknown_installation"
    if event == "installation":
        if p.get("action") == "deleted":
            repo.delete_installation(inst_id)
        elif p.get("action") in ("suspend", "unsuspend"):
            repo.set_installation_suspended(inst_id, p["action"] == "suspend")
        return f"installation_{p.get('action')}"
    if event == "installation_repositories":
        repo.sync_repositories(inst["workspace_id"], inst_id, p.get("repositories_added") or [])
        if p.get("repositories_removed"):
            repo.remove_repositories(inst_id, [r["full_name"] for r in p["repositories_removed"]])
        return "repositories_updated"
    full = (p.get("repository") or {}).get("full_name")
    r = repo.get_repository_by_name(inst_id, full) if full else None
    if r is None or not r["connected"] or inst["suspended_at"]:
        return "ignored_repository_not_connected"
    if event == "push":
        sha, ref = p.get("after") or "", p.get("ref") or ""
        if p.get("deleted") or not sha or set(sha) == {"0"} or not ref.startswith("refs/heads/"):
            return "ignored_push"
        default = ref == f"refs/heads/{r['default_branch']}"
        repo.enqueue_scan(r["workspace_id"], r["id"], sha, ref, "push", head_branch=ref.removeprefix("refs/heads/")) if default else None
        return "scan_queued" if default else "ignored_non_default_branch"       # feature branches are covered by their pull request
    if event == "pull_request" and p.get("action") in ("opened", "synchronize", "reopened"):
        pr = p["pull_request"]
        repo.enqueue_scan(r["workspace_id"], r["id"], pr["head"]["sha"], f"refs/pull/{pr['number']}/head", "pull_request", pr["number"], pr["head"].get("ref"))
        return "scan_queued"
    return "ignored_event"
