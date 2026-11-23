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
