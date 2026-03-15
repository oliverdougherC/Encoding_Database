import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import express from 'express';
import routes, {
  buildSubmissionPayloadHash,
  DEFAULT_QUERY_LIMIT,
  TEST_VIDEO_CATALOG,
  getQueryCacheSize,
  normalizeCpuFreqMHz,
  parseTelemetryFromNotes,
  parseTelemetryMetaFromNotes,
  parseSkipParam,
  parseTakeParam,
  runSubmitTransactionWithRetry,
} from '../dist/routes.js';
import { prisma } from '../dist/db.js';
import {
  aggregateEncoders,
  aggregateHardware,
  aggregateLeaderboards,
  buildAnalyticsWhere,
  deriveCodecFamily,
  parseAnalyticsFilters,
  resolveEncoderName,
} from '../dist/analytics.js';
import { BoundedTtlCache } from '../dist/cache.js';

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
    cpuSampleCount: 310,
    gpuSampleCount: 295,
    ffmpegSampleCount: 320,
    batterySampleCount: 2,
    telemetrySources: 'cpu_psutil,gpu_nvml',
    telemetryMissing: 'battery_unavailable',
  };
  const variant = { ...base, cpuSampleCount: 311 };
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

test('parseTelemetryFromNotes reads new numeric coverage fields', () => {
  const parsed = parseTelemetryFromNotes(
    'telemetry={"cpuSampleCount":12,"gpuSampleCount":8,"ffmpegSampleCount":12,"batterySampleCount":2}; other=data',
  );
  assert.equal(parsed.cpuSampleCount, 12);
  assert.equal(parsed.gpuSampleCount, 8);
  assert.equal(parsed.ffmpegSampleCount, 12);
  assert.equal(parsed.batterySampleCount, 2);
});

test('parseTelemetryMetaFromNotes reads raw diagnostic strings', () => {
  const parsed = parseTelemetryMetaFromNotes(
    'telemetry_meta={"telemetrySources":"cpu_psutil,gpu_nvml","telemetryMissing":"battery_unavailable"}',
  );
  assert.equal(parsed.telemetrySources, 'cpu_psutil,gpu_nvml');
  assert.equal(parsed.telemetryMissing, 'battery_unavailable');
});

test('parseTakeParam normalizes invalid, float, and oversized values', () => {
  assert.equal(parseTakeParam(undefined), DEFAULT_QUERY_LIMIT);
  assert.equal(parseTakeParam(''), DEFAULT_QUERY_LIMIT);
  assert.equal(parseTakeParam('abc'), DEFAULT_QUERY_LIMIT);
  assert.equal(parseTakeParam('12.5'), DEFAULT_QUERY_LIMIT);
  assert.equal(parseTakeParam('-2'), DEFAULT_QUERY_LIMIT);
  assert.equal(parseTakeParam('0'), DEFAULT_QUERY_LIMIT);
  assert.equal(parseTakeParam('42'), 42);
  assert.equal(parseTakeParam('9999'), 500);
});

test('parseSkipParam accepts only positive integers', () => {
  assert.equal(parseSkipParam(undefined), undefined);
  assert.equal(parseSkipParam(''), undefined);
  assert.equal(parseSkipParam('abc'), undefined);
  assert.equal(parseSkipParam('3.14'), undefined);
  assert.equal(parseSkipParam('-4'), undefined);
  assert.equal(parseSkipParam('0'), undefined);
  assert.equal(parseSkipParam('7'), 7);
});

test('runSubmitTransactionWithRetry retries once for non-payload unique conflicts', async () => {
  let attempts = 0;
  const result = await runSubmitTransactionWithRetry(async () => {
    attempts += 1;
    if (attempts === 1) {
      const err = new Error('benchmark key unique conflict');
      err.code = 'P2002';
      err.meta = { target: ['cpuModel', 'gpuModel', 'ramGB'] };
      throw err;
    }
    return 'ok';
  });
  assert.equal(result, 'ok');
  assert.equal(attempts, 2);
});

test('runSubmitTransactionWithRetry does not retry payloadHash conflicts', async () => {
  let attempts = 0;
  await assert.rejects(async () => {
    await runSubmitTransactionWithRetry(async () => {
      attempts += 1;
      const err = new Error('payload hash conflict');
      err.code = 'P2002';
      err.meta = { target: ['payloadHash'] };
      throw err;
    });
  }, /payload hash conflict/);
  assert.equal(attempts, 1);
});

function makeBenchmarkRow(overrides = {}) {
  return {
    id: 'bench-1',
    createdAt: new Date('2026-01-01T00:00:00.000Z'),
    updatedAt: new Date('2026-01-01T00:00:00.000Z'),
    cpuModel: 'Intel Core i7-14700K',
    gpuModel: 'NVIDIA RTX 4070',
    ramGB: 32,
    os: 'Windows 11',
    codec: 'h264_nvenc',
    preset: 'p6',
    crf: 24,
    contentClass: 'mixed',
    resolution: '1080p',
    passes: 1,
    fps: 120,
    vmaf: 95,
    ssim: 0.98,
    psnr: 41,
    fileSizeBytes: 80_000_000,
    notes: null,
    gpuUtilAvg: null,
    gpuPowerAvgW: 200,
    gpuMemPeakMB: null,
    cpuUtilAvg: 78,
    cpuUtilMax: 88,
    peakMemoryMB: 1024,
    thermalThrottle: false,
    gpuTempMaxC: null,
    cpuFreqAvgMHz: null,
    cpuTempMaxC: null,
    ffmpegCpuUtilAvg: null,
    ffmpegCpuUtilMax: null,
    ffmpegReadMB: null,
    ffmpegWriteMB: null,
    ffmpegCpuTimeS: null,
    batteryPercentStart: null,
    batteryPercentEnd: null,
    batteryPercentDrop: null,
    powerSource: null,
    sampleCount: null,
    monitorDurationMs: null,
    cpuSampleCount: null,
    gpuSampleCount: null,
    ffmpegSampleCount: null,
    batterySampleCount: null,
    samples: 3,
    vmafSamples: 3,
    fpsSum: 360,
    fileSizeSum: 240_000_000,
    vmafSum: 285,
    ssimSamples: 3,
    ssimSum: 2.94,
    psnrSamples: 3,
    psnrSum: 123,
    gpuUtilSamples: 0,
    gpuUtilSum: 0,
    gpuPowerSamples: 3,
    gpuPowerSum: 600,
    cpuUtilSamples: 3,
    cpuUtilSum: 234,
    peakMemoryMax: 1024,
    cpuFreqSamples: 0,
    cpuFreqSum: 0,
    ffmpegCpuUtilSamples: 0,
    ffmpegCpuUtilSum: 0,
    ffmpegReadSamples: 0,
    ffmpegReadSum: 0,
    ffmpegWriteSamples: 0,
    ffmpegWriteSum: 0,
    ffmpegCpuTimeSamples: 0,
    ffmpegCpuTimeSum: 0,
    batteryStartSamples: 0,
    batteryStartSum: 0,
    batteryEndSamples: 0,
    batteryEndSum: 0,
    batteryDropSamples: 0,
    batteryDropSum: 0,
    sampleCountSamples: 0,
    sampleCountSum: 0,
    monitorDurationSamples: 0,
    monitorDurationSum: 0,
    cpuSampleCountSamples: 0,
    cpuSampleCountSum: 0,
    gpuSampleCountSamples: 0,
    gpuSampleCountSum: 0,
    ffmpegSampleCountSamples: 0,
    ffmpegSampleCountSum: 0,
    batterySampleCountSamples: 0,
    batterySampleCountSum: 0,
    status: 'accepted',
    ffmpegVersion: null,
    encoderName: 'h264_nvenc',
    clientVersion: null,
    inputHash: null,
    runMs: null,
    payloadHash: null,
    ...overrides,
  };
}

test('parseAnalyticsFilters defaults to the canonical comparison slice', () => {
  const filters = parseAnalyticsFilters({});
  assert.deepEqual(filters, {
    contentClass: 'mixed',
    resolution: '1080p',
    crf: 24,
    passes: 1,
    minSamples: 3,
  });
  assert.deepEqual(buildAnalyticsWhere(filters), {
    status: 'accepted',
    contentClass: 'mixed',
    resolution: '1080p',
    crf: 24,
    passes: 1,
  });
});

test('aggregateLeaderboards keeps distinct workload slices separate and enforces minSamples', () => {
  const rows = [
    makeBenchmarkRow({ id: 'a', resolution: '1080p', samples: 3, fpsSum: 300, fileSizeSum: 210_000_000, vmafSum: 282, vmafSamples: 3 }),
    makeBenchmarkRow({ id: 'b', resolution: '720p', samples: 4, fpsSum: 520, fileSizeSum: 260_000_000, vmafSum: 360, vmafSamples: 4 }),
    makeBenchmarkRow({ id: 'c', codec: 'libx264', encoderName: null, preset: 'fast', samples: 2, fpsSum: 200, fileSizeSum: 160_000_000, vmafSum: 188, vmafSamples: 2 }),
  ];

  const result = aggregateLeaderboards(rows, 3);
  assert.equal(result.length, 2);
  assert.equal(result[0].resolution, '720p');
  assert.equal(result[1].resolution, '1080p');
  assert.ok(result.every((row) => row.sampleCount >= 3));
});

test('aggregateHardware computes stable weighted averages within a fixed slice', () => {
  const rows = [
    makeBenchmarkRow({ id: 'a', samples: 3, fpsSum: 360, gpuPowerSum: 540, gpuPowerSamples: 3 }),
    makeBenchmarkRow({ id: 'b', samples: 5, fpsSum: 700, gpuPowerSum: 1_000, gpuPowerSamples: 5 }),
  ];

  const result = aggregateHardware(rows, 3);
  assert.equal(result.length, 1);
  assert.equal(result[0].sampleCount, 8);
  assert.equal(result[0].avgFps, 132.5);
  assert.equal(result[0].avgPowerW, 192.5);
  assert.ok(result[0].fpsPerWatt > 0);
});

test('aggregateEncoders keeps preset-specific profiles distinct', () => {
  const rows = [
    makeBenchmarkRow({ id: 'a', preset: 'p6' }),
    makeBenchmarkRow({ id: 'b', preset: 'p7' }),
  ];
  const result = aggregateEncoders(rows, 3);
  assert.equal(result.length, 2);
  assert.deepEqual(result.map((row) => row.preset), ['p6', 'p7']);
});

test('codec family helpers resolve encoder names consistently', () => {
  const row = makeBenchmarkRow({ codec: 'hevc_qsv', encoderName: null });
  assert.equal(resolveEncoderName(row), 'hevc_qsv');
  assert.equal(deriveCodecFamily('hevc_qsv'), 'hevc');
  assert.equal(deriveCodecFamily('libaom-av1'), 'av1');
  assert.equal(deriveCodecFamily('mystery_encoder'), 'other');
});

test('BoundedTtlCache supports multi-key hits and bounded eviction', () => {
  const cache = new BoundedTtlCache({ ttlMs: 10_000, maxEntries: 2 });
  cache.set('a', { value: 1 }, 1);
  cache.set('b', { value: 2 }, 2);
  assert.deepEqual(cache.get('a', 3), { value: 1 });
  cache.set('c', { value: 3 }, 4);
  assert.equal(cache.get('b', 5), undefined);
  assert.deepEqual(cache.get('a', 5), { value: 1 });
  assert.deepEqual(cache.get('c', 5), { value: 3 });
});

test('query cache helper reports bounded size', () => {
  assert.ok(getQueryCacheSize() >= 0);
});
