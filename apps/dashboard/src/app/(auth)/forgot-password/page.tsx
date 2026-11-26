"use client";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { api } from "@/lib/api";
import { Button, Field, inputCls } from "@/components/ui";

export default function Page() {
  const [email, setEmail] = useState(""); const [done, setDone] = useState(false); const [err, setErr] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault(); setErr(null);
    try { await api("/v1/auth/forgot-password", { method: "POST", json: { email } }); setDone(true); } catch (x) { setErr((x as Error).message); }
  }
  return done ? (
    <div className="space-y-3 text-sm"><h1 className="text-lg font-semibold">Request received</h1>
      <p className="text-soft">If an account exists for that address, a reset was issued. This deployment has no email provider configured, so reset links are not delivered automatically; ask the operator of this deployment to complete the reset.</p>
      <Link className="text-accent" href="/login">Back to sign in</Link></div>
  ) : (
    <form onSubmit={submit} className="space-y-4"><h1 className="text-lg font-semibold">Reset password</h1>
      <Field label="Email"><input className={inputCls} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
      {err && <p role="alert" className="text-sm text-crit">{err}</p>}
      <Button className="w-full">Request reset</Button><Link className="text-sm text-accent" href="/login">Back to sign in</Link></form>
  );
}
