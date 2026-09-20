import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { Readable } from 'node:stream';
import os from 'node:os';
import path from 'node:path';
import express from 'express';
import { PrismaClient } from '@prisma/client';
import { runNativeProcess, stopNativeProcesses } from '../dist/v7/nativeProcess.js';
import { requireOperator } from '../dist/v7/operatorAuth.js';
import { DEFAULT_RECOMMENDATION_EVIDENCE_POLICY } from '../dist/v7/aggregation.js';
import { buildScoringBehaviorHash } from '../dist/v7/recommendationPolicy.js';
import { canonicalJsonString, sha256Hex } from '../dist/v7/persistence.js';
import { appendEvidenceReview } from '../dist/v7/reviews.js';
import { buildRecipeFingerprint, buildEnvironmentFingerprint } from '../dist/v7/persistence.js';
import { loadAuthoritativeSuiteManifest } from '../dist/v7/suite.js';
import { buildAuthoritativeQualityAnalysisRecord } from '../dist/qualityAnalysis.js';
import {
  ArtifactPipelineService, FfmpegArtifactAnalyzer, createArtifactPipelineRouter, createPrismaArtifactPipelinePersistence, createDefaultDerivedRecomputeCallback, mergeArtifactPipelineConfig,
  validateProbeAgainstRun, probeMedia, validateCanonicalTiming, SERVER_CANONICAL_PROTOCOL_VERSION,
  SERVER_CANONICAL_MINIMUM_CLIENT_VERSION, SERVER_CANONICAL_RECIPE_RULES, SERVER_CANONICAL_OUTPUT_RULES, DEFAULT_ANALYZER_VERSION,
} from '../dist/v7/artifacts.js';

const manifest = loadAuthoritativeSuiteManifest();
const clip = manifest.clips[0];
function requestBody(key = crypto.randomBytes(32).toString('hex'), bytes = Buffer.from('test-video')) {
  const recipe = { codecFamily: 'h264', encoderImplementation: 'libx264', preset: 'medium', pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0', containerFormat: 'mp4', requestedRateControl: { mode: 'crf', qualityValue: 23 }, effectiveRateControl: { mode: 'crf', qualityValue: 23 } };
  const environment = { cpuModel: 'isolated synthetic test fixture', cpuArchitecture: 'x86_64', osName: 'test', osVersion: 'test', ffmpegBuildFingerprint: 'test-build', ffmpegVersion: 'test', clientVersion: SERVER_CANONICAL_MINIMUM_CLIENT_VERSION };
  return {
    benchmarkProtocol: { protocolVersion: SERVER_CANONICAL_PROTOCOL_VERSION, sourceSuiteVersion: manifest.suiteVersion, minimumClientVersion: SERVER_CANONICAL_MINIMUM_CLIENT_VERSION, canonicalRecipeRules: SERVER_CANONICAL_RECIPE_RULES, canonicalOutputRules: SERVER_CANONICAL_OUTPUT_RULES, metricWorkerVersion: DEFAULT_ANALYZER_VERSION },
    testClip: { suiteId: manifest.suiteId, suiteVersion: manifest.suiteVersion, clipKey: clip.id, sha256: clip.sha256 },
    recipe: { fingerprint: buildRecipeFingerprint(recipe).fingerprint, identity: recipe },
    environment: { fingerprint: buildEnvironmentFingerprint(environment).fingerprint, identity: environment },
    preRunEnvironmentCheck: { overallValidity: { state: 'valid' }, environmentValidity: { state: 'valid' }, structuralValidity: { state: 'valid' } },
    payloadHash: key, inputHash: clip.sha256, physicalSourceId: 'isolated-test-installation-0001', encodeTimerBoundary: 'ffmpeg-process-v1',
    sourceFrameCount: clip.media.frameCount, encodedFrameCount: clip.media.frameCount,
    sourceFps: 24, encodeWallTimeMs: 1000, encodeFps: clip.media.frameCount, realTimeRatio: clip.media.frameCount / 24,
    artifact: { role: 'ENCODED', sha256: crypto.createHash('sha256').update(bytes).digest('hex'), byteSize: bytes.length, mediaContainer: 'mp4' },
  };
}

function mediaBundle(frameCount = 24) {
  return { run: { testClip: { width: 64, height: 64, exactFrameCount: frameCount, exactDurationSeconds: frameCount / 24, frameRateNumerator: 24, frameRateDenominator: 1, pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0' }, recipe: { codecFamily: 'h264', pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0', containerFormat: 'mp4' } } };
}

test('native process deadline, output budget and abort terminate owned process trees', async () => {
  const started = Date.now();
  await assert.rejects(runNativeProcess(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { timeoutMs: 80 }), /deadline/);
  assert.ok(Date.now() - started < 2000);
  await assert.rejects(runNativeProcess(process.execPath, ['-e', 'process.stdout.write("x".repeat(1000000))'], { maxBuffer: 1024 }), /output exceeded/);
  const abort = new AbortController();
  const running = runNativeProcess(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { signal: abort.signal });
  abort.abort();
  await assert.rejects(running, /cancelled/);
  const root = await mkdtemp(path.join(os.tmpdir(), 'process-tree-'));
  try {
    const pidFile = path.join(root, 'pid');
    const command = `const c=require('node:child_process').spawn(process.execPath,['-e','setInterval(()=>{},1000)']);require('node:fs').writeFileSync(${JSON.stringify(pidFile)},String(c.pid));setInterval(()=>{},1000)`;
    await assert.rejects(runNativeProcess(process.execPath, ['-e', command], { timeoutMs: 300 }), /deadline/);
    const childPid = Number(await readFile(pidFile, 'utf8'));
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.throws(() => process.kill(childPid, 0), /ESRCH/);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('real media rejects truncated/extra/wrong cadence/timestamp sequences before metric execution', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'media-contract-'));
  try {
    for (const [name, frames, rate, filter] of [['valid', 24, 24, null], ['truncated', 1, 24, null], ['extra', 25, 24, null], ['wrong-fps', 24, 30, null], ['offset', 24, 24, 'setpts=PTS+1/TB']]) {
      const file = path.join(root, `${name}.mp4`);
      await runNativeProcess('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', `testsrc2=size=64x64:rate=${rate}`, '-frames:v', String(frames), ...(filter ? ['-vf', filter] : []), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', file]);
      const probe = await probeMedia(file);
      if (name === 'valid') assert.equal(validateProbeAgainstRun(mediaBundle(), probe).durationSeconds, 1);
      else {
        assert.throws(() => validateProbeAgainstRun(mediaBundle(), probe), /frame count|frame rate|timestamp|duration/i, name);
        await assert.rejects(new FfmpegArtifactAnalyzer(DEFAULT_ANALYZER_VERSION).analyze({ bundle: mediaBundle(), artifactPath: file }), /frame count|frame rate|timestamp|duration/i);
      }
    }
    const valid = await probeMedia(path.join(root, 'valid.mp4'));
    valid.frames[5].best_effort_timestamp_time = valid.frames[4].best_effort_timestamp_time;
    assert.throws(() => validateProbeAgainstRun(mediaBundle(), valid), /timestamp/);
    valid.frames.splice(5, 1);
    assert.throws(() => validateProbeAgainstRun(mediaBundle(), valid), /frame count/);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('max keyframe interval is capped only by the suite-specified GOP, never by observed recipe intervals', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'gop-contract-'));
  try {
    const file = path.join(root, 'forced.mp4');
    await runNativeProcess('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=24', '-frames:v', '24', '-c:v', 'libx264', '-x264-params', 'scenecut=0', '-g', '16', '-pix_fmt', 'yuv420p', file]);
    const probe = await probeMedia(file);
    const base = mediaBundle();
    const withRecipe = (extra) => ({ ...base, run: { ...base.run, recipe: { ...base.run.recipe, ...extra } } });
    // Observed effective intervals (min=8 keyframeInterval, max=16 gopSize) describe the
    // reference encode; they are not an upper bound. The pre-fix server capped the max
    // interval at the observed MINIMUM and rejected valid scene-cut software output.
    assert.equal(validateProbeAgainstRun(withRecipe({ gopSize: 16, keyframeInterval: 8 }), probe).durationSeconds, 1);
    // Only the suite-requested GOP bounds the upload.
    assert.throws(() => validateProbeAgainstRun(withRecipe({ gopSize: 16, keyframeInterval: 8, requestedGopFrames: 12 }), probe), /exceeds recipe GOP 12/);
    assert.equal(validateProbeAgainstRun(withRecipe({ requestedGopFrames: 16 }), probe).durationSeconds, 1);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('VMAF rejects missing/duplicate frame coverage instead of silently accepting shortest streams', () => {
  const options = { source: { width: 64, height: 64, frameRate: 24, expectedFrameCount: 2 }, metricModelPath: 'test-model.json', analysisWorkerVersion: DEFAULT_ANALYZER_VERSION };
  assert.throws(() => buildAuthoritativeQualityAnalysisRecord({ ...options, vmafReport: { frames: [{ frameNum: 0, metrics: { vmaf: 95 } }] } }), /coverage/);
  assert.throws(() => buildAuthoritativeQualityAnalysisRecord({ ...options, vmafReport: { frames: [{ frameNum: 0, metrics: { vmaf: 95 } }, { frameNum: 0, metrics: { vmaf: 95 } }] } }), /contiguous/);
});

test('operator middleware denies anonymous and binds configured credentials', async t => {
  const token = process.env.V7_OPERATOR_TOKEN, identity = process.env.V7_OPERATOR_ID;
  process.env.V7_OPERATOR_TOKEN = 'isolated-secret'; process.env.V7_OPERATOR_ID = 'test-reviewer';
  const app = express(); app.use(express.json()); app.get('/operator', requireOperator, (_req, res) => res.json({ ok: true }));
  app.use(createArtifactPipelineRouter({ persistence: { getCompatibilityProtocols: async () => [], getRunArtifact: async () => ({ artifact: { storageUrl: '/isolated/placeholder' }, run: mediaBundle().run }) }, config: { autoAnalyzeOnUpload: false }, onDerivedRecompute: async () => {} }));
  const server = app.listen(0, '127.0.0.1'); await new Promise(resolve => server.once('listening', resolve));
  t.after(() => { server.close(); if (token === undefined) delete process.env.V7_OPERATOR_TOKEN; else process.env.V7_OPERATOR_TOKEN = token; if (identity === undefined) delete process.env.V7_OPERATOR_ID; else process.env.V7_OPERATOR_ID = identity; });
  const url = `http://127.0.0.1:${server.address().port}/operator`;
  const base = `http://127.0.0.1:${server.address().port}`;
  assert.deepEqual(await (await fetch(`${base}/v7/compatibility`)).json(), { protocolVersion: '7.1', minimumClientVersion: 'client/0.3.0', encodeTimerBoundary: 'ffmpeg-process-v1', sourceSuiteVersion: 'encodingdb-test-suite-v1', suiteFingerprint: 'd40bff563dead0e78003af90b2626003bd80afcc12220ab86bc6d4a4b8c83b6e', activeProtocolId: null });
  assert.equal((await fetch(`${base}/v7/benchmark-runs/run/artifacts/ENCODED/reanalyze`, { method: 'POST' })).status, 401);
  assert.equal((await fetch(`${base}/v7/benchmark-runs/run/artifacts/ENCODED/reanalyze`, { method: 'POST', headers: { authorization: 'Bearer isolated-secret', 'content-type': 'application/json' }, body: JSON.stringify({ reason: 'Inspect installed implementation', analysisWorkerVersion: 'invented-authority' }) })).status, 409);
  assert.equal((await fetch(url)).status, 401);
  assert.equal((await fetch(url, { headers: { authorization: 'Bearer wrong' } })).status, 401);
  assert.equal((await fetch(url, { headers: { authorization: 'Bearer isolated-secret' } })).status, 200);
});

const databaseUrl = process.env.BACKEND_TEST_DATABASE_URL ? new URL(process.env.BACKEND_TEST_DATABASE_URL) : null;
if (databaseUrl && process.env.BACKEND_TEST_TIMEZONE) databaseUrl.searchParams.set('options', `-c timezone=${process.env.BACKEND_TEST_TIMEZONE}`);
test('PostgreSQL admission, upload slots, monotonic retries, lease fencing and durable recovery', { skip: !databaseUrl }, async t => {
  const client = new PrismaClient({ datasources: { db: { url: databaseUrl.toString() } } });
  const replica = new PrismaClient({ datasources: { db: { url: databaseUrl.toString() } } });
  if (process.env.BACKEND_TEST_TIMEZONE) assert.equal((await client.$queryRawUnsafe('SHOW TimeZone'))[0].TimeZone, process.env.BACKEND_TEST_TIMEZONE);
  const root = await mkdtemp(path.join(os.tmpdir(), 'pg-backend-'));
  let backgroundService;
  t.after(async () => { backgroundService?.stopBackgroundWork(); await client.$disconnect(); await replica.$disconnect(); await rm(root, { recursive: true, force: true }); });
  // This file requires its own migrated isolated DB, never the application DATABASE_URL.
  assert.match(new URL(databaseUrl).pathname, /encodingdb_backend$/);
  await client.$executeRawUnsafe('TRUNCATE "BenchmarkRun", "BenchmarkProtocol", "TestClip", "Recipe", "Environment" CASCADE');
  const config = mergeArtifactPipelineConfig({ autoAnalyzeOnUpload: false, validateMediaBeforePublish: false, storage: { rootDir: root, provider: 'localfs', bucket: null }, storageReserveBytes: 0, maxPendingArtifacts: 2, maxPendingAnalyses: 20, maxConcurrentUploads: 1, analysisMaxConcurrent: 1 });
  const persistence = createPrismaArtifactPipelinePersistence(client, config);
  const service = new ArtifactPipelineService(persistence, { analyze: async () => { throw new Error('unused'); } }, config, manifest);
  const body = requestBody();
  for (const change of [{ inputHash: '0'.repeat(64) }, { sourceFrameCount: 1 }, { encodedFrameCount: 241 }, { sourceFps: 30 }, { encodeFps: 1e99 }, { realTimeRatio: 0.1 }, { encodeWallTimeMs: 0 }, { encodeTimerBoundary: 'old-timer' }]) {
    await assert.rejects(service.createRun({ ...body, ...change }), /canonical|boundary|tuple|encodeWallTime|source/i);
  }
  await assert.rejects(service.createRun({ ...body, testClip: { ...body.testClip, sha256: '0'.repeat(64) } }), /sha256/);
  const same = await Promise.all(Array.from({ length: 12 }, () => service.createRun(body)));
  assert.equal(new Set(same.map(x => x.bundle.run.id)).size, 1);
  assert.equal(same.filter(x => x.created).length, 1);
  await assert.rejects(service.createRun({ ...body, physicalSourceId: 'different-source-0001' }), /Idempotency key conflicts/);
  const first = same[0].bundle;
  const created = await client.benchmarkRun.findUnique({ where: { id: first.run.id }, include: { artifacts: true } });
  assert.ok(Math.abs(Date.now() - created.createdAt.getTime()) < 2000, 'run chronology is UTC in every session timezone');
  assert.equal(created.artifacts[0].createdAt.getTime(), created.createdAt.getTime());
  const second = (await service.createRun(requestBody())).bundle;
  await assert.rejects(service.createRun(requestBody()), /backlog capacity/);
  const authorization = await service.authorizeUpload('test', first.run.id, 'ENCODED', { ...body.artifact, contentType: 'video/mp4' });
  assert.ok(authorization.token, 'at-cap valid reservations can drain');
  const replicaPersistence = createPrismaArtifactPipelinePersistence(replica, config);
  const slots = await Promise.all([first, second].map((bundle, index) => [persistence, replicaPersistence][index].claimUploadSlot(bundle.artifact.id, 'upload-owner', new Date(Date.now() + 5000), 1)));
  assert.equal(slots.filter(Boolean).length, 1);
  for (const bundle of [first, second]) await persistence.releaseUploadSlot(bundle.artifact.id, 'upload-owner');
  let releaseCapacity, capacityLocked;
  const capacityReady = new Promise(resolve => { capacityLocked = resolve; });
  const capacityRelease = new Promise(resolve => { releaseCapacity = resolve; });
  const heldCapacity = client.$transaction(async tx => { await tx.$executeRawUnsafe('SELECT pg_advisory_xact_lock(714552)'); capacityLocked(); await capacityRelease; });
  await capacityReady;
  const delayedSlot = replicaPersistence.claimUploadSlot(first.artifact.id, 'delayed-slot', new Date(Date.now() + 100), 1);
  await new Promise(resolve => setTimeout(resolve, 180));
  releaseCapacity(); await heldCapacity;
  const grantedDeadline = await delayedSlot;
  assert.ok(grantedDeadline instanceof Date && grantedDeadline.getTime() > Date.now(), 'slot deadline starts after lock acquisition');
  assert.equal(await persistence.claimUploadSlot(second.artifact.id, 'second-slot', new Date(Date.now() + 100), 1), null, 'waiting cannot create two live slots');
  await persistence.releaseUploadSlot(first.artifact.id, 'delayed-slot');

  await assert.rejects(service.acceptUploadStream('test', authorization.token, 'video/mp4', String(body.artifact.byteSize), Readable.from([Buffer.from('evil-video')])), /sha256/);
  assert.equal((await service.getBundle(first.run.id, 'ENCODED')).artifact.storageState, 'PENDING', 'transport corruption leaves the immutable reservation recoverable');
  await service.acceptUploadStream('test', authorization.token, 'video/mp4', String(body.artifact.byteSize), Readable.from([Buffer.from('test-video')]));
  const third = (await service.createRun(requestBody())).bundle;
  await client.artifact.update({ where: { id: second.artifact.id }, data: { reservationExpiresAt: new Date(0) } });
  assert.equal((await service.createRun(requestBody())).created, true, 'expired reservation capacity reclaimed');
  await assert.rejects(service.authorizeUpload('test', second.run.id, 'ENCODED', { sha256: second.artifact.sha256, byteSize: second.artifact.byteSize }), /backlog capacity/);
  const queueInput = { benchmarkRunId: first.run.id, artifactId: first.artifact.id, metricModelId: 'vmaf-v1-sdr-1080p', analysisWorkerVersion: DEFAULT_ANALYZER_VERSION, maxAttempts: 2, operatorAudit: { operator: 'TEST ONLY', reason: 'Preserve the original queue audit through completion' } };
  await persistence.ensureQualityAnalysisQueued(queueInput);
  const queuedRow = await client.qualityAnalysis.findFirst({ where: { benchmarkRunId: first.run.id } });
  assert.ok(Math.abs(Date.now() - queuedRow.createdAt.getTime()) < 2000, 'queue chronology is UTC in every session timezone');
  assert.equal(queuedRow.createdAt.toISOString(), queuedRow.analysisProvenance.queuedAt);
  const owner = await persistence.claimNextQueuedQualityAnalysis({ leaseToken: 'owner-1', leaseExpiresAt: new Date(Date.now() + 5000), now: new Date() });
  assert.ok(owner);
  await Promise.all(Array.from({ length: 8 }, () => persistence.ensureQualityAnalysisQueued(queueInput)));
  assert.equal((await client.qualityAnalysis.findUnique({ where: { id: owner.analysis.id } })).leaseToken, 'owner-1');
  assert.equal(await persistence.renewAnalysisLease(owner.analysis.id, 'wrong-owner', new Date(Date.now() + 5000)), false);
  assert.equal(await persistence.renewAnalysisLease(owner.analysis.id, 'owner-1', new Date(Date.now() + 5000)), true);
  // Start each mutation while the lease is alive, block its row lock until after expiry.
  for (const mutation of ['retry', 'failure', 'completion', 'renewal']) {
    await client.qualityAnalysis.update({ where: { id: owner.analysis.id }, data: { leaseToken: 'owner-1', leaseExpiresAt: new Date(Date.now() + 150) } });
    let releaseRow, rowLocked;
    const rowReady = new Promise(resolve => { rowLocked = resolve; });
    const rowRelease = new Promise(resolve => { releaseRow = resolve; });
    const heldRow = client.$transaction(async tx => { await tx.$queryRawUnsafe('SELECT id FROM "QualityAnalysis" WHERE id = $1 FOR UPDATE', owner.analysis.id); rowLocked(); await rowRelease; });
    await rowReady;
    const identity = { ...queueInput, analysisId: owner.analysis.id, leaseToken: 'owner-1', errorMessage: 'expired while waiting', nextRetryAt: new Date() };
    const operation = mutation === 'retry' ? persistence.markQualityAnalysisRetry(identity)
      : mutation === 'failure' ? persistence.markQualityAnalysisFailed(identity)
      : mutation === 'renewal' ? persistence.renewAnalysisLease(owner.analysis.id, 'owner-1', new Date(Date.now() + 5000))
      : persistence.saveAuthoritativeAnalysis({ ...identity, result: {} });
    const observed = operation.then(value => ({ value }), error => ({ error }));
    await new Promise(resolve => setTimeout(resolve, 220));
    releaseRow(); await heldRow;
    const outcome = await observed;
    if (mutation === 'renewal') assert.equal(outcome.value, false);
    else assert.match(String(outcome.error), /ownership expired/, mutation);
  }

  await client.qualityAnalysis.update({ where: { id: owner.analysis.id }, data: { leaseExpiresAt: new Date(0) } });
  const successor = await persistence.claimNextQueuedQualityAnalysis({ leaseToken: 'owner-2', leaseExpiresAt: new Date(Date.now() + 5000), now: new Date() });
  assert.equal(successor.analysis.id, owner.analysis.id);
  const result = { metricModelId: queueInput.metricModelId, analysisWorkerVersion: DEFAULT_ANALYZER_VERSION, analysisStatus: 'COMPLETE', analysisProvenance: {}, runStatus: 'ACCEPTED', artifactState: 'RETAINED' };
  await assert.rejects(persistence.saveAuthoritativeAnalysis({ ...queueInput, analysisId: owner.analysis.id, leaseToken: 'owner-1', result }), /ownership/);
  await assert.rejects(persistence.markQualityAnalysisRetry({ ...queueInput, analysisId: owner.analysis.id, leaseToken: 'owner-1', nextRetryAt: new Date(), errorMessage: 'late error' }), /ownership/);
  await persistence.saveAuthoritativeAnalysis({ ...queueInput, analysisId: owner.analysis.id, leaseToken: 'owner-2', result });
  assert.deepEqual((await client.qualityAnalysis.findUnique({ where: { id: owner.analysis.id } })).analysisProvenance.operatorAudit, queueInput.operatorAudit);
  for (const state of ['RETAINED', 'VERIFIED', 'REJECTED']) {
    await client.artifact.update({ where: { id: first.artifact.id }, data: { storageState: state } });
    const retry = await service.acceptUploadStream('test', authorization.token, 'video/mp4', String(body.artifact.byteSize), Readable.from([Buffer.from('test-video')]));
    assert.equal(retry.artifact.storageState, state);
    assert.equal(retry.qualityAnalyses.length, 1);
  }
  await assert.rejects(service.acceptUploadStream('test', authorization.token, 'video/mp4', String(body.artifact.byteSize), Readable.from([Buffer.from('evil-video')])), /sha256/);
  assert.equal((await service.getBundle(first.run.id, 'ENCODED')).artifact.storageState, 'REJECTED');
  // Operator requeue audit must survive the exact re-upload completions it enables, on Prisma.
  const priorRejection = await client.artifact.findUniqueOrThrow({ where: { id: first.artifact.id } });
  await persistence.requeueRejectedArtifact({ artifactId: first.artifact.id, operator: 'TEST OPERATOR', reason: 'audit preservation regression' });
  const requeuedRow = await client.artifact.findUniqueOrThrow({ where: { id: first.artifact.id } });
  assert.equal(requeuedRow.storageState, 'PENDING');
  assert.equal(requeuedRow.stateReason, 'OPERATOR_REQUEUED');
  assert.equal(requeuedRow.stateDetails.operatorRequeue.priorStateReason, priorRejection.stateReason);
  const reauth = await service.authorizeUpload('test', first.run.id, 'ENCODED', { ...body.artifact, contentType: 'video/mp4' });
  assert.equal(reauth.uploadRequired, false, 'sealed bytes dedup onto the stored object');
  const dedupCompleted = await client.artifact.findUniqueOrThrow({ where: { id: first.artifact.id } });
  assert.equal(dedupCompleted.storageState, 'UPLOADED');
  assert.equal(dedupCompleted.stateDetails.reusedExistingObject, true);
  assert.equal(dedupCompleted.stateDetails.operatorRequeue.reason, 'audit preservation regression', 'requeue audit survives dedup completion');
  assert.equal(dedupCompleted.sha256, priorRejection.sha256);
  assert.equal(dedupCompleted.byteSize, priorRejection.byteSize);
  await client.artifact.update({ where: { id: third.artifact.id }, data: { storageState: 'REJECTED', stateReason: 'fixture-rejection', stateDetails: { failedAt: 'fixture' } } });
  await persistence.requeueRejectedArtifact({ artifactId: third.artifact.id, operator: 'TEST OPERATOR', reason: 'stream completion preserves audit' });
  await rm(path.join(root, dedupCompleted.storageKey), { force: true });
  const streamAuth = await service.authorizeUpload('test', third.run.id, 'ENCODED', { ...body.artifact, contentType: 'video/mp4' });
  assert.equal(streamAuth.uploadRequired, true, 'stream path after the stored object was removed');
  await service.acceptUploadStream('test', streamAuth.token, 'video/mp4', String(body.artifact.byteSize), Readable.from([Buffer.from('test-video')]));
  const streamCompleted = await client.artifact.findUniqueOrThrow({ where: { id: third.artifact.id } });
  assert.equal(streamCompleted.storageState, 'UPLOADED');
  assert.equal(streamCompleted.stateDetails.deduplicated, false);
  assert.equal(streamCompleted.stateDetails.operatorRequeue.reason, 'stream completion preserves audit', 'requeue audit survives stream completion');
  await persistence.retryDerivedRecomputes(async () => { throw new Error('aggregate storage unavailable'); });
  assert.equal((await client.qualityAnalysis.findUnique({ where: { id: owner.analysis.id } })).status, 'COMPLETE');
  assert.equal((await client.qualityAnalysis.findUnique({ where: { id: owner.analysis.id } })).recomputePending, true);
  let recomputes = 0;
  await persistence.retryDerivedRecomputes(async () => { recomputes++; });
  assert.equal(recomputes, 1);
  assert.equal((await client.qualityAnalysis.findUnique({ where: { id: owner.analysis.id } })).recomputePending, false);
  // A stale recompute acknowledgement cannot erase a newer review invalidation.
  const observed = await client.qualityAnalysis.findUnique({ where: { id: owner.analysis.id } });
  await new Promise(resolve => setTimeout(resolve, 5));
  await client.qualityAnalysis.update({ where: { id: owner.analysis.id }, data: { recomputePending: true } });
  await persistence.completeDerivedRecompute(owner.analysis.id, observed.updatedAt);
  assert.equal((await client.qualityAnalysis.findUnique({ where: { id: owner.analysis.id } })).recomputePending, true);
  await client.artifact.update({ where: { id: third.artifact.id }, data: { storageState: 'UPLOADED', storageUrl: '/isolated/test' } });
  await persistence.ensureQualityAnalysisQueued({ ...queueInput, benchmarkRunId: third.run.id, artifactId: third.artifact.id });
  const poison = await persistence.claimNextQueuedQualityAnalysis({ leaseToken: 'poison', leaseExpiresAt: new Date(Date.now() + 50), now: new Date() });
  await client.qualityAnalysis.update({ where: { id: poison.analysis.id }, data: { attemptCount: 2, leaseExpiresAt: new Date(0) } });
  await persistence.claimNextQueuedQualityAnalysis({ leaseToken: 'new', leaseExpiresAt: new Date(Date.now() + 5000), now: new Date() });
  assert.equal((await client.qualityAnalysis.findUnique({ where: { id: poison.analysis.id } })).status, 'FAILED');
  await client.artifact.updateMany({ where: { storageState: 'PENDING' }, data: { reservationExpiresAt: new Date(0) } });
  const slowConfig = { ...config, autoAnalyzeOnUpload: true, analysisLeaseMs: 2000, analysisPollIntervalMs: 10 };
  let calls = 0;
  const slowService = new ArtifactPipelineService(persistence, { async analyze() { calls++; await new Promise(resolve => setTimeout(resolve, 5000)); return result; } }, slowConfig, manifest, async () => {});
  backgroundService = slowService;
  const slowRun = (await slowService.createRun(requestBody())).bundle;
  await slowService.authorizeUpload('test', slowRun.run.id, 'ENCODED', { sha256: body.artifact.sha256, byteSize: body.artifact.byteSize });
  for (let index = 0; index < 18; index++) {
    await new Promise(resolve => setTimeout(resolve, 400));
    const competing = await replicaPersistence.claimNextQueuedQualityAnalysis({ leaseToken: 'competing', leaseExpiresAt: new Date(Date.now() + 1000), now: new Date() });
    assert.equal(competing, null, 'healthy slow job renews its lease');
  }
  assert.equal(calls, 1);
  assert.equal((await slowService.getBundle(slowRun.run.id, 'ENCODED')).qualityAnalyses[0].status, 'COMPLETE');
  slowService.stopBackgroundWork();
  await client.artifact.updateMany({ where: { storageState: 'PENDING' }, data: { reservationExpiresAt: new Date(0) } });
  const pressureService = new ArtifactPipelineService(persistence, {}, { ...config, storageQuotaBytes: 1 }, manifest);
  const quotaBody = requestBody();
  await assert.rejects(pressureService.createRun(quotaBody), /quota/);
  assert.equal(await client.benchmarkRun.count({ where: { payloadHash: quotaBody.payloadHash } }), 0, 'quota rollback leaves no orphan run');
  const diskService = new ArtifactPipelineService(persistence, {}, { ...config, storageReserveBytes: Number.MAX_SAFE_INTEGER }, manifest);
  await assert.rejects(diskService.createRun(quotaBody), /filesystem reserve/);
  const burst = await Promise.allSettled(Array.from({ length: 25 }, () => service.createRun(requestBody())));
  assert.equal(burst.filter(entry => entry.status === 'fulfilled').length, 2, '25 contributors reserve at most capacity two');
  assert.ok(burst.filter(entry => entry.status === 'rejected').every(entry => /backlog capacity/.test(entry.reason.message)));
  const metrics = { vmafMean: 95, vmafP5: 90, videoBitrateBps: 1_000_000, fileSizeBytes: 10000 };
  const newRun = burst.find(entry => entry.status === 'fulfilled').value.bundle;
  const groupReceipt = { schemaVersion: 'encodingdb-measurement-group/v1', campaignId: 'snapshot-group', repetitionGroupId: 'snapshot-group', completed: true, countedAttempts: [1, 2].map(repetitionIndex => ({ repetitionIndex, encodeWallTimeMs: 1000 })) };
  for (const [index, bundle] of [slowRun, newRun].entries()) await client.benchmarkRun.update({ where: { id: bundle.run.id }, data: { campaignId: 'snapshot-group', repetitionGroupId: 'snapshot-group', repetitionIndex: index + 1, preRunEnvironmentCheck: { ...body.preRunEnvironmentCheck, snapshot: { telemetry_sources: 'cpu_psutil_thread_window_v1', background_cpu_pct: 0 }, measurementGroup: groupReceipt } } });
  await client.qualityAnalysis.updateMany({ where: { benchmarkRunId: slowRun.run.id }, data: { analysisProvenance: { workerBuildFingerprint: 'a'.repeat(64) } } });

  await client.qualityAnalysis.updateMany({ where: { benchmarkRunId: slowRun.run.id }, data: metrics });
  const oldAnalysis = await client.qualityAnalysis.create({ data: { createdAt: new Date(), benchmarkRunId: slowRun.run.id, artifactId: slowRun.artifact.id, status: 'COMPLETE', metricModelId: queueInput.metricModelId, analysisWorkerVersion: 'historical-test-worker', analysisProvenance: {}, createdAt: new Date('2000-01-01'), completedAt: new Date('2000-01-01'), ...metrics, vmafMean: 100, vmafP5: 100 } });
  await appendEvidenceReview(client, oldAnalysis.id, 'SYNTHETIC TEST FIXTURE NOT HUMAN REVIEW', { benchmarkRunId: slowRun.run.id, artifactId: slowRun.artifact.id, artifactSha256: slowRun.artifact.sha256, metricModelId: queueInput.metricModelId, analysisWorkerVersion: 'historical-test-worker', decision: 'EXPECTED', rationale: 'Synthetic old-analysis selection regression only', evidenceLinks: ['https://example.test/synthetic-fixture'], supersedesId: null });
  const context = await client.scoreContext.create({ data: { benchmarkProtocolId: slowRun.run.benchmarkProtocolId, formulaVersion: '7.0', contextVersion: `isolated-${crypto.randomUUID()}`, workloadId: slowRun.run.workloadId, qualityModelId: queueInput.metricModelId, workloadReferenceBitrateBps: 1_000_000, transformConstants: {} } });
  const activeEnv = {};
  async function deployContext(record) {
    const policy = { ...DEFAULT_RECOMMENDATION_EVIDENCE_POLICY, policyStatus: 'CALIBRATED', policyVersion: `SYNTHETIC-${record.contextVersion}` };
    const payload = { contextVersion: record.contextVersion, formulaVersion: record.formulaVersion, qualityModelId: record.qualityModelId, benchmarkProtocolVersion: SERVER_CANONICAL_PROTOCOL_VERSION, sourceSuiteVersion: manifest.suiteVersion,
      transformConstants: record.transformConstants, scoringBehaviorHash: buildScoringBehaviorHash(), provenance: { sourceMode: 'retained-benchmark-evidence' }, activation: { stage: 'PRODUCTION', productionActivationAllowed: true, calibrationReviewHash: 'a'.repeat(64) },
      recommendationEvidencePolicy: policy, recommendationEvidencePolicyHash: sha256Hex(canonicalJsonString(policy)), workloads: [{ workloadId: record.workloadId, workloadReferenceBitrateBps: record.workloadReferenceBitrateBps, referenceFrontier: [] }] };
    const active = { ...payload, hash: sha256Hex(canonicalJsonString(payload)) };
    const filename = path.join(root, `${record.contextVersion}.json`);
    await writeFile(filename, JSON.stringify(active));
    await client.scoreContext.update({ where: { id: record.id }, data: { referenceFrontier: { contextHash: active.hash, recommendationEvidencePolicy: policy, recommendationEvidencePolicyHash: active.recommendationEvidencePolicyHash, referenceFrontier: [] } } });
    activeEnv.PL_V7_REFERENCE_CONTEXT_PATH = filename;
    return active;
  }
  await deployContext(context);
  let releaseSnapshot, snapshotReady;
  const ready = new Promise(resolve => { snapshotReady = resolve; });
  const release = new Promise(resolve => { releaseSnapshot = resolve; });
  let snapshots = 0;
  const wrappedClient = { $transaction: (callback, options) => client.$transaction(async tx => {
    const proxy = new Proxy(tx, { get(target, name) {
      if (name === 'qualityAnalysis') return { ...target.qualityAnalysis, findMany: async args => {
        const rows = await target.qualityAnalysis.findMany(args);
        snapshots++;
        if (snapshots === 1) { snapshotReady(); await release; }
        return rows;
      } };
      return target[name];
    } });
    return callback(proxy);
  }, options) };
  const rebuild = createDefaultDerivedRecomputeCallback(wrappedClient, activeEnv);
  const rebuildPayload = { benchmarkRunId: slowRun.run.id, artifactId: slowRun.artifact.id, metricModelId: queueInput.metricModelId, analysisWorkerVersion: DEFAULT_ANALYZER_VERSION };
  const older = rebuild(rebuildPayload);
  await ready;
  await client.benchmarkRun.update({ where: { id: newRun.run.id }, data: { status: 'ACCEPTED' } });
  await client.artifact.update({ where: { id: newRun.artifact.id }, data: { storageState: 'RETAINED', storageProvider: 'localfs', storageKey: 'test/object', storageUrl: '/test/object' } });
  await client.qualityAnalysis.create({ data: { createdAt: new Date(), benchmarkRunId: newRun.run.id, artifactId: newRun.artifact.id, status: 'COMPLETE', metricModelId: queueInput.metricModelId, analysisWorkerVersion: DEFAULT_ANALYZER_VERSION, analysisProvenance: { workerBuildFingerprint: 'a'.repeat(64) }, ...metrics } });
  const newer = rebuild(rebuildPayload);
  await new Promise(resolve => setTimeout(resolve, 40));
  assert.equal(snapshots, 1, 'second recomputation cannot read ahead of a locked snapshot');
  releaseSnapshot();
  await Promise.all([older, newer]);
  const aggregate = await client.derivedResult.findFirst({ where: { scoreContextId: context.id, kind: 'WORKLOAD' }, include: { members: true } });
  assert.equal(aggregate.acceptedRunCount, 2);
  assert.equal(aggregate.centerVmafMean, 95, 'updating old evidence cannot resurrect its superseded analysis');
  assert.equal(aggregate.members.length, 2, 'newer complete member set wins after out-of-order scheduling');
  await client.qualityAnalysis.updateMany({ data: { recomputePending: false } });
  const groupRun = await client.benchmarkRun.findUnique({ where: { id: slowRun.run.id } });
  await client.benchmarkRun.update({ where: { id: slowRun.run.id }, data: { preRunEnvironmentCheck: { ...groupRun.preRunEnvironmentCheck, snapshot: { telemetry_sources: 'cpu_psutil_blocking_window_v1', background_cpu_pct: 0 } } } });
  assert.equal((await client.$queryRawUnsafe('SELECT count(*)::int AS count FROM "DerivedResultGroupDependency" WHERE "derivedResultId" = $1 AND "invalidatedAt" IS NOT NULL', aggregate.id))[0].count, 1);
  const previousContextPath = process.env.PL_V7_REFERENCE_CONTEXT_PATH;
  let dependencyRebuilds = 0;
  try {
    process.env.PL_V7_REFERENCE_CONTEXT_PATH = activeEnv.PL_V7_REFERENCE_CONTEXT_PATH;
    await replicaPersistence.retryDerivedRecomputes(async payload => { dependencyRebuilds++; await createDefaultDerivedRecomputeCallback(replica, activeEnv)(payload); });
    const beforeUpgrade = await client.derivedResult.findUnique({ where: { id: aggregate.id }, include: { members: { orderBy: { qualityAnalysisId: 'asc' } } } });
    await client.derivedResult.update({ where: { id: aggregate.id }, data: { evidenceSummary: { ...beforeUpgrade.evidenceSummary, measurementGroupSnapshot: { ...beforeUpgrade.evidenceSummary.measurementGroupSnapshot, version: 'measurement-group-state/v2' } } } });
    assert.equal((await client.$queryRawUnsafe('SELECT count(*)::int AS count FROM "DerivedResultGroupDependency" WHERE "derivedResultId" = $1 AND "invalidatedAt" IS NOT NULL', aggregate.id))[0].count, 0, 'format upgrade does not depend on source invalidation');
    assert.equal(await client.qualityAnalysis.count({ where: { recomputePending: true } }), 0);
    await replicaPersistence.retryDerivedRecomputes(createDefaultDerivedRecomputeCallback(replica, activeEnv));
    const afterUpgrade = await client.derivedResult.findUnique({ where: { id: aggregate.id }, include: { members: { orderBy: { qualityAnalysisId: 'asc' } } } });
    assert.equal(afterUpgrade.evidenceSummary.measurementGroupSnapshot.version, 'measurement-group-state/v3', 'restart upgrades active v2 certificates even with clean dependencies');
    assert.equal(afterUpgrade.plTotal, beforeUpgrade.plTotal);
    assert.deepEqual(afterUpgrade.members.map(m => [m.benchmarkRunId, m.qualityAnalysisId]), beforeUpgrade.members.map(m => [m.benchmarkRunId, m.qualityAnalysisId]), 'format upgrade revalidates the exact retained membership');
  } finally {
    if (previousContextPath === undefined) delete process.env.PL_V7_REFERENCE_CONTEXT_PATH;
    else process.env.PL_V7_REFERENCE_CONTEXT_PATH = previousContextPath;
  }
  assert.equal(dependencyRebuilds, 1, 'a restarted dispatcher discovers dirty active dependencies even with no QA retry flag');
  assert.equal((await client.$queryRawUnsafe('SELECT count(*)::int AS count FROM "DerivedResultGroupDependency" WHERE "derivedResultId" = $1 AND "invalidatedAt" IS NOT NULL', aggregate.id))[0].count, 0);
  const pendingReplacement = await client.qualityAnalysis.create({ data: { createdAt: new Date(), benchmarkRunId: slowRun.run.id, artifactId: slowRun.artifact.id, status: 'PENDING', metricModelId: queueInput.metricModelId, analysisWorkerVersion: 'replacement-test-worker', analysisProvenance: {} } });
  await rebuild(rebuildPayload);
  assert.equal((await client.derivedResult.findUnique({ where: { id: aggregate.id } })).acceptedRunCount, 1, 'new pending analysis blocks reviewed older evidence');
  await client.qualityAnalysis.update({ where: { id: pendingReplacement.id }, data: { status: 'FAILED' } });
  const historical = await client.derivedResult.findUnique({ where: { id: aggregate.id }, include: { members: { orderBy: { id: 'asc' } } } });
  const contextB = await client.scoreContext.create({ data: { benchmarkProtocolId: context.benchmarkProtocolId, formulaVersion: context.formulaVersion, contextVersion: `B-${crypto.randomUUID()}`, workloadId: context.workloadId, qualityModelId: context.qualityModelId, workloadReferenceBitrateBps: context.workloadReferenceBitrateBps, transformConstants: context.transformConstants } });
  await deployContext(contextB);
  const newest = await client.qualityAnalysis.create({ data: { createdAt: new Date(), completedAt: new Date(), benchmarkRunId: slowRun.run.id, artifactId: slowRun.artifact.id, status: 'COMPLETE', metricModelId: queueInput.metricModelId, analysisWorkerVersion: 'B-test-worker', analysisProvenance: {}, ...metrics, vmafMean: 94 } });
  await rebuild(rebuildPayload);
  const activeResult = await client.derivedResult.findFirst({ where: { scoreContextId: contextB.id, kind: 'WORKLOAD' } });
  assert.equal(activeResult.acceptedRunCount, 2, 'active B rebuilds even though historical A would fail the current policy loader');
  await appendEvidenceReview(client, newest.id, 'SYNTHETIC TEST FIXTURE NOT HUMAN REVIEW', { benchmarkRunId: slowRun.run.id, artifactId: slowRun.artifact.id, artifactSha256: slowRun.artifact.sha256, metricModelId: queueInput.metricModelId, analysisWorkerVersion: 'B-test-worker', decision: 'INVESTIGATE', rationale: 'Synthetic active-context review regression only', evidenceLinks: ['https://example.test/context-fixture'], supersedesId: null });
  await persistence.retryDerivedRecomputes(createDefaultDerivedRecomputeCallback(replica, activeEnv));
  assert.equal((await client.derivedResult.findUnique({ where: { id: activeResult.id } })).acceptedRunCount, 1);
  assert.deepEqual(await client.derivedResult.findUnique({ where: { id: aggregate.id }, include: { members: { orderBy: { id: 'asc' } } } }), historical, 'historical A metrics, members and policy survive new B analysis, review and restart');

  await client.artifact.updateMany({ where: { storageState: 'PENDING' }, data: { reservationExpiresAt: new Date(0) } });
  const fractionalMs = 1990.073417;
  const fractionalBody = { ...requestBody(), encodeWallTimeMs: fractionalMs, encodeFps: clip.media.frameCount * 1000 / fractionalMs, realTimeRatio: clip.media.frameCount / 24 * 1000 / fractionalMs };
  const fractionalRun = (await service.createRun(fractionalBody)).bundle;
  assert.equal(fractionalRun.run.encodeWallTimeMs, fractionalMs, 'actual client fractional milliseconds survive intake and database roundtrip');
  const malformedFile = path.join(root, 'one-frame.mp4');
  await runNativeProcess('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=1920x1080:rate=24', '-frames:v', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv', malformedFile]);
  const malformedBytes = await readFile(malformedFile);
  const actualWorker = new ArtifactPipelineService(persistence, new FfmpegArtifactAnalyzer(DEFAULT_ANALYZER_VERSION), { ...config, autoAnalyzeOnUpload: true, analysisMaxAttempts: 1, analysisPollIntervalMs: 20 }, manifest);
  backgroundService = actualWorker;
  const malformed = (await actualWorker.createRun(requestBody(undefined, malformedBytes))).bundle;
  const badAuth = await actualWorker.authorizeUpload('test', malformed.run.id, 'ENCODED', { sha256: malformed.artifact.sha256, byteSize: malformed.artifact.byteSize });
  await actualWorker.acceptUploadStream('test', badAuth.token, null, String(malformedBytes.length), Readable.from([malformedBytes]));
  let rejected;
  const limit = Date.now() + 10_000;
  do { await new Promise(resolve => setTimeout(resolve, 50)); rejected = await actualWorker.getBundle(malformed.run.id, 'ENCODED'); } while (rejected.run.status === 'PENDING' && Date.now() < limit);
  assert.equal(rejected.run.status, 'INVALID');
  assert.equal(rejected.qualityAnalyses[0].status, 'FAILED');
  assert.match(rejected.qualityAnalyses[0].lastError, /frame count|frame rate|duration/);
  assert.equal((await readFile(rejected.artifact.storageUrl)).equals(malformedBytes), true, 'poison media remains available as exact evidence');
  actualWorker.stopBackgroundWork();
  await client.artifact.updateMany({ where: { storageState: 'PENDING' }, data: { reservationExpiresAt: new Date(0) } });
  let entered, resumePhase, phaseDone;
  const phaseReady = new Promise(resolve => { entered = resolve; });
  const phaseResume = new Promise(resolve => { resumePhase = resolve; });
  const phaseFinished = new Promise(resolve => { phaseDone = resolve; });
  const forbiddenOutput = path.join(root, 'post-shutdown-native-output');
  const pausedWorker = new ArtifactPipelineService(persistence, { async analyze() {
    entered(); await phaseResume;
    try { await runNativeProcess(process.execPath, ['-e', `require('node:fs').writeFileSync(${JSON.stringify(forbiddenOutput)},'wrong')`]); return result; }
    finally { phaseDone(); }
  } }, { ...config, autoAnalyzeOnUpload: true }, manifest);
  backgroundService = pausedWorker;
  const pausedRun = (await pausedWorker.createRun(requestBody())).bundle;
  await pausedWorker.authorizeUpload('test', pausedRun.run.id, 'ENCODED', { sha256: body.artifact.sha256, byteSize: body.artifact.byteSize });
  await phaseReady;
  pausedWorker.stopBackgroundWork(); stopNativeProcesses(); resumePhase();
  await phaseFinished;
  await new Promise(resolve => setTimeout(resolve, 80));
  assert.equal(await stat(forbiddenOutput).catch(() => null), null, 'shutdown cancels native phases that have not spawned yet');
  assert.notEqual((await pausedWorker.getBundle(pausedRun.run.id, 'ENCODED')).qualityAnalyses[0].status, 'COMPLETE');
  let claimReady, releaseClaim;
  const claimStarted = new Promise(resolve => { claimReady = resolve; });
  const claimRelease = new Promise(resolve => { releaseClaim = resolve; });
  const delayedPersistence = { ...persistence, async claimNextQueuedQualityAnalysis(input) {
    const claimed = await persistence.claimNextQueuedQualityAnalysis(input);
    if (claimed) { claimReady(); await claimRelease; }
    return claimed;
  } };
  let launches = 0;
  const stoppingWorker = new ArtifactPipelineService(delayedPersistence, { async analyze() { launches++; return result; } }, { ...config, autoAnalyzeOnUpload: true }, manifest);
  backgroundService = stoppingWorker;
  const stoppedRun = (await stoppingWorker.createRun(requestBody())).bundle;
  await stoppingWorker.authorizeUpload('test', stoppedRun.run.id, 'ENCODED', { sha256: body.artifact.sha256, byteSize: body.artifact.byteSize });
  await claimStarted;
  stoppingWorker.stopBackgroundWork(); releaseClaim();
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal(launches, 0, 'an awaited claim cannot launch analysis after stop');




});
