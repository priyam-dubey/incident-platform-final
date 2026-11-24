from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_gateway_port: int = 8005
    environment: str = "development"
    log_level: str = "info"
    database_url: str = "postgresql://incident_app:incident_app_dev_password@localhost:5432/incident_platform"

    # --- auth ---
    # Signs short-lived access tokens. MUST be set to a long random value in production.
    auth_secret_key: str = "dev-only-insecure-secret-change-me-32bytes!"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14
    password_reset_ttl_seconds: int = 3600
    cookie_secure: bool = False  # set true behind HTTPS
    cookie_samesite: str = "lax"

    # --- CORS: explicit allow-list only ---
    cors_allowed_origins: str = "http://localhost:3000"
    dashboard_url: str = "http://localhost:3000"

    # --- service-to-service ---
    internal_api_token: str = ""  # used by ingestion-service to verify app keys
    public_ingestion_url: str = "http://localhost:8001"

    # --- telemetry store (ClickHouse). Use a SELECT-only user for the gateway. ---
    clickhouse_url: str = ""          # empty = telemetry queries report 'not configured' (no fake data)
    clickhouse_user: str = "incident_app"
    clickhouse_password: str = ""
    clickhouse_db: str = "incident_telemetry"
    telemetry_query_timeout_seconds: int = 20

    # --- incident detection / notifications (all optional; unset = 'not configured', never faked) ---
    detection_enabled: bool = False        # background loop; manual 'run detection' always works
    detection_interval_seconds: int = 60
    rca_enabled: bool = True               # still requires LLM_API_KEY; without it incidents stay deterministic-only
    slack_webhook_url: str = ""
    pagerduty_routing_key: str = ""
    notify_min_severity: str = "high"

    # --- GitHub App (all optional; unset = 'not configured') ---
    github_app_id: str = ""
    github_app_slug: str = ""
    github_app_private_key: str = ""       # PEM contents (use \n for newlines) ...
    github_app_private_key_path: str = ""  # ... or a path to the .pem file
    github_webhook_secret: str = ""
    github_api_url: str = "https://api.github.com"
    scan_worker_enabled: bool = False
    scan_max_archive_mb: int = 200
    scan_max_files: int = 50000
    scan_enabled_tools: str = "semgrep,bandit,ruff,eslint,tsc,gitleaks,npm-audit,pip-audit,trivy"

    # --- rate limits (per client IP, per minute) ---
    auth_rate_limit_per_minute: int = 20

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def secret_is_insecure_default(self) -> bool:
        return self.auth_secret_key.startswith("dev-only-insecure")


@lru_cache
def get_settings() -> Settings:
    return Settings()
