from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    alert_router_port: int = 8004
    environment: str = "development"
    log_level: str = "info"

    database_url: str = (
        "postgresql://incident_app:incident_app_dev_password@localhost:5432/incident_platform"
    )

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_incident_candidates: str = "incident.candidates"
    kafka_consumer_group_alerts: str = "alert-router"

    slack_webhook_url: str = ""
    pagerduty_routing_key: str = ""
    alert_max_attempts: int = 3
    alert_base_backoff_seconds: float = 1.0

    # Same pattern as the ingestion service - API keys for machine clients
    # (the dashboard's backend-for-frontend, in Phase 6).
    api_key_header: str = "X-API-Key"
    valid_api_keys_raw: str = "dev-local-dashboard-key"

    @property
    def valid_api_keys(self) -> set[str]:
        return {k.strip() for k in self.valid_api_keys_raw.split(",") if k.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
