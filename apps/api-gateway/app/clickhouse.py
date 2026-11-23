from __future__ import annotations

import logging
from typing import Protocol
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class TelemetryUnavailable(Exception):
    """Telemetry store not configured or unreachable."""


class QueryExecutor(Protocol):
    def query(self, sql: str, params: dict) -> list[dict]: ...


class ClickHouseExecutor:
    """Read-only access to the telemetry store. Use a ClickHouse user with SELECT-only grants."""

    def __init__(self, url: str, user: str, password: str, database: str, timeout_seconds: int = 20) -> None:
        import clickhouse_connect

        p = urlparse(url)
        secure = p.scheme == "https" or p.port == 8443
        self._client = clickhouse_connect.get_client(
            host=p.hostname or "localhost", port=p.port or (8443 if secure else 8123), username=user,
            password=password, database=database, secure=secure, connect_timeout=5, send_receive_timeout=timeout_seconds,
        )
        self._settings = {"max_execution_time": timeout_seconds, "max_result_rows": 20000, "max_memory_usage": 2_000_000_000}

    def query(self, sql: str, params: dict) -> list[dict]:
        try:
            return list(self._client.query(sql, parameters=params, settings=self._settings).named_results())
        except Exception:
            logger.exception("clickhouse_query_failed")
            raise TelemetryUnavailable("Telemetry store query failed") from None
