"""
Dispatches an incident to every channel its severity requires, with bounded
retry and exponential backoff per channel. Each attempt (success or failure)
is recorded via `AlertEventStore` so `alert_events` is a genuine audit trail
of what was attempted, not just what succeeded - useful both operationally
("did the page actually go out during the postmortem?") and for catching a
chronically-failing webhook before it silently stops paging anyone.

A failed channel does not block other channels - if Slack is down but
PagerDuty succeeds, the page still goes out. Each channel's outcome is
independent and independently retried.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from incident_schemas import IncidentSeverity

from app.alert_senders import AlertSender

logger = logging.getLogger(__name__)


class AlertEventStore(Protocol):
    async def record_attempt(
        self, incident_id: str, channel: str, status: str, error: str | None
    ) -> None: ...


class AlertDispatcher:
    def __init__(
        self,
        senders: dict[str, AlertSender],
        event_store: AlertEventStore,
        max_attempts: int = 3,
        base_backoff_seconds: float = 1.0,
    ) -> None:
        self._senders = senders
        self._event_store = event_store
        self._max_attempts = max_attempts
        self._base_backoff = base_backoff_seconds

    async def dispatch(
        self, incident_id: str, severity: IncidentSeverity, summary: str, channels: list[str]
    ) -> dict[str, bool]:
        """Returns {channel: succeeded} for every requested channel."""
        results: dict[str, bool] = {}

        # Channels are dispatched concurrently - one slow/failing channel's
        # retry backoff must not delay paging on a channel that would have
        # succeeded immediately.
        outcomes = await asyncio.gather(
            *(self._send_with_retry(incident_id, severity, summary, ch) for ch in channels)
        )
        for channel, succeeded in zip(channels, outcomes):
            results[channel] = succeeded
        return results

    async def _send_with_retry(
        self, incident_id: str, severity: IncidentSeverity, summary: str, channel: str
    ) -> bool:
        sender = self._senders.get(channel)
        if sender is None:
            logger.error("no_alert_sender_configured", extra={"channel": channel})
            await self._event_store.record_attempt(
                incident_id, channel, "failed", f"no sender configured for channel={channel}"
            )
            return False

        last_error: str | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                await sender.send(incident_id, severity, summary)
                await self._event_store.record_attempt(incident_id, channel, "sent", None)
                return True
            except Exception as exc:  # noqa: BLE001 - any failure triggers retry, by design
                last_error = str(exc)
                logger.warning(
                    "alert_send_attempt_failed",
                    extra={"incident_id": incident_id, "channel": channel, "attempt": attempt, "error": last_error},
                )
                if attempt < self._max_attempts:
                    await asyncio.sleep(self._base_backoff * (2 ** (attempt - 1)))

        await self._event_store.record_attempt(incident_id, channel, "failed", last_error)
        return False
