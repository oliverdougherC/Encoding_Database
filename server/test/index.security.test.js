import test from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';

process.env.DATABASE_URL ||= 'postgresql://app:app@localhost:5432/benchmarks?schema=public';
process.env.INGEST_MODE ||= 'public';
process.env.SKIP_SERVER_START = '1';

const { app } = await import('../dist/index.js');

const CAN_BIND_LOOPBACK = await new Promise((resolve) => {
  const probe = net.createServer();
  probe.once('error', () => resolve(false));
  probe.listen(0, '127.0.0.1', () => {
    probe.close(() => resolve(true));
  });
});

async function startServer() {
  const server = await new Promise((resolve) => {
    const s = app.listen(0, '127.0.0.1', () => resolve(s));
  });
  const addr = server.address();
  if (!addr || typeof addr === 'string') {
    server.close();
    throw new Error('Unexpected server address');
  }
  return { server, baseUrl: `http://127.0.0.1:${addr.port}` };
}

test('GET /submit with token header remains method-guarded (auth applies to POST only)', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }

  const { server, baseUrl } = await startServer();
  try {
    const res = await fetch(`${baseUrl}/submit`, {
      method: 'GET',
      headers: { 'x-ingest-token': 'definitely-invalid-token' },
    });
    assert.equal(res.status, 405);
    assert.equal(res.headers.get('allow'), 'POST');
    const body = await res.json();
    assert.equal(body.error, 'Method Not Allowed');
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('public mode permits unsigned POSTs to reach payload validation', async (t) => {
  if (!CAN_BIND_LOOPBACK) return t.skip('Loopback listen is unavailable in this runtime');
  const { server, baseUrl } = await startServer();
  try {
    const res = await fetch(`${baseUrl}/submit`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{}',
    });
    assert.equal(res.status, 400);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('token is released after validation failure and can be retried', async (t) => {
  if (!CAN_BIND_LOOPBACK) return t.skip('Loopback listen is unavailable in this runtime');
  const { server, baseUrl } = await startServer();
  try {
    const tokenRes = await fetch(`${baseUrl}/submit-token`);
    assert.equal(tokenRes.status, 200);
    const { token } = await tokenRes.json();
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const res = await fetch(`${baseUrl}/submit`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-ingest-token': token },
        body: '{}',
      });
      assert.equal(res.status, 400);
      const body = await res.json();
      assert.notEqual(body.error, 'token_used');
    }
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
