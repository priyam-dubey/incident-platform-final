"""Findings: list/filter, detail, triage, AI explanation, CSV/PDF export. All workspace-scoped."""

from __future__ import annotations

import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from incident_llm import LLMClient
from incident_llm.errors import LLMError
from pydantic import BaseModel, ConfigDict, Field

from app import explain, reports
from app.deps import WorkspaceContext, get_repo, workspace_access
from app.repository import Repository

router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["code"])
SEVERITIES = {"critical", "high", "medium", "low", "info"}
STATUSES = {"open", "fixed", "ignored", "false_positive", "accepted_risk"}
CATEGORIES = {"sast", "lint", "types", "dependency", "secret", "iac", "other"}


def finding_out(f: dict, detail: bool = False) -> dict:
    out = {"id": str(f["id"]), "repository_id": str(f["repository_id"]), "repository": f.get("repository"), "tool": f["tool"], "rule_id": f["rule_id"],
           "category": f["category"], "severity": f["severity"], "title": f["title"], "file_path": f["file_path"], "start_line": f["start_line"],
           "end_line": f["end_line"], "cwe": f["cwe"], "package_name": f["package_name"], "package_version": f["package_version"],
           "fixed_version": f["fixed_version"], "status": f["status"], "first_seen_commit": f["first_seen_commit"], "last_seen_commit": f["last_seen_commit"],
           "reintroduced_count": f["reintroduced_count"], "updated_at": f["updated_at"].isoformat()}
    if detail:
        out |= {"message": f["message"], "code_snippet": f["code_snippet"], "triage_note": f["triage_note"], "explanation": f["explanation"],
                "fixed_at": f["fixed_at"].isoformat() if f["fixed_at"] else None}
    return out


def _check(value, allowed, name):
    if value and value not in allowed:
        raise HTTPException(422, f"{name} must be one of {sorted(allowed)}")
    return value


@router.get("/findings")
def list_findings(repository_id: uuid.UUID | None = None, status: str | None = None, severity: str | None = None, tool: str | None = Query(None, max_length=40),
                  category: str | None = None, q: str | None = Query(None, max_length=100), sort: Literal["severity", "recent", "file"] = "severity",
                  limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo)):
    rows, total = repo.list_findings(ctx.workspace_id, repository_id, _check(status, STATUSES, "status"), _check(severity, SEVERITIES, "severity"), tool,
                                     _check(category, CATEGORIES, "category"), q, sort, limit, offset)
    return {"total": total, "items": [finding_out(r) for r in rows]}


@router.get("/findings/{finding_id}")
def get_finding(finding_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo)):
    f = repo.get_finding(ctx.workspace_id, finding_id)
    if f is None:
        raise HTTPException(404, "Finding not found")
    return finding_out(f, detail=True)


class Triage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "ignored", "false_positive", "accepted_risk"]
    note: str | None = Field(default=None, max_length=1000)


@router.post("/findings/{finding_id}/triage")
def triage(finding_id: uuid.UUID, body: Triage, ctx: WorkspaceContext = Depends(workspace_access("developer")), repo: Repository = Depends(get_repo)):
    if body.status != "open" and not body.note:
        raise HTTPException(422, "A note explaining the decision is required")
    f = repo.triage_finding(ctx.workspace_id, finding_id, body.status, body.note, ctx.user["id"])
    if f is None:
        raise HTTPException(404, "Finding not found")
    repo.audit(ctx.workspace_id, ctx.user["id"], f"finding.{body.status}", "finding", str(finding_id))
    return finding_out(repo.get_finding(ctx.workspace_id, finding_id), detail=True)


@router.post("/findings/{finding_id}/explain")
def explain_finding(finding_id: uuid.UUID, request: Request, ctx: WorkspaceContext = Depends(workspace_access("developer")), repo: Repository = Depends(get_repo)):
    f = repo.get_finding(ctx.workspace_id, finding_id)
    if f is None:
        raise HTTPException(404, "Finding not found")
    llm = getattr(request.app.state, "llm", None) or LLMClient()
    st = llm.status()
    if st["state"] != "configured":
        raise HTTPException(503, detail={"code": f"llm_{st['state']}", "message": st["detail"]})
    try:
        result = asyncio.run(explain.explain(llm, f))
    except LLMError as exc:
        raise HTTPException(502, detail={"code": f"llm_{exc.code}", "message": "The AI provider could not produce an explanation."}) from None
    repo.save_explanation(ctx.workspace_id, finding_id, result)
    repo.audit(ctx.workspace_id, ctx.user["id"], "finding.explained", "finding", str(finding_id))
    return result


@router.get("/repositories/{repository_id}/report.csv")
def report_csv(repository_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo)):
    r = repo.get_repository(ctx.workspace_id, repository_id)
    if r is None:
        raise HTTPException(404, "Repository not found")
    rows, _ = repo.list_findings(ctx.workspace_id, repository_id, limit=200, sort="severity")
    all_rows, off = list(rows), 200
    while len(rows) == 200 and off < 5000:
        rows, _ = repo.list_findings(ctx.workspace_id, repository_id, limit=200, offset=off)
        all_rows += rows
        off += 200
    name = r["full_name"].replace("/", "-")
    return Response(reports.findings_csv(all_rows), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="findings-{name}.csv"'})


@router.get("/repositories/{repository_id}/report.pdf")
def report_pdf(repository_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo)):
    r = repo.get_repository(ctx.workspace_id, repository_id)
    if r is None:
        raise HTTPException(404, "Repository not found")
    rows, _ = repo.list_findings(ctx.workspace_id, repository_id, status="open", limit=200, sort="severity")
    pdf = reports.findings_pdf(r["full_name"], repo.repository_summary(ctx.workspace_id, repository_id), rows)
    name = r["full_name"].replace("/", "-")
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="findings-{name}.pdf"'})
