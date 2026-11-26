-- Migration 0005: PR/branch scans keep their own result without mutating the default-branch finding lifecycle.
ALTER TABLE scans ADD COLUMN result JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE scans ADD COLUMN head_branch TEXT;
CREATE UNIQUE INDEX idx_scans_dedupe ON scans (repository_id, commit_sha, trigger) WHERE status IN ('queued', 'running');
