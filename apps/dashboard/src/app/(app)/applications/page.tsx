"use client";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Application, Onboarding } from "@/lib/types";
import { Async, Badge, Button, Card, CopyBlock, EmptyState, Field, PageHeader, StatusDot, Table, Td, inputCls, useApi } from "@/components/ui";
import { ago } from "@/lib/format";
import { snippet } from "@/lib/snippet";

export default function Applications() {
  const { ws, can } = useAuth(); const w = `/v1/workspaces/${ws!.id}`;
  const list = useApi<Application[]>(`${w}/applications`);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", environment: "production", framework: "nodejs-express", backend_url: "" });
  const [created, setCreated] = useState<{ application: Application; ingestion_key: string; onboarding: Onboarding } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function create(e: FormEvent) {
    e.preventDefault(); setErr(null);
    try {
      const r = await api<{ application: Application; ingestion_key: string; onboarding: Onboarding }>(`${w}/applications`, { method: "POST", json: { ...f, backend_url: f.backend_url || null } });
      setCreated(r); setOpen(false); list.reload();
    } catch (x) { setErr((x as Error).message); }
  }
  return (
    <>
      <PageHeader title="Applications" subtitle="Each application gets its own ingestion key. Telemetry can only ever be written to the application its key belongs to."
        actions={can("developer") && <Button onClick={() => { setOpen(!open); setCreated(null); }}>Add application</Button>} />
      {created && (
        <Card title={`Connect ${created.application.name}`} className="mb-6">
          <p className="mb-3 text-sm text-ok">Application created. Copy the key now - it is shown once and only a hash is stored.</p>
          <CopyBlock label="Setup (Node.js / Express)" text={snippet(created.onboarding, created.ingestion_key, created.application.name, created.application.environment)} />
          <p className="mt-3 text-sm text-muted">{created.onboarding.note} The status below changes to <em>Connected</em> when the first telemetry arrives. <Link className="text-accent" href={`/applications/${created.application.id}`}>Open application</Link></p>
        </Card>)}
      {open && (
        <Card title="New application" className="mb-6">
          <form onSubmit={create} className="grid gap-4 sm:grid-cols-2">
            <Field label="Name"><input className={inputCls} required maxLength={80} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="shop-api" /></Field>
            <Field label="Environment"><select className={inputCls} value={f.environment} onChange={(e) => setF({ ...f, environment: e.target.value })}>{["production", "staging", "development"].map((x) => <option key={x}>{x}</option>)}</select></Field>
            <p className="text-sm text-muted sm:col-span-2">Runtime: Node.js / Express (other stacks can send OTLP/HTTP JSON with the same key).</p>
            <Field label="Backend URL (optional)"><input className={inputCls} type="url" value={f.backend_url} onChange={(e) => setF({ ...f, backend_url: e.target.value })} placeholder="https://api.example.com" /></Field>
            {err && <p role="alert" className="text-sm text-crit sm:col-span-2">{err}</p>}
            <div className="sm:col-span-2"><Button>Create and get key</Button></div>
          </form>
        </Card>)}
      <Card>
        <Async state={list}>{(apps) => apps.length === 0 ? <EmptyState title="No applications yet">Add an application to receive an ingestion key and setup instructions. No telemetry is shown until your own app sends it.</EmptyState> :
          <Table head={["Name", "Environment", "Status", "Last telemetry", ""]}>{apps.map((a) => (
            <tr key={a.id}><Td><Link href={`/applications/${a.id}`} className="font-medium hover:text-accent">{a.name}</Link> {a.is_synthetic && <Badge tone="demo">DEMO</Badge>}</Td><Td>{a.environment}</Td><Td><StatusDot state={a.connection_status} /></Td><Td>{ago(a.last_telemetry_at)}</Td><Td><span className="font-mono text-xs text-muted">{a.active_key_prefix ? `${a.active_key_prefix}…` : ""}</span></Td></tr>))}</Table>}</Async>
      </Card>
    </>
  );
}
