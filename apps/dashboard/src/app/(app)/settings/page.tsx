"use client";
import { FormEvent, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Role } from "@/lib/types";
import { Async, Badge, Button, Card, Field, PageHeader, Select, Table, Td, inputCls, useApi } from "@/components/ui";
import { fmtTime } from "@/lib/format";

interface Member { user_id: string; email: string; display_name: string; role: Role }
const ROLES: Role[] = ["viewer", "developer", "admin", "owner"];

export default function Settings() {
  const { ws, user, can, reload } = useAuth(); const w = `/v1/workspaces/${ws!.id}`;
  const members = useApi<Member[]>(`${w}/members`);
  const audit = useApi<{ id: string; action: string; resource_type: string; actor: string | null; created_at: string }[]>(can("admin") ? `${w}/audit-logs` : null);
  const [name, setName] = useState(user?.display_name ?? ""); const [msg, setMsg] = useState<{ ok: boolean; t: string } | null>(null);
  const [inv, setInv] = useState({ email: "", role: "developer" });
  const run = async (fn: () => Promise<unknown>, ok: string) => { setMsg(null); try { await fn(); setMsg({ ok: true, t: ok }); members.reload(); audit.reload(); } catch (e) { setMsg({ ok: false, t: (e as Error).message }); } };
  return (
    <>
      <PageHeader title="Settings" subtitle={`${ws!.name} · your role: ${ws!.role}`} />
      {msg && <p role={msg.ok ? "status" : "alert"} className={`mb-4 text-sm ${msg.ok ? "text-ok" : "text-crit"}`}>{msg.t}</p>}
      <div className="space-y-6">
        <Card title="Profile">
          <form className="flex max-w-md items-end gap-2" onSubmit={(e: FormEvent) => { e.preventDefault(); void run(async () => { await api("/v1/auth/me", { method: "PATCH", json: { display_name: name } }); await reload(); }, "Profile updated."); }}>
            <div className="flex-1"><Field label="Display name"><input className={inputCls} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></Field></div><Button disabled={!name.trim()}>Save</Button></form>
          <p className="mt-2 text-xs text-muted">{user?.email}</p>
        </Card>
        <Card title="Members">
          <Async state={members}>{(list) => (
            <Table head={["Member", "Role", ""]}>{list.map((m) => (
              <tr key={m.user_id}><Td>{m.display_name} <span className="text-muted">{m.email}</span> {m.user_id === user?.id && <Badge>you</Badge>}</Td>
                <Td>{can("admin") && m.user_id !== user?.id ? <Select label={`Role for ${m.email}`} value={m.role} onChange={(role) => run(() => api(`${w}/members/${m.user_id}`, { method: "PATCH", json: { role } }), "Role updated.")} options={ROLES.map((r) => ({ value: r, label: r }))} /> : m.role}</Td>
                <Td>{can("admin") && m.user_id !== user?.id && <Button variant="ghost" onClick={() => confirm(`Remove ${m.email}?`) && run(() => api(`${w}/members/${m.user_id}`, { method: "DELETE" }), "Member removed.")}>Remove</Button>}</Td></tr>))}</Table>)}</Async>
          {can("admin") && <form className="mt-4 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); void run(() => api(`${w}/members`, { method: "POST", json: inv }), "Member added."); setInv({ ...inv, email: "" }); }}>
            <div className="min-w-[14rem] flex-1"><Field label="Add by email" hint="They need an account first (invitation emails are not implemented)."><input className={inputCls} type="email" required value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} /></Field></div>
            <Select label="Role" value={inv.role} onChange={(role) => setInv({ ...inv, role })} options={ROLES.filter((r) => r !== "owner" || ws!.role === "owner").map((r) => ({ value: r, label: r }))} /><Button>Add</Button></form>}
        </Card>
        {can("admin") && <Card title="Audit log"><Async state={audit}>{(list) => list.length === 0 ? <p className="text-sm text-muted">No activity yet.</p> :
          <Table head={["When", "Actor", "Action", "Resource"]}>{list.slice(0, 100).map((a) => <tr key={a.id}><Td>{fmtTime(a.created_at)}</Td><Td>{a.actor ?? "system"}</Td><Td><code>{a.action}</code></Td><Td>{a.resource_type}</Td></tr>)}</Table>}</Async></Card>}
      </div>
    </>
  );
}
