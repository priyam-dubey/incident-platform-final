import { Severity } from "@/lib/types";

const SEVERITY_STYLES: Record<Severity, { label: string; color: string; dot: string }> = {
  critical: { label: "CRITICAL", color: "text-critical", dot: "bg-critical" },
  high: { label: "HIGH", color: "text-caution", dot: "bg-caution" },
  medium: { label: "MEDIUM", color: "text-muted", dot: "bg-muted" },
  low: { label: "LOW", color: "text-muted", dot: "bg-muted" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const style = SEVERITY_STYLES[severity];
  return (
    <span className={`inline-flex items-center gap-1.5 font-mono text-xs tracking-wider ${style.color}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} aria-hidden />
      {style.label}
    </span>
  );
}
