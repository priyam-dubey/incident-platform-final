# Reasoning Service

Consumes `IncidentCandidate` objects from Kafka (`incident.candidates`),
runs them through a LangGraph reasoning pipeline that generates root-cause
hypotheses, and programmatically validates every citation before anything is
persisted or shown to a human.

## Why this is the hard part

Any pipeline can ask an LLM to produce JSON. The part that makes this a
*production* reasoning system rather than a demo is what happens after the
model responds - specifically, whether a fabricated claim can survive to
reach a human. This service is built so it structurally cannot:

1. **Structured output is schema-constrained**, not requested-and-hoped-for
   (`app/llm_client.py`) - the model's response comes back already shaped
   like `HypothesisSetDraft`, using Gemini's JSON-schema response mode.
2. **Every citation is independently verified** against the actual evidence
   set the candidate was built from (`app/citation_validator.py`) - a
   syntactically valid but fabricated evidence UUID is caught here, not
   trusted because the schema validated.
3. **A hallucinated citation triggers exactly one retry** with an explicit
   correction appended to the prompt (`app/reasoning_graph.py`,
   `app/prompts/root_cause_v1.py`) - not silently accepted, not an infinite
   retry loop, not a hard failure of the whole incident.
4. **If nothing validates after the retry budget**, the incident is
   persisted with zero accepted hypotheses and flagged - never presented to
   a human with fabricated support, and never silently dropped.

## Pipeline

```
Kafka incident.candidates
        │
        ▼
IncidentCandidate.model_validate(...)
        │
        ▼
ReasoningPipeline.run()  [LangGraph]
        │
   ┌────┴─────┐
   ▼          │
generate ──►  validate_citations
   ▲               │
   │        has_valid? ──yes──► finalize
   └────no, retries left────────┘
                    │
                    ▼ (finalize)
         PostgresHypothesisWriter
   (ai_hypotheses rows, ranked by confidence;
    incidents.status -> pending_review or analyzing)
```

## Local development

Requires `GEMINI_API_KEY` set in `.env` to actually call a model - without
it the service starts (and passes health checks) but every candidate it
tries to process will fail at the first LLM call, logged clearly rather than
crashing the consumer loop.

```bash
# from repo root
make infra-up
cd apps/reasoning-service
pip install -r requirements-dev.txt
pytest -v
uvicorn app.main:app --reload --port 8003
```

## Testing strategy

`LLMClient` is a `Protocol`; `GeminiLLMClient` is the real implementation,
`FakeLLMClient` (in `tests/conftest.py`) lets tests script exact response
sequences - including "hallucinate on attempt 1, correct on attempt 2" - so
the retry state machine in `reasoning_graph.py` is tested against real,
deterministic LangGraph execution without ever calling the live API. The
citation validator and structured-output schemas are pure logic, tested
directly. What is **not** exercised in this sandbox: the live Gemini API
call itself, and how the actual model behaves against `root_cause_v1`'s
prompt - that requires `GEMINI_API_KEY` and a live run, which is the one
piece of this service that has to be validated outside this environment.

## Prompt versioning

`app/prompts/root_cause_v1.py` is never edited in place once it's live -
`PROMPT_VERSION` is persisted on every `ai_hypotheses` row, so a new prompt
ships as `root_cause_v2.py` and both can be compared against the same
historical incidents via the eval harness (Phase 7) before v2 is promoted.
