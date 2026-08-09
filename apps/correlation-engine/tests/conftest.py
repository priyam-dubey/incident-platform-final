"""
Shared fakes for correlation-engine tests. Same pattern as the ingestion
service: infra-touching classes (ServiceRegistry, IncidentCandidateSink) are
defined behind Protocols in production code, and tests inject in-memory
fakes implementing the same interface rather than needing live Postgres/Kafka.
"""

from __future__ import annotations

import uuid

import pytest

from incident_schemas import IncidentCandidate


class FakeServiceRegistry:
    def __init__(self) -> None:
        self._ids: dict[tuple[uuid.UUID, str], uuid.UUID] = {}

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def resolve(self, workspace_id: uuid.UUID, service_name: str) -> uuid.UUID:
        key = (workspace_id, service_name)
        if key not in self._ids:
            self._ids[key] = uuid.uuid4()
        return self._ids[key]


class FakeCandidateSink:
    def __init__(self) -> None:
        self.published: list[IncidentCandidate] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def publish(self, candidate: IncidentCandidate) -> None:
        self.published.append(candidate)


@pytest.fixture
def fake_service_registry() -> FakeServiceRegistry:
    return FakeServiceRegistry()


@pytest.fixture
def fake_candidate_sink() -> FakeCandidateSink:
    return FakeCandidateSink()
