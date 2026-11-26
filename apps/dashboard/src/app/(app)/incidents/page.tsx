"use client";
import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { Incident } from "@/lib/types";
import { Async, Badge, Card, EmptyState, PageHeader, Select, SeverityBadge, Table, Td, useApi } from "@/components/ui";
import { ago } from "@/lib/format";
import { qs } from "@/lib/api";

export default function Incidents() {
  const { ws } = useAuth();
  const [status, setStatus] = useState("");
  const d = useApi<Incident[]>(`/v1/workspaces/${ws!.id}/incidents${qs({ status, limit: 100 })}`);
  return (
    <>
      <PageHeader title="Incidents" subtitle="Detected from each application's own baseline - not from fixed thresholds alone."
        actions={<Select label="Status" value={status} onChange={setStatus} options={[{ value: "", label: "All statuses" }, ...["candidate", "pending_review", "published", "resolved", "dismissed"].map((s) => ({ value: s, label: s.replace("_", " ") }))]} />} />
      <Card>
        <Async state={d}>{(list) => list.length === 0 ? <EmptyState title="No incidents">When an application's error rate or latency departs from its baseline with enough traffic, an incident is opened here with its evidence.</EmptyState> :
          <Table head={["Incident", "Application", "Severity", "Status", "Started"]}>{list.map((i) => (
            <tr key={i.id}><Td><Link href={`/incidents/${i.id}`} className="font-medium hover:text-accent">{i.title}</Link> {i.synthetic && <Badge tone="demo">DEMO</Badge>}</Td><Td>{i.application_name ?? "–"}</Td><Td><SeverityBadge severity={i.severity} /></Td><Td>{i.status.replace("_", " ")}</Td><Td>{ago(i.started_at)}</Td></tr>))}</Table>}</Async>
      </Card>
    </>
  );
}
