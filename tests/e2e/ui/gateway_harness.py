"""UI end-to-end harness: the REAL api-gateway (real Postgres, auth, routes) with an embedded ClickHouse (chdb)
as the telemetry store, plus a TEST-ONLY seeding endpoint. Never deployed; used by run_ui_e2e.py."""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api-gateway"))

import uvicorn  # noqa: E402
from fastapi import Request  # noqa: E402

from app.main import create_app  # noqa: E402
from app.routes.incidents import process_application  # noqa: E402
from app.config import get_settings  # noqa: E402
from tests.chdb_support import ChdbExecutor, log, span  # noqa: E402

app = create_app()
store = ChdbExecutor()
app.state.telemetry = store


def ago(minutes: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


@app.post("/__test/seed/{workspace_id}/{application_id}")
def seed(workspace_id: str, application_id: str, request: Request):
    rows = []
    for m in range(60, 5, -1):
        for i in range(25):
            rows.append(span(workspace_id, application_id, ago(m), "/api/foods", "GET", 500 if (m % 11 == 0 and i == 0) else 200, 70 + i))
    for m in range(5, 0, -1):
        for i in range(30):
            rows.append(span(workspace_id, application_id, ago(m - 0.5), "/api/orders", "POST", 500 if i < 18 else 201, 90))
    rows.append(log(workspace_id, application_id, ago(2), "MongoNetworkError: connection closed password=hunter2", "error", trace="a" * 32))
    store.insert(rows)
    repo = request.app.state.repo
    row = repo.get_application(uuid.UUID(workspace_id), uuid.UUID(application_id))
    repo.pool.connection().__enter__().execute("UPDATE applications SET last_telemetry_at=now() WHERE id=%s", (application_id,))
    found = process_application(repo, store, row, get_settings())
    return {"incidents": [str(i["id"]) for i in found]}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8005")), log_level="warning")
