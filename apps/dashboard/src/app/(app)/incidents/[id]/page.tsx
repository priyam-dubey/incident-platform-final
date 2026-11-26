"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Deployment, Evidence, Hypothesis, Incident } from "@/lib/types";
import { AiBadge, Async, Badge, Button, Card, DemoBadge, EmptyState, PageHeader, SeverityBadge, inputCls, useApi } from "@/components/ui";
import { fmtTime, short } from "@/lib/format";

interface Detail {
  incident: Incident; evidence: Evidence[]; hypotheses: Hypothesis[]; notes: { id: string; body: string; author: string | null; created_at: string }[];
  related_deployments: Deployment[]; notifications: { channel: string; status: string; at: string }[];
  ai: { state: string; model: string; detail: string | null; disclaimer: string };
}

export default function IncidentPage() {
  const { id } = useParams<{ id: string }>();
  const { ws, can } = useAuth();
  const base = `/v1/workspaces/${ws!.id}/incidents/${id}`;
  const d = useApi<Detail>(base);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [note, setNote] = useState(""); const [hl, setHl] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>, okText?: string) => {
    setBusy(true); setMsg(null);
    try { await fn(); if (okText) setMsg({ ok: true, text: okText }); d.reload(); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); } finally { setBusy(false); }
  };
  return (
    <Async state={d} rows={6}>{({ incident: i, evidence, hypotheses, notes, related_deployments, notifications, ai }) => (
      <>
        <PageHeader title={<>{i.title} {i.synthetic && <DemoBadge />}</>}
          subtitle={<span className="flex flex-wrap items-center gap-2"><SeverityBadge severity={i.severity} /> <Badge>{i.status.replace("_", " ")}</Badge> {i.application_name && <>on <Link className="text-accent" href={`/applications/${i.application_id}`}>{i.application_name}</Link></>} · started {fmtTime(i.started_at)}</span>}
          actions={can("developer") && <>
            {!["resolved", "dismissed"].includes(i.status) && <><Button variant="ghost" disabled={busy} onClick={() => run(() => api(`${base}/status`, { method: "POST", json: { status: "dismissed" } }))}>Dismiss</Button><Button disabled={busy} onClick={() => run(() => api(`${base}/status`, { method: "POST", json: { status: "resolved" } }))}>Mark resolved</Button></>}
            {["resolved", "dismissed"].includes(i.status) && <Button variant="ghost" disabled={busy} onClick={() => run(() => api(`${base}/status`, { method: "POST", json: { status: "pending_review" } }))}>Reopen</Button>}</>} />
        {msg && <p role={msg.ok ? "status" : "alert"} className={`mb-4 text-sm ${msg.ok ? "text-ok" : "text-crit"}`}>{msg.text}</p>}
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            <Card title="Measured facts" actions={<Badge tone="ok">deterministic</Badge>}>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">{Object.entries(i.details).filter(([k, v]) => k !== "rca" && typeof v !== "object").map(([k, v]) => (
                <div key={k}><dt className="text-xs text-muted">{k.replace(/_/g, " ")}</dt><dd className="tabular-nums">{String(v)}</dd></div>))}</dl>
              <p className="mt-3 text-xs text-muted">Detector: {i.detector}. These numbers come from your telemetry, not from a language model.</p>
            </Card>

            <Card title="Root-cause hypotheses" actions={<AiBadge />}>
              <p className="mb-3 text-xs text-muted">{ai.disclaimer} Each hypothesis cites the evidence it is based on; ungrounded output is discarded.</p>
              {hypotheses.length === 0 ? (
                <EmptyState title={ai.state === "configured" ? "No grounded hypothesis" : "AI analysis is not available"}
                  action={can("developer") && ai.state === "configured" ? <Button disabled={busy} onClick={() => run(() => api(`${base}/analyze`, { method: "POST" }), "Analysis finished.")}>Run analysis</Button> : undefined}>
                  {ai.state === "configured" ? "The model did not produce a hypothesis supported by the evidence, or analysis has not run yet." : <>The AI provider is <strong>{ai.state.replace("_", " ")}</strong>{ai.detail ? ` (${ai.detail})` : ""}. The incident and its evidence are still fully available. Configure it under Integrations.</>}</EmptyState>
              ) : <ol className="space-y-4">{hypotheses.map((h) => <HypothesisCard key={h.id} h={h} evidence={evidence} canReview={can("developer")} onCite={setHl} busy={busy} onReview={(body) => run(() => api(`${base}/hypotheses/${h.id}/review`, { method: "POST", json: body }), "Review saved.")} />)}</ol>}
            </Card>

            <Card title="Evidence">
              {evidence.length === 0 ? <p className="text-sm text-muted">No evidence recorded.</p> : <ul className="divide-y divide-line">{evidence.map((e, n) => (
                <li key={e.id} id={`ev-${e.id}`} className={`flex gap-3 py-2 text-sm ${hl === e.id ? "bg-accent/10" : ""}`}><span className="w-6 shrink-0 text-muted">[{n + 1}]</span>
                  <div className="min-w-0"><p className="break-words font-mono text-xs">{e.snippet}</p><p className="mt-0.5 text-xs text-muted"><Badge>{e.source_type}</Badge> {e.source_ref.length > 70 ? e.source_ref.slice(0, 70) + "…" : e.source_ref}</p></div></li>))}</ul>}
            </Card>
          </div>

          <div className="space-y-6">
            <Card title="Possibly related deployments">
              {related_deployments.length === 0 ? <p className="text-sm text-muted">No deployment registered near this incident.</p> :
                <ul className="space-y-2 text-sm">{related_deployments.map((x) => <li key={x.id}>{fmtTime(x.deployed_at)}<br /><span className="text-muted">version {x.version ?? "–"} · commit <code>{short(x.commit_sha)}</code>{x.repository && ` · ${x.repository}`}</span></li>)}</ul>}
              <p className="mt-3 text-xs text-muted">Timing is a lead to investigate, not proof that the deployment caused the incident.</p>
            </Card>
            <Card title="Notifications">{notifications.length === 0 ? <p className="text-sm text-muted">None sent. Slack and PagerDuty notify only when configured under Integrations.</p> :
              <ul className="text-sm">{notifications.map((n, k) => <li key={k}>{n.channel}: <Badge tone={n.status === "sent" ? "ok" : "crit"}>{n.status}</Badge></li>)}</ul>}</Card>
            <Card title="Notes">
              {notes.length === 0 && <p className="mb-2 text-sm text-muted">No notes yet.</p>}
              <ul className="mb-3 space-y-2 text-sm">{notes.map((n) => <li key={n.id}><p>{n.body}</p><p className="text-xs text-muted">{n.author} · {fmtTime(n.created_at)}</p></li>)}</ul>
              {can("developer") && <form onSubmit={(e) => { e.preventDefault(); if (!note.trim()) return; void run(() => api(`${base}/notes`, { method: "POST", json: { body: note } })); setNote(""); }}>
                <label className="sr-only" htmlFor="note">Add a note</label><textarea id="note" className={inputCls} rows={3} maxLength={4000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did you check or change?" /><Button className="mt-2" disabled={busy || !note.trim()}>Add note</Button></form>}
            </Card>
          </div>
        </div>
      </>)}</Async>
  );
}

function HypothesisCard({ h, evidence, canReview, onCite, onReview, busy }: { h: Hypothesis; evidence: Evidence[]; canReview: boolean; onCite: (id: string) => void; onReview: (b: { verdict: string; notes?: string; edited_text?: string }) => void; busy: boolean }) {
  const [editing, setEditing] = useState(false); const [text, setText] = useState(h.edited_text ?? h.hypothesis); const [notes, setNotes] = useState("");
  return (
    <li className="rounded border border-line p-3">
      <div className="flex items-start justify-between gap-3"><p className="text-sm">{h.edited_text ?? h.hypothesis}</p><span className="shrink-0 text-xs text-muted" title="Model-reported confidence; not a probability">conf. {(h.confidence * 100).toFixed(0)}%</span></div>
      {h.edited_text && <p className="mt-1 text-xs text-muted">Edited by {h.reviewed_by}. Original: {h.hypothesis}</p>}
      <p className="mt-2 text-xs text-muted">Evidence: {h.cited_evidence_ids.map((c) => { const n = evidence.findIndex((e) => e.id === c) + 1; return <a key={c} href={`#ev-${c}`} onClick={() => onCite(c)} className="mr-1 text-accent hover:underline">[{n || "?"}]</a>; })}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {h.human_verdict ? <Badge tone={h.human_verdict === "rejected" ? "crit" : "ok"}>{h.human_verdict} by {h.reviewed_by}</Badge> : <Badge tone="warn">awaiting human review</Badge>}
        {canReview && !h.human_verdict && !editing && <>
          <Button variant="ghost" disabled={busy} onClick={() => onReview({ verdict: "accepted" })}>Accept</Button>
          <Button variant="ghost" disabled={busy} onClick={() => { const n = prompt("Why reject this hypothesis? (optional)") ?? undefined; onReview({ verdict: "rejected", notes: n }); }}>Reject</Button>
          <Button variant="ghost" disabled={busy} onClick={() => setEditing(true)}>Edit</Button></>}
      </div>
      {editing && <div className="mt-3 space-y-2"><label className="sr-only" htmlFor={`e-${h.id}`}>Edited hypothesis</label><textarea id={`e-${h.id}`} className={inputCls} rows={3} maxLength={1500} value={text} onChange={(e) => setText(e.target.value)} />
        <input aria-label="Review notes" className={inputCls} placeholder="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <div className="flex gap-2"><Button disabled={busy || !text.trim()} onClick={() => { onReview({ verdict: "edited", edited_text: text, notes: notes || undefined }); setEditing(false); }}>Save edit</Button><Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button></div></div>}
    </li>
  );
}
