"""
Pure decision logic: given an incident's severity, which channels get paged
immediately versus which just wait in the review queue. Kept separate from
the actual sending mechanism (escalation_sender.py) so the policy itself -
the part most likely to change per-customer or per-workspace in the future -
is trivially testable without touching Slack/PagerDuty at all.
"""

from __future__ import annotations

from incident_schemas import IncidentSeverity


def channels_for_severity(severity: IncidentSeverity) -> list[str]:
    if severity == IncidentSeverity.critical:
        return ["pagerduty", "slack"]
    if severity == IncidentSeverity.high:
        return ["slack"]
    # medium/low: no immediate page - surfaced via the review queue only,
    # since paging on-call for every anomaly-of-note would train people to
    # ignore pages, which defeats the entire point of paging.
    return []
