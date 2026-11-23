"""Reasoning-service LLM adapter.

All provider, model and key handling lives in the shared incident_llm package
(configured only by LLM_MODEL and LLM_API_KEY). This module only maps the
reasoning pipeline's call shape onto that central client.
"""

from __future__ import annotations

from typing import Protocol

from incident_llm import LLMClient as CentralLLMClient

from app.structured_output import HypothesisSetDraft


class LLMClient(Protocol):
    async def generate_hypotheses(
        self, system_prompt: str, user_prompt: str, model: str
    ) -> HypothesisSetDraft: ...


class CentralHypothesisClient:
    def __init__(self, central: CentralLLMClient) -> None:
        self._central = central

    async def generate_hypotheses(
        self, system_prompt: str, user_prompt: str, model: str = ""
    ) -> HypothesisSetDraft:
        # `model` is retained for call-compatibility; the active model comes
        # exclusively from LLM_MODEL via the central client.
        return await self._central.generate_structured(system_prompt, user_prompt, HypothesisSetDraft)
