"""
OTLP/HTTP (JSON) -> platform telemetry events.

Standard OpenTelemetry HTTP exporters (@opentelemetry/exporter-*-otlp-http) send JSON
to {endpoint}/v1/traces|logs|metrics, which map onto the routes in routes/otlp.py.
Conversion is pure (no I/O) so it is unit-testable. workspace_id is set to a
placeholder here; the route overwrites it with the tenant resolved from the key.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

PLACEHOLDER_WORKSPACE = uuid.UUID(int=0)
_SPAN_STATUS = {0: "unset", 1: "ok", 2: "error"}


class OtlpError(ValueError):
    pass


def _any_value(v: dict | None) -> str | int | float | bool | None:
    if not v:
        return None
    if "stringValue" in v:
        return v["stringValue"]
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "intValue" in v:
        try:
            return int(v["intValue"])
        except (TypeError, ValueError):
            return None
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "arrayValue" in v or "kvlistValue" in v:
        return json.dumps(v, default=str)[:1024]
    return None


def _attrs(kvs: list[dict] | None) -> dict[str, str | int | float | bool]:
    out: dict[str, str | int | float | bool] = {}
    for kv in kvs or []:
        val = _any_value(kv.get("value"))
        if val is not None and "key" in kv:
            out[kv["key"]] = val
    return out


def _ts(nanos: Any) -> datetime:
    try:
        n = int(nanos)
    except (TypeError, ValueError):
        raise OtlpError("invalid or missing timestamp") from None
    if n <= 0:
        raise OtlpError("invalid or missing timestamp")
    return datetime.fromtimestamp(n / 1e9, tz=timezone.utc)


def _service(resource_attrs: dict) -> str:
    return str(resource_attrs.get("service.name") or "unknown_service")[:200]


def _hex(v: Any) -> str | None:
    return v if isinstance(v, str) and v else None


def _resource(block: dict) -> tuple[str, dict]:
    ra = _attrs((block.get("resource") or {}).get("attributes"))
    return _service(ra), ra


def convert_traces(body: dict) -> list[dict]:
    events: list[dict] = []
    for rs in body.get("resourceSpans") or []:
        service, ra = _resource(rs)
        for ss in rs.get("scopeSpans") or []:
            for sp in ss.get("spans") or []:
                start, end = _ts(sp.get("startTimeUnixNano")), _ts(sp.get("endTimeUnixNano"))
                attrs = _attrs(sp.get("attributes"))
                for k in ("deployment.environment", "service.version"):
                    if k in ra:
                        attrs.setdefault(k, ra[k])
                attrs["span.kind"] = int(sp.get("kind") or 0)
                status = _SPAN_STATUS.get(int((sp.get("status") or {}).get("code") or 0), "unset")
                msg = (sp.get("status") or {}).get("message")
                if msg:
                    attrs["status.message"] = str(msg)
                if not _hex(sp.get("traceId")) or not _hex(sp.get("spanId")):
                    raise OtlpError("span missing traceId/spanId")
                events.append({
                    "kind": "trace_span", "workspace_id": PLACEHOLDER_WORKSPACE, "service_name": service,
                    "timestamp": start, "trace_id": sp["traceId"], "span_id": sp["spanId"],
                    "parent_span_id": _hex(sp.get("parentSpanId")),
                    "operation_name": str(sp.get("name") or "unnamed")[:200],
                    "duration_ms": max((end - start).total_seconds() * 1000.0, 0.0),
                    "status": status, "attributes": attrs,
                })
                for ev in sp.get("events") or []:
                    if ev.get("name") == "exception":
                        ea = _attrs(ev.get("attributes"))
                        text = ea.get("exception.stacktrace") or ea.get("exception.message") or "exception"
                        events.append({
                            "kind": "log", "workspace_id": PLACEHOLDER_WORKSPACE, "service_name": service,
                            "timestamp": _ts(ev.get("timeUnixNano") or sp.get("startTimeUnixNano")),
                            "severity": "error", "message": str(text)[:8000],
                            "trace_id": sp["traceId"], "span_id": sp["spanId"],
                            "attributes": {"exception.type": str(ea.get("exception.type", "")), "source": "span_event"},
                        })
    return events


def _severity(number: Any, text: Any) -> str:
    try:
        n = int(number)
    except (TypeError, ValueError):
        n = 0
    if n:
        for upper, name in ((4, "trace"), (8, "debug"), (12, "info"), (16, "warn"), (20, "error"), (24, "fatal")):
            if n <= upper:
                return name
    t = str(text or "").lower()
    return {"warning": "warn"}.get(t, t) if t in {"trace", "debug", "info", "warn", "warning", "error", "fatal"} else "info"


def convert_logs(body: dict) -> list[dict]:
    events: list[dict] = []
    for rl in body.get("resourceLogs") or []:
        service, _ = _resource(rl)
        for sl in rl.get("scopeLogs") or []:
            for rec in sl.get("logRecords") or []:
                body_val = _any_value(rec.get("body"))
                message = str(body_val) if body_val not in (None, "") else "(empty log body)"
                events.append({
                    "kind": "log", "workspace_id": PLACEHOLDER_WORKSPACE, "service_name": service,
                    "timestamp": _ts(rec.get("timeUnixNano") or rec.get("observedTimeUnixNano")),
                    "severity": _severity(rec.get("severityNumber"), rec.get("severityText")),
                    "message": message[:8000], "trace_id": _hex(rec.get("traceId")), "span_id": _hex(rec.get("spanId")),
                    "attributes": _attrs(rec.get("attributes")),
                })
    return events


def _number(dp: dict) -> float | None:
    if "asDouble" in dp:
        return float(dp["asDouble"])
    if "asInt" in dp:
        return float(int(dp["asInt"]))
    return None


def convert_metrics(body: dict) -> list[dict]:
    events: list[dict] = []
    for rm in body.get("resourceMetrics") or []:
        service, _ = _resource(rm)
        for sm in rm.get("scopeMetrics") or []:
            for m in sm.get("metrics") or []:
                name, unit = str(m.get("name") or "")[:200], m.get("unit")
                if not name:
                    continue
                for kind in ("gauge", "sum"):
                    for dp in (m.get(kind) or {}).get("dataPoints") or []:
                        v = _number(dp)
                        if v is not None:
                            events.append({"kind": "metric", "workspace_id": PLACEHOLDER_WORKSPACE, "service_name": service,
                                           "timestamp": _ts(dp.get("timeUnixNano")), "metric_name": name, "value": v,
                                           "unit": unit, "attributes": {**_attrs(dp.get("attributes")), "otlp.type": kind}})
                for dp in (m.get("histogram") or {}).get("dataPoints") or []:
                    count = int(dp.get("count") or 0)
                    attrs = _attrs(dp.get("attributes"))
                    ts = _ts(dp.get("timeUnixNano"))
                    events.append({"kind": "metric", "workspace_id": PLACEHOLDER_WORKSPACE, "service_name": service,
                                   "timestamp": ts, "metric_name": f"{name}.count", "value": float(count), "unit": "1",
                                   "attributes": {**attrs, "otlp.type": "histogram"}})
                    if count and "sum" in dp:
                        events.append({"kind": "metric", "workspace_id": PLACEHOLDER_WORKSPACE, "service_name": service,
                                       "timestamp": ts, "metric_name": f"{name}.avg", "value": float(dp["sum"]) / count,
                                       "unit": unit, "attributes": {**attrs, "otlp.type": "histogram"}})
    return events
