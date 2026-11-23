'use strict';
// Generates realistic request traffic against the sample app. Usage: node traffic.js [baseUrl] [rounds]
const base = process.argv[2] || 'http://127.0.0.1:4000';
const rounds = Number(process.argv[3] || 20);
const post = (path, body) => fetch(base + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });

(async () => {
  const tally = {};
  const note = (r) => { tally[r.status] = (tally[r.status] || 0) + 1; return r; };
  for (let i = 0; i < rounds; i++) {
    note(await fetch(base + '/api/foods'));
    note(await post('/api/login', { email: `user${i}@example.com`, password: i % 5 === 0 ? 'wrong' : 'test-password' }));
    note(await post('/api/cart', { foodId: 1 + (i % 3), qty: 2 }));
    note(await post('/api/orders', {}));
  }
  console.log(JSON.stringify({ rounds, statuses: tally }));
})();
