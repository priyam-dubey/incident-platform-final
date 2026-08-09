"""
Shared fixtures. The FastAPI app under test never touches real Kafka or
ClickHouse - it gets fake implementations of EventPublisher/TelemetryWriter
injected via app.state, the exact same seam production code uses (the
lifespan context manager assigns the real implementations to the same
attributes). This is why app/routes/telemetry.py depends on
`request.app.state.event_publisher` rather than importing a concrete
KafkaEventPublisher directly - the route is infrastructure-agnostic.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class FakeEventPublisher:
    def __init__(self, fail_on_kinds: set[str] | None = None):
        self.published: list[tuple[str, object]] = []
        self._fail_on_kinds = fail_on_kinds or set()

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def publish(self, topic: str, event) -> None:
        if event.kind in self._fail_on_kinds:
            raise RuntimeError(f"simulated publish failure for kind={event.kind}")
        self.published.append((topic, event))


class FakeTelemetryWriter:
    def __init__(self, fail_on_kinds: set[str] | None = None):
        self.written: list[object] = []
        self._fail_on_kinds = fail_on_kinds or set()

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def write(self, event) -> None:
        if event.kind in self._fail_on_kinds:
            raise RuntimeError(f"simulated write failure for kind={event.kind}")
        self.written.append(event)


@pytest.fixture
def fake_publisher() -> FakeEventPublisher:
    return FakeEventPublisher()


@pytest.fixture
def fake_writer() -> FakeTelemetryWriter:
    return FakeTelemetryWriter()


@pytest.fixture
def client(fake_publisher: FakeEventPublisher, fake_writer: FakeTelemetryWriter) -> TestClient:
    app = create_app(
        event_publisher_factory=lambda settings: fake_publisher,
        telemetry_writer_factory=lambda settings: fake_writer,
    )

    with TestClient(app) as test_client:
        yield test_client
