"""Typed LLM failures. Messages are safe to show users: they never contain keys."""

from __future__ import annotations


class LLMError(Exception):
    code = "llm_error"
    retryable = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LLMNotConfigured(LLMError):
    code = "llm_not_configured"


class LLMInvalidConfig(LLMError):
    code = "llm_invalid_config"


class LLMAuthError(LLMError):
    code = "llm_auth_failed"


class LLMModelUnavailable(LLMError):
    code = "llm_model_unavailable"


class LLMQuotaExhausted(LLMError):
    code = "llm_quota_exhausted"


class LLMRateLimited(LLMError):
    code = "llm_rate_limited"
    retryable = True


class LLMTimeout(LLMError):
    code = "llm_timeout"
    retryable = True


class LLMTransientError(LLMError):
    code = "llm_transient_error"
    retryable = True


class LLMMalformedResponse(LLMError):
    code = "llm_malformed_response"
    retryable = True
