# Dashboard

Next.js 14 (App Router) dashboard for reviewing incidents: the evidence
trail, AI-generated root-cause hypotheses, and the accept/reject/edit
verdict controls that feed the eval-dataset loop.

## Design

See the design token system in `tailwind.config.js` and `src/app/globals.css`.
Grounded in the actual subject - an SRE reading AI-cited evidence, often at
3am - rather than generic SaaS defaults: a near-black instrument-panel
palette (not pure black, not the generic "dark mode + one accent" look),
Space Grotesk/Inter/JetBrains Mono for display/body/data, and hairline-row
layout instead of rounded cards.

**Signature element**: `src/components/ConfidenceReadout.tsx` renders each
hypothesis's confidence as a meter with numbered citation ticks that are
real anchor links to the exact evidence row they cite (`#evidence-{id}`,
highlighted via CSS `:target` - no client JS needed for that interaction).
This makes the platform's actual mechanism - every AI claim traces to a
specific, inspectable piece of evidence - a physical, clickable part of the
UI instead of a claim in a tooltip.

## Architecture note: backend-for-frontend

`src/lib/api.ts` runs only on the server (Server Components, Route
Handlers) and holds the `ALERT_ROUTER_API_KEY` - it never reaches the
browser. The one client-side write (submitting a verdict,
`VerdictControls.tsx`) calls this app's own `/api/hypotheses/[id]/verdict`
route handler, which proxies to the alert-router using the server-held key.
The browser never sees `ALERT_ROUTER_API_KEY`.

## Known scope cut: no real authentication

There is no session/login system yet. The home page asks for a workspace id
directly, and verdict submission asks for a reviewer email in a plain text
field. This is stated plainly rather than hidden behind a fake-looking login
form: the reviewer-email field in `VerdictControls.tsx` is exactly where a
real signed-in user's identity would be substituted once session auth
exists (e.g. NextAuth with an OIDC provider), and no other code changes
would be needed - `apply_verdict()` on the alert-router side already takes
`reviewed_by` as a plain string parameter.

## Local development

```bash
cp .env.local.example .env.local   # set ALERT_ROUTER_URL / ALERT_ROUTER_API_KEY
npm install
npm run dev
```

Requires `apps/alert-router` running (see its README) with matching
`API_KEY_VALID_KEYS` / `ALERT_ROUTER_API_KEY`.

## Verification performed

`npm install`, `npx tsc --noEmit`, and `npm run build` were run against this
exact codebase and passed cleanly (all 5 routes compiled: `/`,
`/incidents`, `/incidents/[id]`, the verdict API route, and the 404 page).
`next/font/google` requires internet access to `fonts.googleapis.com` at
build time - standard Next.js behavior, not specific to this project - so
`npm run build` needs the same connectivity a normal `npm run build` would.

## Known finding: dependency audit

`npm audit` flags Next.js advisories against the full 14.x-16.x range this
version falls in (see `npm audit` output) - most concern self-hosted image
optimization, i18n middleware, or WebSocket upgrade paths not used by this
app, but this hasn't been individually triaged against 14.2.35 specifically.
Worth a proper look before a real production deploy; noted here rather than
silently ignored.
