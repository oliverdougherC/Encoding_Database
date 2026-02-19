import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import express from 'express';
import routes, { buildSubmissionPayloadHash, DEFAULT_QUERY_LIMIT, TEST_VIDEO_CATALOG, normalizeCpuFreqMHz } from '../dist/routes.js';
import { prisma } from '../dist/db.js';

process.env.DATABASE_URL ||= 'postgresql://app:app@localhost:5432/benchmarks?schema=public';

const CAN_BIND_LOOPBACK = await new Promise((resolve) => {
  const probe = net.createServer();
  probe.once('error', () => resolve(false));
  probe.listen(0, '127.0.0.1', () => {
    probe.close(() => resolve(true));
  });
});

async function startTestServer() {
  const app = express();
  app.use(express.json({ limit: '1mb' }));
  app.use(routes);
  const server = await new Promise((resolve) => {
    const s = app.listen(0, '127.0.0.1', () => resolve(s));
  });
  const addr = server.address();
  if (!addr || typeof addr === 'string') {
    server.close();
    throw new Error('Unexpected server address');
  }
  const baseUrl = `http://127.0.0.1:${addr.port}`;
  return { server, baseUrl };
}

after(async () => {
  // Ensure Prisma doesn't keep the event loop alive in unit tests
  await prisma.$disconnect().catch(() => {});
});

test('GET /test-videos returns a catalog with downloadUrl', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }
  const { server, baseUrl } = await startTestServer();
  try {
    const res = await fetch(`${baseUrl}/test-videos`);
    assert.equal(res.status, 200);
    const data = await res.json();
    assert.ok(Array.isArray(data));
    assert.ok(data.length >= 1);

    const sample = data.find((v) => v && v.name === 'sample.mp4');
    assert.ok(sample, 'sample.mp4 should exist in catalog');
    assert.equal(
      sample.sha256,
      '53a87df054e65d284bc808b8f73e62e938b815cb6aeec8379f904ad6d792aab8',
    );
    assert.equal(
      sample.downloadUrl,
      'https://github.com/oliverdougherC/Encoding_Database/releases/download/test-clips-v1/sample.mp4',
    );
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('Method guard: GET /submit is 405 with Allow=POST', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }
  const { server, baseUrl } = await startTestServer();
  try {
    const res = await fetch(`${baseUrl}/submit`, { method: 'GET' });
    assert.equal(res.status, 405);
    assert.equal(res.headers.get('allow'), 'POST');
    const body = await res.json();
    assert.equal(body.error, 'Method Not Allowed');
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('Method guard: POST /query is 405 with Allow=GET, HEAD', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }
  const { server, baseUrl } = await startTestServer();
  try {
    const res = await fetch(`${baseUrl}/query`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({}),
    });
    assert.equal(res.status, 405);
    assert.equal(res.headers.get('allow'), 'GET, HEAD');
    const body = await res.json();
    assert.equal(body.error, 'Method Not Allowed');
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('POST /submit rejects invalid payloads with 400', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }
  const { server, baseUrl } = await startTestServer();
  try {
    const res = await fetch(`${baseUrl}/submit`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({}),
    });
    assert.equal(res.status, 400);
    const body = await res.json();
    assert.equal(body.error, 'Invalid payload');
    assert.ok(body.details, 'Expected Zod error details');
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('POST /submit rejects non-single-pass payloads', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }
  const { server, baseUrl } = await startTestServer();
  try {
    const res = await fetch(`${baseUrl}/submit`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        cpuModel: 'Intel Core i7-14700K',
        ramGB: 32,
        os: 'Windows 11',
        codec: 'libx264',
        preset: 'fast',
        passes: 2,
        fps: 120.5,
        fileSizeBytes: 123_456_789,
      }),
    });
    assert.equal(res.status, 400);
    const body = await res.json();
    assert.equal(body.error, 'Invalid payload');
    assert.ok(body.details?.fieldErrors?.passes, 'Expected passes field validation error');
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('buildSubmissionPayloadHash changes when telemetry changes', () => {
  const base = {
    cpuModel: 'Intel Core i7-14700K',
    gpuModel: 'NVIDIA RTX 4070',
    ramGB: 32,
    os: 'Windows 11',
    codec: 'libx264',
    preset: 'fast',
    crf: 24,
    contentClass: 'mixed',
    resolution: '1080p',
    passes: 1,
    fps: 120.5,
    vmaf: 95.3,
    ssim: 0.98,
    psnr: 41.2,
    fileSizeBytes: 123_456_789,
    notes: null,
    ffmpegVersion: 'n7.0.2',
    encoderName: 'libx264',
    clientVersion: '1.0.0',
    inputHash: '53a87df054e65d284bc808b8f73e62e938b815cb6aeec8379f904ad6d792aab8',
    runMs: 123456,
    gpuUtilAvg: 67.2,
    gpuPowerAvgW: 210.4,
    gpuMemPeakMB: 1820,
    cpuUtilAvg: 82.4,
    cpuUtilMax: 96.2,
    peakMemoryMB: 2430,
    thermalThrottle: false,
    gpuTempMaxC: 74.1,
    cpuFreqAvgMHz: 4850,
    cpuTempMaxC: 87.3,
    ffmpegCpuUtilAvg: 330.0,
    ffmpegCpuUtilMax: 760.0,
    ffmpegReadMB: 602.3,
    ffmpegWriteMB: 401.7,
    ffmpegCpuTimeS: 74.5,
    batteryPercentStart: null,
    batteryPercentEnd: null,
    batteryPercentDrop: null,
    powerSource: 'ac',
    sampleCount: 320,
    monitorDurationMs: 125000,
  };
  const variant = { ...base, cpuUtilMax: 99.1 };
  const h1 = buildSubmissionPayloadHash(base);
  const h2 = buildSubmissionPayloadHash(variant);
  assert.notEqual(h1, h2);
});

test('buildSubmissionPayloadHash changes when content dimensions change', () => {
  const base = {
    cpuModel: 'Intel Core i7-14700K',
    gpuModel: 'NVIDIA RTX 4070',
    ramGB: 32,
    os: 'Windows 11',
    codec: 'libx264',
    preset: 'fast',
    crf: 24,
    contentClass: 'mixed',
    resolution: '1080p',
    passes: 1,
    fps: 120.5,
    vmaf: 95.3,
    ssim: 0.98,
    psnr: 41.2,
    fileSizeBytes: 123_456_789,
  };
  const variant = { ...base, contentClass: 'action', resolution: '720p' };
  const h1 = buildSubmissionPayloadHash(base);
  const h2 = buildSubmissionPayloadHash(variant);
  assert.notEqual(h1, h2);
});

test('DEFAULT_QUERY_LIMIT is sane', () => {
  assert.ok(Number.isInteger(DEFAULT_QUERY_LIMIT));
  assert.ok(DEFAULT_QUERY_LIMIT >= 1);
  assert.ok(DEFAULT_QUERY_LIMIT <= 500);
});

test('TEST_VIDEO_CATALOG has no placeholders', () => {
  assert.ok(TEST_VIDEO_CATALOG.length >= 1);
  for (const row of TEST_VIDEO_CATALOG) {
    assert.ok(typeof row.sha256 === 'string' && !row.sha256.startsWith('placeholder_'));
    assert.ok(Number(row.sizeBytes) > 0);
  }
});

test('normalizeCpuFreqMHz converts GHz-like values and drops invalid telemetry', () => {
  assert.equal(normalizeCpuFreqMHz(4), 4000);
  assert.equal(normalizeCpuFreqMHz(4050), 4050);
  assert.equal(normalizeCpuFreqMHz(4_050_000), 4050);
  assert.equal(normalizeCpuFreqMHz(0), null);
  assert.equal(normalizeCpuFreqMHz(-1), null);
  assert.equal(normalizeCpuFreqMHz('not-a-number'), null);
});
