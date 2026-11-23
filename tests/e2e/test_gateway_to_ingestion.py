"""
End-to-end (local, real HTTP between processes): API gateway + PostgreSQL + ingestion service.
Requires TEST_DATABASE_URL; otherwise SKIPPED. Kafka/ClickHouse are replaced by an in-memory
sink, so this verifies key->tenant resolution and data flow into the pipeline's entry point,
NOT Kafka/ClickHouse themselves.
"""

import os
import pathlib
import socket
import subprocess
import sys
import time
import uuid

import httpx
import pytest

DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL not set - e2e skipped")
ROOT = pathlib.Path(__file__).resolve().parents[2]
NS = 1_760_000_000_000_000_000


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait(url, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.3)
    raise RuntimeError(f"{url} did not come up")


@pytest.fixture(scope="module")
def stack():
    gw_port, ing_port = free_port(), free_port()
    env = {**os.environ, "DATABASE_URL": DB, "INTERNAL_API_TOKEN": "e2e-token", "ENVIRONMENT": "development",
           "GATEWAY_URL": f"http://127.0.0.1:{gw_port}", "PUBLIC_INGESTION_URL": f"http://127.0.0.1:{ing_port}",
           "KEY_CACHE_TTL_SECONDS": "0", "KEY_NEGATIVE_CACHE_TTL_SECONDS": "0"}
    gw = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(gw_port), "--log-level", "warning"],
                          cwd=ROOT / "apps/api-gateway", env=env)
    ing = subprocess.Popen([sys.executable, str(ROOT / "tests/e2e/run_ingestion_with_fakes.py"), str(ing_port)],
                           cwd=ROOT / "apps/ingestion-service",
                           env={**env, "PYTHONPATH": str(ROOT / "apps/ingestion-service")})
    try:
        wait(f"http://127.0.0.1:{gw_port}/readyz")
        wait(f"http://127.0.0.1:{ing_port}/healthz")
        yield {"gw": f"http://127.0.0.1:{gw_port}", "ing": f"http://127.0.0.1:{ing_port}"}
    finally:
        for p in (gw, ing):
            p.terminate()
            p.wait(10)


def signup(stack):
    email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
    r = httpx.post(f"{stack['gw']}/v1/auth/signup", json={"email": email, "password": "correct-horse-9"}).json()
    return {"ws": r["workspace"]["id"], "h": {"Authorization": f"Bearer {r['access_token']}"}}


def create_app_key(stack, u, name):
    r = httpx.post(f"{stack['gw']}/v1/workspaces/{u['ws']}/applications", headers=u["h"],
                   json={"name": name, "environment": "staging"})
    assert r.status_code == 201, r.text
    return r.json()


def otlp_trace(status_code=500):
    return {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "shop-api"}}]},
            "scopeSpans": [{"spans": [{"traceId": "a" * 32, "spanId": "b" * 16, "name": "GET /orders", "kind": 2,
                                       "startTimeUnixNano": str(NS), "endTimeUnixNano": str(NS + 120_000_000),
                                       "attributes": [{"key": "http.status_code", "value": {"intValue": str(status_code)}}],
                                       "status": {"code": 2}}]}]}]}


def stored(stack):
    return httpx.get(f"{stack['ing']}/_test/events").json()


def test_full_flow_key_to_tenant_to_status(stack):
    u = signup(stack)
    created = create_app_key(stack, u, "e2e-app")
    key, app_id = created["ingestion_key"], created["application"]["id"]
    assert created["application"]["connection_status"] == "waiting_for_telemetry"

    before = len(stored(stack))
    r = httpx.post(f"{stack['ing']}/otlp/v1/traces", json=otlp_trace(), headers={"X-Ingestion-Key": key})
    assert r.status_code == 200, r.text
    new = stored(stack)[before:]
    assert new and all(e["workspace_id"] == u["ws"] for e in new)
    assert new[0]["attributes"]["platform.application_id"] == app_id

    time.sleep(0.5)  # telemetry-seen is reported after the response
    got = httpx.get(f"{stack['gw']}/v1/workspaces/{u['ws']}/applications/{app_id}", headers=u["h"]).json()["application"]
    assert got["connection_status"] == "connected" and got["last_telemetry_at"]


def test_other_tenants_key_cannot_write_into_my_workspace(stack):
    a, b = signup(stack), signup(stack)
    key_b = create_app_key(stack, b, "b-app")["ingestion_key"]
    claimed = {"idempotency_key": "x", "events": [{"kind": "log", "workspace_id": a["ws"], "service_name": "s",
               "timestamp": "2026-08-05T10:00:00Z", "severity": "error", "message": "spoof attempt"}]}
    before = len(stored(stack))
    assert httpx.post(f"{stack['ing']}/v1/telemetry", json=claimed, headers={"X-Ingestion-Key": key_b}).status_code == 202
    new = stored(stack)[before:]
    assert [e["workspace_id"] for e in new] == [b["ws"]]          # forced to B, never A


def test_rotated_and_revoked_keys_stop_working(stack):
    u = signup(stack)
    c = create_app_key(stack, u, "rot-app")
    old, app_id = c["ingestion_key"], c["application"]["id"]
    new = httpx.post(f"{stack['gw']}/v1/workspaces/{u['ws']}/applications/{app_id}/rotate-key", headers=u["h"]).json()["ingestion_key"]
    post = lambda k: httpx.post(f"{stack['ing']}/otlp/v1/traces", json=otlp_trace(), headers={"X-Ingestion-Key": k}).status_code
    assert post(new) == 200
    assert post(old) == 401                      # rotated-out key is rejected (cache disabled in this run)
    assert post("ipk_aaaaaaaaaa_forged") == 401
    httpx.delete(f"{stack['gw']}/v1/workspaces/{u['ws']}/applications/{app_id}", headers=u["h"])
    assert post(new) == 401                      # revoking the application kills its key
