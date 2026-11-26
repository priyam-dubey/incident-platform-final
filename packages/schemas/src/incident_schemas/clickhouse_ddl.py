"""
Single source of truth for the ClickHouse raw-telemetry table, shared by the ingestion writer
(creates/migrates it), the gateway query layer and tests.

Derived columns are MATERIALIZED from the `attributes` JSON string at insert time so dashboard
queries filter on real columns instead of parsing JSON per row. Writers insert with explicit
column names and never supply these, so adding them is backwards compatible.
"""

from __future__ import annotations

TELEMETRY_TABLE = "telemetry_raw"

# (name, definition) - used both in CREATE TABLE and as ALTER ... ADD COLUMN IF NOT EXISTS
_EXTRA_COLUMNS: list[tuple[str, str]] = [
    ("parent_span_id", "String DEFAULT ''"),
    ("application_id", "String MATERIALIZED JSONExtractString(attributes, 'platform.application_id')"),
    ("span_kind", "UInt8 MATERIALIZED toUInt8(JSONExtractInt(attributes, 'span.kind'))"),
    (
        "http_method",
        "LowCardinality(String) MATERIALIZED if(JSONExtractString(attributes, 'http.request.method') != '', "
        "JSONExtractString(attributes, 'http.request.method'), JSONExtractString(attributes, 'http.method'))",
    ),
    (
        "http_status",
        "UInt16 MATERIALIZED toUInt16(if(JSONExtractInt(attributes, 'http.response.status_code') > 0, "
        "JSONExtractInt(attributes, 'http.response.status_code'), JSONExtractInt(attributes, 'http.status_code')))",
    ),
    ("http_route", "String MATERIALIZED JSONExtractString(attributes, 'http.route')"),
]

_BASE_COLUMNS = """
    workspace_id    UUID,
    service_name    LowCardinality(String),
    kind            LowCardinality(String),
    timestamp       DateTime64(3, 'UTC'),
    severity        LowCardinality(String) DEFAULT '',
    message         String DEFAULT '',
    metric_name     LowCardinality(String) DEFAULT '',
    value           Nullable(Float64),
    trace_id        String DEFAULT '',
    span_id         String DEFAULT '',
    operation_name  String DEFAULT '',
    duration_ms     Nullable(Float64),
    status          LowCardinality(String) DEFAULT '',
    attributes      String DEFAULT '{}'"""

CREATE_TABLE_SQL = (
    f"CREATE TABLE IF NOT EXISTS {TELEMETRY_TABLE} ({_BASE_COLUMNS},\n    "
    + ",\n    ".join(f"{n} {d}" for n, d in _EXTRA_COLUMNS)
    + "\n)\nENGINE = MergeTree\nPARTITION BY toYYYYMMDD(timestamp)\n"
    "ORDER BY (workspace_id, service_name, timestamp)\nTTL toDateTime(timestamp) + INTERVAL 90 DAY"
)

# For tables created before these columns existed.
MIGRATION_SQL = [
    f"ALTER TABLE {TELEMETRY_TABLE} ADD COLUMN IF NOT EXISTS {n} {d}" for n, d in _EXTRA_COLUMNS
]
