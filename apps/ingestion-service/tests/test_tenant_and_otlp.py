"""Tenant binding, sanitisation and OTLP conversion/receiver tests (no external services)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.otlp import OtlpError, convert_logs, convert_metrics, convert_traces
from app.sanitize import clean_attributes, is_sensitive_key
from app.tenant_auth import GatewayKeyResolver, TenantContext
from tests.conftest import FakeEventPublisher, FakeTelemetryWriter

WS_A, WS_B = uuid.uuid4(), uuid.uuid4()
CLIENT_CLAIMED_WS = "99999999-9999-9999-9999-999999999999"
NS = 1_760_000_000_000_000_000


class FakeResolver:
    def __init__(self):
        self.seen: list[str] = []

    async def close(self):
        pass

    async def resolve(self, key: str):
        table = {
            "key-a": TenantContext(str(uuid.uuid4()), WS_A, uuid.uuid4(), "app-a", "production", False),
            "key-b": TenantContext(str(uuid.uuid4()), WS_B, uuid.uuid4(), "app-b", "staging", True),
        }
        return table.get(key)

    async def report_seen(self, ctx):
        self.seen.append(str(ctx.application_id))


@pytest.fixture
def saas_client(monkeypatch):
    monkeypatch.setenv("GATEWAY_URL", "http://gateway.test")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "t")
    get_settings.cache_clear()
    pub, wr, res = FakeEventPublisher(), FakeTelemetryWriter(), FakeResolver()
    app = create_app(lambda s: pub, lambda s: wr)
    with TestClient(app) as c:
        app.state.key_resolver = res
        c.pub, c.wr, c.res = pub, wr, res
        yield c
    get_settings.cache_clear()


def envelope(ws=CLIENT_CLAIMED_WS, msg="boom"):
    return {"idempotency_key": "k1", "events": [{
        "kind": "log", "workspace_id": ws, "service_name": "svc", "timestamp": "2026-08-05T10:00:00Z",
        "severity": "error", "message": msg, "attributes": {"authorization": "Bearer abc", "route": "/x"}}]}


# ---------------- tenant binding ----------------
def test_key_decides_tenant_not_payload(saas_client):
    r = saas_client.post("/v1/telemetry", json=envelope(), headers={"X-Ingestion-Key": "key-a"})
    assert r.status_code == 202
    stored = saas_client.wr.written[0]
    assert stored.workspace_id == WS_A != uuid.UUID(CLIENT_CLAIMED_WS)
    assert saas_client.pub.published[0][1].workspace_id == WS_A


def test_two_keys_write_to_their_own_tenants(saas_client):
    saas_client.post("/v1/telemetry", json=envelope(), headers={"X-Ingestion-Key": "key-a"})
    saas_client.post("/v1/telemetry", json=envelope(), headers={"X-Ingestion-Key": "key-b"})
    assert [e.workspace_id for e in saas_client.wr.written] == [WS_A, WS_B]


def test_synthetic_provenance_is_tagged(saas_client):
    saas_client.post("/v1/telemetry", json=envelope(), headers={"X-Ingestion-Key": "key-b"})
    assert saas_client.wr.written[0].attributes["platform.synthetic"] is True
    saas_client.post("/v1/telemetry", json=envelope(), headers={"X-Ingestion-Key": "key-a"})
    assert saas_client.wr.written[1].attributes["platform.synthetic"] is False


def test_unknown_and_missing_key_rejected(saas_client):
    assert saas_client.post("/v1/telemetry", json=envelope(), headers={"X-Ingestion-Key": "nope"}).status_code == 401
    assert saas_client.post("/v1/telemetry", json=envelope()).status_code == 401
    assert saas_client.wr.written == []


def test_static_legacy_key_not_accepted_in_gateway_mode(saas_client):
    assert saas_client.post("/v1/telemetry", json=envelope(), headers={"X-Ingestion-Key": "dev-local-ingestion-key"}).status_code == 401


def test_telemetry_seen_reported(saas_client):
    saas_client.post("/v1/telemetry", json=envelope(), headers={"X-Ingestion-Key": "key-a"})
    assert len(saas_client.res.seen) == 1


# ---------------- redaction ----------------
def test_secrets_redacted_before_storage(saas_client):
    saas_client.post("/v1/telemetry", json=envelope(msg="user bob@example.com failed api_key=AAAAAAAAAAAAAAAAAAAAAAAA"),
                     headers={"X-Ingestion-Key": "key-a"})
    e = saas_client.wr.written[0]
    assert "bob@example.com" not in e.message and "AAAAAAAAAAAA" not in e.message
    assert e.attributes["authorization"] == "[REDACTED:KEY]" and e.attributes["route"] == "/x"
    assert "bob@example.com" not in str(saas_client.pub.published[0][1])


def test_sensitive_key_detection():
    for k in ("Authorization", "http.request.header.cookie", "user.password", "X-Api-Key", "card_number"):
        assert is_sensitive_key(k)
    assert not is_sensitive_key("http.route")
    assert clean_attributes({"password": "x", "a": "b" * 5000})["a"].endswith("…[truncated]")


# ---------------- OTLP conversion ----------------
def span(**o):
    base = {"traceId": "a" * 32, "spanId": "b" * 16, "name": "GET /api/orders", "kind": 2,
            "startTimeUnixNano": str(NS), "endTimeUnixNano": str(NS + 250_000_000),
            "attributes": [{"key": "http.status_code", "value": {"intValue": "500"}},
                           {"key": "http.route", "value": {"stringValue": "/api/orders"}}],
            "status": {"code": 2, "message": "boom"}}
    base.update(o)
    return base


def traces_body(*spans, svc="shop"):
    return {"resourceSpans": [{"resource": {"attributes": [
        {"key": "service.name", "value": {"stringValue": svc}},
        {"key": "deployment.environment", "value": {"stringValue": "production"}}]},
        "scopeSpans": [{"spans": list(spans)}]}]}


def test_convert_trace_span():
    ev = convert_traces(traces_body(span()))[0]
    assert (ev["kind"], ev["service_name"], ev["status"]) == ("trace_span", "shop", "error")
    assert ev["duration_ms"] == pytest.approx(250.0) and ev["attributes"]["http.status_code"] == 500
    assert ev["attributes"]["deployment.environment"] == "production" and ev["parent_span_id"] is None


def test_exception_span_event_becomes_error_log_with_trace_id():
    s = span(events=[{"name": "exception", "timeUnixNano": str(NS), "attributes": [
        {"key": "exception.type", "value": {"stringValue": "MongoError"}},
        {"key": "exception.message", "value": {"stringValue": "connection closed"}}]}])
    logs = [e for e in convert_traces(traces_body(s)) if e["kind"] == "log"]
    assert logs and logs[0]["severity"] == "error" and logs[0]["trace_id"] == "a" * 32


def test_convert_rejects_bad_span():
    with pytest.raises(OtlpError):
        convert_traces(traces_body(span(startTimeUnixNano="x")))
    with pytest.raises(OtlpError):
        convert_traces(traces_body(span(traceId="")))


def test_convert_logs_severity_and_correlation():
    body = {"resourceLogs": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "shop"}}]},
            "scopeLogs": [{"logRecords": [{"timeUnixNano": str(NS), "severityNumber": 17, "body": {"stringValue": "db down"},
                                           "traceId": "c" * 32, "spanId": "d" * 16}]}]}]}
    ev = convert_logs(body)[0]
    assert ev["severity"] == "error" and ev["message"] == "db down" and ev["trace_id"] == "c" * 32


def test_convert_metrics_gauge_sum_histogram():
    body = {"resourceMetrics": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "shop"}}]},
            "scopeMetrics": [{"metrics": [
                {"name": "process.memory.usage", "unit": "By", "gauge": {"dataPoints": [{"timeUnixNano": str(NS), "asInt": "1024"}]}},
                {"name": "http.server.duration", "unit": "ms", "histogram": {"dataPoints": [
                    {"timeUnixNano": str(NS), "count": "4", "sum": 400.0}]}}]}]}]}
    names = {e["metric_name"]: e["value"] for e in convert_metrics(body)}
    assert names["process.memory.usage"] == 1024.0
    assert names["http.server.duration.count"] == 4.0 and names["http.server.duration.avg"] == 100.0


# ---------------- OTLP receiver ----------------
def test_otlp_traces_end_to_end_binds_tenant(saas_client):
    r = saas_client.post("/otlp/v1/traces", json=traces_body(span()), headers={"X-Ingestion-Key": "key-a"})
    assert r.status_code == 200 and r.json() == {"partialSuccess": {}}
    e = saas_client.wr.written[0]
    assert e.workspace_id == WS_A and e.kind == "trace_span" and e.attributes["platform.environment"] == "production"


def test_otlp_auth_and_content_type(saas_client):
    assert saas_client.post("/otlp/v1/traces", json=traces_body(span())).status_code == 401
    assert saas_client.post("/otlp/v1/traces", json=traces_body(span()), headers={"X-Ingestion-Key": "bad"}).status_code == 401
    r = saas_client.post("/otlp/v1/traces", content=b"\x0a\x00", headers={"X-Ingestion-Key": "key-a", "content-type": "application/x-protobuf"})
    assert r.status_code == 415


def test_otlp_invalid_payloads_get_clear_errors(saas_client):
    h = {"X-Ingestion-Key": "key-a"}
    assert saas_client.post("/otlp/v1/traces", content=b"{not json", headers={**h, "content-type": "application/json"}).status_code == 400
    assert saas_client.post("/otlp/v1/traces", json=traces_body(span(startTimeUnixNano="x")), headers=h).status_code == 422


def test_otlp_batch_size_limit(saas_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_events_per_request", 2)
    body = traces_body(*[span(spanId=f"{i:016x}") for i in range(3)])
    assert saas_client.post("/otlp/v1/traces", json=body, headers={"X-Ingestion-Key": "key-a"}).status_code == 413


def test_otlp_rate_limit_is_per_application(saas_client):
    saas_client.app.state.rate_limiter = type("L", (), {"allow": lambda self, k, cost=1: False})()
    r = saas_client.post("/otlp/v1/traces", json=traces_body(span()), headers={"X-Ingestion-Key": "key-a"})
    assert r.status_code == 429


# ---------------- resolver (real class, mocked gateway) ----------------
async def test_resolver_caches_and_maps_responses():
    calls = {"n": 0}

    def handler(request: httpx.Request):
        calls["n"] += 1
        assert request.headers["x-internal-token"] == "t"
        if b"good" in request.content:
            return httpx.Response(200, json={"workspace_id": str(WS_A), "application_id": str(uuid.uuid4()),
                                             "application_name": "a", "environment": "production", "is_synthetic": False})
        return httpx.Response(401, json={})

    s = Settings(gateway_url="http://g", internal_api_token="t")
    r = GatewayKeyResolver(s, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert (await r.resolve("good-key")).workspace_id == WS_A
    await r.resolve("good-key")
    assert calls["n"] == 1                       # cached
    assert await r.resolve("bad") is None


async def test_resolver_gateway_down_gives_503_not_401():
    from fastapi import HTTPException

    def boom(request):
        raise httpx.ConnectError("down")

    s = Settings(gateway_url="http://g", internal_api_token="t")
    r = GatewayKeyResolver(s, httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    with pytest.raises(HTTPException) as e:
        await r.resolve("k")
    assert e.value.status_code == 503
