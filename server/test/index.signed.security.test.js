import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import net from 'node:net';

process.env.DATABASE_URL ||= 'postgresql://app:app@localhost:5432/benchmarks?schema=public';
process.env.INGEST_MODE = 'signed';
process.env.INGEST_HMAC_SECRET = 'test-signed-secret';
process.env.SKIP_SERVER_START = '1';

const { app } = await import('../dist/index.js');
const CAN_BIND_LOOPBACK = await new Promise((resolve) => {
  const probe = net.createServer();
  probe.once('error', () => resolve(false));
  probe.listen(0, '127.0.0.1', () => probe.close(() => resolve(true)));
});

test('signed mode rejects tokens and accepts only a valid HMAC', async (t) => {
  if (!CAN_BIND_LOOPBACK) return t.skip('Loopback listen is unavailable in this runtime');
  const server = await new Promise((resolve) => {
    const instance = app.listen(0, '127.0.0.1', () => resolve(instance));
  });
  const address = server.address();
  const baseUrl = `http://127.0.0.1:${address.port}`;
  try {
    const tokenResponse = await fetch(`${baseUrl}/submit-token`);
    const { token } = await tokenResponse.json();
    const tokenOnly = await fetch(`${baseUrl}/submit`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-ingest-token': token },
      body: '{}',
    });
    assert.equal(tokenOnly.status, 401);

    const timestamp = String(Math.floor(Date.now() / 1000));
    const signature = crypto.createHmac('sha256', process.env.INGEST_HMAC_SECRET)
      .update(`${timestamp}.`).update('{}').digest('hex');
    const signed = await fetch(`${baseUrl}/submit`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-timestamp': timestamp, 'x-signature': signature },
      body: '{}',
    });
    assert.equal(signed.status, 400);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
