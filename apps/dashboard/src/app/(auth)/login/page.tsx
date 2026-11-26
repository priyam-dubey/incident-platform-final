"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { Button, Field, inputCls } from "@/components/ui";

function Form() {
  const { login, user, loading } = useAuth();
  const router = useRouter();
  const next = useSearchParams().get("next");
  const [email, setEmail] = useState(""); const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const dest = next && next.startsWith("/") && !next.startsWith("//") ? next : "/overview";
  useEffect(() => { if (!loading && user) router.replace(dest); }, [loading, user, router, dest]);
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await login(email, password); router.replace(dest); } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <h1 className="text-lg font-semibold">Sign in</h1>
      <Field label="Email"><input className={inputCls} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
      <Field label="Password"><input className={inputCls} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
      {err && <p role="alert" className="text-sm text-crit">{err}</p>}
      <Button className="w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</Button>
      <p className="flex justify-between text-sm text-muted"><Link className="text-accent" href="/signup">Create account</Link><Link className="text-accent" href="/forgot-password">Forgot password?</Link></p>
    </form>
  );
}
export default function Page() { return <Suspense><Form /></Suspense>; }
