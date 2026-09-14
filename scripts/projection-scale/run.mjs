/** Synthetic metadata-only benchmark. Never use with a production database. */
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import http from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../../server/package.json', import.meta.url));
const { PrismaClient } = require('@prisma/client');
const { CANONICAL_MEASUREMENT_RULES, createMeasurementGroupVerifier } = await import('../../server/dist/v7/measurementGroup.js');
const { persistDerivedResultAggregate, DEFAULT_RECOMMENDATION_EVIDENCE_POLICY } = await import('../../server/dist/v7/aggregation.js');
const { loadPublicCorpusPage, refreshPublicCorpusGroups } = await import('../../server/dist/v7/corpusQuery.js');
const mode = process.argv[2];
const url = new URL(process.env.PROJECTION_SCALE_DATABASE_URL ?? 'http://missing');
assert.equal(url.hostname, '127.0.0.1'); assert.equal(url.pathname, '/encodingdb_projection_synthetic');
const output = process.env.PROJECTION_SCALE_OUTPUT;
assert.ok(output, 'Explicit evidence output directory required'); await mkdir(output, { recursive: true });
const client = new PrismaClient({ datasources: { db: { url: url.toString() } } });
const id = 'SYNTHETIC-PROJECTION-ONLY';
const model = `${id}-model`, worker = 'authoritative-analysis/SYNTHETIC-NO-MEDIA';
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const environmentId = index => `${id}-env-${String(index).padStart(4, '0')}`;
const cohortSize = index => index === 0 ? 2000 : 100;
const receipt = (group, times) => ({ schemaVersion: 'encodingdb-measurement-group/v1', campaignId: id, repetitionGroupId: group, completed: true, countedAttempts: times.map((ms, i) => ({ repetitionIndex: i + 1, encodeWallTimeMs: ms })) });
function rowsForGroup(env, group, times, kind = 'stable', retainedCount = times.length) {
  const base = Number(env.slice(-4));
  const summary = receipt(group, times);
  return times.slice(0, retainedCount).map((ms, i) => {
    const runId = `${group}-run-${i}`;
    return { id: runId, benchmarkProtocolId: id, testClipId: id, workloadId: id, recipeId: id, environmentId: env,
      payloadHash: hash(runId), physicalSourceId: `${group}-source`, campaignId: id, repetitionGroupId: group, repetitionIndex: i + 1,
      encodeTimerBoundary: 'ffmpeg-process-v1', inputHash: hash(id), encodeWallTimeMs: ms, encodeFps: 240000 / ms, sourceFps: 24, realTimeRatio: 10000 / ms, sourceFrameCount: 240, encodedFrameCount: 240,
      preRunEnvironmentCheck: { syntheticOnly: true, measurementGroup: summary, snapshot: { telemetry_sources: 'cpu_psutil_thread_window_v1', background_cpu_pct: 0 }, overallValidity: { state: 'valid' } }, status: 'ACCEPTED',
      artifact: { id: `${runId}-artifact`, benchmarkRunId: runId, role: 'ENCODED', sha256: hash(runId), byteSize: 1250000, storageState: 'RETAINED', storageProvider: 'localfs', storageKey: `SYNTHETIC-NO-BYTES/${runId}`, storageUrl: `synthetic://${runId}` },
      analysis: { id: `${runId}-analysis`, benchmarkRunId: runId, artifactId: `${runId}-artifact`, status: 'COMPLETE', metricModelId: model, analysisWorkerVersion: worker, analysisProvenance: { syntheticOnly: true, workerBuildFingerprint: hash(id) }, vmafMean: kind === 'stable' ? 90 + base % 10 / 10 : 70, vmafP5: kind === 'stable' ? 85 : 60, videoBitrateBps: 1000000, fileSizeBytes: 1250000 },
    };
  });
}
async function insertRows(rows) {
  for (let offset = 0; offset < rows.length; offset += 250) {
    const chunk = rows.slice(offset, offset + 250);
    await client.$transaction(async tx => {
      await tx.benchmarkRun.createMany({ data: chunk.map(({ artifact, analysis, ...run }) => run) });
      await tx.artifact.createMany({ data: chunk.map(row => row.artifact) });
      await tx.qualityAnalysis.createMany({ data: chunk.map(row => row.analysis) });
    }, { timeout: 60000 });
  }
}
async function rebuild(env) {
  const current = await client.benchmarkRun.findMany({ where: { environmentId: env }, include: { qualityAnalyses: { orderBy: [{ createdAt: 'desc' }, { id: 'desc' }], take: 1 } } });
  const verify = createMeasurementGroupVerifier(client, { metricModelId: model });
  const analyses = [];
  for (const run of current) {
    const qa = run.qualityAnalyses[0]; if (!qa) continue;
    analyses.push({ benchmarkRunId: run.id, qualityAnalysisId: qa.id, analysisWorkerVersion: qa.analysisWorkerVersion, benchmarkRunStatus: run.status, qualityAnalysisStatus: qa.status, encodeFps: run.encodeFps, sourceFps: run.sourceFps, videoBitrateBps: qa.videoBitrateBps, fileSizeBytes: qa.fileSizeBytes, vmafMean: qa.vmafMean, vmafP5: qa.vmafP5, physicalSourceId: run.physicalSourceId, repetitionGroupId: run.repetitionGroupId, measurementGroup: await verify(run) });
  }
  return persistDerivedResultAggregate(client, { identity: { kind: 'workload', benchmarkProtocolId: id, protocolVersion: '7.1', sourceSuiteVersion: id, workloadId: id, testClipId: id, recipeId: id, recipeFingerprint: id, environmentId: env, environmentFingerprint: env, scoreContextId: id, scoreContextVersion: id, qualityModelId: model, formulaVersion: '7.0' }, scoreContext: { workloadId: id, workloadReferenceBitrateBps: 1000000 }, evidencePolicy: { ...DEFAULT_RECOMMENDATION_EVIDENCE_POLICY, policyStatus: 'CALIBRATED' }, analyses });
}
async function drain() { while (await refreshPublicCorpusGroups(client, 128)) {} }
const contexts = new Set([id]);
async function page(query, options = {}) { return loadPublicCorpusPage(client, query, { take: 25, publicReferenceContextVersions: contexts, ...options }); }
const publicId = env => `${id}::${id}::${id}::${env}::${model}`;
async function validateCohort(env, extraPairs = 0) {
  const index = Number(env.slice(-4)), blocks = cohortSize(index) / 100;
  const result = await page({}, { id: publicId(env), take: 1 });
  assert.equal(result.rows.length, 1);
  const row = result.rows[0];
  assert.equal(row.status.centerBasis, 'eligible-stable-groups'); assert.ok(row.pl.total > 0);
  assert.equal(row.sampleCounts.accepted, blocks * 100 + extraPairs * 2);
  assert.equal(row.sampleCounts.independentSources, blocks * 48 + extraPairs);
  const persisted = await client.derivedResult.findFirst({ where: { environmentId: env }, include: { members: true } });
  assert.equal(persisted.members.length, blocks * 80 + extraPairs * 2);
  assert.equal(new Set(persisted.members.map(member => member.benchmarkRunId)).size, persisted.members.length);
  assert.ok(persisted.members.every(member => member.benchmarkRunId.includes('-stable-') || member.benchmarkRunId.includes('-arrival-')));
  assert.equal(row.fps, persisted.centerEncodeFps);
  return { environmentId: env, rawAccepted: row.sampleCounts.accepted, sources: row.sampleCounts.independentSources, exactQualifiedMemberCount: persisted.members.length, memberHash: hash(persisted.members.map(m => m.benchmarkRunId).sort().join('\n')), centerBasis: row.status.centerBasis, fps: row.fps, pl: row.pl.total };
}
if (mode === 'seed') {
  assert.equal(await client.benchmarkRun.count(), 0, 'Seed requires empty isolated database');
  const started = new Date();
  await client.benchmarkProtocol.create({ data: { id, protocolVersion: '7.1', sourceSuiteVersion: id, minimumClientVersion: 'client/0.3.0', canonicalRecipeRules: CANONICAL_MEASUREMENT_RULES, canonicalOutputRules: {}, metricWorkerVersion: worker } });
  await client.testClip.create({ data: { id, suiteId: id, suiteVersion: id, manifestVersion: id, clipKey: id, displayName: id, workloadId: id, contentClass: 'SYNTHETIC', sourceProvenance: { syntheticOnly: true }, sha256: hash(id), byteSize: 1, exactFrameCount: 240, exactDurationSeconds: 10, frameRateNumerator: 24, frameRateDenominator: 1, width: 1920, height: 1080, pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0' } });
  await client.recipe.create({ data: { id, fingerprint: id, canonicalJson: { syntheticOnly: true }, codecFamily: 'h264', encoderImplementation: 'libx264', preset: 'SYNTHETIC', pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0', requestedRateControlMode: 'CRF', effectiveRateControlMode: 'CRF', requestedRateControl: {}, effectiveRateControl: {} } });
  await client.scoreContext.create({ data: { id, benchmarkProtocolId: id, formulaVersion: '7.0', contextVersion: id, workloadId: id, qualityModelId: model, workloadReferenceBitrateBps: 1000000, transformConstants: {} } });
  for (let index = 0; index <= 980; index++) {
    const env = environmentId(index);
    await client.environment.create({ data: { id: env, fingerprint: env, canonicalJson: { syntheticOnly: true }, cpuModel: `SYNTHETIC CPU ${String(index).padStart(4, '0')}`, cpuArchitecture: 'synthetic', osName: 'SYNTHETIC', osVersion: '1', ffmpegBuildFingerprint: id, ffmpegVersion: id, clientVersion: 'client/0.3.0' } });
    const rows = [];
    for (let block = 0; block < cohortSize(index) / 100; block++) {
      const ms = 24000 + index * 10;
      for (let group = 0; group < 40; group++) rows.push(...rowsForGroup(env, `${env}-block-${block}-stable-${group}`, [ms, ms + 1]));
      for (let group = 0; group < 4; group++) rows.push(...rowsForGroup(env, `${env}-block-${block}-unstable-${group}`, [2400, 2500, 2400, 2400], 'unstable'));
      for (let group = 0; group < 4; group++) rows.push(...rowsForGroup(env, `${env}-block-${block}-partial-${group}`, [2400, 2401], 'partial', 1));
    }
    await insertRows(rows); await rebuild(env);
    if (index % 25 === 0) console.log(JSON.stringify({ seededCohorts: index + 1, at: new Date() }));
  }
  await drain(); await client.$executeRawUnsafe('ANALYZE');
  const checks = [];
  for (const index of [0, 1, 500, 980]) checks.push(await validateCohort(environmentId(index)));
  const counts = { runs: await client.benchmarkRun.count(), artifacts: await client.artifact.count(), analyses: await client.qualityAnalysis.count(), derived: await client.derivedResult.count(), members: await client.derivedResultMember.count() };
  assert.equal(counts.runs, 100000); assert.equal(counts.artifacts, 100000); assert.equal(counts.analyses, 100000); assert.equal(counts.derived, 981); assert.equal(counts.members, 80000);
  await writeFile(`${output}/seed.json`, JSON.stringify({ syntheticOnly: true, sourceSha: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(), started, completed: new Date(), counts, checks }, null, 2));
  await client.$disconnect();
} else if (mode === 'serve') {
  const port = Number(process.env.PROJECTION_SCALE_PORT ?? 55442);
  let cycles = 0, peakRss = 0;
  setInterval(() => { peakRss = Math.max(peakRss, process.memoryUsage().rss); }, 200).unref();
  const mutations = [];
  const server = http.createServer(async (request, response) => {
    try {
      const req = new URL(request.url, `http://127.0.0.1:${port}`);
      let result;
      if (req.pathname === '/memory') result = { peakRss, ...process.memoryUsage(), mutations };
      else if (req.pathname === '/mutate' && request.method === 'POST') {
        const started = new Date(); const cycle = ++cycles;
        const env = environmentId(0), group = `${env}-block-0-stable-0`;
        const extraId = `${id}-invalidating-extra-${cycle}`;
        await client.benchmarkRun.create({ data: { id: extraId, benchmarkProtocolId: id, testClipId: id, workloadId: id, recipeId: id, environmentId: env, payloadHash: hash(extraId), physicalSourceId: `${group}-source`, campaignId: id, repetitionGroupId: group, status: 'PENDING' } });
        const invalid = await page({}, { id: publicId(env), take: 1 });
        assert.equal(invalid.rows[0].pl.total, null); assert.equal(invalid.rows[0].sampleCounts.accepted, 2000 + (cycle - 1) * 2);
        await client.benchmarkRun.delete({ where: { id: extraId } });
        for (const target of [environmentId(0), environmentId(1)]) {
          await insertRows(rowsForGroup(target, `${target}-arrival-${cycle}`, [24000 + Number(target.slice(-4)) * 10, 24001 + Number(target.slice(-4)) * 10]));
          await rebuild(target);
        }
        await drain();
        const checks = [await validateCohort(environmentId(0), cycle), await validateCohort(environmentId(1), cycle)];
        result = { cycle, started, completed: new Date(), checks, invalidationObserved: true }; mutations.push(result);
      } else if (req.pathname === '/corpus') {
        const query = Object.fromEntries(req.searchParams); delete query.id; delete query.take; delete query.skip;
        result = await page(query, { take: Number(req.searchParams.get('take') ?? 25), skip: Number(req.searchParams.get('skip') ?? 0), ...(req.searchParams.has('id') ? { id: req.searchParams.get('id') } : {}) });
      } else { response.writeHead(404); response.end(); return; }
      response.writeHead(200, { 'content-type': 'application/json' }); response.end(JSON.stringify(result));
    } catch (error) { response.writeHead(503, { 'content-type': 'application/json' }); response.end(JSON.stringify({ error: String(error), code: error.code })); }
  });
  server.listen(port, '127.0.0.1', () => console.log(JSON.stringify({ ready: true, port, pid: process.pid, syntheticOnly: true })));
  const close = () => server.close(async () => { await client.$disconnect(); process.exit(0); }); process.on('SIGTERM', close); process.on('SIGINT', close);
} else if (mode === 'measure') {
  await client.$disconnect();
  const base = `http://127.0.0.1:${process.env.PROJECTION_SCALE_PORT ?? 55442}`;
  const durationMs = Number(process.env.PROJECTION_SCALE_DURATION_MS ?? 600000);
  assert.ok(durationMs >= 600000, 'Declared trial lasts at least600s');
  const container = process.env.PROJECTION_SCALE_CONTAINER; assert.ok(container?.startsWith('encodingdb-projection-synthetic-'));
  const paths = ['/corpus?sort=fps&dir=desc', '/corpus?sort=vmaf&dir=asc&skip=100', '/corpus?sort=fps&dir=asc&skip=500', '/corpus?search=SYNTHETIC%20CPU%2000&sort=fps&dir=desc', `/corpus?id=${encodeURIComponent(publicId(environmentId(0)))}`];
  const latencies = [], failures = [], mutations = [], resources = [];
  let requests = 0, scoredRows = 0, diagnosticRows = 0;
  for (const path of paths) assert.equal((await fetch(base + path)).status, 200);
  const started = new Date(), deadline = performance.now() + durationMs;
  async function reader(readerId) {
    let iteration = 0;
    while (performance.now() < deadline) {
      const path = paths[(readerId + iteration++) % paths.length], begin = performance.now();
      try {
        const response = await fetch(base + path, { signal: AbortSignal.timeout(35000) }); const body = await response.json();
        assert.equal(response.status, 200, JSON.stringify(body)); assert.ok(body.rows.length > 0); assert.ok(body.rows.length <= 25);
        if (!path.includes('id=')) {
          const ascending = path.includes('dir=asc'), metric = path.includes('sort=vmaf') ? 'vmaf' : 'fps';
          for (let i = 1; i < body.rows.length; i++) assert.ok(ascending ? body.rows[i - 1][metric] <= body.rows[i][metric] : body.rows[i - 1][metric] >= body.rows[i][metric], 'page ordering matches displayed centers');
        }
        for (const row of body.rows) {
          if (row.status.centerBasis === 'eligible-stable-groups') { scoredRows++; assert.ok(row.pl.total > 0); } else { diagnosticRows++; assert.equal(row.pl.total, null); }
          assert.ok(row.sampleCounts.accepted >= 100); assert.ok(row.sampleCounts.independentSources >= 48);
        }
      } catch (error) { failures.push({ readerId, path, at: new Date(), error: String(error) }); }
      latencies.push(performance.now() - begin); requests++;
    }
  }
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const sampler = (async () => { while (performance.now() < deadline) {
    const node = await (await fetch(base + '/memory')).json();
    const dbBytes = Number(execFileSync('docker', ['exec', container, 'cat', '/sys/fs/cgroup/memory.current'], { encoding: 'utf8' }).trim());
    resources.push({ at: new Date(), nodeRss: node.rss, nodePeakRss: node.peakRss, dbCgroupBytes: dbBytes }); await sleep(5000);
  } })();
  const writer = (async () => { for (let cycle = 0; cycle < 5; cycle++) {
    await sleep(cycle === 0 ? 30000 : 90000);
    try { const response = await fetch(base + '/mutate', { method: 'POST', signal: AbortSignal.timeout(90000) }); const body = await response.json(); assert.equal(response.status, 200, JSON.stringify(body)); mutations.push(body); }
    catch (error) { failures.push({ writer: true, at: new Date(), error: String(error) }); }
  } })();
  await Promise.all([...Array.from({ length: 25 }, (_, index) => reader(index)), sampler, writer]);
  latencies.sort((a, b) => a - b); const quantile = p => latencies[Math.floor((latencies.length - 1) * p)];
  const report = { syntheticOnly: true, sourceSha: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(), started, completed: new Date(), durationMs, readers: 25, targetP95Ms: 1000, requests, failures, scoredRows, diagnosticRows, latencyMs: { p50: quantile(.5), p95: quantile(.95), p99: quantile(.99), max: latencies.at(-1) }, peakNodeRss: Math.max(...resources.map(r => r.nodePeakRss)), peakDbCgroupBytes: Math.max(...resources.map(r => r.dbCgroupBytes)), mutations, resources };
  report.passed = failures.length === 0 && report.latencyMs.p95 <= 1000 && mutations.length === 5 && scoredRows > 0;
  await writeFile(`${output}/measurement.json`, JSON.stringify(report, null, 2)); console.log(JSON.stringify({ ...report, resources: undefined, mutations: mutations.length, failures: failures.slice(0, 5) }));
  process.exitCode = report.passed ? 0 : 1;
} else { throw new Error('Expected seed, serve or measure'); }
