"use client";
import { download } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Incident, Repo } from "@/lib/types";
import { Async, Button, Card, EmptyState, PageHeader, Table, Td, useApi } from "@/components/ui";

const guard = (v: unknown) => { const s = v === null || v === undefined ? "" : String(v); return /^[=+\-@\t\r]/.test(s) ? `'${s}` : s; };
function incidentsCsv(rows: Incident[]) {
  const q = (s: string) => `"${s.replace(/"/g, '""')}"`;
  const head = ["id", "title", "application", "severity", "status", "detector", "started_at", "resolved_at", "synthetic"];
  return [head.join(","), ...rows.map((i) => [i.id, i.title, i.application_name, i.severity, i.status, i.detector, i.started_at, i.resolved_at, i.synthetic].map((v) => q(guard(v))).join(","))].join("\r\n");
}

export default function Reports() {
  const { ws } = useAuth(); const w = `/v1/workspaces/${ws!.id}`;
  const repos = useApi<Repo[]>(`${w}/repositories`); const inc = useApi<Incident[]>(`${w}/incidents?limit=200`);
  return (
    <>
      <PageHeader title="Reports" subtitle="Export real data from this workspace. Reports contain only what is stored; nothing is generated or estimated." />
      <div className="space-y-6">
        <Card title="Code findings (per repository)"><Async state={repos}>{(list) => list.filter((r) => r.connected).length === 0 ? <EmptyState title="No connected repositories" /> :
          <Table head={["Repository", "Open findings", "Export"]}>{list.filter((r) => r.connected).map((r) => (
            <tr key={r.id}><Td>{r.full_name}</Td><Td>{r.open_findings}</Td><Td><span className="flex gap-2"><Button variant="ghost" onClick={() => download(`${w}/repositories/${r.id}/report.csv`, "findings.csv")}>CSV</Button><Button variant="ghost" onClick={() => download(`${w}/repositories/${r.id}/report.pdf`, "findings.pdf")}>PDF</Button></span></Td></tr>))}</Table>}</Async></Card>
        <Card title="Incidents"><Async state={inc}>{(list) => list.length === 0 ? <EmptyState title="No incidents to export" /> : (
          <div className="flex items-center justify-between"><p className="text-sm text-muted">{list.length} incidents (most recent 200).</p>
            <Button variant="ghost" onClick={() => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([incidentsCsv(list)], { type: "text/csv" })); a.download = "incidents.csv"; a.click(); }}>Export CSV</Button></div>)}</Async></Card>
      </div>
    </>
  );
}
