'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { resolveConfig } = require('../src/config');
const { sanitizeAttributes, isSensitiveKey, stripQuery } = require('../src/sanitize');
const sdk = require('../src');

const GOOD_KEY = 'ipk_0123456789_abcdefghijklmnopqrstuv';

test('config: valid options resolve and trailing slash is trimmed', () => {
  const { ok, cfg } = resolveConfig({ endpoint: 'https://ing.example.com/', key: GOOD_KEY, serviceName: 'shop' }, {});
  assert.equal(ok, true);
  assert.equal(cfg.endpoint, 'https://ing.example.com');
  assert.equal(cfg.environment, 'production');
});

test('config: env vars are used and explicit options win', () => {
  const env = { INCIDENT_PLATFORM_ENDPOINT: 'http://a', INCIDENT_PLATFORM_KEY: GOOD_KEY, INCIDENT_PLATFORM_APP: 'fromenv', INCIDENT_PLATFORM_ENV: 'staging' };
  const { cfg } = resolveConfig({ serviceName: 'explicit' }, env);
  assert.equal(cfg.serviceName, 'explicit');
  assert.equal(cfg.environment, 'staging');
});

test('config: reports every problem instead of throwing', () => {
  const { ok, problems } = resolveConfig({ endpoint: 'ftp://x', key: 'nope' }, {});
  assert.equal(ok, false);
  assert.ok(problems.length >= 3);
});

test('config: rejects too-small metric interval', () => {
  const { ok } = resolveConfig({ endpoint: 'http://a', key: GOOD_KEY, serviceName: 's', metricIntervalMs: 10 }, {});
  assert.equal(ok, false);
});

test('init: invalid config disables telemetry and never throws', () => {
  const r = sdk.init({});
  assert.equal(r.started, false);
  assert.ok(r.problems.length > 0);
});

test('sanitize: sensitive keys redacted, urls lose query strings', () => {
  const out = sanitizeAttributes({
    authorization: 'Bearer x', 'http.request.header.cookie': 'a=b', password: 'p', 'http.route': '/api/foods',
    'http.url': 'http://x/api?token=abc&email=a@b.com', 'url.query': 'token=abc',
  });
  assert.equal(out.authorization, '[REDACTED:KEY]');
  assert.equal(out['http.request.header.cookie'], '[REDACTED:KEY]');
  assert.equal(out.password, '[REDACTED:KEY]');
  assert.equal(out['http.route'], '/api/foods');
  assert.equal(out['http.url'], 'http://x/api?[REDACTED]');
  assert.equal(out['url.query'], '[REDACTED]');
});

test('sanitize: extra sensitive keys are honoured; helpers behave', () => {
  assert.equal(isSensitiveKey('order.aadhaar', ['aadhaar']), true);
  assert.equal(isSensitiveKey('http.route'), false);
  assert.equal(stripQuery('/a?b=c'), '/a?[REDACTED]');
  assert.equal(stripQuery('/a'), '/a');
});

test('captureException/logger are safe no-ops before init', () => {
  assert.doesNotThrow(() => sdk.captureException(new Error('x')));
  assert.doesNotThrow(() => sdk.logger.error('x', { a: 1 }));
});

test('expressErrorHandler forwards the error to next()', () => {
  const err = new Error('boom');
  let forwarded;
  sdk.expressErrorHandler()(err, { method: 'GET', route: { path: '/x' } }, {}, (e) => { forwarded = e; });
  assert.equal(forwarded, err);
});

const { registerDeployment } = require('../src/deployments');
const mkFetch = (status, json = { id: 'dep-1' }, seen = {}) => async (url, init) => { seen.url = url; seen.init = init; return { ok: status < 300, status, json: async () => json }; };

test('registerDeployment: posts commit/version with the ingestion key', async () => {
  const seen = {};
  const r = await registerDeployment({ apiUrl: 'https://api.example.com/', key: GOOD_KEY, repository: 'o/r' },
    { INCIDENT_PLATFORM_COMMIT: 'abc1234', INCIDENT_PLATFORM_RELEASE: '1.2.3' }, mkFetch(201, { id: 'dep-1' }, seen));
  assert.deepEqual(r, { ok: true, status: 201, id: 'dep-1' });
  assert.equal(seen.url, 'https://api.example.com/v1/deployments');
  assert.equal(seen.init.headers['X-Ingestion-Key'], GOOD_KEY);
  assert.deepEqual(JSON.parse(seen.init.body), { version: '1.2.3', commit_sha: 'abc1234', repository: 'o/r' });
});

test('registerDeployment: never throws and never echoes the key', async () => {
  assert.equal((await registerDeployment({}, {}, mkFetch(201))).ok, false);
  assert.equal((await registerDeployment({ key: GOOD_KEY, apiUrl: 'ftp://x' }, {}, mkFetch(201))).ok, false);
  const r401 = await registerDeployment({ key: GOOD_KEY, apiUrl: 'http://a' }, {}, mkFetch(401));
  assert.deepEqual(r401, { ok: false, status: 401, error: 'platform responded 401' });
  const boom = await registerDeployment({ key: GOOD_KEY, apiUrl: 'http://a' }, {}, async () => { throw new Error('connect ECONNREFUSED ' + GOOD_KEY); });
  assert.equal(boom.ok, false);
  assert.ok(!JSON.stringify(boom).includes(GOOD_KEY));
});

test('registerDeployment: falls back to the ingestion endpoint and is exported', async () => {
  const seen = {};
  await registerDeployment({}, { INCIDENT_PLATFORM_KEY: GOOD_KEY, INCIDENT_PLATFORM_ENDPOINT: 'http://ing:8001' }, mkFetch(201, {}, seen));
  assert.equal(seen.url, 'http://ing:8001/v1/deployments');
  assert.equal(typeof sdk.registerDeployment, 'function');
});
