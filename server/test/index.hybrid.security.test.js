import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import net from 'node:net';
import { spawnSync } from 'node:child_process';

process.env.DATABASE_URL ||= 'postgresql://app:app@localhost:5432/benchmarks?schema=public';
process.env.INGEST_MODE = 'hybrid';
process.env.INGEST_HMAC_SECRET = 'test-hybrid-secret';
process.env.SKIP_SERVER_START = '1';

const { app } = await import('../dist/index.js');
const CAN_BIND_LOOPBACK = await new Promise((resolve) => {
  const probe = net.createServer();
  probe.once('error', () => resolve(false));
  probe.listen(0, '127.0.0.1', () => probe.close(() => resolve(true)));
});

async function withServer(run) {
  const server = await new Promise((resolve) => {
    const instance = app.listen(0, '127.0.0.1', () => resolve(instance));
  });
  const address = server.address();
  try {
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test('hybrid rejects unsigned requests and accepts token or HMAC authentication', async (t) => {
  if (!CAN_BIND_LOOPBACK) return t.skip('Loopback listen is unavailable in this runtime');
  await withServer(async (baseUrl) => {
    const unsigned = await fetch(`${baseUrl}/submit`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}',
    });
    assert.equal(unsigned.status, 401);

    const tokenResponse = await fetch(`${baseUrl}/submit-token`);
    const { token } = await tokenResponse.json();
    const tokenAuthed = await fetch(`${baseUrl}/submit`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-ingest-token': token },
      body: '{}',
    });
    assert.equal(tokenAuthed.status, 400);

    const timestamp = String(Math.floor(Date.now() / 1000));
    const signature = crypto.createHmac('sha256', process.env.INGEST_HMAC_SECRET)
      .update(`${timestamp}.`).update('{}').digest('hex');
    const hmacAuthed = await fetch(`${baseUrl}/submit`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-timestamp': timestamp, 'x-signature': signature },
      body: '{}',
    });
    assert.equal(hmacAuthed.status, 400);
  });
});

test('invalid INGEST_MODE fails module startup', () => {
  const result = spawnSync(process.execPath, [
    '--input-type=module',
    '--eval',
    "import('./dist/index.js')",
  ], {
    cwd: new URL('..', import.meta.url),
    encoding: 'utf8',
    env: { ...process.env, INGEST_MODE: 'singed', SKIP_SERVER_START: '1' },
  });
  assert.notEqual(result.status, 0);
  assert.match(`${result.stdout}\n${result.stderr}`, /Invalid INGEST_MODE/);
});
