"""
Channel-specific alert senders, behind a common `AlertSender` interface so
the dispatcher (alert_dispatcher.py) doesn't need to know which channel it's
talking to. Both are thin, real HTTP integrations against documented APIs -
Slack's incoming webhook format, PagerDuty's Events API v2 "trigger" action.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from incident_schemas import IncidentSeverity


class AlertSender(Protocol):
    channel: str

    async def send(self, incident_id: str, severity: IncidentSeverity, summary: str) -> None:
        """Raises on failure - the dispatcher is responsible for retry/backoff."""
        ...


class SlackAlertSender:
    channel = "slack"

    def __init__(self, webhook_url: str, http_client: httpx.AsyncClient | None = None) -> None:
        self._webhook_url = webhook_url
        self._http = http_client or httpx.AsyncClient(timeout=5.0)

    async def send(self, incident_id: str, severity: IncidentSeverity, summary: str) -> None:
        response = await self._http.post(
            self._webhook_url,
            json={
                "text": (
                    f":rotating_light: *{severity.value.upper()} incident detected*\n"
                    f"Incident `{incident_id}`\n{summary}"
                )
            },
        )
        response.raise_for_status()


class PagerDutyAlertSender:
    channel = "pagerduty"
    _EVENTS_API_URL = "https://events.pagerduty.com/v2/enqueue"

    def __init__(self, routing_key: str, http_client: httpx.AsyncClient | None = None) -> None:
        self._routing_key = routing_key
        self._http = http_client or httpx.AsyncClient(timeout=5.0)

    async def send(self, incident_id: str, severity: IncidentSeverity, summary: str) -> None:
        response = await self._http.post(
            self._EVENTS_API_URL,
            json={
                "routing_key": self._routing_key,
                "event_action": "trigger",
                "dedup_key": incident_id,
                "payload": {
                    "summary": summary,
                    "severity": "critical" if severity == IncidentSeverity.critical else "error",
                    "source": "incident-platform",
                    "custom_details": {"incident_id": incident_id},
                },
            },
        )
        response.raise_for_status()
