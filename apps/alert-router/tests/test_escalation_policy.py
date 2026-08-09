from app.escalation_policy import channels_for_severity
from incident_schemas import IncidentSeverity


def test_critical_pages_both_pagerduty_and_slack() -> None:
    assert set(channels_for_severity(IncidentSeverity.critical)) == {"pagerduty", "slack"}


def test_high_pages_slack_only() -> None:
    assert channels_for_severity(IncidentSeverity.high) == ["slack"]


def test_medium_and_low_do_not_page_anyone() -> None:
    assert channels_for_severity(IncidentSeverity.medium) == []
    assert channels_for_severity(IncidentSeverity.low) == []
