"""
Shared fakes. FakeLLMClient lets tests script a sequence of canned
HypothesisSetDraft responses (e.g. "first call hallucinates, second call is
clean") so the retry logic in reasoning_graph.py can be exercised
deterministically without a live model call.
"""

from __future__ import annotations

import pytest

from app.structured_output import HypothesisSetDraft


class FakeLLMClient:
    def __init__(self, responses: list[HypothesisSetDraft]) -> None:
        self._responses = list(responses)
        self.call_count = 0
        self.received_prompts: list[tuple[str, str]] = []

    async def generate_hypotheses(
        self, system_prompt: str, user_prompt: str, model: str
    ) -> HypothesisSetDraft:
        self.received_prompts.append((system_prompt, user_prompt))
        if self.call_count >= len(self._responses):
            raise AssertionError(
                f"FakeLLMClient called {self.call_count + 1} times but only "
                f"{len(self._responses)} scripted responses were provided"
            )
        response = self._responses[self.call_count]
        self.call_count += 1
        return response


@pytest.fixture
def make_fake_llm_client():
    return FakeLLMClient
