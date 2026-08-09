"""
Centralized configuration. Every tunable lives here and nowhere else -
no service module reads os.environ directly, so the entire service's
external surface (what env vars it needs) is visible in one file.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- service ---
    ingestion_service_port: int = 8001
    environment: str = "development"
    log_level: str = "info"

    # --- auth ---
    ingestion_api_key_header: str = "X-Ingestion-Key"
    ingestion_valid_api_keys: str = "dev-local-ingestion-key"

    # --- kafka ---
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_telemetry_events: str = "telemetry.events"
    kafka_producer_acks: str = "all"  # wait for full ISR ack - correctness over latency here
    kafka_producer_linger_ms: int = 20  # small batching window, real throughput win at low cost

    # --- clickhouse ---
    clickhouse_url: str = "http://localhost:8123"
    clickhouse_user: str = "incident_app"
    clickhouse_password: str = "incident_app_dev_password"
    clickhouse_db: str = "incident_telemetry"

    # --- rate limiting (per API key, token bucket) ---
    rate_limit_events_per_second: int = 5000
    rate_limit_burst: int = 10000

    @property
    def valid_api_keys(self) -> set[str]:
        return {k.strip() for k in self.ingestion_valid_api_keys.split(",") if k.strip()}


@lru_cache
def get_settings() -> Settings:
    # Cached: Settings() re-parses env on every call otherwise, and this is
    # called from a FastAPI Depends() on every request.
    return Settings()
