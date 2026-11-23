from datetime import datetime, timedelta, timezone

import pytest

from app import telemetry_queries as q

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
S = q.Scope("11111111-1111-1111-1111-111111111111", "app-1", NOW - timedelta(hours=1), NOW)


def test_range_presets_and_custom():
    s, e = q.resolve_range("6h", None, None, NOW)
    assert e - s == timedelta(hours=6)
    s, e = q.resolve_range(None, None, None, NOW)
    assert e - s == timedelta(hours=1)                     # default
    s, e = q.resolve_range(None, NOW - timedelta(minutes=5), NOW)
    assert e - s == timedelta(minutes=5)


@pytest.mark.parametrize("args", [("2d", None, None), (None, NOW, None), (None, NOW, NOW),
                                  (None, NOW - timedelta(days=8), NOW), (None, NOW, NOW - timedelta(hours=1))])
def test_bad_ranges_rejected(args):
    with pytest.raises(ValueError):
        q.resolve_range(*args, NOW)


def test_bucket_size_keeps_series_bounded():
    for minutes in (15, 60, 360, 1440, 10080):
        s = q.Scope("w", "a", NOW - timedelta(minutes=minutes), NOW)
        assert (minutes * 60) / s.bucket_seconds <= 90


def all_builders():
    yield q.summary_query(S)
    yield q.timeseries_query(S)
    yield q.status_query(S)
    yield q.endpoints_query(S, "p95", 10)
    yield q.runtime_query(S)
    yield q.logs_query(S, ["error"], "x", "a" * 32)
    yield q.traces_query(S, True, 5.0)
    yield q.trace_detail_query(S, "a" * 32)


def test_every_query_is_tenant_and_application_scoped_via_bound_params():
    for sql, params in all_builders():
        assert "workspace_id = {ws:UUID}" in sql and "application_id = {app:String}" in sql
        assert params["ws"] == S.workspace_id and params["app"] == S.application_id


def test_user_input_never_appears_in_sql_text():
    evil = "x'; DROP TABLE telemetry_raw; --"
    sql, params = q.logs_query(S, None, evil, evil)
    assert "DROP TABLE" not in sql and evil[:200] in params.values()
    sql, _ = q.trace_detail_query(S, evil)
    assert "DROP" not in sql


def test_whitelists_reject_unknown_sort_and_severity():
    with pytest.raises(ValueError):
        q.endpoints_query(S, "requests; DROP TABLE x")
    with pytest.raises(ValueError):
        q.logs_query(S, ["error' OR 1=1 --"], None, None)


def test_limits_are_clamped():
    assert q.endpoints_query(S, "requests", 10**6)[1]["lim"] == 200
    assert q.logs_query(S, None, None, None, limit=10**6)[1]["lim"] == 500


def test_empty_summary_has_no_fake_zero_latency():
    out = q.shape_summary([{"requests": 0}], S)
    assert out["requests"] == 0 and out["error_rate"] is None and out["p95_ms"] is None and out["avg_ms"] is None


def test_public_attrs_hide_platform_internals_and_tolerate_garbage():
    assert q.public_attrs('{"platform.application_id":"x","http.route":"/a"}') == {"http.route": "/a"}
    assert q.public_attrs("not json") == {} and q.public_attrs(None) == {}
