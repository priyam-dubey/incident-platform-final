"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, refreshSession, setAccessToken, setOnAuthLost } from "./api";
import type { Role, User, Workspace } from "./types";

const RANK: Record<Role, number> = { viewer: 0, developer: 1, admin: 2, owner: 3 };
interface Ctx {
  user: User | null; workspaces: Workspace[]; ws: Workspace | null; loading: boolean;
  setWorkspace: (id: string) => void; can: (min: Role) => boolean; reload: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, name: string, workspace: string) => Promise<void>;
  logout: () => Promise<void>;
}
const AuthCtx = createContext<Ctx | null>(null);
export const useAuth = () => { const c = useContext(AuthCtx); if (!c) throw new Error("AuthProvider missing"); return c; };

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [wsId, setWsId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const me = await api<User & { workspaces: Workspace[] }>("/v1/auth/me");
    setUser({ id: me.id, email: me.email, display_name: me.display_name, email_verified: me.email_verified });
    setWorkspaces(me.workspaces);
    let saved: string | null = null;
    try { saved = localStorage.getItem("workspace"); } catch { /* storage unavailable */ }
    setWsId((cur) => me.workspaces.find((w) => w.id === (cur ?? saved))?.id ?? me.workspaces[0]?.id ?? null);
  }, []);

  useEffect(() => {
    setOnAuthLost(() => { setAccessToken(null); setUser(null); setWorkspaces([]); });
    (async () => {
      try { if (await refreshSession()) await load(); } catch { /* not signed in */ }
      setLoading(false);
    })();
    return () => setOnAuthLost(null);
  }, [load]);

  const value = useMemo<Ctx>(() => {
    const ws = workspaces.find((w) => w.id === wsId) ?? null;
    return {
      user, workspaces, ws, loading,
      setWorkspace: (id) => { setWsId(id); try { localStorage.setItem("workspace", id); } catch { /* ignore */ } },
      can: (min) => !!ws && RANK[ws.role] >= RANK[min],
      reload: load,
      login: async (email, password) => { const r = await api<{ access_token: string }>("/v1/auth/login", { method: "POST", json: { email, password } }); setAccessToken(r.access_token); await load(); },
      signup: async (email, password, display_name, workspace_name) => {
        const r = await api<{ access_token: string }>("/v1/auth/signup", { method: "POST", json: { email, password, display_name, workspace_name } });
        setAccessToken(r.access_token); await load();
      },
      logout: async () => { try { await api("/v1/auth/logout", { method: "POST" }); } catch { /* ignore */ } setAccessToken(null); setUser(null); setWorkspaces([]); },
    };
  }, [user, workspaces, wsId, loading, load]);
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}
