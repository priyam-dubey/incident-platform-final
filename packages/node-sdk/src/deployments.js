'use strict';
const { ENV_ALIASES } = require('./config');

/**
 * Register a deployment (commit SHA, version) with the platform so incidents can list it as a
 * *possible* cause. Never throws: returns { ok, status?, error? }. Works from a CI step without init().
 * Gateway URL: options.apiUrl || INCIDENT_PLATFORM_API_URL || the ingestion endpoint.
 */
async function registerDeployment(options = {}, env = process.env, fetchImpl = globalThis.fetch) {
  const key = options.key ?? env[ENV_ALIASES.key];
  const base = (options.apiUrl ?? env.INCIDENT_PLATFORM_API_URL ?? options.endpoint ?? env[ENV_ALIASES.endpoint] ?? '').replace(/\/+$/, '');
  if (!key || !/^ipk_[0-9a-f]{10}_.+/.test(key)) return { ok: false, error: 'ingestion key missing or invalid' };
  if (!/^https?:\/\//.test(base)) return { ok: false, error: 'api url missing (INCIDENT_PLATFORM_API_URL)' };
  if (typeof fetchImpl !== 'function') return { ok: false, error: 'fetch is not available (Node >= 18 required)' };
  const body = {};
  const version = options.version ?? options.release ?? env[ENV_ALIASES.release];
  const commit = options.commitSha ?? env[ENV_ALIASES.commitSha];
  const environment = options.environment ?? env[ENV_ALIASES.environment];
  if (version) body.version = String(version);
  if (commit) body.commit_sha = String(commit);
  if (options.branch) body.branch = options.branch;
  if (options.repository) body.repository = options.repository;
  if (options.deployedBy) body.deployed_by = options.deployedBy;
  if (options.deployedAt) body.deployed_at = new Date(options.deployedAt).toISOString();
  if (environment) body.environment = environment;
  if (options.metadata) body.metadata = options.metadata;
  try {
    const res = await fetchImpl(`${base}/v1/deployments`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'X-Ingestion-Key': key },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(options.timeoutMs ?? 10000),
    });
    if (!res.ok) return { ok: false, status: res.status, error: `platform responded ${res.status}` };
    const data = await res.json().catch(() => ({}));
    return { ok: true, status: res.status, id: data.id };
  } catch (e) {
    return { ok: false, error: `request failed: ${e && e.name === 'TimeoutError' ? 'timeout' : 'network error'}` };
  }
}
module.exports = { registerDeployment };
