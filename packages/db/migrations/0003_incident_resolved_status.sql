-- Migration 0003: add the 'resolved' lifecycle state (kept alone: a new enum value
-- cannot be used in the same transaction that adds it).
ALTER TYPE incident_status ADD VALUE IF NOT EXISTS 'resolved';
