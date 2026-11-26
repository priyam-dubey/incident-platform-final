"use client";
import Link from "next/link";
import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";

export function cx(...a: (string | false | null | undefined)[]) { return a.filter(Boolean).join(" "); }

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("min-w-0 rounded-lg border border-line bg-panel", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">{title}</h2><div className="flex items-center gap-2">{actions}</div>
        </header>)}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Button({ variant = "primary", className, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  const v = { primary: "bg-accent text-white hover:opacity-90", ghost: "border border-line bg-panel text-ink hover:bg-raised", danger: "bg-crit text-white hover:opacity-90" }[variant];
  return <button {...p} className={cx("inline-flex items-center justify-center gap-2 rounded px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50", v, className)} />;
}

const SEV: Record<string, string> = { critical: "bg-crit/15 text-crit", high: "bg-high/15 text-high", medium: "bg-warn/15 text-warn", low: "bg-accent/15 text-accent", info: "bg-raised text-muted" };
export function SeverityBadge({ severity }: { severity: string }) {
  return <span className={cx("inline-block rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide", SEV[severity] ?? SEV.info)}>{severity}</span>;
}
export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "warn" | "crit" | "ai" | "demo" }) {
  const t = { neutral: "bg-raised text-soft", ok: "bg-ok/15 text-ok", warn: "bg-warn/15 text-warn", crit: "bg-crit/15 text-crit", ai: "bg-ai/15 text-ai", demo: "bg-warn/20 text-warn border border-warn/40" }[tone];
  return <span className={cx("inline-flex items-center rounded px-2 py-0.5 text-xs font-medium", t)}>{children}</span>;
}
export const DemoBadge = () => <Badge tone="demo">DEMO · synthetic data</Badge>;
export const AiBadge = ({ children = "AI-generated" }: { children?: ReactNode }) => <Badge tone="ai">✦ {children}</Badge>;

export function StatusDot({ state }: { state: string }) {
  const map: Record<string, [string, string]> = {
    connected: ["bg-ok", "Connected"], configured: ["bg-ok", "Configured"], waiting_for_telemetry: ["bg-warn", "Waiting for telemetry"],
    stale: ["bg-high", "Stale"], not_configured: ["bg-muted", "Not configured"], invalid_config: ["bg-crit", "Invalid configuration"],
  };
  const [c, label] = map[state] ?? ["bg-muted", state];
  return <span className="inline-flex items-center gap-2 text-sm text-soft"><span className={cx("h-2 w-2 rounded-full", c)} aria-hidden />{label}</span>;
}

export function Skeleton({ h = 16, w = "100%" }: { h?: number; w?: number | string }) { return <div className="skeleton" style={{ height: h, width: w }} aria-hidden />; }
export function LoadingBlock({ rows = 3 }: { rows?: number }) {
  return <div className="space-y-3" role="status" aria-label="Loading">{Array.from({ length: rows }).map((_, i) => <Skeleton key={i} h={18} w={`${90 - i * 12}%`} />)}</div>;
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-line px-6 py-10 text-center">
      <p className="font-medium text-ink">{title}</p>{children && <div className="max-w-md text-sm text-muted">{children}</div>}{action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const e = error as ApiError;
  const notConfigured = e?.code?.endsWith("not_configured");
  return (
    <div role="alert" className={cx("rounded-lg border px-4 py-3 text-sm", notConfigured ? "border-warn/40 bg-warn/10 text-warn" : "border-crit/40 bg-crit/10 text-crit")}>
      <p className="font-medium">{notConfigured ? "Not configured" : "Something went wrong"}</p>
      <p className="mt-1 text-soft">{e?.message ?? "Unexpected error"}</p>
      {retry && !notConfigured && <Button variant="ghost" className="mt-2" onClick={retry}>Retry</Button>}
    </div>
  );
}

/** Fetch hook with loading / error / reload. Pass null to skip. */
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(path !== null);
  const seq = useRef(0);
  const load = useCallback(async () => {
    if (path === null) return;
    const my = ++seq.current;
    setLoading(true); setError(null);
    try { const d = await api<T>(path); if (my === seq.current) setData(d); }
    catch (e) { if (my === seq.current) { setError(e); setData(null); } }
    finally { if (my === seq.current) setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => { void load(); }, [load]);
  return { data, error, loading, reload: load, setData };
}

export function Async<T>({ state, children, rows }: { state: ReturnType<typeof useApi<T>>; children: (d: T) => ReactNode; rows?: number }) {
  if (state.loading && !state.data) return <LoadingBlock rows={rows} />;
  if (state.error) return <ErrorState error={state.error} retry={state.reload} />;
  if (!state.data) return null;
  return <>{children(state.data)}</>;
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>{subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}</div>
      <div className="flex items-center gap-2">{actions}</div>
    </div>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: { id: string; label: string }[]; value: string; onChange: (id: string) => void }) {
  return (
    <div role="tablist" className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cx("whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition", value === t.id ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink")}>{t.label}</button>
      ))}
    </div>
  );
}

export function Select({ value, onChange, options, label }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; label: string }) {
  return (
    <label className="inline-flex items-center gap-2 text-sm text-muted">
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label} className="rounded border border-line bg-panel px-2 py-1.5 text-sm text-ink">
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

export const inputCls = "w-full rounded border border-line bg-panel px-3 py-2 text-sm text-ink placeholder:text-muted";
export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <label className="block text-sm"><span className="mb-1 block font-medium text-soft">{label}</span>{children}{hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}</label>;
}

export function CopyBlock({ text, label }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="relative">
      {label && <p className="mb-1 text-xs font-medium text-muted">{label}</p>}
      <pre className="overflow-x-auto rounded border border-line bg-raised p-3 pr-16 font-mono text-xs text-soft">{text}</pre>
      <button type="button" onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard unavailable */ } }}
        className="absolute right-2 top-2 rounded border border-line bg-panel px-2 py-1 text-xs text-soft hover:bg-raised" style={label ? { top: 26 } : undefined}>{done ? "Copied" : "Copy"}</button>
    </div>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "crit" | "ok" }) {
  return (
    <div className="rounded-lg border border-line bg-panel p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className={cx("mt-1 text-2xl font-semibold tabular-nums", tone === "crit" ? "text-crit" : "text-ink")}>{value}</p>
      {sub && <p className="mt-1 text-xs text-muted">{sub}</p>}
    </div>
  );
}

export function Table({ head, children, empty }: { head: string[]; children: ReactNode; empty?: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead><tr className="border-b border-line text-xs uppercase tracking-wide text-muted">{head.map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
      {empty}
    </div>
  );
}
export const Td = ({ children, className }: { children: ReactNode; className?: string }) => <td className={cx("px-3 py-2 align-top", className)}>{children}</td>;
export const NavLink = ({ href, children }: { href: string; children: ReactNode }) => <Link href={href} className="text-accent hover:underline">{children}</Link>;
