"""
LLM configuration: exactly two environment variables select provider, model
and credential.

    LLM_MODEL=<provider>/<model-name>     e.g. gemini/gemini-2.5-flash
    LLM_API_KEY=<key for that provider>

The provider is inferred from the prefix before the first "/". Switching model
or key is an environment change plus a restart; no code or schema changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL = "gemini/gemini-2.5-flash"
SUPPORTED_PROVIDERS = ("gemini",)


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str  # bare model name, without provider prefix
    api_key: str = ""
    timeout_seconds: float = 60.0
    max_retries: int = 2
    max_output_tokens: int = 4096
    config_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key) and self.config_error is None

    @property
    def model_id(self) -> str:
        return f"{self.provider}/{self.model}"

    def __repr__(self) -> str:  # never leak the key through logs/tracebacks
        return (
            f"LLMConfig(provider={self.provider!r}, model={self.model!r}, "
            f"api_key={'<set>' if self.api_key else '<unset>'}, configured={self.configured})"
        )

    __str__ = __repr__


def parse_model_id(raw: str) -> tuple[str, str]:
    raw = (raw or "").strip()
    if "/" not in raw:
        raise ValueError(
            f"LLM_MODEL must look like '<provider>/<model>' (e.g. {DEFAULT_MODEL}); got {raw!r}"
        )
    provider, model = raw.split("/", 1)
    provider, model = provider.strip().lower(), model.strip()
    if not provider or not model:
        raise ValueError("LLM_MODEL has an empty provider or model name")
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported LLM provider {provider!r}. Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    return provider, model


def load_llm_config(env: dict[str, str] | None = None) -> LLMConfig:
    """Never raises: invalid settings yield a config whose config_error explains why,
    so non-AI features keep working and AI features can show a clear state."""
    env = os.environ if env is None else env
    raw_model = env.get("LLM_MODEL") or DEFAULT_MODEL
    api_key = (env.get("LLM_API_KEY") or "").strip()
    timeout = float(env.get("LLM_TIMEOUT_SECONDS") or 60)
    retries = int(env.get("LLM_MAX_RETRIES") or 2)
    max_tokens = int(env.get("LLM_MAX_OUTPUT_TOKENS") or 4096)
    try:
        provider, model = parse_model_id(raw_model)
    except ValueError as exc:
        return LLMConfig(
            provider="unknown", model=raw_model, api_key=api_key, timeout_seconds=timeout,
            max_retries=retries, max_output_tokens=max_tokens, config_error=str(exc),
        )
    return LLMConfig(
        provider=provider, model=model, api_key=api_key, timeout_seconds=timeout,
        max_retries=retries, max_output_tokens=max_tokens,
    )
