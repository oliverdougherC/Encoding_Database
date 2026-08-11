import test from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';

process.env.DATABASE_URL ||= 'postgresql://app:app@localhost:5432/benchmarks?schema=public';
process.env.INGEST_MODE = 'public';
process.env.SKIP_SERVER_START = '1';
process.env.RATE_LIMIT_MAX = '100';
process.env.SUBMIT_TOKEN_RATE_MAX = '2';
process.env.SUBMIT_RATE_MAX = '2';

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

test('all token aliases share an IP-only issuance ceiling', async (t) => {
  if (!CAN_BIND_LOOPBACK) return t.skip('Loopback listen is unavailable in this runtime');
  await withServer(async (baseUrl) => {
    const paths = ['/submit-token', '/submit/token', '/health/token'];
    const statuses = [];
    for (let index = 0; index < paths.length; index += 1) {
      const response = await fetch(`${baseUrl}${paths[index]}`, {
        headers: { 'user-agent': `rotating-agent-${index}` },
      });
      statuses.push(response.status);
    }
    assert.deepEqual(statuses, [200, 200, 429]);
  });
});

test('rotating User-Agent does not bypass submit ceiling', async (t) => {
  if (!CAN_BIND_LOOPBACK) return t.skip('Loopback listen is unavailable in this runtime');
  await withServer(async (baseUrl) => {
    const statuses = [];
    for (let index = 0; index < 3; index += 1) {
      const response = await fetch(`${baseUrl}/submit`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'user-agent': `rotating-agent-${index}`,
        },
        body: '{}',
      });
      statuses.push(response.status);
    }
    assert.deepEqual(statuses, [400, 400, 429]);
  });
});
