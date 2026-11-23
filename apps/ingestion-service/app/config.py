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

    # --- per-application keys (SaaS mode) ---
    # When GATEWAY_URL + INTERNAL_API_TOKEN are set, every ingestion key is verified
    # against the API gateway and the key - not the request body - decides the tenant.
    # Otherwise the legacy static key list above is used (development only).
    gateway_url: str = ""
    internal_api_token: str = ""
    key_cache_ttl_seconds: int = 30
    key_negative_cache_ttl_seconds: int = 5
    max_events_per_request: int = 1000
    max_body_bytes: int = 5_000_000
    redact_telemetry: bool = True

    @property
    def gateway_mode(self) -> bool:
        return bool(self.gateway_url and self.internal_api_token)

    # --- kafka ---
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_telemetry_events: str = "telemetry.events"
    kafka_producer_acks: str = "all"  # wait for full ISR ack - correctness over latency here
    kafka_producer_linger_ms: int = 20  # small batching window, real throughput win at low cost

    # --- kafka auth (optional - only needed for managed/cloud Kafka) ---
    # Defaults preserve plaintext local Redpanda behavior untouched. Set
    # KAFKA_SECURITY_PROTOCOL=SASL_SSL (+ mechanism/username/password) when
    # pointing at a managed provider like Upstash Kafka or Redpanda Cloud.
    kafka_security_protocol: str = "PLAINTEXT"
    kafka_sasl_mechanism: str | None = None
    kafka_sasl_username: str | None = None
    kafka_sasl_password: str | None = None

    @property
    def kafka_client_kwargs(self) -> dict:
        """Extra kwargs to splat into AIOKafkaProducer/AIOKafkaConsumer.

        PLAINTEXT (the local default) omits SASL kwargs entirely, since
        aiokafka rejects sasl_mechanism=None combined with certain brokers'
        strict handshake checks. Only added when actually configured.
        """
        kwargs: dict = {"security_protocol": self.kafka_security_protocol}
        if self.kafka_security_protocol != "PLAINTEXT":
            kwargs["sasl_mechanism"] = self.kafka_sasl_mechanism or "PLAIN"
            kwargs["sasl_plain_username"] = self.kafka_sasl_username
            kwargs["sasl_plain_password"] = self.kafka_sasl_password
        return kwargs

    # --- clickhouse ---
    # Set to false to run without ClickHouse (e.g. no cloud deployment for
    # it yet, or local resource constraints). Telemetry still reaches Kafka/
    # correlation-engine either way - only the raw-telemetry durable store
    # is skipped, and nothing else in the platform reads from it today.
    clickhouse_enabled: bool = True
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
