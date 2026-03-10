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
