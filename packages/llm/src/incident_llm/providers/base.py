from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    async def generate_json(self, system_prompt: str, user_prompt: str, schema: type) -> object:
        """Return the provider's parsed/JSON-decoded structured output.
        Must raise incident_llm.errors.* for failures."""
        ...
