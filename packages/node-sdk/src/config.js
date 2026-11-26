'use strict';

const ENV_ALIASES = {
  endpoint: 'INCIDENT_PLATFORM_ENDPOINT',
  key: 'INCIDENT_PLATFORM_KEY',
  serviceName: 'INCIDENT_PLATFORM_APP',
  environment: 'INCIDENT_PLATFORM_ENV',
  release: 'INCIDENT_PLATFORM_RELEASE',
  commitSha: 'INCIDENT_PLATFORM_COMMIT',
};

/** Merge explicit options over env vars and validate. Never throws: returns {ok:false, problems}. */
function resolveConfig(options = {}, env = process.env) {
  const cfg = {};
  for (const [opt, envName] of Object.entries(ENV_ALIASES)) cfg[opt] = options[opt] ?? env[envName];
  cfg.metricIntervalMs = Number(options.metricIntervalMs ?? env.INCIDENT_PLATFORM_METRIC_INTERVAL_MS ?? 15000);
  cfg.captureConsole = options.captureConsole ?? false;
  cfg.debug = options.debug ?? env.INCIDENT_PLATFORM_DEBUG === '1';
  cfg.extraSensitiveKeys = options.extraSensitiveKeys ?? [];

  const problems = [];
  if (!cfg.endpoint) problems.push('endpoint is missing (INCIDENT_PLATFORM_ENDPOINT)');
  else if (!/^https?:\/\//.test(cfg.endpoint)) problems.push('endpoint must start with http:// or https://');
  if (!cfg.key) problems.push('ingestion key is missing (INCIDENT_PLATFORM_KEY)');
  else if (!/^ipk_[0-9a-f]{10}_.+/.test(cfg.key)) problems.push('ingestion key format is invalid (expected ipk_...)');
  if (!cfg.serviceName) problems.push('application name is missing (INCIDENT_PLATFORM_APP)');
  if (!Number.isFinite(cfg.metricIntervalMs) || cfg.metricIntervalMs < 1000) problems.push('metricIntervalMs must be >= 1000');
  if (cfg.endpoint) cfg.endpoint = cfg.endpoint.replace(/\/+$/, '');
  cfg.environment = cfg.environment || 'production';
  return { ok: problems.length === 0, problems, cfg };
}

module.exports = { resolveConfig, ENV_ALIASES };
