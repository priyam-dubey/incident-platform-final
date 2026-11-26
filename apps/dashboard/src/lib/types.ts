export type Role = "owner" | "admin" | "developer" | "viewer";
export interface Workspace { id: string; name: string; role: Role; is_demo: boolean }
export interface User { id: string; email: string; display_name: string; email_verified: boolean }
export interface Application {
  id: string; name: string; environment: string; framework: string; backend_url: string | null; is_synthetic: boolean;
  connection_status: "waiting_for_telemetry" | "connected" | "stale"; last_telemetry_at: string | null; active_key_prefix: string | null; created_at: string;
}
export interface Onboarding { ingestion_endpoint: string; key_header: string; env: Record<string, string>; note: string }
export interface Summary {
  requests: number; errors_5xx: number; errors_4xx: number; error_rate: number | null; requests_per_minute: number;
  avg_ms: number | null; p50_ms: number | null; p95_ms: number | null; p99_ms: number | null;
}
export interface Point { t: string; requests: number; errors_5xx: number; avg_ms: number | null; p95_ms: number | null; p99_ms: number | null; error_rate: number | null; requests_per_minute: number }
export interface Endpoint { method: string; route: string; requests: number; errors_5xx: number; errors_4xx: number; error_rate: number | null; avg_ms: number | null; p95_ms: number | null; p99_ms: number | null }
export interface LogRow { timestamp: string; severity: string; message: string; trace_id: string | null; span_id: string | null; attributes: Record<string, unknown> }
export interface TraceRow { trace_id: string; start: string; duration_ms: number | null; spans: number; failed_spans: number; root_operation: string | null }
export interface Incident {
  id: string; title: string; status: string; severity: string; detector: string | null; application_id: string | null; application_name: string | null;
  started_at: string; resolved_at: string | null; details: Record<string, unknown>; synthetic: boolean; updated_at: string;
}
export interface Hypothesis {
  id: string; rank: number; hypothesis: string; edited_text: string | null; confidence: number; cited_evidence_ids: string[]; human_verdict: string | null;
  verdict_notes: string | null; reviewed_by: string | null; model: string; ai_generated: boolean;
}
export interface Evidence { id: string; source_type: string; source_ref: string; snippet: string; relevance_score: number; occurred_at: string }
export interface Deployment { id: string; application_id: string; application_name?: string; version: string | null; commit_sha: string | null; branch: string | null; repository: string | null; environment: string; deployed_by: string | null; source: string; deployed_at: string }
export interface Repo { id: string; full_name: string; default_branch: string; private: boolean; connected: boolean; languages: Record<string, number>; last_scan_at: string | null; open_findings: number; by_severity: Record<string, number> }
export interface Finding {
  id: string; repository_id: string; repository: string | null; tool: string; rule_id: string; category: string; severity: string; title: string;
  file_path: string | null; start_line: number | null; end_line: number | null; cwe: string | null; package_name: string | null; package_version: string | null;
  fixed_version: string | null; status: string; first_seen_commit: string | null; last_seen_commit: string | null; reintroduced_count: number; updated_at: string;
  message?: string; code_snippet?: string | null; triage_note?: string | null;
  explanation?: { summary: string; why_it_matters: string; suggested_fix: string; false_positive_likelihood: string; model: string; disclaimer: string } | null;
}
export interface Scan { id: string; repository_id: string; commit_sha: string; ref: string | null; trigger: string; pr_number: number | null; status: string; error: string | null; tools: Record<string, { status: string; detail: string | null; findings: number }>; counts: Record<string, number>; queued_at: string; finished_at: string | null; result: { new_findings?: { title: string; severity: string; file_path: string | null; start_line: number | null; tool: string }[] } }
export interface Integrations {
  llm: { state: string; provider: string; model: string; detail: string | null };
  notifications: { slack: string; pagerduty: string };
  github_app: { state: string; missing: string[]; app_slug: string | null };
  telemetry_store: string;
}
