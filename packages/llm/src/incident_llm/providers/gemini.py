from __future__ import annotations

import json

from incident_llm.config import LLMConfig
from incident_llm.errors import (
    LLMAuthError, LLMMalformedResponse, LLMModelUnavailable, LLMQuotaExhausted,
    LLMRateLimited, LLMTransientError,
)


def map_gemini_error(code: int | None, message: str) -> Exception:
    """Translate a Gemini API error into a typed LLMError. Pure function (testable)."""
    low = (message or "").lower()
    if code in (401, 403) or "api key not valid" in low or "api_key_invalid" in low:
        return LLMAuthError("The configured LLM_API_KEY was rejected by the provider.")
    if code == 400 and "api key" in low:
        return LLMAuthError("The configured LLM_API_KEY was rejected by the provider.")
    if code == 404 or ("model" in low and "not found" in low):
        return LLMModelUnavailable("The configured LLM_MODEL is not available for this key.")
    if code == 429:
        if "per day" in low or "daily" in low or "billing" in low:
            return LLMQuotaExhausted("The provider quota for this key is exhausted.")
        return LLMRateLimited("The provider rate limit was hit; retry shortly.")
    if code is not None and code >= 500:
        return LLMTransientError("The LLM provider is temporarily unavailable.")
    return LLMTransientError("The LLM provider returned an unexpected error.")


class GeminiProvider:
    def __init__(self, config: LLMConfig) -> None:
        from google import genai  # lazy: only needed when Gemini is actually used

        self._config = config
        self._client = genai.Client(api_key=config.api_key)

    async def generate_json(self, system_prompt: str, user_prompt: str, schema: type) -> object:
        from google.genai import errors as genai_errors
        from google.genai import types

        try:
            response = await self._client.aio.models.generate_content(
                model=self._config.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=schema,
                    max_output_tokens=self._config.max_output_tokens,
                ),
            )
        except genai_errors.APIError as exc:
            raise map_gemini_error(getattr(exc, "code", None), str(exc)) from None

        if response.parsed is not None:
            return response.parsed
        if not response.text:
            raise LLMMalformedResponse("The model returned no structured output.")
        try:
            return json.loads(response.text)
        except json.JSONDecodeError:
            raise LLMMalformedResponse("The model returned invalid JSON.") from None
