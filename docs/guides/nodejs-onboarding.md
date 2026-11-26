# Connect a Node.js / Express app

This takes about five minutes and needs **no access to your database or payment credentials**. The SDK
only sends HTTP request spans, logs and process metrics to your platform's ingestion endpoint.

## 1. Create the application and copy its key
Dashboard -> Applications -> Add Application. Choose the environment (development / staging / production).
The ingestion key (`ipk_...`) is shown **once**. Lost it? Use *Rotate key* (the old key stops working immediately).

## 2. Install the SDK
```bash
npm install @incident-platform/node
```
(While the package is not yet published, install from this repo: `npm install ../path/to/packages/node-sdk`.)

## 3. Configure (environment variables - never commit the key)
```bash
INCIDENT_PLATFORM_ENDPOINT=https://<your-ingestion-host>     # no trailing path
INCIDENT_PLATFORM_KEY=ipk_xxxxxxxxxx_...
INCIDENT_PLATFORM_APP=my-backend                              # should match the application name
INCIDENT_PLATFORM_ENV=production                              # development | staging | production
INCIDENT_PLATFORM_RELEASE=1.4.2                               # optional: version you are deploying
INCIDENT_PLATFORM_COMMIT=$GIT_COMMIT_SHA                      # optional: enables deploy <-> incident correlation
```

## 4. Initialise FIRST in your server entry file
```js
const incident = require('@incident-platform/node');
incident.init();                       // must run before require('express') / mongodb / mongoose

const express = require('express');
const app = express();
// ... your routes ...
app.use(incident.expressErrorHandler());   // after routes, before your own error handler
```
ESM apps: `node --require ./incident-init.cjs server.mjs`, where `incident-init.cjs` calls `init()`.

Optional helpers:
```js
incident.logger.info('order placed', { 'order.id': id });   // structured log, auto-linked to the request trace
incident.captureException(err);                              // mark span failed + log stack
```

## 5. Deploy and generate traffic
The application card turns **Connected** once telemetry arrives (usually within ~15 s).
Until then it stays **Waiting for telemetry**; the platform never shows made-up values.

## What is collected
| Signal | Details |
|---|---|
| Traces | HTTP server spans (method, route, status, duration), Express route spans, MongoDB operation spans (operation + collection; **no query values**) |
| Logs | Only what you send via `incident.logger`, `captureException`, and (opt-in) `captureConsole: true` |
| Metrics | **Process-level only**: RSS memory, heap used/total, event-loop lag p99, process CPU fraction, uptime. These describe your Node process, **not** the host or container. |

## What is NOT collected (and redaction)
No request/response bodies, no headers or cookies, no query strings (replaced with `?[REDACTED]`).
Attributes whose names contain `authorization`, `cookie`, `password`, `token`, `secret`, `api_key`, `card`, ... are masked
in the SDK *and again* on the server; emails, JWTs, API-key-like strings and card numbers are removed from log text.
Add your own: `incident.init({ extraSensitiveKeys: ['aadhaar'] })`.
The SDK never reads process arguments, environment variables, or host identifiers.

## Safety
`init()` never throws and never blocks startup: with missing/invalid configuration it prints one warning and telemetry stays off.
Export failures are swallowed; your app keeps serving requests.

## Known limitations
- OTLP **JSON** only (protobuf not accepted yet).
- Latency percentiles are computed server-side from request spans, so sampling would reduce accuracy (the SDK does not sample).
- Auto-instrumentation covers http, Express and the MongoDB driver. Mongoose works through the driver. Other libraries
  (Redis, Postgres, axios/fetch outbound calls) are not instrumented yet.
