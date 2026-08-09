import asyncio

import pytest

from app.alert_dispatcher import AlertDispatcher
from incident_schemas import IncidentSeverity


class FakeSender:
    def __init__(self, channel: str, fail_times: int = 0):
        self.channel = channel
        self._fail_times = fail_times
        self.call_count = 0

    async def send(self, incident_id: str, severity: IncidentSeverity, summary: str) -> None:
        self.call_count += 1
        if self.call_count <= self._fail_times:
            raise RuntimeError(f"simulated failure #{self.call_count}")


class FakeEventStore:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, str, str | None]] = []

    async def record_attempt(self, incident_id, channel, status, error) -> None:
        self.records.append((incident_id, channel, status, error))


async def test_dispatch_succeeds_on_first_attempt() -> None:
    sender = FakeSender("slack", fail_times=0)
    store = FakeEventStore()
    dispatcher = AlertDispatcher({"slack": sender}, store, max_attempts=3, base_backoff_seconds=0.01)

    results = await dispatcher.dispatch("inc-1", IncidentSeverity.high, "summary", ["slack"])

    assert results == {"slack": True}
    assert sender.call_count == 1
    assert store.records == [("inc-1", "slack", "sent", None)]


async def test_dispatch_retries_and_eventually_succeeds() -> None:
    sender = FakeSender("slack", fail_times=2)  # fails twice, succeeds on 3rd
    store = FakeEventStore()
    dispatcher = AlertDispatcher({"slack": sender}, store, max_attempts=3, base_backoff_seconds=0.01)

    results = await dispatcher.dispatch("inc-1", IncidentSeverity.high, "summary", ["slack"])

    assert results == {"slack": True}
    assert sender.call_count == 3
    assert store.records[-1] == ("inc-1", "slack", "sent", None)


async def test_dispatch_gives_up_after_max_attempts_and_records_failure() -> None:
    sender = FakeSender("slack", fail_times=10)  # always fails
    store = FakeEventStore()
    dispatcher = AlertDispatcher({"slack": sender}, store, max_attempts=3, base_backoff_seconds=0.01)

    results = await dispatcher.dispatch("inc-1", IncidentSeverity.high, "summary", ["slack"])

    assert results == {"slack": False}
    assert sender.call_count == 3  # exactly max_attempts, no more
    assert store.records[-1][2] == "failed"
    assert "simulated failure" in store.records[-1][3]


async def test_one_channel_failing_does_not_block_another_succeeding() -> None:
    failing_sender = FakeSender("slack", fail_times=10)
    working_sender = FakeSender("pagerduty", fail_times=0)
    store = FakeEventStore()
    dispatcher = AlertDispatcher(
        {"slack": failing_sender, "pagerduty": working_sender}, store, max_attempts=2, base_backoff_seconds=0.01
    )

    results = await dispatcher.dispatch(
        "inc-1", IncidentSeverity.critical, "summary", ["slack", "pagerduty"]
    )

    assert results == {"slack": False, "pagerduty": True}


async def test_missing_sender_for_requested_channel_fails_gracefully() -> None:
    store = FakeEventStore()
    dispatcher = AlertDispatcher({}, store, max_attempts=3, base_backoff_seconds=0.01)

    results = await dispatcher.dispatch("inc-1", IncidentSeverity.critical, "summary", ["pagerduty"])

    assert results == {"pagerduty": False}
    assert store.records[0][2] == "failed"
    assert "no sender configured" in store.records[0][3]


async def test_channels_are_dispatched_concurrently_not_sequentially() -> None:
    # If two channels each retry with backoff, dispatching them concurrently
    # should take roughly as long as the SLOWEST one, not the sum of both.
    class SlowFailThenSucceed(FakeSender):
        pass

    sender_a = SlowFailThenSucceed("slack", fail_times=2)
    sender_b = SlowFailThenSucceed("pagerduty", fail_times=2)
    store = FakeEventStore()
    dispatcher = AlertDispatcher(
        {"slack": sender_a, "pagerduty": sender_b}, store, max_attempts=3, base_backoff_seconds=0.05
    )

    start = asyncio.get_event_loop().time()
    await dispatcher.dispatch("inc-1", IncidentSeverity.critical, "summary", ["slack", "pagerduty"])
    elapsed = asyncio.get_event_loop().time() - start

    # Sequential would be ~2x (0.05 + 0.10) * 2 channels = ~0.6s; concurrent
    # should be close to a single channel's ~0.3s. Generous upper bound to
    # avoid flakiness while still catching an accidental sequential regression.
    assert elapsed < 0.5
