"use client";
import { useAuth } from "@/lib/auth";
import { Integrations } from "@/lib/types";
import { Async, Badge, Card, PageHeader, StatusDot, useApi } from "@/components/ui";

function Row({ name, state, children }: { name: string; state: string; children: React.ReactNode }) {
  return (
    <Card><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">{name}</h2><StatusDot state={state} /></div><div className="mt-3 text-sm text-muted">{children}</div></Card>
  );
}

export default function IntegrationsPage() {
  const { ws } = useAuth();
  const d = useApi<Integrations>(`/v1/workspaces/${ws!.id}/integrations/status`);
  return (
    <>
      <PageHeader title="Integrations" subtitle="Live configuration status. Secrets are set as environment variables on the server and are never shown here." />
      <Async state={d}>{(i) => (
        <div className="grid gap-4 md:grid-cols-2">
          <Row name="AI provider" state={i.llm.state}>
            <p>Provider <code>{i.llm.provider}</code>, model <code>{i.llm.model}</code>. Configured only through <code>LLM_MODEL</code> and <code>LLM_API_KEY</code>.</p>
            {i.llm.state !== "configured" && <p className="mt-2 text-warn">{i.llm.detail ?? "Not configured."} Scanning, monitoring and incident detection work without it; only AI explanations and hypotheses are unavailable.</p>}
          </Row>
          <Row name="GitHub App" state={i.github_app.state}>
            {i.github_app.state === "configured" ? <p>Install and connect repositories under <a className="text-accent" href="/repositories">Repositories</a>.</p> :
              <p>Missing server settings: {i.github_app.missing.map((m) => <code key={m} className="mr-1">{m}</code>)}. See <code>docs/guides/github-app-setup.md</code>.</p>}
          </Row>
          <Row name="Telemetry store (ClickHouse)" state={i.telemetry_store}>{i.telemetry_store === "configured" ? "Monitoring queries are available." : <>Set <code>CLICKHOUSE_URL</code> so the gateway can read telemetry. Until then monitoring pages report “not configured”.</>}</Row>
          <Row name="Slack" state={i.notifications.slack}>{i.notifications.slack === "configured" ? "High and critical incidents are posted to Slack." : <>Set <code>SLACK_WEBHOOK_URL</code> to enable. No messages are sent until then.</>}</Row>
          <Row name="PagerDuty" state={i.notifications.pagerduty}>{i.notifications.pagerduty === "configured" ? "High and critical incidents create PagerDuty events." : <>Set <code>PAGERDUTY_ROUTING_KEY</code> to enable. No events are sent until then.</>}</Row>
          <Row name="OpenTelemetry (Node.js)" state="configured"><p>Per-application ingestion keys are managed under <a className="text-accent" href="/applications">Applications</a>. Supported: Node.js / Express via the SDK, or OTLP/HTTP JSON.</p><p className="mt-2"><Badge>OTLP protobuf not supported</Badge></p></Row>
        </div>)}</Async>
    </>
  );
}
