"""
REAL instrumentation path: the sample Express app (using @incident-platform/node) sends actual OTLP
over HTTP to the real ingestion service with a real per-application key issued by the real gateway.
Traffic and the injected faults are SYNTHETIC test data created by this test; they use a dedicated
workspace so nothing here can mix with customer telemetry.
Requires TEST_DATABASE_URL and Node (SKIPPED otherwise). Kafka/ClickHouse are in-memory stand-ins.
"""

import os
import pathlib
import shutil
import subprocess
import time

import httpx
import pytest

from tests.e2e.helpers import DB, ROOT, create_app_key, free_port, signup, stack, stored, wait  # noqa: F401

pytestmark = [
    pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL not set - e2e skipped"),
    pytest.mark.skipif(shutil.which("node") is None, reason="node not installed - e2e skipped"),
]
SAMPLE = ROOT / "examples" / "sample-express-app"


@pytest.fixture(scope="module")
def sample(stack):
    if not (SAMPLE / "node_modules").exists():
        pytest.skip("run `npm install` in examples/sample-express-app first")
    u = signup(stack)
    created = create_app_key(stack, u, "sample-express-app")
    port = free_port()
    env = {**os.environ, "PORT": str(port), "FAULT_INJECTION": "1", "INCIDENT_PLATFORM_ENDPOINT": stack["ing"],
           "INCIDENT_PLATFORM_KEY": created["ingestion_key"], "INCIDENT_PLATFORM_APP": "sample-express-app",
           "INCIDENT_PLATFORM_ENV": "staging", "INCIDENT_PLATFORM_RELEASE": "0.1.0",
           "INCIDENT_PLATFORM_COMMIT": "abc1234def", "INCIDENT_PLATFORM_METRIC_INTERVAL_MS": "1000"}
    proc = subprocess.Popen(["node", "server.js"], cwd=SAMPLE, env=env, stdout=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        wait(base + "/healthz")
        yield {"base": base, "ws": u["ws"], "app_id": created["application"]["id"], "u": u, "proc": proc}
    finally:
        proc.terminate()
        proc.wait(15)


def traffic(base, rounds=6):
    subprocess.run(["node", "traffic.js", base, str(rounds)], cwd=SAMPLE, check=True, capture_output=True, timeout=60)


def mine(stack, sample):
    return [e for e in stored(stack) if e["workspace_id"] == sample["ws"]]


def wait_for(pred, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.5)
    return False


def test_real_requests_become_server_spans_with_route_status_and_release(stack, sample):
    traffic(sample["base"])
    assert wait_for(lambda: any(e["kind"] == "trace_span" and e["attributes"].get("http.route") == "/api/foods" for e in mine(stack, sample)))
    spans = [e for e in mine(stack, sample) if e["kind"] == "trace_span"]
    foods = next(s for s in spans if s["attributes"].get("http.route") == "/api/foods")
    assert foods["service_name"] == "sample-express-app" and foods["duration_ms"] >= 0
    assert foods["attributes"]["platform.environment"] == "staging"
    assert foods["attributes"]["service.version"] == "0.1.0" or foods["attributes"].get("deployment.environment") == "staging"
    statuses = {int(s["attributes"].get("http.status_code") or s["attributes"].get("http.response.status_code") or 0) for s in spans}
    assert {200, 401, 400} & statuses            # login failures + empty cart produce real 4xx


def test_everything_is_bound_to_the_applications_workspace(stack, sample):
    assert wait_for(lambda: len(mine(stack, sample)) > 0)
    assert all(e["attributes"]["platform.application_id"] == sample["app_id"] for e in mine(stack, sample))


def test_process_metrics_arrive_and_are_labelled_process_scope(stack, sample):
    assert wait_for(lambda: any(e["kind"] == "metric" and e["metric_name"] == "process.memory.usage" for e in mine(stack, sample)), 25)
    names = {e["metric_name"] for e in mine(stack, sample) if e["kind"] == "metric"}
    assert {"process.memory.usage", "nodejs.heap.used", "nodejs.eventloop.lag.p99", "process.cpu.utilization"} <= names
    mem = next(e for e in mine(stack, sample) if e["kind"] == "metric" and e["metric_name"] == "process.memory.usage")
    assert mem["attributes"]["scope"] == "process" and mem["value"] > 1_000_000   # no host-level claims


def test_app_logs_carry_trace_ids(stack, sample):
    assert wait_for(lambda: any(e["kind"] == "log" and e["message"] == "order placed" for e in mine(stack, sample)))
    log = next(e for e in mine(stack, sample) if e["kind"] == "log" and e["message"] == "order placed")
    assert log["trace_id"] and len(log["trace_id"]) == 32


def test_injected_fault_produces_error_spans_stack_logs_and_correlated_trace_ids(stack, sample):
    assert httpx.post(sample["base"] + "/_fault", json={"mode": "errors"}).status_code == 200
    traffic(sample["base"], rounds=4)
    httpx.post(sample["base"] + "/_fault", json={"mode": "none"})

    def failing():
        return [e for e in mine(stack, sample) if e["kind"] == "trace_span" and e["status"] == "error"
                and e["attributes"].get("http.route") == "/api/orders"]

    assert wait_for(lambda: len(failing()) >= 3)
    err_trace_ids = {e["trace_id"] for e in failing()}
    err_logs = [e for e in mine(stack, sample) if e["kind"] == "log" and e["severity"] == "error" and "payment gateway" in e["message"]]
    assert err_logs, "expected the exception to be logged with its stack"
    assert any(l["trace_id"] in err_trace_ids for l in err_logs)       # log <-> trace correlation
    assert "app/server.js" in err_logs[0]["message"] or "server.js" in err_logs[0]["message"]  # stack trace kept


def test_secrets_and_query_strings_never_reach_the_platform(stack, sample):
    httpx.get(sample["base"] + "/api/foods?token=SUPERSECRETTOKENVALUE1234567890&email=jane@example.com")
    assert wait_for(lambda: any(e["kind"] == "trace_span" for e in mine(stack, sample)[-20:]))
    time.sleep(3)
    blob = str(mine(stack, sample))
    assert "SUPERSECRETTOKENVALUE" not in blob and "jane@example.com" not in blob
    assert "synthetic-session-token" not in blob and "test-password" not in blob


def test_app_status_flips_to_connected(stack, sample):
    assert wait_for(lambda: httpx.get(f"{stack['gw']}/v1/workspaces/{sample['ws']}/applications/{sample['app_id']}",
                                      headers=sample["u"]["h"]).json()["application"]["connection_status"] == "connected")
