import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import express from 'express';
import routes, {
  buildSubmissionPayloadHash,
  benchmarkWhereFromSubmission,
  buildEncoderTypeFilter,
  buildGlobalSearchFilter,
  buildWorkbenchWhere,
  DEFAULT_QUERY_LIMIT,
  TEST_VIDEO_CATALOG,
  getQueryCacheSize,
  normalizeCpuFreqMHz,
  determineSubmissionStatus,
  parseTelemetryFromNotes,
  parseTelemetryMetaFromNotes,
  parseSkipParam,
  parseTakeParam,
  runSubmitTransactionWithRetry,
  SORT_WHITELIST,
} from '../dist/routes.js';
import {
  buildPublicCorpusOrderBy,
  buildPublicCorpusWhere,
} from '../dist/v7/corpus.js';
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

test('GET /test-videos returns the seven-clip manifest-backed catalog', async (t) => {
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
    assert.equal(data.length, 7);

    assert.equal(data.some((v) => v && v.fileName === 'sample.mp4'), false);

    const sports = data.find((v) => v && v.clipId === 'sports-action-960x540-24p');
    assert.ok(sports, 'sports-action-960x540-24p should exist in catalog');
    assert.equal(sports.suiteVersion, 'encodingdb-test-suite-v1');
    assert.equal(sports.contentClass, 'high-motion-sports');
    assert.equal(sports.sha256, '8dff09e5120e42c478ef02501ff75d7ae7e94a509b651a2a9506c03ff512876a');
    assert.equal(sports.sizeBytes, 3243818);
    assert.equal(sports.source.license, 'CC0-1.0');
    assert.equal(sports.acquisition.kind, 'generated');
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

test('buildPublicCorpusWhere scopes direct V7 evidence filters', async () => {
  const where = buildPublicCorpusWhere({
    cpu: 'Ryzen',
    gpu: 'RTX',
    search: 'nvenc',
    preset: 'p6',
    encoderType: 'hardware',
  });

  assert.deepEqual(where.status, { in: ['ACCEPTED', 'SUSPECT'] });
  assert.equal(where.benchmarkProtocol.state, 'ACTIVE');
  assert.equal(where.artifacts.some.role, 'ENCODED');
  assert.ok(Array.isArray(where.AND));
  assert.equal(where.AND.length, 5);
});

test('buildPublicCorpusOrderBy supports V7 public sort keys only', () => {
  assert.deepEqual(buildPublicCorpusOrderBy('samples', 'asc'), { sortKey: 'samples', dir: 'asc' });
  assert.deepEqual(buildPublicCorpusOrderBy('sampleCount', 'asc'), { sortKey: 'createdAt', dir: 'asc' });
});

test('GET /corpus returns unscored rows from direct retained evidence when no ScoreContext or DerivedResult exists', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }

  const originalBenchmarkRunFindMany = prisma.benchmarkRun.findMany;
  const originalDerivedFindMany = prisma.derivedResult.findMany;
  prisma.benchmarkRun.findMany = async () => [
    makeBenchmarkRunRow(),
    makeBenchmarkRunRow({
      id: 'benchmark-run-2',
      createdAt: new Date('2026-08-12T00:01:00.000Z'),
      updatedAt: new Date('2026-08-12T00:01:00.000Z'),
      payloadHash: 'payload-hash-2',
      repetitionGroupId: 'repeat-b',
      repetitionIndex: 1,
      campaignId: 'campaign-b',
      encodeFps: 100,
      artifacts: [{
        ...makeBenchmarkRunRow().artifacts[0],
        id: 'artifact-2',
        benchmarkRunId: 'benchmark-run-2',
      }],
      qualityAnalyses: [{
        ...makeBenchmarkRunRow().qualityAnalyses[0],
        id: 'analysis-2',
        benchmarkRunId: 'benchmark-run-2',
        artifactId: 'artifact-2',
        vmafMean: 94,
        vmafP5: 92,
        videoBitrateBps: 4_200_000,
      }],
    }),
  ];
  prisma.derivedResult.findMany = async () => [];
  t.after(() => {
    prisma.benchmarkRun.findMany = originalBenchmarkRunFindMany;
    prisma.derivedResult.findMany = originalDerivedFindMany;
  });

  const { server, baseUrl } = await startTestServer();
  try {
    const res = await fetch(`${baseUrl}/corpus?total=1&limit=10`);
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('x-total-count'), '1');
    const data = await res.json();
    assert.equal(data.length, 1);
    assert.equal(data[0].encoderName, 'libx265');
    assert.equal(data[0].samples, 2);
    assert.equal(data[0].sampleCounts.accepted, 2);
    assert.equal(data[0].sampleCounts.repetitions, 2);
    assert.equal(data[0].status.scoring, 'UNSCORED_NO_PUBLIC_DERIVED_RESULT');
    assert.equal(data[0].pl.total, null);
    assert.equal(data[0].versions.scoreContextId, null);
    assert.equal(data[0].bitrate.workloadReferenceBitrateBps, null);
    assert.equal(data[0].confidence.available, false);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('GET /query rejects categorical telemetry filters on mixed aggregates', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }
  const { server, baseUrl } = await startTestServer();
  try {
    for (const params of ['powerSource=ac', 'thermalThrottle=false']) {
      const res = await fetch(`${baseUrl}/query?${params}`);
      assert.equal(res.status, 400);
      const body = await res.json();
      assert.match(body.error, /unavailable for aggregated results/);
    }
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
    workloadId: null,
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

test('aggregate sample count is an allowed workbench sort', () => {
  assert.ok(SORT_WHITELIST.has('samples'));
});

test('TEST_VIDEO_CATALOG has no placeholders', () => {
  assert.equal(TEST_VIDEO_CATALOG.length, 7);
  for (const row of TEST_VIDEO_CATALOG) {
    assert.notEqual(row.fileName, 'sample.mp4');
    assert.ok(typeof row.sha256 === 'string' && !row.sha256.startsWith('placeholder_'));
    assert.ok(Number(row.sizeBytes) > 0);
    assert.equal(row.source.license, 'CC0-1.0');
    assert.equal(row.acquisition.kind, 'generated');
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

test('only canonical, plausible submissions can be accepted', () => {
  assert.equal(determineSubmissionStatus({ plausible: true, canonicalInput: true, maxAbsoluteZScore: 0 }), 'accepted');
  assert.equal(determineSubmissionStatus({ plausible: true, canonicalInput: false, maxAbsoluteZScore: 0 }), 'pending');
  assert.equal(determineSubmissionStatus({ plausible: true, canonicalInput: true, maxAbsoluteZScore: 4 }), 'suspect');
  assert.equal(determineSubmissionStatus({ plausible: false, canonicalInput: true, maxAbsoluteZScore: 0 }), 'rejected');
});

test('idempotent retry lookup derives the aggregate key from Submission', () => {
  const source = {
    cpuModel: 'Ryzen 9 7950X', gpuModel: 'RTX 4090', ramGB: 64, os: 'Linux',
    codec: 'h264_nvenc', preset: 'p6', crf: 0, contentClass: 'gaming', resolution: '4k', passes: 1, workloadId: null,
  };
  assert.deepEqual(benchmarkWhereFromSubmission(source), source);
});

test('global workbench search spans advertised text and numeric result fields', () => {
  const text = buildGlobalSearchFilter('RTX 4090');
  assert.ok(text.OR.some((entry) => entry.cpuModel?.contains === 'RTX 4090'));
  assert.ok(text.OR.some((entry) => entry.gpuModel?.contains === 'RTX 4090'));
  assert.ok(text.OR.some((entry) => entry.encoderName?.contains === 'RTX 4090'));
  assert.ok(text.OR.some((entry) => entry.preset?.contains === 'RTX 4090'));

  const numeric = buildGlobalSearchFilter('24');
  assert.ok(numeric.OR.some((entry) => entry.crf === 24));
  assert.ok(numeric.OR.some((entry) => entry.fps === 24));
  assert.ok(numeric.OR.some((entry) => entry.samples === 24));
});

test('workbench CPU and GPU filters remain server-side alongside global search', () => {
  const where = buildWorkbenchWhere({ cpu: 'Ryzen', gpu: '4090', search: 'nvenc' });
  assert.deepEqual(where.cpuModel, { contains: 'Ryzen', mode: 'insensitive' });
  assert.deepEqual(where.gpuModel, { contains: '4090', mode: 'insensitive' });
  assert.ok(where.AND.some((entry) => Array.isArray(entry.OR)));
});

test('hardware encoder classification includes Linux and Raspberry Pi suffixes', () => {
  const filter = buildEncoderTypeFilter('hardware');
  const suffixes = filter.OR.flatMap((entry) => [entry.codec?.endsWith, entry.encoderName?.endsWith]).filter(Boolean);
  assert.ok(suffixes.includes('_v4l2m2m'));
  assert.ok(suffixes.includes('_omx'));
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
    vmafP5: null,
    ssim: 0.98,
    psnr: 41,
    fileSizeBytes: 80_000_000,
    videoBitrateBps: null,
    sourceFps: null,
    sourceDurationSeconds: null,
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
    vmafP5Samples: 0,
    vmafP5Sum: 0,
    videoBitrateSamples: 0,
    videoBitrateSum: 0,
    sourceFpsSamples: 0,
    sourceFpsSum: 0,
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
    scoreFormulaVersion: null,
    benchmarkProtocolVersion: null,
    sourceSuiteVersion: null,
    workloadId: null,
    metricModelId: null,
    payloadHash: null,
    ...overrides,
  };
}

function makeDerivedResultRow(overrides = {}) {
  return {
    id: 'derived-1',
    createdAt: new Date('2026-08-12T00:00:00.000Z'),
    updatedAt: new Date('2026-08-12T00:00:00.000Z'),
    kind: 'WORKLOAD',
    scopeKey: 'workload:mixed-1080p',
    benchmarkProtocolId: 'protocol-1',
    workloadId: 'mixed-1080p',
    testClipId: null,
    recipeId: 'recipe-1',
    environmentId: 'environment-1',
    scoreContextId: 'score-context-1',
    aggregatorVersion: 'derived-result-aggregation/v1',
    acceptedRunCount: 4,
    suspectRunCount: 0,
    rejectedRunCount: 0,
    invalidRunCount: 0,
    repetitionCount: 4,
    centerEncodeFps: 120,
    centerRealTimeRatio: 4,
    centerVideoBitrateBps: 4_500_000,
    centerFileSizeBytes: 80_000_000,
    centerVmafMean: 95,
    centerVmafP5: 93,
    plQuality: 0.85,
    plBitrate: 0.52,
    plSpeed: 0.97,
    plTotal: 77.7,
    confidenceLower: 74.1,
    confidenceUpper: 79.9,
    evidenceTier: 'MEDIUM',
    evidenceSummary: { eligibleForDefaultRecommendation: true },
    confidenceIntervals: {},
    dispersion: {},
    recomputationSpec: {},
    recipe: {
      id: 'recipe-1',
      fingerprint: 'recipe-fingerprint',
      canonicalJson: {},
      codecFamily: 'hevc',
      encoderImplementation: 'libx265',
      preset: 'slow',
      requestedRateControlMode: 'CONSTANT_QUALITY',
      effectiveRateControlMode: 'CONSTANT_QUALITY',
      requestedQualityValue: 24,
      effectiveQualityValue: 24,
    },
    environment: {
      id: 'environment-1',
      fingerprint: 'environment-fingerprint',
      canonicalJson: {},
      cpuModel: 'AMD Ryzen 9 9950X',
      gpuModel: 'NVIDIA RTX 5090',
      physicalCoreCount: 16,
      logicalThreadCount: 32,
      osName: 'Linux',
      osVersion: '6.10',
      ffmpegVersion: '7.1',
    },
    scoreContext: {
      id: 'score-context-1',
      formulaVersion: '7.0',
      contextVersion: 'reference-frontier-v1',
      workloadId: 'mixed-1080p',
      qualityModelId: 'vmaf-v1',
      workloadReferenceBitrateBps: 5_000_000,
      transformConstants: {
        qualityExponent: 2.4,
        speedCurveRate: 1.2,
        speedSaturationRealtime: 4,
      },
      benchmarkProtocol: {
        id: 'protocol-1',
        protocolVersion: 'benchmark-protocol-v1',
        sourceSuiteVersion: 'encodingdb-test-suite-v1',
        state: 'ACTIVE',
      },
    },
    ...overrides,
  };
}

function makeBenchmarkRunRow(overrides = {}) {
  return {
    id: 'benchmark-run-1',
    createdAt: new Date('2026-08-12T00:00:00.000Z'),
    updatedAt: new Date('2026-08-12T00:00:00.000Z'),
    benchmarkProtocolId: 'protocol-1',
    testClipId: 'clip-1',
    workloadId: 'mixed-1080p',
    recipeId: 'recipe-1',
    environmentId: 'environment-1',
    payloadHash: 'payload-hash-1',
    inputHash: null,
    campaignId: 'campaign-a',
    repetitionGroupId: 'repeat-a',
    repetitionIndex: 0,
    encodeWallTimeMs: 10_000,
    encodeFps: 120,
    sourceFps: 30,
    realTimeRatio: 4,
    sourceFrameCount: 300,
    encodedFrameCount: 300,
    telemetry: null,
    telemetrySources: null,
    telemetryMissing: null,
    energyDomains: null,
    decodeBenchmark: null,
    preRunEnvironmentCheck: null,
    ffmpegProgressTelemetry: null,
    clientQualityDebug: null,
    status: 'ACCEPTED',
    statusReason: null,
    benchmarkProtocol: {
      id: 'protocol-1',
      protocolVersion: 'benchmark-protocol-v1',
      sourceSuiteVersion: 'encodingdb-test-suite-v1',
      minimumClientVersion: 'client/0.2.0',
      metricWorkerVersion: 'authoritative-analysis/v1',
      canonicalRecipeRules: {},
      canonicalOutputRules: {},
      state: 'ACTIVE',
    },
    recipe: {
      id: 'recipe-1',
      fingerprint: 'recipe-fingerprint',
      canonicalJson: {},
      codecFamily: 'hevc',
      encoderImplementation: 'libx265',
      encoderVersion: '7.1',
      preset: 'slow',
      tune: null,
      profile: 'main',
      level: '5.1',
      tier: null,
      pixelFormat: 'yuv420p10le',
      bitDepth: 10,
      chromaSubsampling: '4:2:0',
      containerFormat: 'mp4',
      videoCodecTag: null,
      requestedRateControlMode: 'CONSTANT_QUALITY',
      requestedQualityValue: 24,
      requestedTargetBitrateKbps: null,
      requestedMaxBitrateKbps: null,
      requestedBufferSizeKbits: null,
      requestedQmin: null,
      requestedQmax: null,
      effectiveRateControlMode: 'CONSTANT_QUALITY',
      effectiveQualityValue: 24,
      effectiveTargetBitrateKbps: null,
      effectiveMaxBitrateKbps: null,
      effectiveBufferSizeKbits: null,
      effectiveQmin: null,
      effectiveQmax: null,
      requestedRateControl: {},
      effectiveRateControl: {},
      requestedOutputSettings: null,
      effectiveOutputSettings: null,
      normalizedRequestedOptions: null,
      normalizedEffectiveOptions: null,
      gopSize: null,
      keyframeInterval: null,
      bFrames: null,
      frameReordering: null,
      lookahead: null,
      filmGrainSynthesis: null,
      majorTools: null,
    },
    environment: {
      id: 'environment-1',
      fingerprint: 'environment-fingerprint',
      canonicalJson: {},
      cpuModel: 'AMD Ryzen 9 9950X',
      cpuArchitecture: 'x86_64',
      physicalCoreCount: 16,
      logicalThreadCount: 32,
      gpuModel: 'NVIDIA RTX 5090',
      selectedAcceleratorId: null,
      selectedAccelerator: 'cuda',
      driverVersion: '555.12',
      osName: 'Linux',
      osVersion: '6.10',
      ffmpegBuildFingerprint: 'ffmpeg-build-fingerprint',
      ffmpegVersion: '7.1',
      encoderVersion: '7.1',
      clientVersion: 'client/0.2.0',
    },
    artifacts: [
      {
        id: 'artifact-1',
        createdAt: new Date('2026-08-12T00:00:00.000Z'),
        updatedAt: new Date('2026-08-12T00:00:00.000Z'),
        benchmarkRunId: 'benchmark-run-1',
        role: 'ENCODED',
        sha256: 'a'.repeat(64),
        byteSize: 80_000_000,
        storageState: 'RETAINED',
        storageProvider: 'local',
        storageBucket: 'bucket',
        storageKey: 'artifact-1',
        storageUrl: null,
        mediaContainer: 'mp4',
        stateReason: null,
        stateDetails: null,
        uploadedAt: new Date('2026-08-12T00:00:00.000Z'),
        verifiedAt: new Date('2026-08-12T00:00:00.000Z'),
        retainedAt: new Date('2026-08-12T00:00:00.000Z'),
        deletedAt: null,
      },
    ],
    qualityAnalyses: [
      {
        id: 'analysis-1',
        createdAt: new Date('2026-08-12T00:00:00.000Z'),
        updatedAt: new Date('2026-08-12T00:00:00.000Z'),
        benchmarkRunId: 'benchmark-run-1',
        artifactId: 'artifact-1',
        status: 'COMPLETE',
        metricModelId: 'vmaf-v1-sdr-sd',
        qualityContextId: null,
        analysisWorkerVersion: 'authoritative-analysis/v1',
        analysisProvenance: {},
        vmafMean: 95,
        vmafMedian: 95,
        vmafP1: 90,
        vmafP5: 93,
        vmafMin: 88,
        vmafMax: 98,
        vmafStdDev: 2,
        vmafHarmonicMean: 94,
        worstFrameIndex: 1,
        worstFrameTimestampMs: 100,
        belowThresholdFractions: null,
        vmafDistribution: null,
        xpsnr: null,
        ssim: null,
        psnr: null,
        videoBitrateBps: 4_500_000,
        videoPayloadBytes: 79_500_000,
        videoPacketCount: 1_000,
        measuredDurationSeconds: 10,
        bitrateMethod: 'payload',
        containerBitrateBps: 4_700_000,
        fileSizeBytes: 80_000_000,
      },
    ],
    ...overrides,
  };
}

test('parseAnalyticsFilters defaults to the canonical comparison slice', () => {
  const filters = parseAnalyticsFilters({});
  assert.deepEqual(filters, {
    workloadId: null,
    contentClass: 'mixed',
    resolution: '1080p',
    crf: 24,
    passes: 1,
    minSamples: 3,
    fitMode: 'balanced',
    customQualityWeight: null,
    customBitrateWeight: null,
    customSpeedWeight: null,
    minimumQuality: null,
    minimumRealtimeRatio: null,
    maximumBitrateBps: null,
    compatibleCodecFamilies: null,
    requireRecommendationEligibility: false,
    environmentId: null,
    environmentFingerprint: null,
    scoreContextId: null,
  });
  assert.deepEqual(buildAnalyticsWhere(filters), {
    status: 'accepted',
    contentClass: 'mixed',
    resolution: '1080p',
    crf: 24,
    passes: 1,
  });
});

test('parseAnalyticsFilters preserves lossless CRF 0', () => {
  assert.equal(parseAnalyticsFilters({ crf: '0' }).crf, 0);
});

test('GET /analytics/leaderboards uses canonical derived results and an exact immutable Environment scope', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }

  const originalDerivedFindMany = prisma.derivedResult.findMany;
  const originalBenchmarkFindMany = prisma.benchmark.findMany;
  let benchmarkCalls = 0;

  const canonicalRows = [
    makeDerivedResultRow(),
    makeDerivedResultRow({
      id: 'derived-2',
      recipeId: 'recipe-2',
      scoreContextId: 'score-context-1',
      centerEncodeFps: 90,
      centerRealTimeRatio: 3,
      centerVideoBitrateBps: 5_100_000,
      centerVmafMean: 96,
      centerVmafP5: 94.5,
      plQuality: 0.9,
      plBitrate: 0.49,
      plSpeed: 0.92,
      plTotal: 78.9,
      environmentId: 'environment-2',
      environment: {
        id: 'environment-2',
        fingerprint: 'environment-fingerprint-2',
        canonicalJson: {},
        cpuModel: 'AMD Ryzen 9 9950X',
        gpuModel: 'NVIDIA RTX 5090',
        physicalCoreCount: 16,
        logicalThreadCount: 32,
        osName: 'Linux',
        osVersion: '6.10',
        ffmpegVersion: '7.1',
      },
      recipe: {
        id: 'recipe-2',
        fingerprint: 'recipe-fingerprint-2',
        canonicalJson: {},
        codecFamily: 'hevc',
        encoderImplementation: 'hevc_videotoolbox',
        preset: 'medium',
        requestedRateControlMode: 'TARGET_BITRATE',
        effectiveRateControlMode: 'TARGET_BITRATE',
        requestedTargetBitrateKbps: 5_000,
        effectiveTargetBitrateKbps: 5_000,
        requestedQualityValue: 24,
        effectiveQualityValue: 24,
      },
      scoreContext: {
        id: 'score-context-1',
        formulaVersion: '7.0',
        contextVersion: 'reference-frontier-v1',
        workloadId: 'mixed-1080p',
        qualityModelId: 'vmaf-v1',
        workloadReferenceBitrateBps: 5_000_000,
        transformConstants: {
          qualityExponent: 2.4,
          speedCurveRate: 1.2,
          speedSaturationRealtime: 4,
        },
        benchmarkProtocol: {
          id: 'protocol-1',
          protocolVersion: 'benchmark-protocol-v1',
          sourceSuiteVersion: 'encodingdb-test-suite-v1',
          state: 'ACTIVE',
        },
      },
    }),
  ];
  prisma.derivedResult.findMany = async () => canonicalRows;
  prisma.benchmark.findMany = async () => {
    benchmarkCalls += 1;
    return [makeBenchmarkRow({ encoderName: 'legacy_benchmark_only' })];
  };
  t.after(() => {
    prisma.derivedResult.findMany = originalDerivedFindMany;
    prisma.benchmark.findMany = originalBenchmarkFindMany;
  });

  const { server, baseUrl } = await startTestServer();
  try {
    const res = await fetch(`${baseUrl}/analytics/leaderboards?contentClass=action&resolution=720p&crf=24&environmentId=environment-2&scoreContextId=score-context-1`);
    assert.equal(res.status, 200);
    const data = await res.json();
    assert.equal(benchmarkCalls, 0);
    assert.equal(data.rows.length, 1);
    assert.equal(data.rows[0].encoderName, 'hevc_videotoolbox');
    assert.deepEqual(data.rows[0].rateControl, {
      requestedMode: 'TARGET_BITRATE',
      effectiveMode: 'TARGET_BITRATE',
      qualityValue: 24,
      targetBitrateKbps: 5_000,
      maxBitrateKbps: null,
      bufferSizeKbits: null,
      label: 'TARGET_BITRATE 5000 kbps',
    });
    assert.deepEqual(data.rows[0].hardwareContext, {
      environmentId: 'environment-2',
      environmentFingerprint: 'environment-fingerprint-2',
      cpuModel: 'AMD Ryzen 9 9950X',
      gpuModel: 'NVIDIA RTX 5090',
      ramGB: 16,
      os: 'Linux 6.10',
    });
    assert.equal(data.environmentScope.exact, true);
    assert.equal(data.contextScope.exact, true);
    assert.equal(data.contextScope.selectedScoreContextId, 'score-context-1');
    assert.equal(data.rows.every((row) => row.encoderName !== 'legacy_benchmark_only'), true);

    canonicalRows.push(makeDerivedResultRow({
      id: 'derived-unrelated-faster',
      environmentId: 'environment-unrelated',
      centerEncodeFps: 10_000,
      centerRealTimeRatio: 300,
      plTotal: 99.9,
      environment: {
        ...makeDerivedResultRow().environment,
        id: 'environment-unrelated',
        fingerprint: 'environment-fingerprint-unrelated',
        cpuModel: 'Unrelated faster CPU',
      },
    }));
    canonicalRows.push(makeDerivedResultRow({
      id: 'derived-future-context',
      environmentId: 'environment-2',
      scoreContextId: 'score-context-future',
      plTotal: 99.8,
      environment: canonicalRows[1].environment,
      scoreContext: {
        ...canonicalRows[1].scoreContext,
        id: 'score-context-future',
        contextVersion: 'reference-frontier-future',
      },
    }));
    const invariantRes = await fetch(`${baseUrl}/analytics/leaderboards?contentClass=action&resolution=720p&crf=24&environmentId=environment-2&environmentFingerprint=environment-fingerprint-2&scoreContextId=score-context-1`);
    assert.equal(invariantRes.status, 200);
    const invariant = await invariantRes.json();
    assert.equal(invariant.recommendation.rowId, data.recommendation.rowId);
    assert.deepEqual(invariant.rows.map((row) => row.rowId), data.rows.map((row) => row.rowId));
    assert.deepEqual(invariant.rows.map((row) => row.plScore), data.rows.map((row) => row.plScore));

    const constrainedRes = await fetch(`${baseUrl}/analytics/leaderboards?contentClass=action&resolution=720p&environmentId=environment-2&scoreContextId=score-context-1&fitMode=quality&minimumQuality=99`);
    assert.equal(constrainedRes.status, 200);
    const constrained = await constrainedRes.json();
    assert.equal(constrained.rows[0].plScore, data.rows[0].plScore);
    assert.equal(constrained.rows[0].context.scoreContextId, 'score-context-1');

    const ambiguousContextRes = await fetch(`${baseUrl}/analytics/leaderboards?contentClass=action&resolution=720p&environmentId=environment-2`);
    assert.equal(ambiguousContextRes.status, 200);
    const ambiguousContext = await ambiguousContextRes.json();
    assert.equal(ambiguousContext.rows.length, 0);
    assert.equal(ambiguousContext.contextScope.exact, false);
    assert.deepEqual(ambiguousContext.contextScope.available.map((context) => context.scoreContextId).sort(), [
      'score-context-1',
      'score-context-future',
    ]);
    assert.match(ambiguousContext.recommendation.reason, /immutable score context/);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('GET /analytics/leaderboards returns an empty canonical payload when only legacy benchmark rows exist', async (t) => {
  if (!CAN_BIND_LOOPBACK) {
    t.skip('Loopback listen is unavailable in this runtime');
    return;
  }

  const originalDerivedFindMany = prisma.derivedResult.findMany;
  const originalBenchmarkFindMany = prisma.benchmark.findMany;
  let benchmarkCalls = 0;

  prisma.derivedResult.findMany = async () => [];
  prisma.benchmark.findMany = async () => {
    benchmarkCalls += 1;
    return [makeBenchmarkRow({ encoderName: 'legacy_only' })];
  };
  t.after(() => {
    prisma.derivedResult.findMany = originalDerivedFindMany;
    prisma.benchmark.findMany = originalBenchmarkFindMany;
  });

  const { server, baseUrl } = await startTestServer();
  try {
    const res = await fetch(`${baseUrl}/analytics/leaderboards?contentClass=mixed&resolution=1080p&crf=24`);
    assert.equal(res.status, 200);
    const data = await res.json();
    assert.equal(benchmarkCalls, 0);
    assert.deepEqual(data.rows, []);
    assert.equal(data.recommendation.rowId, null);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
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

test('aggregateLeaderboards computes filter-invariant PL v7 only from complete versioned evidence', () => {
  const priorRefs = process.env.PL_V7_REFERENCE_BITRATES_JSON;
  const priorVersion = process.env.PL_V7_REFERENCE_CONTEXT_VERSION;
  process.env.PL_V7_REFERENCE_BITRATES_JSON = JSON.stringify({ 'sports-1080p': 4_000_000 });
  process.env.PL_V7_REFERENCE_CONTEXT_VERSION = 'test-reference-v1';
  try {
    const scored = makeBenchmarkRow({
      id: 'pl7', workloadId: 'sports-1080p', samples: 3, fpsSum: 180,
      vmafSum: 282, vmafSamples: 3, vmafP5Sum: 264, vmafP5Samples: 3,
      videoBitrateSum: 12_000_000, videoBitrateSamples: 3,
      sourceFpsSum: 90, sourceFpsSamples: 3,
    });
    const unrelated = makeBenchmarkRow({ id: 'unrelated', encoderName: 'libx264', preset: 'slow', samples: 3 });
    const alone = aggregateLeaderboards([scored], 3).find((row) => row.encoderName === 'h264_nvenc');
    const withCandidate = aggregateLeaderboards([scored, unrelated], 3).find((row) => row.encoderName === 'h264_nvenc');
    assert.ok(alone.plScore != null);
    assert.equal(withCandidate.plScore, alone.plScore);
    assert.equal(alone.plScoreVersion, '7.0');
    assert.deepEqual(alone.hardwareContext, {
      cpuModel: 'Intel Core i7-14700K',
      gpuModel: 'NVIDIA RTX 4070',
      ramGB: 32,
      os: 'Windows 11',
    });
    assert.equal(alone.plScoreContext.referenceContextVersion, 'test-reference-v1');
    assert.ok(alone.plScoreComponents.quality > 0);
  } finally {
    if (priorRefs == null) delete process.env.PL_V7_REFERENCE_BITRATES_JSON;
    else process.env.PL_V7_REFERENCE_BITRATES_JSON = priorRefs;
    if (priorVersion == null) delete process.env.PL_V7_REFERENCE_CONTEXT_VERSION;
    else process.env.PL_V7_REFERENCE_CONTEXT_VERSION = priorVersion;
  }
});

test('aggregateLeaderboards keeps hardware-scoped PL rows separate for identical encoder/workload slices', () => {
  const priorRefs = process.env.PL_V7_REFERENCE_BITRATES_JSON;
  const priorVersion = process.env.PL_V7_REFERENCE_CONTEXT_VERSION;
  process.env.PL_V7_REFERENCE_BITRATES_JSON = JSON.stringify({ 'sports-1080p': 4_000_000 });
  process.env.PL_V7_REFERENCE_CONTEXT_VERSION = 'test-reference-v1';
  try {
    const baseline = makeBenchmarkRow({
      id: 'pl7-hw-a',
      workloadId: 'sports-1080p',
      samples: 3,
      fpsSum: 180,
      vmafSum: 282,
      vmafSamples: 3,
      vmafP5Sum: 264,
      vmafP5Samples: 3,
      videoBitrateSum: 12_000_000,
      videoBitrateSamples: 3,
      sourceFpsSum: 90,
      sourceFpsSamples: 3,
    });
    const otherHardware = makeBenchmarkRow({
      id: 'pl7-hw-b',
      workloadId: 'sports-1080p',
      cpuModel: 'AMD Ryzen 9 9950X',
      gpuModel: 'NVIDIA RTX 5090',
      ramGB: 64,
      os: 'Linux',
      samples: 3,
      fpsSum: 420,
      vmafSum: 291,
      vmafSamples: 3,
      vmafP5Sum: 279,
      vmafP5Samples: 3,
      videoBitrateSum: 9_000_000,
      videoBitrateSamples: 3,
      sourceFpsSum: 90,
      sourceFpsSamples: 3,
    });

    const rows = aggregateLeaderboards([baseline, otherHardware], 3).filter((row) => row.encoderName === 'h264_nvenc');
    assert.equal(rows.length, 2);

    const baselineRow = rows.find((row) => row.hardwareContext.cpuModel === 'Intel Core i7-14700K');
    const otherHardwareRow = rows.find((row) => row.hardwareContext.cpuModel === 'AMD Ryzen 9 9950X');
    const isolatedBaseline = aggregateLeaderboards([baseline], 3).find((row) => row.encoderName === 'h264_nvenc');

    assert.ok(baselineRow);
    assert.ok(otherHardwareRow);
    assert.ok(isolatedBaseline);
    assert.equal(baselineRow.sampleCount, isolatedBaseline.sampleCount);
    assert.equal(baselineRow.avgFps, isolatedBaseline.avgFps);
    assert.equal(baselineRow.avgVideoBitrateBps, isolatedBaseline.avgVideoBitrateBps);
    assert.equal(baselineRow.plScore, isolatedBaseline.plScore);
    assert.notEqual(otherHardwareRow.plScore, baselineRow.plScore);
  } finally {
    if (priorRefs == null) delete process.env.PL_V7_REFERENCE_BITRATES_JSON;
    else process.env.PL_V7_REFERENCE_BITRATES_JSON = priorRefs;
    if (priorVersion == null) delete process.env.PL_V7_REFERENCE_CONTEXT_VERSION;
    else process.env.PL_V7_REFERENCE_CONTEXT_VERSION = priorVersion;
  }
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
