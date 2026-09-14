import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID, createHash } from 'node:crypto';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { PrismaClient } from '@prisma/client';
import { verifyCalibrationRetainedEvidence } from '../dist/v7/calibrationRetention.js';

test('live PostgreSQL and retained object verification rejects relabeled measurements, identities and bytes', { skip: !process.env.CALIBRATION_TEST_DATABASE_URL }, async () => {
  const db = new PrismaClient({ datasources: { db: { url: process.env.CALIBRATION_TEST_DATABASE_URL } } });
  const suffix = randomUUID();
  const root = await mkdtemp(path.join(os.tmpdir(), 'encodingdb-retention-test-'));
  const bytes = Buffer.from('TEST ONLY object identity fixture; not video calibration');
  const hash = createHash('sha256').update(bytes).digest('hex');
  await writeFile(path.join(root, 'retained.bin'), bytes);
  try {
    const protocol = await db.benchmarkProtocol.create({ data: {
      protocolVersion: `7.1`, sourceSuiteVersion: 'test-only', minimumClientVersion: 'client/0.3.0',
      canonicalRecipeRules: {}, canonicalOutputRules: {}, metricWorkerVersion: suffix,
    } });
    const clip = await db.testClip.create({ data: {
      suiteId: suffix, suiteVersion: 'test-only', manifestVersion: 'test-only', clipKey: suffix, displayName: 'TEST ONLY',
      workloadId: suffix, contentClass: 'talking-head', sourceProvenance: {}, sha256: suffix, byteSize: 1,
      exactFrameCount: 240, exactDurationSeconds: 10, frameRateNumerator: 24, frameRateDenominator: 1,
      width: 1920, height: 1080, pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0',
    } });
    const recipe = await db.recipe.create({ data: {
      fingerprint: suffix, canonicalJson: {}, codecFamily: 'h264', encoderImplementation: 'libx264', pixelFormat: 'yuv420p',
      bitDepth: 8, chromaSubsampling: '4:2:0', requestedRateControlMode: 'CRF', effectiveRateControlMode: 'CRF',
      requestedRateControl: {}, effectiveRateControl: {},
    } });
    const environment = await db.environment.create({ data: {
      fingerprint: suffix, canonicalJson: {}, cpuModel: 'TEST ONLY', cpuArchitecture: 'arm64', osName: 'test', osVersion: 'test',
      ffmpegBuildFingerprint: suffix, ffmpegVersion: 'test', clientVersion: 'client/0.3.0',
    } });
    const run = await db.benchmarkRun.create({ data: {
      benchmarkProtocolId: protocol.id, testClipId: clip.id, workloadId: suffix, recipeId: recipe.id, environmentId: environment.id,
      payloadHash: suffix, status: 'ACCEPTED', physicalSourceId: suffix, encodeTimerBoundary: 'ffmpeg-process-v1', realTimeRatio: 2,
    } });
    const artifact = await db.artifact.create({ data: { benchmarkRunId: run.id, role: 'ENCODED', sha256: hash, byteSize: bytes.length, storageState: 'RETAINED', storageProvider: 'localfs', storageKey: 'retained.bin' } });
    const analysis = await db.qualityAnalysis.create({ data: {
      benchmarkRunId: run.id, artifactId: artifact.id, status: 'COMPLETE', metricModelId: 'test-model',
      analysisWorkerVersion: 'test-worker', analysisProvenance: { testOnly: true }, completedAt: new Date(), vmafMean: 92.4, vmafP5: 88, xpsnr: 37, videoBitrateBps: 1000000,
    } });

    const evidence = {
      evidenceId: analysis.id, benchmarkRunId: run.id, artifactId: artifact.id, artifactSha256: hash,
      artifactStorageState: 'RETAINED', analysisWorkerVersion: 'test-worker', qualityAnalysisId: analysis.id,
      recipeFingerprint: suffix, environmentFingerprint: suffix, machineSourceId: suffix, workloadId: suffix,
      contentClass: 'talking-head', hardwareFamily: 'software', encoderFamily: 'h264', encoderImplementation: 'libx264', nativeRateControl: {},
      preset: 'unspecified', runStatus: 'ACCEPTED', analysisStatus: 'COMPLETE', vmafMean: 92.4, vmafP5: 88,
      xpsnr: 37, videoBitrateBps: 1000000, realTimeRatio: 2,
    };
    const document = { corpus: [evidence], metricSanityReviews: [], qualityModelId: 'test-model', benchmarkProtocolVersion: '7.1', sourceSuiteVersion: 'test-only' };
    assert.deepEqual(await verifyCalibrationRetainedEvidence(db, document, root), { verifiedAnalyses: 1, verifiedObjects: 1 });
    for (const [field, value] of [['vmafMean', 99], ['machineSourceId', 'another-machine'], ['artifactId', 'wrong-artifact'], ['nativeRateControl', { mode: 'crf', value: 3 }]]) {
      await assert.rejects(verifyCalibrationRetainedEvidence(db, { ...document, corpus: [{ ...evidence, [field]: value }] }, root), /mismatch/);
    }
    await writeFile(path.join(root, 'retained.bin'), Buffer.alloc(bytes.length, 1));
    await assert.rejects(verifyCalibrationRetainedEvidence(db, document, root), /SHA-256 mismatch/);
  } finally { await db.$disconnect(); await rm(root, { recursive: true, force: true }); }
});
