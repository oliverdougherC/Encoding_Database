import test from 'node:test';
import assert from 'node:assert/strict';
import https from 'node:https';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createFaultProxy, validateTarget } from './candidate-upload-fault-proxy.mjs';

const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'encodingdb-fault-proxy-'));
execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', `${temp}/key.pem`, '-out', `${temp}/cert.pem`, '-days', '1', '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1'], { stdio: 'ignore' });
const cert = fs.readFileSync(`${temp}/cert.pem`), key = fs.readFileSync(`${temp}/key.pem`);
const listen = (server) => new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));
const close = (server) => new Promise((resolve) => { server.close(resolve); server.closeAllConnections(); });
function send(port, pathname, body, method = 'PUT') {
  return new Promise((resolve, reject) => {
    const request = https.request({ hostname: '127.0.0.1', port, path: pathname, method, ca: cert,
      headers: { 'content-length': body.length, authorization: 'never-log-this-secret' } }, (response) => {
      const chunks = [];
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('error', reject);
      response.on('end', () => resolve({ status: response.statusCode, body: Buffer.concat(chunks).toString(), retryAfter: response.headers['retry-after'] }));
    });
    request.on('error', reject); request.end(body);
  });
}

test('only explicit loopback TLS targets are allowed', () => {
  for (const value of ['http://127.0.0.1:3094', 'https://encodingdb.example', 'https://user:secret@127.0.0.1', 'https://127.0.0.1/path']) assert.throws(() => validateTarget(value));
  assert.equal(validateTarget('https://127.0.0.1:3094').port, '3094');
});

test('real TLS streaming, injected retry responses, and one lost committed response', async () => {
  let upstreamRequests = 0;
  const upstream = https.createServer({ cert, key }, async (request, response) => {
    let bytes = 0; for await (const chunk of request) bytes += chunk.length;
    upstreamRequests++; response.writeHead(201).end(JSON.stringify({ bytes }));
  });
  const upstreamPort = await listen(upstream);
  const records = []; let mode = 'pass';
  const proxy = createFaultProxy({ upstream: `https://127.0.0.1:${upstreamPort}`, ca: cert, cert, key, mode: () => mode, record: (entry) => records.push(entry) });
  const port = await listen(proxy);
  try {
    const body = Buffer.alloc(2 * 1024 * 1024, 7);
    const successful = await send(port, '/v7/artifact-uploads/sensitive-token', body);
    assert.equal(JSON.parse(successful.body).bytes, body.length);
    mode = 'offline';
    assert.equal((await send(port, '/v7/benchmark-runs', Buffer.from('{}'), 'POST')).status, 503);
    mode = 'pressure';
    const pressure = await send(port, '/v7/benchmark-runs/id/artifacts/ENCODED/upload-authorizations', Buffer.from('{}'), 'POST');
    assert.equal(pressure.status, 429); assert.equal(pressure.retryAfter, '2');
    assert.equal(upstreamRequests, 1);
    assert.equal((await send(port, '/health/ready', Buffer.alloc(0), 'GET')).status, 201);
    mode = 'lost-response-once';
    await assert.rejects(send(port, '/v7/artifact-uploads/sensitive-token', body));
    assert.equal(upstreamRequests, 3); // Server consumed the upload before its response disappeared.
    assert.equal((await send(port, '/v7/artifact-uploads/sensitive-token', body)).status, 201);
    assert.equal(records.filter((r) => r.kind === 'lost-response-after-upstream-success').length, 1);
    assert.ok(records.some((r) => r.requestBytes === body.length));
    assert.ok(!JSON.stringify(records).includes('sensitive-token'));
    assert.ok(!JSON.stringify(records).includes('never-log-this-secret'));
  } finally { await close(proxy); await close(upstream); }
});

test('body and wall-clock budgets terminate owned proxy work', async () => {
  const upstream = https.createServer({ cert, key }, (request) => request.resume());
  const upstreamPort = await listen(upstream); const records = [];
  const proxy = createFaultProxy({ upstream: `https://127.0.0.1:${upstreamPort}`, ca: cert, cert, key,
    mode: () => 'pass', record: (entry) => records.push(entry), maxBytes: 64, timeoutMs: 200 });
  const port = await listen(proxy);
  try {
    await assert.rejects(send(port, '/v7/artifact-uploads/private', Buffer.alloc(8192)));
    await assert.rejects(send(port, '/stall', Buffer.alloc(0), 'GET'));
    assert.ok(records.some((r) => r.kind === 'proxy-body-limit'));
    assert.ok(records.some((r) => r.kind === 'proxy-deadline'));
  } finally { await close(proxy); await close(upstream); }
});

test('TLS verification rejects an untrusted upstream certificate', async () => {
  const upstream = https.createServer({ cert, key }, (_request, response) => response.end('unexpected'));
  const upstreamPort = await listen(upstream); const records = [];
  const proxy = createFaultProxy({ upstream: `https://127.0.0.1:${upstreamPort}`, cert, key,
    mode: () => 'pass', record: (entry) => records.push(entry) });
  const port = await listen(proxy);
  try {
    assert.equal((await send(port, '/health/ready', Buffer.alloc(0), 'GET')).status, 502);
    assert.ok(records.some((r) => r.kind === 'upstream-connection-failure' && r.injected === false));
  } finally { await close(proxy); await close(upstream); }
});

test('active concurrency and streamed response sizes remain bounded', async () => {
  let entered;
  const stalled = new Promise((resolve) => { entered = resolve; });
  const upstream = https.createServer({ cert, key }, (request, response) => {
    request.resume();
    if (request.url === '/large-response') response.end(Buffer.alloc(4096));
    else entered();
  });
  const upstreamPort = await listen(upstream); const records = [];
  const proxy = createFaultProxy({ upstream: `https://127.0.0.1:${upstreamPort}`, ca: cert, cert, key,
    mode: () => 'pass', record: (entry) => records.push(entry), maxActive: 1, maxResponseBytes: 64, timeoutMs: 500 });
  const port = await listen(proxy);
  try {
    const first = assert.rejects(send(port, '/stall', Buffer.alloc(0), 'GET'));
    await stalled;
    const busy = await send(port, '/busy', Buffer.alloc(0), 'GET');
    assert.equal(busy.status, 503); assert.equal(busy.retryAfter, '1');
    await first;
    await assert.rejects(send(port, '/large-response', Buffer.alloc(0), 'GET'));
    assert.ok(records.some((r) => r.kind === 'proxy-capacity-limit'));
    assert.ok(records.some((r) => r.kind === 'proxy-response-limit'));
  } finally { await close(proxy); await close(upstream); }
});

test('a rejected upload does not consume the once-only successful-response fault', async () => {
  let status = 503;
  const upstream = https.createServer({ cert, key }, (request, response) => {
    request.resume(); request.on('end', () => response.writeHead(status).end());
  });
  const upstreamPort = await listen(upstream); const records = [];
  const proxy = createFaultProxy({ upstream: `https://127.0.0.1:${upstreamPort}`, ca: cert, cert, key,
    mode: () => 'lost-response-once', record: (entry) => records.push(entry) });
  const port = await listen(proxy);
  try {
    assert.equal((await send(port, '/v7/artifact-uploads/private', Buffer.from('bytes'))).status, 503);
    status = 201;
    await assert.rejects(send(port, '/v7/artifact-uploads/private', Buffer.from('bytes')));
    assert.equal((await send(port, '/v7/artifact-uploads/private', Buffer.from('bytes'))).status, 201);
    assert.equal(records.filter((r) => r.kind === 'lost-response-after-upstream-success').length, 1);
  } finally { await close(proxy); await close(upstream); }
});

test.after(() => fs.rmSync(temp, { recursive: true, force: true }));
