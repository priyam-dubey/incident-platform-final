'use strict';

// Defence in depth: the platform also redacts server-side, but secrets should not leave the process.
const SENSITIVE = ['authorization', 'cookie', 'password', 'passwd', 'secret', 'token', 'api_key', 'apikey',
  'x-api-key', 'private_key', 'credit', 'card', 'cvv', 'ssn'];
const URL_KEYS = new Set(['http.url', 'url.full', 'http.target', 'url.query', 'http.route_raw']);

function isSensitiveKey(key, extra = []) {
  const k = String(key).toLowerCase();
  return SENSITIVE.some((s) => k.includes(s)) || extra.some((s) => k.includes(String(s).toLowerCase()));
}

/** Remove query strings: they routinely carry tokens, emails and ids. */
function stripQuery(value) {
  if (typeof value !== 'string') return value;
  const i = value.indexOf('?');
  return i === -1 ? value : value.slice(0, i) + '?[REDACTED]';
}

function sanitizeAttributes(attrs, extra = []) {
  if (!attrs) return attrs;
  const out = {};
  for (const [k, v] of Object.entries(attrs)) {
    if (isSensitiveKey(k, extra)) out[k] = '[REDACTED:KEY]';
    else if (URL_KEYS.has(k)) out[k] = k === 'url.query' ? '[REDACTED]' : stripQuery(v);
    else out[k] = v;
  }
  return out;
}

module.exports = { isSensitiveKey, stripQuery, sanitizeAttributes };
