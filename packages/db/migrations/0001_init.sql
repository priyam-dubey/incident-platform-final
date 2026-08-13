-- Migration 0001: core schema for incidents, evidence, hypotheses, approvals.
-- Applied via packages/db/src/migrate.py. Idempotent-safe: guarded by
-- schema_migrations bookkeeping table, never re-run once recorded.

BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto"; -- gen_random_uuid()

CREATE TABLE workspaces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE services (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, name)
);

-- Deploy events feed the reasoning layer with "what changed recently" context.
CREATE TABLE deploy_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    service_id      UUID NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    revision        TEXT NOT NULL,
    deployed_by     TEXT,
    deployed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_deploy_events_service_time ON deploy_events (service_id, deployed_at DESC);

CREATE TYPE incident_status AS ENUM (
    'candidate',        -- correlation engine produced it, not yet reasoned over
    'analyzing',         -- reasoning service is generating hypotheses
    'pending_review',    -- hypotheses generated, awaiting human verdict
    'published',          -- human accepted, postmortem live
    'dismissed'            -- human rejected as noise / false positive
);

CREATE TYPE incident_severity AS ENUM ('low', 'medium', 'high', 'critical');

CREATE TABLE incidents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    title           TEXT,
    status          incident_status NOT NULL DEFAULT 'candidate',
    severity        incident_severity NOT NULL DEFAULT 'medium',
    started_at      TIMESTAMPTZ NOT NULL,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_incidents_workspace_status ON incidents (workspace_id, status);
CREATE INDEX idx_incidents_started_at ON incidents (started_at DESC);

-- Every service implicated in an incident's anomaly cluster (dependency-graph output).
CREATE TABLE incident_services (
    incident_id     UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    service_id      UUID NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    anomaly_score   NUMERIC NOT NULL,
    PRIMARY KEY (incident_id, service_id)
);

-- Structured evidence handed to the reasoning layer - never raw, unbounded telemetry.
-- source_ref points back into ClickHouse (a queryable row/span/metric identifier)
-- so every citation the AI makes can be resolved and validated against real data.
CREATE TABLE incident_evidence (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id     UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL CHECK (source_type IN ('log', 'metric', 'trace', 'deploy')),
    source_ref      TEXT NOT NULL,       -- e.g. clickhouse row id / trace span id
    service_id      UUID REFERENCES services(id),
    snippet         TEXT NOT NULL,       -- redacted, bounded excerpt shown to the model
    relevance_score NUMERIC NOT NULL DEFAULT 0,
    occurred_at     TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_evidence_incident ON incident_evidence (incident_id);

CREATE TABLE ai_hypotheses (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id         UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    rank                INT NOT NULL,
    hypothesis          TEXT NOT NULL,
    confidence          NUMERIC NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    cited_evidence_ids  UUID[] NOT NULL DEFAULT '{}',
    prompt_version      TEXT NOT NULL,
    model_name          TEXT NOT NULL,
    human_verdict       TEXT CHECK (human_verdict IN ('accepted', 'rejected', 'edited')),
    verdict_notes       TEXT,
    reviewed_by         TEXT,
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_hypotheses_incident ON ai_hypotheses (incident_id, rank);

-- Every human accept/reject/edit becomes a labeled example for the eval harness (Phase 4/7).
CREATE TABLE eval_examples (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hypothesis_id   UUID NOT NULL REFERENCES ai_hypotheses(id) ON DELETE CASCADE,
    label           TEXT NOT NULL CHECK (label IN ('accepted', 'rejected', 'edited')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE oncall_schedules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    engineer_name   TEXT NOT NULL,
    engineer_contact TEXT NOT NULL,
    starts_at       TIMESTAMPTZ NOT NULL,
    ends_at         TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_oncall_window ON oncall_schedules (workspace_id, starts_at, ends_at);

CREATE TABLE alert_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id     UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    channel         TEXT NOT NULL CHECK (channel IN ('slack', 'pagerduty', 'email')),
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    attempts        INT NOT NULL DEFAULT 0,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ
);

COMMIT;
