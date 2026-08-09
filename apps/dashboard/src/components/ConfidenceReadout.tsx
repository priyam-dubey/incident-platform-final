import { EvidenceItem } from "@/lib/types";

/**
 * The signature element of the whole dashboard. A hypothesis's confidence is
 * rendered as a meter (evoking a VU meter / instrument-panel readout,
 * fitting the "flight recorder for production systems" concept), and every
 * cited evidence id becomes a small numbered tick that's a real anchor link
 * to that evidence row below (#evidence-{id}), highlighted on arrival via
 * the CSS :target pseudo-class - no client JS needed for the core
 * interaction. This is deliberately not a generic progress bar: it makes
 * the platform's actual mechanism (every claim traces to a specific,
 * clickable piece of evidence) a physical, interactive part of the UI
 * rather than a claim in a tooltip.
 */
export function ConfidenceReadout({
  confidence,
  citedEvidenceIds,
  evidence,
}: {
  confidence: number;
  citedEvidenceIds: string[];
  evidence: EvidenceItem[];
}) {
  const pct = Math.round(confidence * 100);
  const evidenceIndexById = new Map(evidence.map((e, i) => [e.id, i + 1]));

  const level = confidence >= 0.75 ? "high" : confidence >= 0.4 ? "mid" : "low";
  const barColor =
    level === "high" ? "bg-ai" : level === "mid" ? "bg-caution" : "bg-critical";

  return (
    <div className="flex items-center gap-3">
      <div className="flex h-3 w-32 items-center gap-[2px] border border-hairline bg-void p-[2px]">
        {Array.from({ length: 20 }).map((_, i) => (
          <span
            key={i}
            className={`h-full flex-1 ${i < pct / 5 ? barColor : "bg-panel-raised"}`}
            aria-hidden
          />
        ))}
      </div>
      <span className="font-mono text-xs text-primary">{pct}%</span>
      <div className="flex items-center gap-1">
        {citedEvidenceIds.map((id) => {
          const index = evidenceIndexById.get(id);
          if (!index) return null;
          return (
            <a
              key={id}
              href={`#evidence-${id}`}
              className="flex h-5 w-5 items-center justify-center border border-hairline font-mono text-[10px] text-ai transition-colors hover:border-ai hover:bg-panel-raised"
              title={`Jump to cited evidence #${index}`}
            >
              {index}
            </a>
          );
        })}
      </div>
    </div>
  );
}
