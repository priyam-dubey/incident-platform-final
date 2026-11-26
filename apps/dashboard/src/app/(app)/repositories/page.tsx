"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Integrations, Repo } from "@/lib/types";
import { Async, Badge, Button, Card, EmptyState, ErrorState, PageHeader, SeverityBadge, Table, Td, useApi } from "@/components/ui";
import { ago } from "@/lib/format";

const FLASH: Record<string, [boolean, string]> = {
  connected: [true, "GitHub account connected. Choose which repositories to scan."], invalid_state: [false, "That install link expired or was already used. Start again."],
  verification_failed: [false, "GitHub could not verify the installation."], installation_in_use: [false, "That GitHub installation is already linked to another workspace."],
};

function Content() {
  const { ws, can } = useAuth(); const w = `/v1/workspaces/${ws!.id}`;
  const repos = useApi<Repo[]>(`${w}/repositories`);
  const gh = useApi<{ state: string; missing: string[]; installations: { installation_id: number; account: string; suspended: boolean }[] }>(`${w}/github/status`);
  const flash = FLASH[useSearchParams().get("github") ?? ""];
  const [err, setErr] = useState<unknown>(null); const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>) => { setBusy(true); setErr(null); try { await fn(); repos.reload(); gh.reload(); } catch (e) { setErr(e); } finally { setBusy(false); } };
  return (
    <>
      <PageHeader title="Repositories" subtitle="Connect repositories through the GitHub App. Only repositories you choose are scanned." />
      {flash && <p role="status" className={`mb-4 text-sm ${flash[0] ? "text-ok" : "text-crit"}`}>{flash[1]}</p>}
      {!!err && <div className="mb-4"><ErrorState error={err} /></div>}
      <Async state={gh}>{(g) => g.state !== "configured" ? (
        <Card title="GitHub App"><EmptyState title="GitHub App: Not configured">This deployment has no GitHub App credentials yet, so repositories cannot be connected. Missing: {g.missing.map((m) => <code key={m} className="mx-1">{m}</code>)}. See <code>docs/guides/github-app-setup.md</code>.</EmptyState></Card>
      ) : (
        <>
          <div className="mb-4 flex gap-2">
            {can("admin") && <Button disabled={busy} onClick={() => act(async () => { const r = await api<{ url: string }>(`${w}/github/install-url`, { method: "POST" }); window.location.href = r.url; })}>{g.installations.length ? "Add another GitHub account" : "Install the GitHub App"}</Button>}
            {can("admin") && g.installations.length > 0 && <Button variant="ghost" disabled={busy} onClick={() => act(() => api(`${w}/github/sync`, { method: "POST" }))}>Sync repositories</Button>}
          </div>
          <Card>
            <Async state={repos}>{(list) => list.length === 0 ? <EmptyState title="No repositories visible yet">{g.installations.length ? "Grant the App access to repositories on GitHub, then press Sync." : "Install the GitHub App to list your repositories."}</EmptyState> :
              <Table head={["Repository", "Branch", "Status", "Open findings", "Last scan", ""]}>{list.map((r) => (
                <tr key={r.id}><Td>{r.connected ? <Link className="font-medium hover:text-accent" href={`/repositories/${r.id}`}>{r.full_name}</Link> : r.full_name} {r.private && <Badge>private</Badge>}</Td><Td>{r.default_branch}</Td>
                  <Td>{r.connected ? <Badge tone="ok">connected</Badge> : <Badge>not connected</Badge>}</Td>
                  <Td>{r.connected ? <span className="flex gap-1">{["critical", "high", "medium", "low"].filter((s) => r.by_severity[s]).map((s) => <span key={s} className="inline-flex items-center gap-1"><SeverityBadge severity={s} />{r.by_severity[s]}</span>)}{!r.open_findings && "0"}</span> : "–"}</Td><Td>{ago(r.last_scan_at)}</Td>
                  <Td>{can("admin") && <Button variant="ghost" disabled={busy} onClick={() => act(() => api(`${w}/repositories/${r.id}/${r.connected ? "disconnect" : "connect"}`, { method: "POST" }))}>{r.connected ? "Disconnect" : "Connect"}</Button>}</Td></tr>))}</Table>}</Async>
          </Card>
        </>)}</Async>
    </>
  );
}
export default function Repositories() { return <Suspense><Content /></Suspense>; }
void ApiError; void ({} as Integrations);
