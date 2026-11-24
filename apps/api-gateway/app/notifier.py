"""Slack / PagerDuty notifications. Only used when explicitly configured; status is reported honestly."""

from __future__ import annotations

import logging

import httpx

from app.config import Settings

logger = logging.getLogger("notifier")
SEV_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def channel_status(settings: Settings) -> dict:
    return {"slack": "configured" if settings.slack_webhook_url else "not_configured",
            "pagerduty": "configured" if settings.pagerduty_routing_key else "not_configured"}


def notify(settings: Settings, incident: dict, link: str, transport: httpx.BaseTransport | None = None) -> list[tuple[str, str, str | None]]:
    """Returns [(channel, 'sent'|'failed', error)] for each *configured* channel. Nothing is sent when nothing is configured."""
    if SEV_RANK.get(incident["severity"], 0) < SEV_RANK.get(settings.notify_min_severity, 2):
        return []
    results = []
    with httpx.Client(timeout=8, transport=transport) as http:
        if settings.slack_webhook_url:
            results.append(_send("slack", http, settings.slack_webhook_url, {
                "text": f":rotating_light: *{incident['severity'].upper()}* {incident['title']}\n{link}"}))
        if settings.pagerduty_routing_key:
            results.append(_send("pagerduty", http, "https://events.pagerduty.com/v2/enqueue", {
                "routing_key": settings.pagerduty_routing_key, "event_action": "trigger", "dedup_key": str(incident["id"]),
                "payload": {"summary": incident["title"][:1000], "source": incident.get("application_name") or "incident-platform",
                            "severity": "critical" if incident["severity"] == "critical" else "error"},
                "links": [{"href": link, "text": "Open incident"}]}))
    return results


def _send(channel: str, http: httpx.Client, url: str, payload: dict) -> tuple[str, str, str | None]:
    try:
        r = http.post(url, json=payload)
        if r.status_code >= 300:
            return channel, "failed", f"HTTP {r.status_code}"
        return channel, "sent", None
    except Exception as exc:                      # never include URL (contains the secret)
        logger.warning("notify_failed channel=%s type=%s", channel, type(exc).__name__)
        return channel, "failed", type(exc).__name__
