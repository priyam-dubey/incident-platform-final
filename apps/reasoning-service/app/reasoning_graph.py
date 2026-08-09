"""
LangGraph orchestration of the reasoning pipeline:

    generate_hypotheses ──► validate_citations ──► (conditional)
                                   │                     │
                                   │              all invalid AND
                                   │              attempts remain?
                                   │                     │
                                   │                    yes ──► generate_hypotheses (retry, stricter prompt)
                                   │                     │
                                   └─────────────────────┴── no ──► finalize ──► END

This is a small graph (one real decision point), but the state machine
matters: it's the mechanism by which "the model hallucinated a citation"
becomes "retry once with an explicit correction" instead of either silently
accepting a fabricated claim or hard-failing the whole incident analysis.
After the retry budget is exhausted with zero valid hypotheses, the incident
is finalized with an empty accepted list and flagged for human analysis -
never silently dropped, and never presented as an answer with fabricated
support.
"""

from __future__ import annotations

import logging
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from incident_schemas import IncidentCandidate

from app.citation_validator import ValidationResult, validate_citations
from app.llm_client import LLMClient
from app.prompts.root_cause_v1 import PROMPT_VERSION, build_prompt

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2


class ReasoningState(TypedDict):
    candidate: IncidentCandidate
    model: str
    attempt: int
    max_attempts: int
    validation_result: ValidationResult | None


def _build_graph(llm_client: LLMClient):
    async def generate_node(state: ReasoningState) -> dict:
        is_retry = state["attempt"] > 0
        system_prompt, user_prompt = build_prompt(state["candidate"], is_retry=is_retry)

        draft = await llm_client.generate_hypotheses(
            system_prompt=system_prompt, user_prompt=user_prompt, model=state["model"]
        )

        result = validate_citations(draft, state["candidate"])

        logger.info(
            "hypothesis_generation_attempt",
            extra={
                "incident_id": str(state["candidate"].id),
                "attempt": state["attempt"],
                "accepted": len(result.accepted),
                "rejected": len(result.rejected),
                "evidence_sufficient": draft.evidence_sufficient,
            },
        )

        return {"validation_result": result, "attempt": state["attempt"] + 1}

    def route_after_generate(state: ReasoningState) -> str:
        result = state["validation_result"]
        assert result is not None

        if result.has_any_valid_hypothesis:
            return "finalize"
        if state["attempt"] >= state["max_attempts"]:
            return "finalize"
        return "retry"

    async def finalize_node(state: ReasoningState) -> dict:
        return {}

    graph = StateGraph(ReasoningState)
    graph.add_node("generate", generate_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "generate")
    graph.add_conditional_edges(
        "generate", route_after_generate, {"retry": "generate", "finalize": "finalize"}
    )
    graph.add_edge("finalize", END)

    return graph.compile()


class ReasoningPipeline:
    def __init__(self, llm_client: LLMClient, max_attempts: int = MAX_ATTEMPTS) -> None:
        self._graph = _build_graph(llm_client)
        self._max_attempts = max_attempts

    async def run(self, candidate: IncidentCandidate, model: str) -> ValidationResult:
        initial_state: ReasoningState = {
            "candidate": candidate,
            "model": model,
            "attempt": 0,
            "max_attempts": self._max_attempts,
            "validation_result": None,
        }
        final_state = await self._graph.ainvoke(initial_state)
        result = final_state["validation_result"]
        assert result is not None
        return result

    @property
    def prompt_version(self) -> str:
        return PROMPT_VERSION
