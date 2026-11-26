"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthProvider, useAuth } from "@/lib/auth";
import { Button, DemoBadge, LoadingBlock, cx } from "@/components/ui";

const NAV = [
  { href: "/overview", label: "Overview" },
  { href: "/repositories", label: "Repositories" },
  { href: "/code", label: "Code analysis" },
  { href: "/applications", label: "Applications" },
  { href: "/incidents", label: "Incidents" },
  { href: "/deployments", label: "Deployments" },
  { href: "/reports", label: "Reports" },
  { href: "/integrations", label: "Integrations" },
  { href: "/settings", label: "Settings" },
];

function Shell({ children }: { children: React.ReactNode }) {
  const { user, loading, ws, workspaces, setWorkspace, logout } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark" | "system">("system");
  useEffect(() => { if (!loading && !user) router.replace(`/login?next=${encodeURIComponent(path)}`); }, [loading, user, router, path]);
  useEffect(() => { setOpen(false); }, [path]);
  useEffect(() => { try { const t = localStorage.getItem("theme"); if (t === "light" || t === "dark") setTheme(t); } catch { /* ignore */ } }, []);
  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next); document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch { /* ignore */ }
  };
  if (loading || !user) return <div className="mx-auto max-w-md p-10"><LoadingBlock /></div>;
  return (
    <div className="flex min-h-screen">
      <aside className={cx("fixed inset-y-0 left-0 z-30 w-60 shrink-0 border-r border-line bg-panel transition-transform md:static md:translate-x-0", open ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex h-14 items-center border-b border-line px-4"><Link href="/overview" className="font-semibold tracking-tight">Incident<span className="text-accent">/</span>Platform</Link></div>
        <nav className="space-y-0.5 p-2" aria-label="Main">
          {NAV.map((n) => {
            const active = path === n.href || path.startsWith(n.href + "/");
            return <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined}
              className={cx("block rounded px-3 py-2 text-sm", active ? "bg-accent/15 font-medium text-accent" : "text-soft hover:bg-raised")}>{n.label}</Link>;
          })}
        </nav>
      </aside>
      {open && <button aria-label="Close menu" className="fixed inset-0 z-20 bg-black/40 md:hidden" onClick={() => setOpen(false)} />}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between gap-3 border-b border-line bg-panel px-4">
          <div className="flex items-center gap-3">
            <button className="rounded border border-line px-2 py-1 text-sm md:hidden" onClick={() => setOpen(true)} aria-label="Open menu">☰</button>
            {workspaces.length > 0 && (
              <select aria-label="Workspace" value={ws?.id ?? ""} onChange={(e) => setWorkspace(e.target.value)} className="max-w-[14rem] rounded border border-line bg-panel px-2 py-1.5 text-sm">
                {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}{w.is_demo ? " (demo)" : ""}</option>)}
              </select>)}
            {ws?.is_demo && <DemoBadge />}
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Button variant="ghost" onClick={toggleTheme} aria-label="Toggle theme">Theme</Button>
            <span className="hidden text-muted sm:inline">{user.email} · {ws?.role}</span>
            <Button variant="ghost" onClick={async () => { await logout(); router.replace("/login"); }}>Sign out</Button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 p-4 md:p-6">{ws ? children : <div className="p-10 text-center text-muted">You do not belong to any workspace yet.</div>}</main>
      </div>
    </div>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AuthProvider><Shell>{children}</Shell></AuthProvider>;
}
