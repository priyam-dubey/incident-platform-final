/**
 * Same-origin proxy to the API gateway. The browser only ever talks to this origin, so the httpOnly
 * refresh cookie is first-party (works on hosted platforms where the dashboard and API are on different
 * sites). GATEWAY_URL is read at runtime. Only a fixed set of headers is forwarded.
 */
import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
const GATEWAY = () => (process.env.GATEWAY_URL ?? "http://localhost:8005").replace(/\/$/, "");
const FORWARD = ["authorization", "content-type", "cookie", "x-requested-with", "x-github-event", "user-agent"];

async function proxy(req: NextRequest, { params }: { params: { path: string[] } }) {
  const url = `${GATEWAY()}/${params.path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  FORWARD.forEach((h) => { const v = req.headers.get(h); if (v) headers.set(h, v); });
  const hasBody = !["GET", "HEAD"].includes(req.method);
  let upstream: Response;
  try {
    upstream = await fetch(url, { method: req.method, headers, body: hasBody ? await req.arrayBuffer() : undefined, redirect: "manual", cache: "no-store" });
  } catch {
    return Response.json({ detail: { code: "gateway_unreachable", message: "The API gateway is not reachable." } }, { status: 502 });
  }
  const out = new Headers();
  ["content-type", "content-disposition", "cache-control"].forEach((h) => { const v = upstream.headers.get(h); if (v) out.set(h, v); });
  // The gateway scopes its refresh cookie to /v1/auth; behind this proxy that path is /gw/v1/auth.
  upstream.headers.getSetCookie().forEach((c) => out.append("set-cookie", c.replace(/Path=\/v1\//i, "Path=/gw/v1/")));
  return new Response(upstream.status === 204 ? null : await upstream.arrayBuffer(), { status: upstream.status, headers: out });
}
export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };
