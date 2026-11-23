"""Read APIs for monitoring charts, logs and traces. Viewer role and above."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app import telemetry_queries as q
from app.clickhouse import QueryExecutor, TelemetryUnavailable
from app.deps import WorkspaceContext, get_repo, workspace_access
from app.repository import Repository

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/applications/{application_id}/telemetry", tags=["telemetry"])
TRACE_ID = re.compile(r"^[0-9a-fA-F]{32}$")


def get_executor(request: Request) -> QueryExecutor:
    ex = getattr(request.app.state, "telemetry", None)
    if ex is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail={
            "code": "telemetry_store_not_configured",
            "message": "The telemetry store (ClickHouse) is not configured for this deployment. Set CLICKHOUSE_URL.",
        })
    return ex


class Ctx:
    """Resolves and authorises the application, then exposes a tenant-bound Scope."""

    def __init__(self, application_id: uuid.UUID, range: str | None = Query(default=None, alias="range"),
                 start: datetime | None = Query(default=None, alias="from"), end: datetime | None = Query(default=None, alias="to"),
                 ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo),
                 executor: QueryExecutor = Depends(get_executor)) -> None:
        app = repo.get_application(ctx.workspace_id, application_id)   # 404 unless it is in THIS workspace
        if app is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
        try:
            t0, t1 = q.resolve_range(range, start, end)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
        self.scope = q.Scope(str(ctx.workspace_id), str(application_id), t0, t1)
        self.executor = executor
        self.meta = {"synthetic": bool(app["is_synthetic"]), "application": app["name"], "environment": app["environment"],
                     "from": t0.isoformat(), "to": t1.isoformat()}

    def run(self, built: tuple[str, dict]) -> list[dict]:
        try:
            return self.executor.query(*built)
        except TelemetryUnavailable:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail={
                "code": "telemetry_store_unavailable", "message": "The telemetry store could not be queried; try again shortly."}) from None


def _bad(exc: ValueError):
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.get("/summary")
def summary(c: Ctx = Depends()):
    return {**c.meta, "summary": q.shape_summary(c.run(q.summary_query(c.scope)), c.scope),
            "status_distribution": q.shape_status(c.run(q.status_query(c.scope)))}


@router.get("/timeseries")
def timeseries(c: Ctx = Depends()):
    return {**c.meta, **q.shape_timeseries(c.run(q.timeseries_query(c.scope)), c.scope)}


@router.get("/endpoints")
def endpoints(sort: str = "requests", limit: int = Query(default=50, ge=1, le=200), c: Ctx = Depends()):
    try:
        built = q.endpoints_query(c.scope, sort, limit)
    except ValueError as exc:
        raise _bad(exc) from None
    return {**c.meta, "endpoints": q.shape_endpoints(c.run(built))}


@router.get("/runtime")
def runtime(c: Ctx = Depends()):
    return {**c.meta, **q.shape_runtime(c.run(q.runtime_query(c.scope)), c.scope),
            "note": "Process-level metrics of the instrumented Node.js process; not host or container metrics."}


@router.get("/logs")
def logs(severity: list[str] | None = Query(default=None), search: str | None = Query(default=None, max_length=200),
         trace_id: str | None = Query(default=None, max_length=64), limit: int = Query(default=100, ge=1, le=500),
         offset: int = Query(default=0, ge=0, le=100000), c: Ctx = Depends()):
    try:
        built = q.logs_query(c.scope, severity, search, trace_id, limit, offset)
    except ValueError as exc:
        raise _bad(exc) from None
    return {**c.meta, "logs": q.shape_logs(c.run(built)), "limit": limit, "offset": offset}


@router.get("/traces")
def traces(only_errors: bool = False, min_duration_ms: float | None = Query(default=None, ge=0),
           limit: int = Query(default=50, ge=1, le=200), c: Ctx = Depends()):
    return {**c.meta, "traces": q.shape_traces(c.run(q.traces_query(c.scope, only_errors, min_duration_ms, limit)))}


@router.get("/traces/{trace_id}")
def trace_detail(trace_id: str, c: Ctx = Depends()):
    if not TRACE_ID.match(trace_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "trace_id must be 32 hex characters")
    spans = q.shape_trace_detail(c.run(q.trace_detail_query(c.scope, trace_id)))
    if not spans:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trace not found in this time range")
    return {**c.meta, "trace_id": trace_id, "spans": spans, "logs": q.shape_logs(c.run(q.trace_logs_query(c.scope, trace_id)))}
