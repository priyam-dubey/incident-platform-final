"use client";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { Application, Incident, Integrations, Repo } from "@/lib/types";
import { Async, Badge, Card, EmptyState, PageHeader, SeverityBadge, Stat, StatusDot, useApi } from "@/components/ui";
import { ago } from "@/lib/format";

export default function Overview() {
  const { ws } = useAuth(); const w = `/v1/workspaces/${ws!.id}`;
  const apps = useApi<{ items?: Application[] } | Application[]>(`${w}/applications`);
  const incidents = useApi<Incident[]>(`${w}/incidents?limit=100`);
  const repos = useApi<Repo[]>(`${w}/repositories`);
  const integ = useApi<Integrations>(`${w}/integrations/status`);
  const appList = (Array.isArray(apps.data) ? apps.data : apps.data?.items) ?? [];
  const open = (incidents.data ?? []).filter((i) => !["resolved", "dismissed"].includes(i.status));
  const findings = (repos.data ?? []).reduce((n, r) => n + r.open_findings, 0);
  const setup = [
    { done: appList.length > 0, label: "Add an application and install the SDK", href: "/applications" },
    { done: (repos.data ?? []).some((r) => r.connected), label: "Connect a GitHub repository", href: "/repositories" },
    { done: integ.data?.llm.state === "configured", label: "Configure the AI provider (optional)", href: "/integrations" },
  ];
  return (
    <>
      <PageHeader title="Overview" subtitle="What is happening across your code and your running applications." />
      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Applications" value={appList.length} sub={`${appList.filter((a) => a.connection_status === "connected").length} sending telemetry`} />
        <Stat label="Open incidents" value={open.length} tone={open.length ? "crit" : "ok"} sub={open.length ? `${open.filter((i) => ["critical", "high"].includes(i.severity)).length} high or critical` : "None right now"} />
        <Stat label="Repositories" value={(repos.data ?? []).filter((r) => r.connected).length} sub={`${(repos.data ?? []).length} visible`} />
        <Stat label="Open code findings" value={findings} />
      </div>
      {setup.some((s) => !s.done) && (
        <Card title="Get set up" className="mb-6"><ul className="space-y-2 text-sm">{setup.map((s) => (
          <li key={s.label} className="flex items-center gap-2"><span aria-hidden>{s.done ? "✓" : "○"}</span>{s.done ? <span className="text-muted line-through">{s.label}</span> : <Link className="text-accent hover:underline" href={s.href}>{s.label}</Link>}</li>))}</ul></Card>)}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="Recent incidents" actions={<Link href="/incidents" className="text-xs text-accent">View all</Link>}>
          <Async state={incidents}>{(list) => list.length === 0 ? <EmptyState title="No incidents">Incidents appear when an application's error rate or latency departs from its own baseline.</EmptyState> :
            <ul className="divide-y divide-line">{list.slice(0, 6).map((i) => <li key={i.id} className="flex items-center justify-between gap-3 py-2"><div className="min-w-0"><Link href={`/incidents/${i.id}`} className="block truncate text-sm font-medium hover:text-accent">{i.title}</Link><p className="text-xs text-muted">{i.application_name} · {ago(i.started_at)}</p></div><div className="flex items-center gap-2">{i.synthetic && <Badge tone="demo">DEMO</Badge>}<SeverityBadge severity={i.severity} /></div></li>)}</ul>}</Async>
        </Card>
        <Card title="Applications" actions={<Link href="/applications" className="text-xs text-accent">Manage</Link>}>
          <Async state={apps}>{() => appList.length === 0 ? <EmptyState title="No applications yet" action={<Link className="text-accent" href="/applications">Add your first application</Link>}>Register an app to get an ingestion key and a copy-paste setup snippet.</EmptyState> :
            <ul className="divide-y divide-line">{appList.map((a) => <li key={a.id} className="flex items-center justify-between py-2"><Link href={`/applications/${a.id}`} className="text-sm font-medium hover:text-accent">{a.name} <span className="text-muted">· {a.environment}</span></Link><StatusDot state={a.connection_status} /></li>)}</ul>}</Async>
        </Card>
      </div>
    </>
  );
}
