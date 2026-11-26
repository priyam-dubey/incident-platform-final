'use strict';

const api = require('@opentelemetry/api');
const { logs, SeverityNumber } = api; // Logs API is part of @opentelemetry/api >= 1.10
const { NodeSDK } = require('@opentelemetry/sdk-node');
const { resourceFromAttributes } = require('@opentelemetry/resources');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');
const { OTLPLogExporter } = require('@opentelemetry/exporter-logs-otlp-http');
const { OTLPMetricExporter } = require('@opentelemetry/exporter-metrics-otlp-http');
const { BatchLogRecordProcessor } = require('@opentelemetry/sdk-logs');
const { PeriodicExportingMetricReader } = require('@opentelemetry/sdk-metrics');
const { HttpInstrumentation } = require('@opentelemetry/instrumentation-http');
const { ExpressInstrumentation } = require('@opentelemetry/instrumentation-express');
const { MongoDBInstrumentation } = require('@opentelemetry/instrumentation-mongodb');

const { resolveConfig } = require('./config');
const { sanitizeAttributes } = require('./sanitize');
const { registerDeployment } = require('./deployments');
const { registerRuntimeMetrics } = require('./runtime-metrics');

let state = { sdk: null, cfg: null, stopRuntime: null, started: false };
const SDK_NAME = '@incident-platform/node';

function warn(msg) {
  // eslint-disable-next-line no-console
  console.warn(`[incident-platform] ${msg}`);
}

/** Wrap an exporter so attributes are scrubbed before leaving the process. */
function sanitizingExporter(inner, extra) {
  return {
    export(items, cb) {
      try {
        for (const s of items) if (s.attributes) s.attributes = sanitizeAttributes(s.attributes, extra);
      } catch { /* never block export */ }
      inner.export(items, cb);
    },
    shutdown: () => inner.shutdown(),
    forceFlush: () => (inner.forceFlush ? inner.forceFlush() : Promise.resolve()),
  };
}

/**
 * Start instrumentation. Call this FIRST in your app (before requiring express/mongodb).
 * Never throws and never blocks startup: invalid config disables telemetry with a warning.
 * Returns { started: boolean, problems: string[] }.
 */
function init(options = {}) {
  if (state.started) return { started: true, problems: [] };
  const { ok, problems, cfg } = resolveConfig(options);
  if (!ok) {
    warn(`telemetry disabled: ${problems.join('; ')}`);
    return { started: false, problems };
  }
  if (cfg.debug) api.diag.setLogger(new api.DiagConsoleLogger(), api.DiagLogLevel.INFO);
  const headers = { 'X-Ingestion-Key': cfg.key };
  const otlp = (signal) => ({ url: `${cfg.endpoint}/otlp/v1/${signal}`, headers, timeoutMillis: 10000 });

  const resourceAttrs = {
    'service.name': cfg.serviceName,
    'deployment.environment': cfg.environment,
    'telemetry.sdk.name': SDK_NAME,
  };
  if (cfg.release) resourceAttrs['service.version'] = cfg.release;
  if (cfg.commitSha) resourceAttrs['vcs.commit.id'] = cfg.commitSha;

  try {
    const sdk = new NodeSDK({
      resource: resourceFromAttributes(resourceAttrs),
      // Privacy: do not auto-collect host/process details (process.command_args can contain secrets).
      resourceDetectors: [],
      traceExporter: sanitizingExporter(new OTLPTraceExporter(otlp('traces')), cfg.extraSensitiveKeys),
      logRecordProcessors: [new BatchLogRecordProcessor({ exporter: new OTLPLogExporter(otlp('logs')), scheduledDelayMillis: 1000 })],
      metricReaders: [new PeriodicExportingMetricReader({
        exporter: new OTLPMetricExporter(otlp('metrics')), exportIntervalMillis: cfg.metricIntervalMs,
      })],
      instrumentations: [
        // No request/response bodies or headers are captured by these instrumentations.
        new HttpInstrumentation({ ignoreIncomingRequestHook: (req) => req.url === '/healthz' || req.url === '/health' }),
        new ExpressInstrumentation(),
        new MongoDBInstrumentation({ enhancedDatabaseReporting: false }), // no query values
      ],
    });
    sdk.start();
    state = { sdk, cfg, started: true, stopRuntime: registerRuntimeMetrics(api.metrics.getMeter(SDK_NAME)) };
    if (cfg.captureConsole) captureConsole();
    const stop = () => shutdown().finally(() => process.exit());
    process.once('SIGTERM', stop);
    return { started: true, problems: [] };
  } catch (err) {
    warn(`telemetry failed to start and is disabled: ${err && err.message}`);
    return { started: false, problems: [String(err && err.message)] };
  }
}

function emit(severityNumber, severityText, message, attributes) {
  const logger = logs.getLogger(SDK_NAME);
  logger.emit({
    severityNumber, severityText, body: String(message),
    attributes: sanitizeAttributes(attributes || {}, state.cfg ? state.cfg.extraSensitiveKeys : []),
  });
}

/** Structured logger. Records emitted inside a request automatically carry its trace/span IDs. */
const logger = {
  debug: (m, a) => emit(SeverityNumber.DEBUG, 'debug', m, a),
  info: (m, a) => emit(SeverityNumber.INFO, 'info', m, a),
  warn: (m, a) => emit(SeverityNumber.WARN, 'warn', m, a),
  error: (m, a) => emit(SeverityNumber.ERROR, 'error', m, a),
};

/** Record an exception on the active span (marking it failed) and emit an error log with the stack. */
function captureException(err, attributes = {}) {
  const e = err instanceof Error ? err : new Error(String(err));
  const span = api.trace.getActiveSpan();
  if (span) {
    span.recordException(e);
    span.setStatus({ code: api.SpanStatusCode.ERROR, message: e.message });
  }
  emit(SeverityNumber.ERROR, 'error', e.stack || e.message, { 'exception.type': e.name, ...attributes });
}

/** Express error-handling middleware. Register AFTER your routes: app.use(incident.expressErrorHandler()) */
function expressErrorHandler() {
  // eslint-disable-next-line no-unused-vars
  return function incidentErrorHandler(err, req, res, next) {
    captureException(err, { 'http.route': req.route && req.route.path, 'http.method': req.method });
    next(err);
  };
}

function captureConsole() {
  for (const [method, fn] of [['warn', logger.warn], ['error', logger.error]]) {
    const original = console[method].bind(console);
    console[method] = (...args) => {
      original(...args);
      try { fn(args.map((a) => (typeof a === 'string' ? a : JSON.stringify(a))).join(' ')); } catch { /* ignore */ }
    };
  }
}

/** Flush and stop. Safe to call more than once. */
async function shutdown() {
  if (!state.started) return;
  const { sdk, stopRuntime } = state;
  state = { sdk: null, cfg: null, stopRuntime: null, started: false };
  try { stopRuntime && stopRuntime(); await sdk.shutdown(); } catch { /* ignore */ }
}

module.exports = { init, registerDeployment, shutdown, logger, captureException, expressErrorHandler, resolveConfig };
