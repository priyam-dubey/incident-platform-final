"""
Worker entrypoint. Consumes `incident.candidates` from Kafka, runs each
candidate through the LangGraph reasoning pipeline, and persists the
outcome. A semaphore bounds concurrent in-flight LLM calls
(reasoning_max_concurrency) - Kafka delivers messages faster than the
Gemini API should be hit, so the bound prevents unbounded concurrency for cost
control and to avoid tripping rate limits.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from aiokafka import AIOKafkaConsumer
from fastapi import FastAPI

from app.config import get_settings
from app.hypothesis_writer import PostgresHypothesisWriter
from incident_llm import LLMClient as CentralLLMClient
from app.llm_client import CentralHypothesisClient
from app.logging_config import configure_logging
from app.metrics import (
    CANDIDATES_WITH_NO_VALID_HYPOTHESIS_TOTAL,
    HYPOTHESES_ACCEPTED_TOTAL,
    HYPOTHESES_REJECTED_TOTAL,
    metrics_response,
)
from app.reasoning_graph import ReasoningPipeline
from incident_schemas import IncidentCandidate

logger = logging.getLogger(__name__)

_stats = {"candidates_consumed": 0, "hypotheses_accepted": 0, "candidates_with_no_valid_hypothesis": 0}


async def _process_candidate(
    raw_value: bytes,
    pipeline: ReasoningPipeline,
    writer: PostgresHypothesisWriter,
    model: str,
    semaphore: asyncio.Semaphore,
) -> None:
    candidate = IncidentCandidate.model_validate(json.loads(raw_value))

    async with semaphore:
        result = await pipeline.run(candidate, model=model)

    await writer.write(
        incident_id=candidate.id,
        result=result,
        prompt_version=pipeline.prompt_version,
        model_name=model,
    )

    _stats["candidates_consumed"] += 1
    _stats["hypotheses_accepted"] += len(result.accepted)
    HYPOTHESES_ACCEPTED_TOTAL.inc(len(result.accepted))
    HYPOTHESES_REJECTED_TOTAL.inc(len(result.rejected))
    if not result.has_any_valid_hypothesis:
        _stats["candidates_with_no_valid_hypothesis"] += 1
        CANDIDATES_WITH_NO_VALID_HYPOTHESIS_TOTAL.inc()
        logger.warning(
            "incident_candidate_produced_no_valid_hypothesis",
            extra={"incident_id": str(candidate.id), "rejected_count": len(result.rejected)},
        )


async def _consume_loop(
    consumer: AIOKafkaConsumer,
    pipeline: ReasoningPipeline,
    writer: PostgresHypothesisWriter,
    model: str,
    max_concurrency: int,
) -> None:
    semaphore = asyncio.Semaphore(max_concurrency)
    in_flight: set[asyncio.Task] = set()

    async for message in consumer:
        task = asyncio.create_task(
            _process_candidate(message.value, pipeline, writer, model, semaphore)
        )
        in_flight.add(task)
        task.add_done_callback(lambda t: in_flight.discard(t))

        for t in list(in_flight):
            if t.done() and t.exception() is not None:
                logger.exception("candidate_processing_failed", exc_info=t.exception())
                in_flight.discard(t)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    central_llm = CentralLLMClient()
    llm_status = central_llm.status()
    if llm_status["state"] != "configured":
        logger.warning("llm_not_ready", extra=llm_status)
    else:
        logger.info("llm_ready", extra={"provider": llm_status["provider"], "model": llm_status["model"]})
    app.state.llm_status = central_llm.status
    llm_client = CentralHypothesisClient(central_llm)
    pipeline = ReasoningPipeline(llm_client=llm_client, max_attempts=settings.reasoning_max_attempts)

    writer = PostgresHypothesisWriter(settings.database_url)
    await writer.start()

    consumer = AIOKafkaConsumer(
        settings.kafka_topic_incident_candidates,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group_reasoning,
        enable_auto_commit=True,
        auto_offset_reset="latest",
        **settings.kafka_client_kwargs,
    )
    await consumer.start()

    app.state.stats = _stats

    consume_task = asyncio.create_task(
        _consume_loop(consumer, pipeline, writer, central_llm.config.model, settings.reasoning_max_concurrency)
    )

    logger.info("reasoning_service_started", extra={"environment": settings.environment})

    yield

    consume_task.cancel()
    await consumer.stop()
    await writer.stop()
    logger.info("reasoning_service_stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="Incident Platform - Reasoning Service", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/llm-status", tags=["ops"])
    async def llm_status() -> dict:
        # Reports provider/model/state only; never any secret value.
        status_fn = getattr(app.state, "llm_status", None)
        return status_fn() if status_fn else {"state": "unknown"}

    @app.get("/stats", tags=["ops"])
    async def stats() -> dict:
        return dict(_stats)

    @app.get("/metrics", tags=["ops"])
    async def metrics():
        return metrics_response()

    return app


app = create_app()
