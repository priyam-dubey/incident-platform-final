/**
 * Server-side client for the alert-router API. Every function here runs
 * only on the server (in a Server Component or Route Handler) - the API key
 * that authenticates the dashboard as a trusted machine client never
 * reaches the browser. Client components that need to trigger a write (the
 * verdict buttons) call this app's own /api/* route handlers instead, which
 * proxy through here.
 */

import { IncidentDetail, IncidentStatus, IncidentSummary, Verdict } from "./types";

const ALERT_ROUTER_URL = process.env.ALERT_ROUTER_URL ?? "http://localhost:8004";
const ALERT_ROUTER_API_KEY = process.env.ALERT_ROUTER_API_KEY ?? "dev-local-dashboard-key";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${ALERT_ROUTER_URL}${path}`, {
    ...init,
    headers: {
      "X-API-Key": ALERT_ROUTER_API_KEY,
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    // Incident state changes constantly - never let Next.js cache these.
    cache: "no-store",
  });

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiError(response.status, `${path} -> ${response.status}: ${body}`);
  }

  return response.json() as Promise<T>;
}

export async function listIncidents(
  workspaceId: string,
  statusFilter?: IncidentStatus,
): Promise<IncidentSummary[]> {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  if (statusFilter) params.set("status_filter", statusFilter);
  return request<IncidentSummary[]>(`/v1/incidents?${params.toString()}`);
}

export async function getIncidentDetail(incidentId: string): Promise<IncidentDetail | null> {
  try {
    return await request<IncidentDetail>(`/v1/incidents/${incidentId}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export async function submitVerdict(
  hypothesisId: string,
  verdict: Verdict,
  notes: string | undefined,
  reviewerEmail: string,
): Promise<{ hypothesis: unknown; incident_status: IncidentStatus }> {
  return request(`/v1/hypotheses/${hypothesisId}/verdict`, {
    method: "POST",
    headers: { "X-Reviewer-Email": reviewerEmail },
    body: JSON.stringify({ verdict, notes }),
  });
}
