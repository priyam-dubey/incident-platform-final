import { EvidenceItem } from "@/lib/types";

const SOURCE_TYPE_LABEL: Record<string, string> = {
  log: "LOG",
  metric: "METRIC",
  trace: "TRACE",
  deploy: "DEPLOY",
};

export function EvidenceRow({ item, index }: { item: EvidenceItem; index: number }) {
  return (
    <div
      id={`evidence-${item.id}`}
      className="signal-row grid grid-cols-[2.5rem_5rem_1fr_auto] items-baseline gap-4 py-3 target:bg-panel-raised"
    >
      <span className="font-mono text-xs text-muted">#{index}</span>
      <span className="font-mono text-[11px] tracking-wider text-ai">
        {SOURCE_TYPE_LABEL[item.source_type] ?? item.source_type.toUpperCase()}
      </span>
      <span className="font-mono text-sm text-primary">{item.snippet}</span>
      <span className="font-mono text-xs text-muted">
        {new Date(item.occurred_at).toISOString().split("T")[1]?.replace("Z", "")}
      </span>
    </div>
  );
}
