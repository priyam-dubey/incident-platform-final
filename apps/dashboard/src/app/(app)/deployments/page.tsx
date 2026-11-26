"use client";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { Deployment } from "@/lib/types";
import { Async, Card, CopyBlock, EmptyState, PageHeader, Table, Td, useApi } from "@/components/ui";
import { fmtTime, short } from "@/lib/format";

export default function Deployments() {
  const { ws } = useAuth();
  const d = useApi<Deployment[]>(`/v1/workspaces/${ws!.id}/deployments?limit=100`);
  return (
    <>
      <PageHeader title="Deployments" subtitle="Release events with commit SHAs, used to correlate incidents with what shipped. Correlation is a lead, not proof." />
      <Card className="mb-6">
        <Async state={d}>{(list) => list.length === 0 ? <EmptyState title="No deployments registered">Set <code>INCIDENT_PLATFORM_COMMIT</code> in your app, or register releases from CI with the API call below.</EmptyState> :
          <Table head={["When", "Application", "Version", "Commit", "Branch", "Source"]}>{list.map((x) => (
            <tr key={x.id}><Td>{fmtTime(x.deployed_at)}</Td><Td><Link className="text-accent" href={`/applications/${x.application_id}`}>{x.application_name}</Link></Td><Td>{x.version ?? "–"}</Td><Td><code>{short(x.commit_sha)}</code></Td><Td>{x.branch ?? "–"}</Td><Td>{x.source}</Td></tr>))}</Table>}</Async>
      </Card>
      <Card title="Register a deployment from CI"><CopyBlock text={`curl -X POST "$INCIDENT_PLATFORM_API/v1/deployments" \\
  -H "X-Ingestion-Key: $INCIDENT_PLATFORM_KEY" -H "Content-Type: application/json" \\
  -d '{"version":"1.4.2","commit_sha":"'$GIT_SHA'","branch":"main","repository":"acme/shop"}'`} />
        <p className="mt-2 text-xs text-muted">The workspace and application come from the key. The Node SDK can do this for you with <code>incident.registerDeployment()</code>.</p></Card>
    </>
  );
}
