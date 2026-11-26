import json

import pytest

from tests.chdb_support import ChdbExecutor, log, metric, minutes_ago, span

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def store(client):
    ex = ChdbExecutor()
    client.app.state.telemetry = ex
    yield ex
    client.app.state.telemetry = None


def mk_app(client, u, name="shop-api"):
    r = client.post(f"/v1/workspaces/{u['workspace_id']}/applications", headers=u["headers"], json={"name": name, "environment": "production"})
    assert r.status_code == 201, r.text
    return r.json()["application"]["id"]


def url(u, app, path, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return f"/v1/workspaces/{u['workspace_id']}/applications/{app}/telemetry/{path}" + (f"?{q}" if q else "")


def get(client, u, app, path, **params):
    return client.get(url(u, app, path, **params), headers=u["headers"])


def seed_traffic(store, u, app):
    ws = u["workspace_id"]
    rows = []
    # 10 requests to /api/foods: 100..1000ms, all 200
    rows += [span(ws, app, minutes_ago(30 - i), "/api/foods", "GET", 200, 100.0 * (i + 1)) for i in range(10)]
    # 4 orders: 2 fail with 500
    rows += [span(ws, app, minutes_ago(20 - i), "/api/orders", "POST", 500 if i < 2 else 201, 300.0) for i in range(4)]
    # 2 login 401s, one unrouted 404
    rows += [span(ws, app, minutes_ago(10), "/api/login", "POST", 401, 50.0) for _ in range(2)]
    rows += [span(ws, app, minutes_ago(5), "", "GET", 404, 5.0)]
    store.insert(rows)


# ---------------------------------------------------------------- correctness
def test_summary_matches_seeded_traffic(client, store, make_user):
    u = make_user(); app = mk_app(client, u); seed_traffic(store, u, app)
    r = get(client, u, app, "summary", range="1h").json()
    s = r["summary"]
    assert s["requests"] == 17 and s["errors_5xx"] == 2 and s["errors_4xx"] == 3
    assert s["error_rate"] == pytest.approx(2 / 17)
    assert 400 <= s["p95_ms"] <= 1000 and s["p50_ms"] < s["p95_ms"] <= s["p99_ms"]
    assert r["status_distribution"] == {"1xx": 0, "2xx": 12, "3xx": 0, "4xx": 3, "5xx": 2}
    assert r["synthetic"] is False and r["application"] == "shop-api"


def test_non_request_spans_do_not_count_as_requests(client, store, make_user):
    u = make_user(); app = mk_app(client, u)
    store.insert([span(u["workspace_id"], app, minutes_ago(3), kind=0, op="middleware - query", route="/x", status=200)])
    assert get(client, u, app, "summary").json()["summary"]["requests"] == 0


def test_empty_application_returns_honest_empty_not_zero_latency(client, store, make_user):
    u = make_user(); app = mk_app(client, u)
    s = get(client, u, app, "summary").json()["summary"]
    assert s["requests"] == 0 and s["p95_ms"] is None and s["error_rate"] is None
    pts = get(client, u, app, "timeseries").json()["points"]
    assert pts and all(p["requests"] == 0 and p["p95_ms"] is None and p["error_rate"] is None for p in pts)


def test_timeseries_is_continuous_with_gaps_as_null(client, store, make_user):
    u = make_user(); app = mk_app(client, u); seed_traffic(store, u, app)
    body = get(client, u, app, "timeseries", range="1h").json()
    pts = body["points"]
    assert sum(p["requests"] for p in pts) == 17 and len(pts) >= 30
    empty = [p for p in pts if p["requests"] == 0]
    assert empty and all(p["avg_ms"] is None for p in empty)
    assert any(p["error_rate"] and p["error_rate"] > 0 for p in pts)
    ts = [p["t"] for p in pts]
    assert ts == sorted(ts)


def test_endpoints_breakdown_sorting_and_unrouted(client, store, make_user):
    u = make_user(); app = mk_app(client, u); seed_traffic(store, u, app)
    eps = get(client, u, app, "endpoints", sort="requests").json()["endpoints"]
    assert (eps[0]["method"], eps[0]["route"], eps[0]["requests"]) == ("GET", "/api/foods", 10)
    orders = next(e for e in eps if e["route"] == "/api/orders")
    assert orders["errors_5xx"] == 2 and orders["error_rate"] == 0.5
    assert any(e["route"] == "(unrouted)" for e in eps)             # no high-cardinality raw paths
    by_p95 = get(client, u, app, "endpoints", sort="p95").json()["endpoints"]
    assert by_p95[0]["route"] == "/api/foods"
    assert get(client, u, app, "endpoints", sort="nope").status_code == 422


def test_runtime_metrics_are_process_scoped(client, store, make_user):
    u = make_user(); app = mk_app(client, u)
    store.insert([metric(u["workspace_id"], app, minutes_ago(i), "process.memory.usage", 100e6 + i) for i in range(1, 6)]
                 + [metric(u["workspace_id"], app, minutes_ago(2), "host.cpu.fake", 99.0)])
    r = get(client, u, app, "runtime").json()
    assert r["scope"] == "process" and "not host" in r["note"].lower()
    mem = [p for p in r["series"]["process.memory.usage"] if p["avg"] is not None]
    assert len(mem) >= 1 and r["series"]["nodejs.heap.used"] == []
    assert "host.cpu.fake" not in json.dumps(r)                     # only whitelisted process metrics


def test_logs_filters_search_pagination_and_hidden_internals(client, store, make_user):
    u = make_user(); app = mk_app(client, u); ws = u["workspace_id"]
    store.insert([log(ws, app, minutes_ago(9), "order placed", "info"), log(ws, app, minutes_ago(8), "Payment gateway TIMEOUT", "error", trace="a" * 32),
                  log(ws, app, minutes_ago(7), "slow query", "warn"), log(ws, app, minutes_ago(6), "boom", "error", trace="b" * 32)])
    allr = get(client, u, app, "logs").json()["logs"]
    assert [l["message"] for l in allr][0] == "boom"                # newest first
    assert all("platform.application_id" not in l["attributes"] for l in allr)
    assert {l["message"] for l in get(client, u, app, "logs", severity="error").json()["logs"]} == {"Payment gateway TIMEOUT", "boom"}
    assert [l["message"] for l in get(client, u, app, "logs", search="gateway timeout").json()["logs"]] == ["Payment gateway TIMEOUT"]
    assert [l["trace_id"] for l in get(client, u, app, "logs", trace_id="b" * 32).json()["logs"]] == ["b" * 32]
    assert len(get(client, u, app, "logs", limit=2, offset=0).json()["logs"]) == 2
    assert len(get(client, u, app, "logs", limit=2, offset=3).json()["logs"]) == 1
    assert get(client, u, app, "logs", severity="bogus").status_code == 422


def test_traces_list_detail_and_log_correlation(client, store, make_user):
    u = make_user(); app = mk_app(client, u); ws = u["workspace_id"]
    t_ok, t_bad = "c" * 32, "d" * 32
    store.insert([
        span(ws, app, minutes_ago(9), "/api/foods", "GET", 200, 80, trace=t_ok, span_id="1" * 16),
        span(ws, app, minutes_ago(8), "/api/orders", "POST", 500, 900, trace=t_bad, span_id="2" * 16),
        span(ws, app, minutes_ago(8), "", "POST", 200, 700, trace=t_bad, span_id="3" * 16, parent="2" * 16, kind=3, op="mongodb.insert orders", span_status="error"),
        log(ws, app, minutes_ago(8), "MongoNetworkError: closed", "error", trace=t_bad, span_id="3" * 16),
    ])
    lst = get(client, u, app, "traces").json()["traces"]
    bad = next(t for t in lst if t["trace_id"] == t_bad)
    assert bad["spans"] == 2 and bad["failed_spans"] >= 1 and bad["duration_ms"] >= 900
    assert {t["trace_id"] for t in get(client, u, app, "traces", only_errors="true").json()["traces"]} == {t_bad}
    assert {t["trace_id"] for t in get(client, u, app, "traces", min_duration_ms=500).json()["traces"]} == {t_bad}
    d = get(client, u, app, "traces/" + t_bad).json()
    child = next(s for s in d["spans"] if s["span_id"] == "3" * 16)
    assert child["parent_span_id"] == "2" * 16 and child["status"] == "error"
    assert [l["message"] for l in d["logs"]] == ["MongoNetworkError: closed"]
    assert get(client, u, app, "traces/not-hex").status_code == 422
    assert get(client, u, app, "traces/" + "e" * 32).status_code == 404


# ------------------------------------------------------------------ isolation
def test_other_tenants_data_is_invisible(client, store, make_user):
    a, b = make_user("a"), make_user("b")
    app_a, app_b = mk_app(client, a), mk_app(client, b)
    seed_traffic(store, a, app_a)
    assert get(client, b, app_b, "summary").json()["summary"]["requests"] == 0
    assert get(client, a, app_a, "summary").json()["summary"]["requests"] == 17
    # B cannot read A's application at all, through any telemetry route, or by id-swapping into B's workspace
    for path in ("summary", "timeseries", "endpoints", "runtime", "logs", "traces"):
        assert get(client, b, app_a, path).status_code == 404
        assert client.get(url(a, app_a, path), headers=b["headers"]).status_code == 404


def test_rows_with_wrong_workspace_or_app_are_never_returned(client, store, make_user):
    """Even if rows are mislabelled in storage, queries are bound to (workspace, application)."""
    a, b = make_user("a"), make_user("b")
    app_a, app_b = mk_app(client, a), mk_app(client, b)
    other_app_same_ws = mk_app(client, a, "second-app")
    store.insert([span(b["workspace_id"], app_a, minutes_ago(3)),                 # right app id, WRONG workspace
                  span(a["workspace_id"], other_app_same_ws, minutes_ago(3)),     # right workspace, other app
                  span(a["workspace_id"], app_a, minutes_ago(3))])                # the only legitimate row
    assert get(client, a, app_a, "summary").json()["summary"]["requests"] == 1
    assert get(client, b, app_b, "summary").json()["summary"]["requests"] == 0


def test_sql_injection_attempts_are_inert(client, store, make_user):
    u = make_user(); app = mk_app(client, u); seed_traffic(store, u, app)
    evil = "%27%3B%20DROP%20TABLE%20telemetry_raw%3B%20--"
    assert get(client, u, app, "logs", search=evil).status_code == 200
    assert get(client, u, app, "logs", trace_id=evil).json()["logs"] == []
    assert get(client, u, app, "summary").json()["summary"]["requests"] == 17      # table intact


def test_viewer_can_read_but_unauthenticated_cannot(client, store, make_user):
    owner, viewer = make_user("o"), make_user("v")
    client.post(f"/v1/workspaces/{owner['workspace_id']}/members", headers=owner["headers"], json={"email": viewer["email"], "role": "viewer"})
    app = mk_app(client, owner)
    assert client.get(url(owner, app, "summary"), headers=viewer["headers"]).status_code == 200
    assert client.get(url(owner, app, "summary")).status_code == 401


# ----------------------------------------------------------------- behaviours
def test_range_validation_over_http(client, store, make_user):
    u = make_user(); app = mk_app(client, u)
    for params in ({"range": "30d"}, {"from": "2026-11-01T00:00:00Z"}, {"from": "2026-11-10T00:00:00Z", "to": "2026-11-01T00:00:00Z"},
                   {"from": "2026-11-01T00:00:00Z", "to": "2026-11-20T00:00:00Z"}):
        assert get(client, u, app, "summary", **params).status_code == 422, params


def test_synthetic_label_is_reported_for_demo_workspace_apps(client, store, make_user, db):
    u = make_user()
    db.execute("UPDATE workspaces SET is_demo=true WHERE id=%s", (u["workspace_id"],))
    r = client.post(f"/v1/workspaces/{u['workspace_id']}/applications", headers=u["headers"],
                    json={"name": "demo-shop", "environment": "staging", "is_synthetic": True})
    app = r.json()["application"]["id"]
    assert get(client, u, app, "summary").json()["synthetic"] is True


def test_not_configured_store_is_reported_honestly_not_as_empty_data(client, make_user):
    u = make_user(); app = mk_app(client, u)
    previous = client.app.state.telemetry
    client.app.state.telemetry = None
    try:
        r = get(client, u, app, "summary")
        assert r.status_code == 503 and r.json()["detail"]["code"] == "telemetry_store_not_configured"
        assert client.get("/v1/system/status").json()["telemetry_store"] == "not_configured"
    finally:
        client.app.state.telemetry = previous


def test_executor_failure_gives_503_without_leaking_details(client, make_user):
    from app.clickhouse import TelemetryUnavailable

    class Broken:
        def query(self, sql, params):
            raise TelemetryUnavailable("clickhouse at 10.0.0.5 refused connection password=hunter2")

    u = make_user(); app = mk_app(client, u)
    previous = client.app.state.telemetry
    client.app.state.telemetry = Broken()
    try:
        r = get(client, u, app, "summary")
        assert r.status_code == 503 and "hunter2" not in r.text and "10.0.0.5" not in r.text
    finally:
        client.app.state.telemetry = previous
