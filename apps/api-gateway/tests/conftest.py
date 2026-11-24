"""
Integration tests run against a real PostgreSQL (TEST_DATABASE_URL). If it is not
set they are SKIPPED (and reported as skipped), never silently passed.
"""

from __future__ import annotations

import os
import pathlib
import uuid

import psycopg
import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
MIGRATIONS = pathlib.Path(__file__).resolve().parents[3] / "packages" / "db" / "migrations"

os.environ.setdefault("INTERNAL_API_TOKEN", "test-internal-token")
os.environ.setdefault("AUTH_RATE_LIMIT_PER_MINUTE", "1000")
os.environ.setdefault("ENVIRONMENT", "development")
if TEST_DB:
    os.environ["DATABASE_URL"] = TEST_DB


def pytest_collection_modifyitems(config, items):
    if TEST_DB:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set - integration test skipped")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def db_ready():
    """Apply any pending migrations with the project's own runner (so tests exercise it too)."""
    import sys

    sys.path.insert(0, str(MIGRATIONS.parent / "src"))
    import migrate

    with psycopg.connect(TEST_DB) as conn:
        applied = migrate.fetch_applied(conn)
        conn.commit()
        for m in migrate.discover_migrations():
            if m.version not in applied:
                migrate.apply_migration(conn, m)
    return True


@pytest.fixture(scope="session")
def client(db_ready):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app(), base_url="http://testserver") as c:
        yield c


@pytest.fixture
def make_user(client):
    """Signs up a fresh user (own workspace). Returns helper dict with auth headers."""

    def _make(prefix="u"):
        client.cookies.clear()
        email = f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"
        r = client.post("/v1/auth/signup", json={"email": email, "password": "correct-horse-9", "workspace_name": f"WS {prefix}"})
        assert r.status_code == 201, r.text
        body = r.json()
        return {"email": email, "token": body["access_token"], "workspace_id": body["workspace"]["id"],
                "user_id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['access_token']}"}}

    return _make


@pytest.fixture
def db():
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        yield conn


# Make locally installed analysis tools (semgrep, gitleaks, ...) discoverable for scan tests, if present.
_S = pathlib.Path("/tmp/claude-0/-home-claude/162ae94c-78d8-5309-ab2c-5867527ed50b/scratchpad")
for _d in (_S / "semgrepenv" / "bin", _S / "tools"):
    if _d.exists():
        os.environ["SCANNER_TOOL_PATH"] = os.pathsep.join(filter(None, [os.environ.get("SCANNER_TOOL_PATH"), str(_d)]))
