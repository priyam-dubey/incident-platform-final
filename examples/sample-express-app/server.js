'use strict';
// IMPORTANT: init() must run before express is required so it can be instrumented.
const incident = require('@incident-platform/node');
incident.init({ captureConsole: true });

const express = require('express');
const app = express();
app.use(express.json({ limit: '10kb' }));

// ---- in-memory data (stands in for MongoDB) ----
const foods = [{ id: 1, name: 'Paneer Tikka', price: 220 }, { id: 2, name: 'Masala Dosa', price: 140 }, { id: 3, name: 'Biryani', price: 260 }];
const carts = new Map();
const orders = [];

// ---- fault injection (SAFE TEST ONLY; disabled unless FAULT_INJECTION=1) ----
let fault = 'none'; // none | errors | slow | db
const FAULTS_ENABLED = process.env.FAULT_INJECTION === '1';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

app.get('/healthz', (req, res) => res.json({ ok: true }));
app.get('/api/foods', (req, res) => res.json(foods));

app.post('/api/login', (req, res) => {
  const { email, password } = req.body || {};
  if (!email || !password) return res.status(400).json({ error: 'email and password required' });
  if (password !== 'test-password') {
    incident.logger.warn('login failed', { 'user.email_domain': String(email).split('@')[1] || 'unknown' });
    return res.status(401).json({ error: 'invalid credentials' });
  }
  res.json({ token: 'synthetic-session-token' });
});

app.post('/api/cart', (req, res) => {
  const { foodId, qty } = req.body || {};
  const food = foods.find((f) => f.id === foodId);
  if (!food) return res.status(404).json({ error: 'food not found' });
  const cart = carts.get('demo') || [];
  cart.push({ foodId, qty: Number(qty) || 1 });
  carts.set('demo', cart);
  res.status(201).json({ items: cart.length });
});

app.post('/api/orders', async (req, res, next) => {
  try {
    if (fault === 'errors') throw new Error('Order service failure: payment gateway returned 502');
    if (fault === 'db') {
      const e = new Error('MongoNetworkError: connection to db closed');
      e.name = 'MongoNetworkError';
      throw e;
    }
    if (fault === 'slow') await sleep(1200);
    const cart = carts.get('demo') || [];
    if (!cart.length) return res.status(400).json({ error: 'cart is empty' });
    const order = { id: orders.length + 1, items: cart };
    orders.push(order);
    carts.delete('demo');
    incident.logger.info('order placed', { 'order.id': order.id, 'order.items': cart.length });
    res.status(201).json(order);
  } catch (err) { next(err); }
});

app.post('/_fault', (req, res) => {
  if (!FAULTS_ENABLED) return res.status(404).end();
  const mode = (req.body || {}).mode;
  if (!['none', 'errors', 'slow', 'db'].includes(mode)) return res.status(400).json({ error: 'bad mode' });
  fault = mode;
  res.json({ fault });
});

app.use(incident.expressErrorHandler());
// eslint-disable-next-line no-unused-vars
app.use((err, req, res, next) => res.status(500).json({ error: 'internal error' }));

const port = Number(process.env.PORT || 4000);
const server = app.listen(port, () => console.log(`sample app on :${port} (synthetic test app)`));
process.on('SIGTERM', () => server.close());
