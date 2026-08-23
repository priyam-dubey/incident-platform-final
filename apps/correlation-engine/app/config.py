from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    correlation_service_port: int = 8002
    environment: str = "development"
    log_level: str = "info"

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_telemetry_events: str = "telemetry.events"
    kafka_topic_incident_candidates: str = "incident.candidates"
    kafka_consumer_group_correlation: str = "correlation-engine"

    # --- kafka auth (optional - only needed for managed/cloud Kafka) ---
    kafka_security_protocol: str = "PLAINTEXT"
    kafka_sasl_mechanism: str | None = None
    kafka_sasl_username: str | None = None
    kafka_sasl_password: str | None = None

    @property
    def kafka_client_kwargs(self) -> dict:
        kwargs: dict = {"security_protocol": self.kafka_security_protocol}
        if self.kafka_security_protocol != "PLAINTEXT":
            kwargs["sasl_mechanism"] = self.kafka_sasl_mechanism or "PLAIN"
            kwargs["sasl_plain_username"] = self.kafka_sasl_username
            kwargs["sasl_plain_password"] = self.kafka_sasl_password
        return kwargs

    database_url: str = (
        "postgresql://incident_app:incident_app_dev_password@localhost:5432/incident_platform"
    )

    anomaly_zscore_threshold: float = 3.0
    anomaly_window_size: int = 60
    anomaly_min_samples: int = 10
    correlation_window_seconds: float = 60.0
    evidence_retention_minutes: float = 15.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
