"use client";
import { useState } from "react";
import { api, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Finding, Repo } from "@/lib/types";
import { AiBadge, Async, Badge, Button, Card, EmptyState, ErrorState, PageHeader, Select, SeverityBadge, Table, Td, inputCls, useApi } from "@/components/ui";

const SEVS = ["critical", "high", "medium", "low", "info"];
export function FindingsExplorer({ repositoryId }: { repositoryId?: string }) {
  const { ws, can } = useAuth(); const w = `/v1/workspaces/${ws!.id}`;
  const [f, setF] = useState({ severity: "", status: "open", tool: "", category: "", q: "", sort: "severity", repository_id: repositoryId ?? "" });
  const [page, setPage] = useState(0); const [open, setOpen] = useState<string | null>(null);
  const repos = useApi<Repo[]>(repositoryId ? null : `${w}/repositories`);
  const d = useApi<{ total: number; items: Finding[] }>(`${w}/findings${qs({ ...f, limit: 25, offset: page * 25 })}`);
  const set = (k: keyof typeof f) => (v: string) => { setF({ ...f, [k]: v }); setPage(0); };
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {!repositoryId && <Select label="Repository" value={f.repository_id} onChange={set("repository_id")} options={[{ value: "", label: "All repositories" }, ...(repos.data ?? []).filter((r) => r.connected).map((r) => ({ value: r.id, label: r.full_name }))]} />}
        <Select label="Severity" value={f.severity} onChange={set("severity")} options={[{ value: "", label: "Any severity" }, ...SEVS.map((s) => ({ value: s, label: s }))]} />
        <Select label="Status" value={f.status} onChange={set("status")} options={[{ value: "", label: "Any status" }, ...["open", "fixed", "ignored", "false_positive", "accepted_risk"].map((s) => ({ value: s, label: s.replace("_", " ") }))]} />
        <Select label="Category" value={f.category} onChange={set("category")} options={[{ value: "", label: "Any category" }, ...["sast", "secret", "dependency", "lint", "types", "iac"].map((s) => ({ value: s, label: s }))]} />
        <Select label="Tool" value={f.tool} onChange={set("tool")} options={[{ value: "", label: "Any tool" }, ...["semgrep", "bandit", "ruff", "eslint", "tsc", "gitleaks", "npm-audit", "pip-audit", "trivy"].map((s) => ({ value: s, label: s }))]} />
        <Select label="Sort" value={f.sort} onChange={set("sort")} options={[{ value: "severity", label: "Severity" }, { value: "recent", label: "Recently changed" }, { value: "file", label: "File" }]} />
        <input aria-label="Search findings" className={inputCls + " w-48"} placeholder="Search title, file, rule…" value={f.q} onChange={(e) => set("q")(e.target.value)} />
      </div>
      <Card>
        <Async state={d}>{(r) => r.items.length === 0 ? <EmptyState title="No findings match">{f.status === "open" && !f.severity && !f.q ? "Nothing open - or no scan has completed yet. Connect a repository and run a scan." : "Adjust the filters."}</EmptyState> : (
          <>
            <Table head={["Severity", "Finding", "Location", "Tool", "Status"]}>{r.items.flatMap((x) => [
              <tr key={x.id} className="cursor-pointer hover:bg-raised" onClick={() => setOpen(open === x.id ? null : x.id)}><Td><SeverityBadge severity={x.severity} /></Td>
                <Td><button className="text-left font-medium hover:text-accent" aria-expanded={open === x.id}>{x.title}</button>{x.reintroduced_count > 0 && <> <Badge tone="warn">reintroduced</Badge></>}<p className="text-xs text-muted">{x.rule_id}{x.cwe && ` · ${x.cwe}`}{x.package_name && ` · ${x.package_name}@${x.package_version ?? "?"}`}</p></Td>
                <Td><span className="font-mono text-xs">{x.file_path ?? "–"}{x.start_line ? `:${x.start_line}` : ""}</span>{!repositoryId && <p className="text-xs text-muted">{x.repository}</p>}</Td><Td>{x.tool}</Td><Td>{x.status.replace("_", " ")}</Td></tr>,
              open === x.id ? <tr key={x.id + "d"}><td colSpan={5} className="bg-raised px-3 py-3"><FindingDetail id={x.id} canEdit={can("developer")} onChanged={d.reload} /></td></tr> : null])}</Table>
            <div className="mt-3 flex items-center justify-between text-sm text-muted"><span>{r.total} findings</span><span className="flex gap-2"><Button variant="ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button><Button variant="ghost" disabled={(page + 1) * 25 >= r.total} onClick={() => setPage(page + 1)}>Next</Button></span></div>
          </>)}</Async>
      </Card>
    </>
  );
}

function FindingDetail({ id, canEdit, onChanged }: { id: string; canEdit: boolean; onChanged: () => void }) {
  const { ws } = useAuth(); const base = `/v1/workspaces/${ws!.id}/findings/${id}`;
  const d = useApi<Finding>(base);
  const [err, setErr] = useState<unknown>(null); const [busy, setBusy] = useState(false); const [note, setNote] = useState("");
  const run = async (fn: () => Promise<unknown>) => { setBusy(true); setErr(null); try { await fn(); d.reload(); onChanged(); } catch (e) { setErr(e); } finally { setBusy(false); } };
  return (
    <Async state={d}>{(x) => (
      <div className="space-y-3 text-sm" onClick={(e) => e.stopPropagation()}>
        {x.message && <p className="text-soft">{x.message}</p>}
        {x.code_snippet && <pre className="overflow-x-auto rounded border border-line bg-panel p-2 font-mono text-xs">{x.code_snippet}</pre>}
        {x.fixed_version && <p>Fixed in version <code>{x.fixed_version}</code>.</p>}
        <p className="text-xs text-muted">First seen at commit {x.first_seen_commit?.slice(0, 7) ?? "?"}, last seen at {x.last_seen_commit?.slice(0, 7) ?? "?"}.{x.triage_note && ` Triage note: ${x.triage_note}`}</p>
        {x.explanation ? (
          <div className="rounded border border-ai/40 bg-ai/5 p-3"><p className="mb-1 flex items-center gap-2"><AiBadge /> <span className="text-xs text-muted">{x.explanation.model}</span></p>
            <p><strong>Summary:</strong> {x.explanation.summary}</p><p className="mt-1"><strong>Why it matters:</strong> {x.explanation.why_it_matters}</p><p className="mt-1"><strong>Suggested fix:</strong> {x.explanation.suggested_fix}</p>
            <p className="mt-1 text-xs text-muted">False-positive likelihood: {x.explanation.false_positive_likelihood}. {x.explanation.disclaimer}</p></div>
        ) : canEdit && <Button variant="ghost" disabled={busy} onClick={() => run(() => api(`${base}/explain`, { method: "POST" }))}>✦ Explain with AI</Button>}
        {!!err && <ErrorState error={err} />}
        {canEdit && <div className="flex flex-wrap items-center gap-2"><input aria-label="Triage note" className={inputCls + " max-w-xs"} placeholder="Reason (required to suppress)" value={note} onChange={(e) => setNote(e.target.value)} />
          {x.status === "open" ? <>{(["ignored", "false_positive", "accepted_risk"] as const).map((s) => <Button key={s} variant="ghost" disabled={busy || !note.trim()} onClick={() => run(() => api(`${base}/triage`, { method: "POST", json: { status: s, note } }))}>{s.replace("_", " ")}</Button>)}</> :
            ["ignored", "false_positive", "accepted_risk"].includes(x.status) && <Button variant="ghost" disabled={busy} onClick={() => run(() => api(`${base}/triage`, { method: "POST", json: { status: "open" } }))}>Reopen</Button>}</div>}
      </div>)}</Async>
  );
}


