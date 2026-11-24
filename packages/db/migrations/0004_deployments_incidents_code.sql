-- Migration 0004: deployments, application-scoped incidents, notes, GitHub + code scanning.

-- ---------------- deployments (code <-> runtime correlation) ----------------
CREATE TABLE deployments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    application_id      UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    version             TEXT,
    commit_sha          TEXT CHECK (commit_sha IS NULL OR commit_sha ~ '^[0-9a-fA-F]{7,64}$'),
    branch              TEXT,
    repository_full_name TEXT,
    environment         TEXT NOT NULL,
    deployed_by         TEXT,
    source              TEXT NOT NULL DEFAULT 'api' CHECK (source IN ('api', 'sdk', 'github', 'manual')),
    deployed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_deployments_app_time ON deployments (workspace_id, application_id, deployed_at DESC);

-- ---------------- incidents on real application telemetry ----------------
ALTER TABLE incidents
    ADD COLUMN application_id UUID REFERENCES applications(id) ON DELETE CASCADE,
    ADD COLUMN fingerprint    TEXT,
    ADD COLUMN detector       TEXT,                           -- e.g. 'error_rate_zscore'
    ADD COLUMN details        JSONB NOT NULL DEFAULT '{}'::jsonb, -- measured numbers, never model output
    ADD COLUMN is_synthetic   BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN resolved_by    UUID REFERENCES users(id) ON DELETE SET NULL;
-- At most one open incident per (application, fingerprint): this is the dedupe guarantee.
CREATE UNIQUE INDEX idx_incidents_open_fingerprint ON incidents (application_id, fingerprint)
    WHERE application_id IS NOT NULL AND status NOT IN ('dismissed', 'resolved');
CREATE INDEX idx_incidents_app ON incidents (workspace_id, application_id, started_at DESC);

CREATE TABLE incident_notes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id  UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
    body         TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 4000),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_incident_notes ON incident_notes (incident_id, created_at);

-- Hypotheses gain an edited text body and a flag marking model output that could not be grounded.
ALTER TABLE ai_hypotheses ADD COLUMN edited_text TEXT;
ALTER TABLE incident_evidence DROP CONSTRAINT IF EXISTS incident_evidence_source_type_check;
ALTER TABLE incident_evidence ADD CONSTRAINT incident_evidence_source_type_check
    CHECK (source_type IN ('log', 'metric', 'trace', 'deploy'));

-- Notification channel configuration state (never stores secrets; those live in env vars).
CREATE TABLE notification_deliveries (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    incident_id  UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    channel      TEXT NOT NULL CHECK (channel IN ('slack', 'pagerduty')),
    status       TEXT NOT NULL CHECK (status IN ('sent', 'failed')),
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------- GitHub App + code intelligence ----------------
CREATE TABLE github_installations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    installation_id  BIGINT NOT NULL,
    account_login    TEXT NOT NULL,
    account_type     TEXT,
    suspended_at     TIMESTAMPTZ,
    created_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (installation_id)                 -- an installation belongs to exactly one workspace
);
CREATE INDEX idx_gh_inst_ws ON github_installations (workspace_id);

-- One-time, expiring `state` values bind the GitHub install redirect to a user + workspace.
CREATE TABLE github_install_states (
    state_hash   TEXT PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at   TIMESTAMPTZ NOT NULL
);

CREATE TABLE github_webhook_deliveries (
    delivery_id  TEXT PRIMARY KEY,           -- idempotency: GitHub retries reuse the id
    event        TEXT NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE repositories (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    installation_id  BIGINT NOT NULL REFERENCES github_installations(installation_id) ON DELETE CASCADE,
    github_repo_id   BIGINT,
    full_name        TEXT NOT NULL,
    default_branch   TEXT NOT NULL DEFAULT 'main',
    is_private       BOOLEAN NOT NULL DEFAULT true,
    connected        BOOLEAN NOT NULL DEFAULT false,
    language_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_scan_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, full_name)
);

CREATE TABLE scans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    repository_id   UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    commit_sha      TEXT NOT NULL,
    ref             TEXT,
    trigger         TEXT NOT NULL CHECK (trigger IN ('manual', 'push', 'pull_request', 'schedule')),
    pr_number       INT,
    status          TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    error           TEXT,
    tools           JSONB NOT NULL DEFAULT '{}'::jsonb,   -- per-tool: ok/skipped/failed + reason + version
    counts          JSONB NOT NULL DEFAULT '{}'::jsonb,
    locked_at       TIMESTAMPTZ,
    queued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    requested_by    UUID REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX idx_scans_repo ON scans (workspace_id, repository_id, queued_at DESC);
CREATE INDEX idx_scans_queue ON scans (status, queued_at) WHERE status = 'queued';

CREATE TABLE findings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    repository_id   UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    fingerprint     TEXT NOT NULL,                       -- stable across commits
    tool            TEXT NOT NULL,
    rule_id         TEXT NOT NULL,
    category        TEXT NOT NULL CHECK (category IN ('sast', 'lint', 'types', 'dependency', 'secret', 'iac', 'other')),
    severity        TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    title           TEXT NOT NULL,
    message         TEXT,
    file_path       TEXT,
    start_line      INT,
    end_line        INT,
    code_snippet    TEXT,                                -- redacted for secrets
    cwe             TEXT,
    package_name    TEXT,
    package_version TEXT,
    fixed_version   TEXT,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'fixed', 'ignored', 'false_positive', 'accepted_risk')),
    first_seen_scan UUID REFERENCES scans(id) ON DELETE SET NULL,
    last_seen_scan  UUID REFERENCES scans(id) ON DELETE SET NULL,
    first_seen_commit TEXT,
    last_seen_commit  TEXT,
    fixed_at        TIMESTAMPTZ,
    reintroduced_count INT NOT NULL DEFAULT 0,
    triage_note     TEXT,
    triaged_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    explanation     JSONB,                               -- AI explanation (explicitly labelled as AI-generated)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repository_id, fingerprint)
);
CREATE INDEX idx_findings_repo_status ON findings (workspace_id, repository_id, status, severity);
