import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID, createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { CANONICAL_MEASUREMENT_RULES, loadMeasurementGroupEligibility } from '../dist/v7/measurementGroup.js';
import { applyEffectiveReview, appendEvidenceReview } from '../dist/v7/reviews.js';
import { canonicalJsonString, sha256Hex } from '../dist/v7/persistence.js';
import { validationSourceHash, VALIDATION_SOURCE_SUITE } from '../dist/v7/validationSources.js';
import { loadRetainedReferenceEvidence } from '../dist/v7/referenceContext.js';
import { loadRecomputeInputs } from '../../scripts/activate-pl-v7-production.mjs';
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
      canonicalRecipeRules: CANONICAL_MEASUREMENT_RULES, canonicalOutputRules: {}, metricWorkerVersion: suffix,
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
    const groupReceipt = ms => ({ schemaVersion: 'encodingdb-measurement-group/v1', campaignId: suffix, repetitionGroupId: suffix, completed: true, countedAttempts: [1, 2].map(repetitionIndex => ({ repetitionIndex, encodeWallTimeMs: ms })) });
    const run = await db.benchmarkRun.create({ data: {
      benchmarkProtocolId: protocol.id, testClipId: clip.id, workloadId: suffix, recipeId: recipe.id, environmentId: environment.id,
      payloadHash: suffix, status: 'ACCEPTED', physicalSourceId: suffix, encodeTimerBoundary: 'ffmpeg-process-v1', realTimeRatio: 2,
      campaignId: suffix, repetitionGroupId: suffix, repetitionIndex: 1, inputHash: clip.sha256, sourceFrameCount: 240, encodedFrameCount: 240, sourceFps: 24, encodeFps: 48, encodeWallTimeMs: 5000, preRunEnvironmentCheck: { measurementGroup: groupReceipt(5000) },
    } });
    const artifact = await db.artifact.create({ data: { benchmarkRunId: run.id, role: 'ENCODED', sha256: hash, byteSize: bytes.length, storageState: 'RETAINED', storageProvider: 'localfs', storageKey: 'retained.bin', storageUrl: path.join(root, 'retained.bin') } });
    const analysis = await db.qualityAnalysis.create({ data: {
      createdAt: new Date('2001-01-01T00:00:00Z'), benchmarkRunId: run.id, artifactId: artifact.id, status: 'COMPLETE', metricModelId: 'test-model',
      analysisWorkerVersion: 'test-worker', analysisProvenance: { testOnly: true, workerBuildFingerprint: 'b'.repeat(64) }, completedAt: new Date(), vmafMean: 92.4, vmafP5: 88, xpsnr: 37, videoBitrateBps: 1000000,
    } });

    const sibling = await db.benchmarkRun.create({ data: { benchmarkProtocolId: protocol.id, testClipId: clip.id, workloadId: suffix, recipeId: recipe.id, environmentId: environment.id, payloadHash: `${suffix}-sibling`, status: 'ACCEPTED', physicalSourceId: suffix, campaignId: suffix, repetitionGroupId: suffix, repetitionIndex: 2, encodeTimerBoundary: 'ffmpeg-process-v1', inputHash: clip.sha256, sourceFrameCount: 240, encodedFrameCount: 240, sourceFps: 24, encodeFps: 48, realTimeRatio: 2, encodeWallTimeMs: 5000, preRunEnvironmentCheck: { measurementGroup: groupReceipt(5000) } } });
    const siblingArtifact = await db.artifact.create({ data: { benchmarkRunId: sibling.id, role: 'ENCODED', sha256: hash, byteSize: bytes.length, storageState: 'RETAINED', storageProvider: 'localfs', storageKey: 'retained.bin', storageUrl: path.join(root, 'retained.bin') } });
    await db.qualityAnalysis.create({ data: { benchmarkRunId: sibling.id, artifactId: siblingArtifact.id, status: 'COMPLETE', metricModelId: 'test-model', analysisWorkerVersion: 'test-worker', analysisProvenance: { testOnly: true, workerBuildFingerprint: 'b'.repeat(64) }, completedAt: new Date(), vmafMean: 92.4, vmafP5: 88, xpsnr: 37, videoBitrateBps: 1000000 } });
    assert.equal((await loadRetainedReferenceEvidence(db, { benchmarkProtocolId: protocol.id, qualityModelId: 'test-model', suiteVersion: 'test-only' })).length, 2, 'positive complete stable group baseline before newer analysis tests');
    assert.equal((await loadRecomputeInputs(db, protocol.id, { qualityModelId: 'test-model' }, { applyEffectiveReview, loadMeasurementGroupEligibility })).length, 2);

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
    await assert.rejects(verifyCalibrationRetainedEvidence(db, document, root), /SHA-256 mismatch|missing-or-corrupt-retained-group-object/);
    await writeFile(path.join(root, 'retained.bin'), bytes);
    const registration = { sourceSuiteVersion: VALIDATION_SOURCE_SUITE, workloadId: `validation-${suffix}`, sourceSha256: hash,
      sourceGroupId: 'https://example.invalid/test-only-master', sceneGroupId: 'test-only-disjoint-scene', firstSourceFrame: 2400, endSourceFrameExclusive: 3120,
      sourceFrameRate: '24/1', contentClass: 'talking-head', frameCount: 720, durationSeconds: 30, byteSize: bytes.length,
      width: 1920, height: 1080, pixelFormat: 'yuv420p', frameRate: '24/1', normalization: 'TEST ONLY fixture, not media', sourceEvidenceHash: 'b'.repeat(64),
    };
    const registry = { schemaVersion: 'encodingdb-validation-source-registry/v1', sources: [registration] };
    registry.registryHash = sha256Hex(canonicalJsonString(registry));
    const registryPath = path.join(root, 'validation-sources.json'); await writeFile(registryPath, JSON.stringify(registry));
    process.env.VALIDATION_SOURCE_REGISTRY_PATH = registryPath;
    await db.testClip.update({ where: { id: clip.id }, data: { suiteVersion: VALIDATION_SOURCE_SUITE, workloadId: registration.workloadId,
      sha256: hash, byteSize: bytes.length, exactFrameCount: 720, exactDurationSeconds: 30, sourceProvenance: { validationSource: registration } } });
    await db.benchmarkRun.updateMany({ where: { benchmarkProtocolId: protocol.id }, data: { workloadId: registration.workloadId, inputHash: hash, sourceFrameCount: 720, encodedFrameCount: 720, encodeWallTimeMs: 15000, preRunEnvironmentCheck: { measurementGroup: groupReceipt(15000) } } });
    await db.benchmarkProtocol.update({ where: { id: protocol.id }, data: { sourceSuiteVersion: VALIDATION_SOURCE_SUITE } });
    const held = { ...evidence, partition: 'HOLDOUT', workloadId: registration.workloadId, sourceSuiteVersion: VALIDATION_SOURCE_SUITE, sourceSha256: hash, sourceRegistrationHash: validationSourceHash(registration) };
    assert.deepEqual(await verifyCalibrationRetainedEvidence(db, { ...document, corpus: [held] }, root), { verifiedAnalyses: 1, verifiedObjects: 1 });
    for (const change of [{ partition: 'CALIBRATION' }, { sourceSuiteVersion: 'encodingdb-test-suite-v1' }, { sourceRegistrationHash: '0'.repeat(64) }, { sourceSha256: '0'.repeat(64) }]) {
      await assert.rejects(verifyCalibrationRetainedEvidence(db, { ...document, corpus: [{ ...held, ...change }] }, root), /Validation-only|Registered validation/);
    }
    delete process.env.VALIDATION_SOURCE_REGISTRY_PATH;
    await assert.rejects(verifyCalibrationRetainedEvidence(db, { ...document, corpus: [held] }, root), /operator-installed source registry/);
    await db.testClip.update({ where: { id: clip.id }, data: { suiteVersion: 'test-only', workloadId: suffix, sha256: suffix, byteSize: 1, exactFrameCount: 240, exactDurationSeconds: 10, sourceProvenance: {} } });
    await db.benchmarkRun.updateMany({ where: { benchmarkProtocolId: protocol.id }, data: { workloadId: suffix, inputHash: suffix, sourceFrameCount: 240, encodedFrameCount: 240, encodeWallTimeMs: 5000, preRunEnvironmentCheck: { measurementGroup: groupReceipt(5000) } } });
    await db.benchmarkProtocol.update({ where: { id: protocol.id }, data: { sourceSuiteVersion: 'test-only' } });
    const newer = await db.qualityAnalysis.create({ data: {
      createdAt: new Date('2002-01-01T00:00:00Z'), benchmarkRunId: run.id, artifactId: artifact.id, status: 'SUSPECT', metricModelId: 'test-model',
      analysisWorkerVersion: 'test-worker-newer', analysisProvenance: { testOnly: true, workerBuildFingerprint: 'b'.repeat(64) }, completedAt: new Date(), vmafMean: 91, vmafP5: 80, xpsnr: 36, videoBitrateBps: 1000000,
    } });
    await appendEvidenceReview(db, analysis.id, 'test-operator-not-human-review', {
      benchmarkRunId: run.id, artifactId: artifact.id, artifactSha256: hash, metricModelId: 'test-model', analysisWorkerVersion: 'test-worker',
      decision: 'EXPECTED', rationale: 'Synthetic regression fixture: this is not a genuine perceptual review.', evidenceLinks: ['https://example.invalid/test-only'],
    });
    const reviewedOld = await db.qualityAnalysis.findUnique({ where: { id: analysis.id } });
    assert.ok(reviewedOld.updatedAt > newer.createdAt);
    assert.deepEqual(await loadRetainedReferenceEvidence(db, { benchmarkProtocolId: protocol.id, qualityModelId: 'test-model', suiteVersion: 'test-only' }), []);
    assert.deepEqual(await loadRecomputeInputs(db, protocol.id, { qualityModelId: 'test-model' }, { applyEffectiveReview, loadMeasurementGroupEligibility }), []);
    await assert.rejects(verifyCalibrationRetainedEvidence(db, document, root), /superseded/);
    const exported = path.join(root, 'newest-draft.json');
    assert.throws(() => execFileSync(process.execPath, [fileURLToPath(new URL('../../scripts/generate-calibration-evidence.mjs', import.meta.url)), '--benchmark-protocol-id', protocol.id, '--quality-model-id', 'test-model', '--calibration-version', 'test-only-newest', '--output', exported], { env: { ...process.env, DATABASE_URL: process.env.CALIBRATION_TEST_DATABASE_URL } }), /No retained authoritative calibration evidence/);
    for (const status of ['PENDING', 'FAILED', 'REJECTED']) {
      await db.qualityAnalysis.update({ where: { id: newer.id }, data: { status } });
      assert.deepEqual(await loadRetainedReferenceEvidence(db, { benchmarkProtocolId: protocol.id, qualityModelId: 'test-model', suiteVersion: 'test-only' }), []);
      assert.deepEqual(await loadRecomputeInputs(db, protocol.id, { qualityModelId: 'test-model' }, { applyEffectiveReview, loadMeasurementGroupEligibility }), []);
    }
  } finally { await db.$disconnect(); await rm(root, { recursive: true, force: true }); }
});
