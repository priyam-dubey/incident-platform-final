/** Browser API client. Access token lives in memory only; the refresh token is an httpOnly cookie. */

export class ApiError extends Error {
  constructor(public status: number, public code: string | null, message: string, public detail?: unknown) {
    super(message);
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onAuthLost: (() => void) | null = null;
export const setOnAuthLost = (fn: (() => void) | null) => { onAuthLost = fn; };
export const setAccessToken = (t: string | null) => { accessToken = t; };

const BASE = "/gw";
const CSRF = { "X-Requested-With": "incident-platform" };

function parseError(status: number, body: unknown): ApiError {
  const d = (body as { detail?: unknown })?.detail;
  if (typeof d === "string") return new ApiError(status, null, d);
  if (Array.isArray(d)) return new ApiError(status, null, d.map((e: { msg?: string }) => e.msg).filter(Boolean).join("; ") || "Invalid request", d);
  if (d && typeof d === "object") {
    const o = d as { code?: string; message?: string };
    return new ApiError(status, o.code ?? null, o.message ?? "Request failed", d);
  }
  return new ApiError(status, null, status === 502 ? "The API is not reachable." : `Request failed (${status})`);
}

export async function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const r = await fetch(`${BASE}/v1/auth/refresh`, { method: "POST", headers: CSRF, credentials: "same-origin" });
      if (!r.ok) return false;
      const j = await r.json();
      accessToken = j.access_token;
      return true;
    } catch { return false; } finally { setTimeout(() => { refreshing = null; }, 0); }
  })();
  return refreshing;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown; raw?: boolean } = {}, retry = true): Promise<T> {
  const headers: Record<string, string> = { ...CSRF, ...(init.headers as Record<string, string> | undefined) };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (init.json !== undefined) { headers["Content-Type"] = "application/json"; init = { ...init, body: JSON.stringify(init.json) }; }
  const r = await fetch(`${BASE}${path}`, { ...init, headers, credentials: "same-origin", cache: "no-store" });
  if (r.status === 401 && retry && !path.startsWith("/v1/auth/")) {
    if (await refreshSession()) return api<T>(path, init, false);
    onAuthLost?.();
  }
  if (!r.ok) throw parseError(r.status, await r.json().catch(() => null));
  if (init.raw) return r as unknown as T;
  if (r.status === 204) return undefined as T;
  return r.json();
}

export async function download(path: string, fallbackName: string): Promise<void> {
  const r = await api<Response>(path, { raw: true });
  const blob = await r.blob();
  const name = /filename="([^"]+)"/.exec(r.headers.get("content-disposition") ?? "")?.[1] ?? fallbackName;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export const qs = (o: Record<string, string | number | boolean | null | undefined>) => {
  const p = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") p.set(k, String(v)); });
  const s = p.toString();
  return s ? `?${s}` : "";
};
