"""See helpers.py for what this e2e layer does and does not cover."""
import time

import httpx
import pytest

from tests.e2e.helpers import DB, create_app_key, otlp_trace, signup, stack, stored  # noqa: F401

pytestmark = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL not set - e2e skipped")


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
