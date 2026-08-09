import Link from "next/link";
import { listIncidents } from "@/lib/api";
import { SeverityBadge } from "@/components/SeverityBadge";
import { IncidentStatus } from "@/lib/types";

const STATUS_FILTERS: { value: IncidentStatus | undefined; label: string }[] = [
  { value: undefined, label: "ALL" },
  { value: "pending_review", label: "PENDING REVIEW" },
  { value: "published", label: "PUBLISHED" },
  { value: "dismissed", label: "DISMISSED" },
];

export default async function IncidentsPage({
  searchParams,
}: {
  searchParams: { workspace_id?: string; status?: string };
}) {
  const workspaceId = searchParams.workspace_id;

  if (!workspaceId) {
    return (
      <div className="mx-auto max-w-lg px-6 py-24">
        <p className="font-mono text-sm text-critical">
          Missing workspace_id. <Link href="/" className="text-ai underline">Go back</Link>.
        </p>
      </div>
    );
  }

  const statusFilter = (searchParams.status as IncidentStatus | undefined) || undefined;
  const incidents = await listIncidents(workspaceId, statusFilter);

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <div className="flex items-baseline justify-between">
        <h1 className="font-display text-xl font-medium">Incident feed</h1>
        <span className="font-mono text-xs text-muted">{incidents.length} shown</span>
      </div>

      <nav className="mt-4 flex gap-4 border-b border-hairline pb-3">
        {STATUS_FILTERS.map((f) => {
          const href = `/incidents?workspace_id=${workspaceId}${f.value ? `&status=${f.value}` : ""}`;
          const active = (statusFilter ?? undefined) === f.value;
          return (
            <Link
              key={f.label}
              href={href}
              className={`font-mono text-xs tracking-wider ${
                active ? "text-ai" : "text-muted hover:text-primary"
              }`}
            >
              {f.label}
            </Link>
          );
        })}
      </nav>

      {incidents.length === 0 ? (
        <div className="mt-16 text-center">
          <p className="font-mono text-sm text-muted">
            No incidents{statusFilter ? ` with status "${statusFilter}"` : ""} yet.
          </p>
        </div>
      ) : (
        <div className="mt-2">
          {incidents.map((incident) => (
            <Link
              key={incident.id}
              href={`/incidents/${incident.id}`}
              className="signal-row grid grid-cols-[6rem_1fr_10rem_auto] items-center gap-4 py-4 transition-colors hover:bg-panel"
            >
              <SeverityBadge severity={incident.severity} />
              <span className="font-mono text-sm text-primary">{incident.id}</span>
              <span className="font-mono text-xs text-muted">{incident.status.toUpperCase()}</span>
              <span className="font-mono text-xs text-muted">
                {new Date(incident.started_at).toISOString().replace("T", " ").slice(0, 19)}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
