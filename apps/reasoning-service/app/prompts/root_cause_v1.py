"""
Versioned prompt for root-cause hypothesis generation.

Versioning matters here for two reasons: (1) `ai_hypotheses.prompt_version`
is persisted alongside every hypothesis, so a bad prompt change can be
identified in production data after the fact, and (2) the eval harness
(referenced in ai_hypotheses -> eval_examples) can compare hypothesis
quality across prompt versions on the same historical incidents before a
new version is promoted - never overwrite PROMPT_VERSION_V1's text in place;
add a new module (root_cause_v2.py) instead, exactly like a DB migration.
"""

from __future__ import annotations

import json

from incident_schemas import IncidentCandidate

PROMPT_VERSION = "root_cause_v1"

_SYSTEM_PROMPT = """You are an incident root-cause analysis assistant for a production \
observability platform. You are given a structured set of evidence - anomalous metrics, \
error logs, and trace spans - that a deterministic correlation engine has already identified \
as occurring together during a suspected incident. You are NOT given raw, unfiltered \
telemetry; everything in the evidence set has already been filtered for relevance.

Your job is to propose the most likely root cause(s) for this incident, using ONLY the \
evidence provided. Follow these rules strictly:

1. Every hypothesis MUST cite at least one evidence id from the provided evidence list, \
using its exact "id" field. Do not invent, guess, or paraphrase an id you were not given.
2. Do not state any fact that is not directly supported by the provided evidence. If you are \
uncertain, reflect that uncertainty in a lower confidence score rather than stating a \
guess as if it were established.
3. If the evidence is too sparse or ambiguous to support any confident hypothesis, set \
evidence_sufficient to false and give your best (low-confidence) hypotheses anyway - do not \
refuse to answer, since a low-confidence hypothesis with clear caveats is more useful to an \
on-call engineer than no answer at all.
4. Rank hypotheses by how well the evidence supports them, most-supported first.
5. Confidence is a calibrated probability, not a vibe: 0.9+ means the evidence essentially \
proves this is the cause; 0.3-0.5 means it's a plausible explanation but far from certain.
"""

_RETRY_SUFFIX = """

IMPORTANT: Your previous attempt cited one or more evidence ids that do not exist in the \
evidence list below. This is a serious error - every cited_evidence_ids value MUST be copied \
EXACTLY from the "id" field of an item in the evidence list. Re-read the evidence list \
carefully before citing anything.
"""


def _format_evidence(candidate: IncidentCandidate) -> str:
    items = [
        {
            "id": str(item.id),
            "source_type": item.source_type,
            "service": item.service_name,
            "occurred_at": item.occurred_at.isoformat(),
            "content": item.snippet,
        }
        for item in candidate.evidence
    ]
    return json.dumps(items, indent=2)


def _format_affected_services(candidate: IncidentCandidate) -> str:
    items = [
        {
            "service": s.service_name,
            "metric": s.metric_name,
            "observed_value": s.observed_value,
            "baseline_mean": s.baseline_mean,
            "baseline_stddev": s.baseline_stddev,
            "anomaly_score": s.anomaly_score,
        }
        for s in candidate.affected_services
    ]
    return json.dumps(items, indent=2)


def build_prompt(candidate: IncidentCandidate, is_retry: bool = False) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt)."""
    system = _SYSTEM_PROMPT + (_RETRY_SUFFIX if is_retry else "")

    user = f"""Incident window: {candidate.window_start.isoformat()} to {candidate.window_end.isoformat()}
Suggested severity (from anomaly magnitude, not causal analysis): {candidate.suggested_severity.value}

Affected services and their anomalous metrics:
{_format_affected_services(candidate)}

Evidence (cite ids from this list ONLY):
{_format_evidence(candidate)}

Propose the most likely root cause hypotheses for this incident."""

    return system, user
