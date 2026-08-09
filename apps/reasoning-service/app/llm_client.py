"""Gemini SDK wrapper enforcing JSON-schema structured output."""

from __future__ import annotations

import json
from typing import Protocol

from google import genai
from google.genai import types

from app.structured_output import HypothesisSetDraft


class LLMClient(Protocol):
    async def generate_hypotheses(
        self, system_prompt: str, user_prompt: str, model: str
    ) -> HypothesisSetDraft: ...


class GeminiLLMClient:
    def __init__(self, api_key: str, max_tokens: int = 4096) -> None:
        self._client = genai.Client(api_key=api_key)
        self._max_tokens = max_tokens

    async def generate_hypotheses(
        self, system_prompt: str, user_prompt: str, model: str
    ) -> HypothesisSetDraft:
        response = await self._client.aio.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=HypothesisSetDraft,
                max_output_tokens=self._max_tokens,
            ),
        )

        # The SDK provides ``parsed`` for schema-constrained responses. Fall
        # back to the returned JSON text to give a clear validation failure if
        # a future SDK version does not populate that convenience property.
        payload = response.parsed
        if payload is None:
            if not response.text:
                raise RuntimeError("Gemini response did not contain structured JSON output")
            payload = json.loads(response.text)
        return HypothesisSetDraft.model_validate(payload)
