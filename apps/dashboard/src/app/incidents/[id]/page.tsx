import { notFound } from "next/navigation";
import { getIncidentDetail } from "@/lib/api";
import { SeverityBadge } from "@/components/SeverityBadge";
import { EvidenceRow } from "@/components/EvidenceRow";
import { ConfidenceReadout } from "@/components/ConfidenceReadout";
import { VerdictControls } from "@/components/VerdictControls";
import { BackLink } from "@/components/BackLink";

export default async function IncidentDetailPage({ params }: { params: { id: string } }) {
  const detail = await getIncidentDetail(params.id);
  if (!detail) notFound();

  const { incident, evidence, hypotheses } = detail;

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <BackLink />

      <div className="mt-4 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <SeverityBadge severity={incident.severity} />
            <span className="font-mono text-xs text-muted">{incident.status.toUpperCase()}</span>
          </div>
          <h1 className="mt-2 font-display text-xl font-medium">{incident.id}</h1>
          <p className="mt-1 font-mono text-xs text-muted">
            started {new Date(incident.started_at).toISOString().replace("T", " ").slice(0, 19)} UTC
          </p>
        </div>
      </div>

      <section className="mt-10">
        <h2 className="font-display text-sm font-medium uppercase tracking-wider text-muted">
          Root-cause hypotheses
        </h2>
        {hypotheses.length === 0 ? (
          <p className="mt-3 font-mono text-sm text-muted">
            No hypotheses generated yet - the reasoning service may still be processing this
            incident, or every attempt failed citation validation.
          </p>
        ) : (
          <div className="mt-3 flex flex-col gap-4">
            {hypotheses.map((h) => (
              <div key={h.id} className="border border-hairline bg-panel p-4">
                <div className="flex items-start justify-between gap-4">
                  <p className="font-body text-sm leading-relaxed text-primary">
                    <span className="mr-2 font-mono text-xs text-muted">#{h.rank}</span>
                    {h.hypothesis}
                  </p>
                </div>
                <div className="mt-3">
                  <ConfidenceReadout
                    confidence={h.confidence}
                    citedEvidenceIds={h.cited_evidence_ids}
                    evidence={evidence}
                  />
                </div>
                <div className="mt-4">
                  <VerdictControls
                    hypothesisId={h.id}
                    existingVerdict={h.human_verdict}
                    reviewedBy={h.reviewed_by}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="mt-10">
        <h2 className="font-display text-sm font-medium uppercase tracking-wider text-muted">
          Evidence trail
        </h2>
        <p className="mt-1 font-mono text-xs text-muted">
          Everything the reasoning service was given - and only what it was given.
        </p>
        <div className="mt-3 border-t border-hairline">
          {evidence.map((item, i) => (
            <EvidenceRow key={item.id} item={item} index={i + 1} />
          ))}
        </div>
      </section>
    </div>
  );
}
