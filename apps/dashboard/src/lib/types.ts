export type Severity = "low" | "medium" | "high" | "critical";
export type IncidentStatus =
  | "candidate"
  | "analyzing"
  | "pending_review"
  | "published"
  | "dismissed";
export type Verdict = "accepted" | "rejected" | "edited";

export interface IncidentSummary {
  id: string;
  status: IncidentStatus;
  severity: Severity;
  started_at: string;
  resolved_at: string | null;
}

export interface EvidenceItem {
  id: string;
  source_type: string;
  source_ref: string;
  snippet: string;
  relevance_score: number;
  occurred_at: string;
}

export interface Hypothesis {
  id: string;
  rank: number;
  hypothesis: string;
  confidence: number;
  cited_evidence_ids: string[];
  human_verdict: Verdict | null;
  reviewed_by: string | null;
}

export interface IncidentDetail {
  incident: IncidentSummary;
  evidence: EvidenceItem[];
  hypotheses: Hypothesis[];
}
