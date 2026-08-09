from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    reasoning_service_port: int = 8003
    environment: str = "development"
    log_level: str = "info"

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_incident_candidates: str = "incident.candidates"
    kafka_consumer_group_reasoning: str = "reasoning-service"

    database_url: str = (
        "postgresql://incident_app:incident_app_dev_password@localhost:5432/incident_platform"
    )

    gemini_api_key: str = ""
    # Gemini Flash is available on Gemini's development free tier (within its
    # rate limits) and supports JSON-schema structured output.
    reasoning_model_synthesis: str = "gemini-2.5-flash"
    reasoning_max_attempts: int = 2
    reasoning_max_tokens: int = 4096
    # Caps concurrent in-flight LLM calls so a burst of incident candidates
    # can't spike Gemini API usage or exhaust the service's own event loop
    # capacity - the concrete cost-control mechanism referenced in the
    # platform-level architecture doc's "reasoning-service autoscales... with
    # a max-concurrency cap (LLM cost control)".
    reasoning_max_concurrency: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
