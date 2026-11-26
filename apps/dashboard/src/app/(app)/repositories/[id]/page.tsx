"use client";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, download } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Repo, Scan } from "@/lib/types";
import { Async, Badge, Button, Card, EmptyState, ErrorState, PageHeader, Stat, Table, Tabs, Td, useApi } from "@/components/ui";
import { BarList, LineChart } from "@/components/Chart";
import { ago, short } from "@/lib/format";
import { FindingsExplorer } from "@/components/FindingsExplorer";

interface Detail extends Repo { summary: { by_severity: Record<string, number>; by_tool: Record<string, number>; by_status: Record<string, number>; history: { at: string; commit: string; counts: Record<string, number> }[] }; scans: Scan[] }

export default function RepositoryPage() {
  const { id } = useParams<{ id: string }>(); const { ws, can } = useAuth(); const base = `/v1/workspaces/${ws!.id}/repositories/${id}`;
  const d = useApi<Detail>(base); const [tab, setTab] = useState("overview"); const [err, setErr] = useState<unknown>(null); const [busy, setBusy] = useState(false);
  const scans = useApi<Scan[]>(tab === "scans" ? `${base}/scans` : null);
  const scan = async () => { setBusy(true); setErr(null); try { await api(`${base}/scans`, { method: "POST" }); d.reload(); scans.reload(); } catch (e) { setErr(e); } finally { setBusy(false); } };
  return (
    <Async state={d} rows={5}>{(r) => (
      <>
        <PageHeader title={r.full_name} subtitle={<>default branch {r.default_branch} · last scan {ago(r.last_scan_at)}</>}
          actions={<><Button variant="ghost" onClick={() => download(`${base}/report.csv`, "findings.csv")}>Export CSV</Button><Button variant="ghost" onClick={() => download(`${base}/report.pdf`, "findings.pdf")}>Export PDF</Button>{can("developer") && <Button disabled={busy} onClick={scan}>Scan now</Button>}</>} />
        {!!err && <div className="mb-4"><ErrorState error={err} /></div>}
        <Tabs value={tab} onChange={setTab} tabs={[{ id: "overview", label: "Overview" }, { id: "findings", label: "Findings" }, { id: "scans", label: "Scans" }]} />
        {tab === "overview" && (
          <div className="space-y-6">
            {r.scans.length === 0 && <EmptyState title="No scans yet">Press “Scan now”, or push a commit - pushes to {r.default_branch} and pull requests are scanned automatically.</EmptyState>}
            <div className="grid gap-3 sm:grid-cols-5">{["critical", "high", "medium", "low", "info"].map((s) => <Stat key={s} label={s} value={r.summary.by_severity[s] ?? 0} />)}</div>
            <div className="grid gap-6 lg:grid-cols-2">
              <Card title="Open findings by tool">{Object.keys(r.summary.by_tool).length === 0 ? <p className="text-sm text-muted">No open findings.</p> : <BarList items={Object.entries(r.summary.by_tool).map(([k, v]) => ({ label: k, value: v }))} />}</Card>
              <Card title="New vs fixed per scan">{r.summary.history.length < 2 ? <p className="text-sm text-muted">Needs at least two completed scans.</p> :
                <LineChart times={r.summary.history.map((h) => h.at)} series={[{ name: "new", color: "rgb(var(--s2))", values: r.summary.history.map((h) => h.counts.new ?? 0) }, { name: "fixed", color: "rgb(var(--s3))", values: r.summary.history.map((h) => h.counts.fixed ?? 0) }]} />}</Card>
            </div>
            <Card title="Languages">{Object.keys(r.languages).length === 0 ? <p className="text-sm text-muted">Detected after the first scan.</p> : <p className="text-sm">{Object.entries(r.languages).map(([k, v]) => <Badge key={k}>{k} · {v} files</Badge>)}</p>}</Card>
          </div>)}
        {tab === "findings" && <FindingsExplorer repositoryId={id} />}
        {tab === "scans" && <Card><Async state={scans}>{(list) => list.length === 0 ? <EmptyState title="No scans" /> :
          <Table head={["Commit", "Trigger", "Status", "Results", "Tools", "Queued"]}>{list.map((s) => (
            <tr key={s.id}><Td><code>{short(s.commit_sha)}</code>{s.pr_number && ` PR #${s.pr_number}`}</Td><Td>{s.trigger}</Td><Td><Badge tone={s.status === "completed" ? "ok" : s.status === "failed" ? "crit" : "warn"}>{s.status}</Badge>{s.error && <p className="text-xs text-crit">{s.error}</p>}</Td>
              <Td className="text-xs">{s.status === "completed" ? `new ${s.counts.new ?? 0} · fixed ${s.counts.fixed ?? 0} · unchanged ${s.counts.unchanged ?? 0}${s.counts.reintroduced ? ` · reintroduced ${s.counts.reintroduced}` : ""}` : "–"}</Td>
              <Td><div className="flex flex-wrap gap-1">{Object.entries(s.tools).map(([t, v]) => <span key={t} title={v.detail ?? ""}><Badge tone={v.status === "ok" ? "ok" : v.status === "failed" ? "crit" : "neutral"}>{t}: {v.status}</Badge></span>)}</div></Td><Td>{ago(s.queued_at)}</Td></tr>))}</Table>}</Async></Card>}
      </>)}</Async>
  );
}
