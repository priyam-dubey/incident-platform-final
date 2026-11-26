"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Application, Deployment, Endpoint, LogRow, Onboarding, Point, Summary, TraceRow } from "@/lib/types";
import { Async, Badge, Button, Card, CopyBlock, DemoBadge, EmptyState, ErrorState, Field, PageHeader, Select, Stat, StatusDot, Table, Tabs, Td, inputCls, useApi } from "@/components/ui";
import { BarList, LineChart } from "@/components/Chart";
import { ago, fmtMs, fmtNum, fmtPct, fmtTime, short } from "@/lib/format";
import { snippet } from "@/lib/snippet";

const RANGES = [{ value: "15m", label: "Last 15 min" }, { value: "1h", label: "Last hour" }, { value: "6h", label: "Last 6 hours" }, { value: "24h", label: "Last 24 hours" }, { value: "7d", label: "Last 7 days" }];
type Meta = { synthetic: boolean };

export default function ApplicationPage() {
  const { id } = useParams<{ id: string }>();
  const { ws, can } = useAuth();
  const base = `/v1/workspaces/${ws!.id}/applications/${id}`;
  const app = useApi<{ application: Application; onboarding: Onboarding }>(base);
  const [tab, setTab] = useState("overview");
  const [range, setRange] = useState("1h");
  const [live, setLive] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => { if (!live) return; const t = setInterval(() => setTick((n) => n + 1), 30000); return () => clearInterval(t); }, [live]);
  const a = app.data?.application;
  return (
    <>
      <PageHeader title={<>{a?.name ?? "Application"} {a?.is_synthetic && <DemoBadge />}</>} subtitle={a && <span className="flex items-center gap-3">{a.environment} · <StatusDot state={a.connection_status} /> · last telemetry {ago(a.last_telemetry_at)}</span>}
        actions={<>
          <Select label="Time range" value={range} onChange={setRange} options={RANGES} />
          <label className="flex items-center gap-1 text-sm text-muted"><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Auto-refresh</label>
        </>} />
      {app.error ? <ErrorState error={app.error} retry={app.reload} /> : (
        <>
          <Tabs value={tab} onChange={setTab} tabs={[{ id: "overview", label: "Overview" }, { id: "endpoints", label: "Endpoints" }, { id: "runtime", label: "Runtime" }, { id: "logs", label: "Logs" }, { id: "traces", label: "Traces" }, { id: "setup", label: "Setup & keys" }]} />
          {a?.connection_status === "waiting_for_telemetry" && tab !== "setup" && (
            <EmptyState title="Waiting for the first telemetry" action={<Button variant="ghost" onClick={() => setTab("setup")}>Show setup instructions</Button>}>No data has arrived from this application yet, so nothing is shown. Nothing here is simulated.</EmptyState>)}
          {a && a.connection_status !== "waiting_for_telemetry" && (
            <>
              {tab === "overview" && <Overview base={base} range={range} tick={tick} />}
              {tab === "endpoints" && <Endpoints base={base} range={range} tick={tick} />}
              {tab === "runtime" && <Runtime base={base} range={range} tick={tick} />}
              {tab === "logs" && <Logs base={base} range={range} tick={tick} />}
              {tab === "traces" && <Traces base={base} range={range} tick={tick} />}
            </>)}
          {tab === "setup" && app.data && <Setup app={app.data.application} onboarding={app.data.onboarding} base={base} canAdmin={can("admin")} />}
        </>)}
    </>
  );
}

function Overview({ base, range, tick }: { base: string; range: string; tick: number }) {
  const sum = useApi<Meta & { summary: Summary; status_distribution: Record<string, number> }>(`${base}/telemetry/summary${qs({ range })}`, [tick]);
  const ts = useApi<{ points: Point[] }>(`${base}/telemetry/timeseries${qs({ range })}`, [tick]);
  const dep = useApi<Deployment[]>(`${base.split("/applications/")[0]}/deployments${qs({ application_id: base.split("/").pop(), limit: 5 })}`);
  return (
    <div className="space-y-6">
      <Async state={sum}>{(d) => (
        <>
          {d.synthetic && <DemoBadge />}
          {d.summary.requests === 0 && <EmptyState title="No requests in this range">Try a longer range, or generate traffic against your app.</EmptyState>}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Stat label="Requests" value={fmtNum(d.summary.requests)} sub={`${fmtNum(d.summary.requests_per_minute)} / min`} />
            <Stat label="Error rate (5xx)" value={fmtPct(d.summary.error_rate)} tone={(d.summary.error_rate ?? 0) > 0.05 ? "crit" : undefined} sub={`${d.summary.errors_5xx} server errors`} />
            <Stat label="p50 latency" value={fmtMs(d.summary.p50_ms)} />
            <Stat label="p95 latency" value={fmtMs(d.summary.p95_ms)} />
            <Stat label="p99 latency" value={fmtMs(d.summary.p99_ms)} />
          </div>
          <Card title="Status codes"><BarList items={Object.entries(d.status_distribution).map(([k, v]) => ({ label: k, value: v }))} /></Card>
        </>)}</Async>
      <Async state={ts}>{(d) => (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="Requests per minute"><LineChart area times={d.points.map((p) => p.t)} series={[{ name: "req/min", color: "rgb(var(--s1))", values: d.points.map((p) => p.requests_per_minute) }]} /></Card>
          <Card title="Error rate (5xx)"><LineChart yFmt={(v) => fmtPct(v)} times={d.points.map((p) => p.t)} series={[{ name: "error rate", color: "rgb(var(--crit))", values: d.points.map((p) => p.error_rate), fmt: fmtPct }]} /></Card>
          <Card title="Latency" className="lg:col-span-2"><LineChart yFmt={(v) => fmtMs(v)} times={d.points.map((p) => p.t)} series={[
            { name: "avg", color: "rgb(var(--s3))", values: d.points.map((p) => p.avg_ms), fmt: fmtMs }, { name: "p95", color: "rgb(var(--s1))", values: d.points.map((p) => p.p95_ms), fmt: fmtMs }, { name: "p99", color: "rgb(var(--s2))", values: d.points.map((p) => p.p99_ms), fmt: fmtMs }]} /></Card>
        </div>)}</Async>
      <Card title="Recent deployments"><Async state={dep}>{(list) => list.length === 0 ? <p className="text-sm text-muted">No deployments registered. Set <code>INCIDENT_PLATFORM_COMMIT</code> or call the deployments API to correlate releases with incidents.</p> :
        <ul className="space-y-1 text-sm">{list.map((x) => <li key={x.id}>{fmtTime(x.deployed_at)} · version {x.version ?? "–"} · commit <code>{short(x.commit_sha)}</code> {x.branch && `(${x.branch})`}</li>)}</ul>}</Async></Card>
    </div>
  );
}

function Endpoints({ base, range, tick }: { base: string; range: string; tick: number }) {
  const [sort, setSort] = useState("requests");
  const d = useApi<{ endpoints: Endpoint[] }>(`${base}/telemetry/endpoints${qs({ range, sort })}`, [tick]);
  return (
    <Card title="Endpoints" actions={<Select label="Sort by" value={sort} onChange={setSort} options={[{ value: "requests", label: "Requests" }, { value: "errors", label: "Errors" }, { value: "p95", label: "p95 latency" }, { value: "avg", label: "Avg latency" }]} />}>
      <Async state={d}>{(r) => r.endpoints.length === 0 ? <EmptyState title="No requests in this range" /> :
        <Table head={["Route", "Requests", "5xx", "Error rate", "Avg", "p95", "p99"]}>{r.endpoints.map((e) => (
          <tr key={e.method + e.route}><Td><span className="font-mono text-xs"><span className="text-muted">{e.method}</span> {e.route}</span></Td><Td className="tabular-nums">{fmtNum(e.requests)}</Td><Td className="tabular-nums">{e.errors_5xx}</Td>
            <Td className={`tabular-nums ${(e.error_rate ?? 0) > 0.05 ? "text-crit" : ""}`}>{fmtPct(e.error_rate)}</Td><Td className="tabular-nums">{fmtMs(e.avg_ms)}</Td><Td className="tabular-nums">{fmtMs(e.p95_ms)}</Td><Td className="tabular-nums">{fmtMs(e.p99_ms)}</Td></tr>))}</Table>}</Async>
    </Card>
  );
}

const RUNTIME_LABEL: Record<string, [string, (v: number) => string]> = {
  "process.memory.usage": ["Process memory (RSS)", (v) => `${(v / 1048576).toFixed(0)} MB`],
  "nodejs.heap.used": ["Heap used", (v) => `${(v / 1048576).toFixed(0)} MB`],
  "nodejs.eventloop.lag.p99": ["Event-loop lag p99", (v) => `${v.toFixed(1)} ms`],
  "process.cpu.utilization": ["Process CPU", (v) => `${(v * 100).toFixed(0)}%`],
};
function Runtime({ base, range, tick }: { base: string; range: string; tick: number }) {
  const d = useApi<{ series: Record<string, { bucket: string; avg: number | null }[]>; note: string }>(`${base}/telemetry/runtime${qs({ range })}`, [tick]);
  return (
    <Async state={d}>{(r) => (
      <div className="space-y-4">
        <p className="rounded border border-line bg-panel px-3 py-2 text-sm text-muted"><Badge>process scope</Badge> {r.note}</p>
        <div className="grid gap-6 lg:grid-cols-2">{Object.entries(RUNTIME_LABEL).map(([k, [label, fmt]]) => (
          <Card key={k} title={label}>{(r.series[k] ?? []).length === 0 ? <p className="text-sm text-muted">No samples for this metric in this range.</p> :
            <LineChart yFmt={fmt} times={r.series[k].map((p) => p.bucket)} series={[{ name: label, color: "rgb(var(--s1))", values: r.series[k].map((p) => p.avg), fmt }]} />}</Card>))}</div>
      </div>)}</Async>
  );
}

function Logs({ base, range, tick }: { base: string; range: string; tick: number }) {
  const [severity, setSeverity] = useState(""); const [search, setSearch] = useState(""); const [applied, setApplied] = useState(""); const [offset, setOffset] = useState(0);
  const d = useApi<{ logs: LogRow[]; limit: number }>(`${base}/telemetry/logs${qs({ range, severity, search: applied, limit: 50, offset })}`, [tick]);
  const tone = (s: string) => (["error", "fatal"].includes(s) ? "crit" : s === "warn" ? "warn" : "neutral") as "crit" | "warn" | "neutral";
  return (
    <Card title="Logs" actions={<>
      <Select label="Severity" value={severity} onChange={(v) => { setSeverity(v); setOffset(0); }} options={[{ value: "", label: "All severities" }, ...["debug", "info", "warn", "error", "fatal"].map((s) => ({ value: s, label: s }))]} />
      <form onSubmit={(e) => { e.preventDefault(); setApplied(search); setOffset(0); }}><input aria-label="Search logs" className={inputCls + " w-44"} placeholder="Search message…" value={search} onChange={(e) => setSearch(e.target.value)} /></form></>}>
      <Async state={d}>{(r) => r.logs.length === 0 ? <EmptyState title="No logs match">Adjust the filters or time range.</EmptyState> : (
        <>
          <ul className="divide-y divide-line font-mono text-xs">{r.logs.map((l, i) => (
            <li key={i} className="flex gap-3 py-2"><span className="w-36 shrink-0 text-muted">{new Date(l.timestamp).toLocaleTimeString()}</span><span className="w-14 shrink-0"><Badge tone={tone(l.severity)}>{l.severity}</Badge></span>
              <span className="min-w-0 break-words text-ink">{l.message}{l.trace_id && <span className="ml-2 text-muted">trace {l.trace_id.slice(0, 8)}</span>}</span></li>))}</ul>
          <div className="mt-3 flex justify-between"><Button variant="ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Newer</Button><Button variant="ghost" disabled={r.logs.length < 50} onClick={() => setOffset(offset + 50)}>Older</Button></div>
        </>)}</Async>
    </Card>
  );
}

function Traces({ base, range, tick }: { base: string; range: string; tick: number }) {
  const [errorsOnly, setErrorsOnly] = useState(false); const [open, setOpen] = useState<string | null>(null);
  const d = useApi<{ traces: TraceRow[] }>(`${base}/telemetry/traces${qs({ range, only_errors: errorsOnly || undefined, limit: 50 })}`, [tick]);
  return (
    <div className="space-y-4">
      <Card title="Traces" actions={<label className="flex items-center gap-1 text-sm text-muted"><input type="checkbox" checked={errorsOnly} onChange={(e) => setErrorsOnly(e.target.checked)} /> Only traces with failures</label>}>
        <Async state={d}>{(r) => r.traces.length === 0 ? <EmptyState title="No traces in this range" /> :
          <Table head={["Trace", "Root operation", "Duration", "Spans", "Started"]}>{r.traces.map((t) => (
            <tr key={t.trace_id} className="cursor-pointer hover:bg-raised" onClick={() => setOpen(t.trace_id)}><Td><button className="font-mono text-xs text-accent" onClick={() => setOpen(t.trace_id)}>{t.trace_id.slice(0, 12)}…</button></Td><Td>{t.root_operation ?? "–"}</Td><Td>{fmtMs(t.duration_ms)}</Td>
              <Td>{t.spans} {t.failed_spans > 0 && <Badge tone="crit">{t.failed_spans} failed</Badge>}</Td><Td>{ago(t.start)}</Td></tr>))}</Table>}</Async>
      </Card>
      {open && <TraceDetail base={base} id={open} range={range} onClose={() => setOpen(null)} />}
    </div>
  );
}

function TraceDetail({ base, id, range, onClose }: { base: string; id: string; range: string; onClose: () => void }) {
  const d = useApi<{ spans: { span_id: string; parent_span_id: string | null; operation: string; start: string; duration_ms: number | null; status: string }[]; logs: LogRow[] }>(`${base}/telemetry/traces/${id}${qs({ range })}`);
  return (
    <Card title={`Trace ${id.slice(0, 12)}…`} actions={<Button variant="ghost" onClick={onClose}>Close</Button>}>
      <Async state={d}>{(r) => {
        const t0 = Math.min(...r.spans.map((s) => +new Date(s.start))); const end = Math.max(...r.spans.map((s) => +new Date(s.start) + (s.duration_ms ?? 0))); const total = Math.max(end - t0, 1);
        const depth = (s: (typeof r.spans)[number]): number => { let n = 0, p = s.parent_span_id; while (p && n < 20) { const par = r.spans.find((x) => x.span_id === p); if (!par) break; n++; p = par.parent_span_id; } return n; };
        return (<>
          <ul className="space-y-1">{r.spans.map((s) => (
            <li key={s.span_id} className="grid grid-cols-[minmax(0,14rem)_1fr_4.5rem] items-center gap-2 text-xs"><span className="truncate" style={{ paddingLeft: depth(s) * 12 }} title={s.operation}>{s.operation}</span>
              <div className="relative h-3 rounded bg-raised"><div className="absolute h-3 rounded" style={{ left: `${((+new Date(s.start) - t0) / total) * 100}%`, width: `${Math.max(((s.duration_ms ?? 0) / total) * 100, 0.6)}%`, background: s.status === "error" ? "rgb(var(--crit))" : "rgb(var(--s1))" }} /></div>
              <span className="text-right tabular-nums text-muted">{fmtMs(s.duration_ms)}</span></li>))}</ul>
          {r.logs.length > 0 && <div className="mt-4"><h3 className="mb-1 text-xs font-semibold uppercase text-muted">Correlated logs</h3><ul className="font-mono text-xs">{r.logs.map((l, i) => <li key={i} className="py-0.5"><Badge tone={["error", "fatal"].includes(l.severity) ? "crit" : "neutral"}>{l.severity}</Badge> {l.message}</li>)}</ul></div>}
        </>);
      }}</Async>
    </Card>
  );
}

function Setup({ app, onboarding, base, canAdmin }: { app: Application; onboarding: Onboarding; base: string; canAdmin: boolean }) {
  const router = useRouter();
  const [newKey, setNewKey] = useState<string | null>(null); const [err, setErr] = useState<string | null>(null);
  return (
    <div className="space-y-6">
      <Card title="Connect this application"><CopyBlock text={snippet(onboarding, newKey ?? "<your ingestion key>", app.name, app.environment)} />
        <p className="mt-3 text-sm text-muted">The key identifies this application. Only its hash is stored, so it cannot be shown again - rotate it if lost.</p></Card>
      {canAdmin && (
        <Card title="Key management">
          {newKey && <div className="mb-3"><p className="mb-1 text-sm text-ok">New key (shown once; the old key no longer works):</p><CopyBlock text={newKey} /></div>}
          {err && <p role="alert" className="mb-2 text-sm text-crit">{err}</p>}
          <div className="flex gap-2">
            <Button variant="ghost" onClick={async () => { if (!confirm("Rotate the key? The current key stops working immediately.")) return; try { setNewKey((await api<{ ingestion_key: string }>(`${base}/rotate-key`, { method: "POST" })).ingestion_key); } catch (e) { setErr((e as Error).message); } }}>Rotate key</Button>
            <Button variant="danger" onClick={async () => { if (!confirm(`Revoke ${app.name}? Its key stops working and telemetry is rejected.`)) return; try { await api(base, { method: "DELETE" }); router.replace("/applications"); } catch (e) { setErr((e as Error).message); } }}>Revoke application</Button>
          </div>
        </Card>)}
    </div>
  );
}
