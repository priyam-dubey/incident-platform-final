"""The single LLM entry point every AI feature uses."""

from __future__ import annotations

import asyncio
import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from incident_llm.config import LLMConfig, load_llm_config
from incident_llm.errors import (
    LLMError, LLMInvalidConfig, LLMMalformedResponse, LLMNotConfigured, LLMTimeout,
)
from incident_llm.providers.base import LLMProvider

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def _build_provider(config: LLMConfig) -> LLMProvider:
    if config.provider == "gemini":
        from incident_llm.providers.gemini import GeminiProvider

        return GeminiProvider(config)
    raise LLMInvalidConfig(f"Unsupported provider {config.provider!r}")


class LLMClient:
    def __init__(
        self,
        config: LLMConfig | None = None,
        provider: LLMProvider | None = None,
        sleep=asyncio.sleep,
    ) -> None:
        self.config = config or load_llm_config()
        self._provider = provider
        self._sleep = sleep

    def status(self) -> dict:
        """Safe to expose via health endpoints: contains no secret values."""
        if self.config.config_error:
            state, detail = "invalid_config", self.config.config_error
        elif not self.config.api_key:
            state, detail = "not_configured", "LLM_API_KEY is not set."
        else:
            state, detail = "configured", None
        return {
            "state": state, "provider": self.config.provider,
            "model": self.config.model, "detail": detail,
        }

    def _ensure_ready(self) -> LLMProvider:
        if self.config.config_error:
            raise LLMInvalidConfig(self.config.config_error)
        if not self.config.api_key:
            raise LLMNotConfigured("LLM_API_KEY is not set; AI features are unavailable.")
        if self._provider is None:
            self._provider = _build_provider(self.config)
        return self._provider

    async def generate_structured(self, system_prompt: str, user_prompt: str, schema: type[T]) -> T:
        provider = self._ensure_ready()
        attempts = self.config.max_retries + 1
        last: LLMError | None = None
        for attempt in range(attempts):
            try:
                raw = await asyncio.wait_for(
                    provider.generate_json(system_prompt, user_prompt, schema),
                    timeout=self.config.timeout_seconds,
                )
                try:
                    return raw if isinstance(raw, schema) else schema.model_validate(raw)
                except ValidationError:
                    raise LLMMalformedResponse("The model output did not match the required schema.") from None
            except asyncio.TimeoutError:
                last = LLMTimeout("The LLM request timed out.")
            except LLMError as exc:
                last = exc
            if not last.retryable or attempt == attempts - 1:
                break
            delay = min(2 ** attempt, 8)
            logger.warning(
                "llm_retry",
                extra={"provider": self.config.provider, "model": self.config.model,
                       "error_code": last.code, "attempt": attempt + 1, "delay_s": delay},
            )
            await self._sleep(delay)
        assert last is not None
        logger.error(
            "llm_failed",
            extra={"provider": self.config.provider, "model": self.config.model, "error_code": last.code},
        )
        raise last
