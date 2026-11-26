"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { useAuth } from "@/lib/auth";
import { Button, Field, inputCls } from "@/components/ui";

export default function Page() {
  const { signup } = useAuth();
  const router = useRouter();
  const [f, setF] = useState({ name: "", email: "", password: "", workspace: "" });
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await signup(f.email, f.password, f.name, f.workspace || `${f.name}'s workspace`); router.replace("/overview"); }
    catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <h1 className="text-lg font-semibold">Create your account</h1>
      <Field label="Your name"><input className={inputCls} required value={f.name} onChange={set("name")} autoComplete="name" /></Field>
      <Field label="Email"><input className={inputCls} type="email" required value={f.email} onChange={set("email")} autoComplete="email" /></Field>
      <Field label="Password" hint="At least 10 characters, with letters and digits."><input className={inputCls} type="password" required minLength={10} value={f.password} onChange={set("password")} autoComplete="new-password" /></Field>
      <Field label="Workspace name" hint="Your team or project. You can add teammates later."><input className={inputCls} value={f.workspace} onChange={set("workspace")} placeholder="Acme Engineering" /></Field>
      {err && <p role="alert" className="text-sm text-crit">{err}</p>}
      <Button className="w-full" disabled={busy}>{busy ? "Creating…" : "Create account"}</Button>
      <p className="text-sm text-muted">Already registered? <Link className="text-accent" href="/login">Sign in</Link></p>
    </form>
  );
}
