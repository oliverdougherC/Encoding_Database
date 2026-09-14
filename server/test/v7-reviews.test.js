import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { PrismaClient } from '@prisma/client';
import { applyEffectiveReview, appendEvidenceReview } from '../dist/v7/reviews.js';

const automatic = { runStatus: 'SUSPECT', analysisStatus: 'SUSPECT', artifactState: 'VERIFIED', analysisId: 'analysis' };
const review = (decision, n = 1, analysisId = 'analysis') => ({ id: `review-${n}`, decision, analysisId, createdAt: new Date(n) });

test('exact-analysis review preserves automatic evidence and fails closed across revocation and reanalysis', () => {
  assert.equal(applyEffectiveReview(automatic).eligible, false);
  assert.equal(applyEffectiveReview({ ...automatic, reviews: [review('EXPECTED')] }).eligible, true);
  for (const decision of ['REJECT', 'INVESTIGATE', 'REVOKE']) {
    assert.equal(applyEffectiveReview({ ...automatic, reviews: [review('EXPECTED'), review(decision, 2)] }).eligible, false);
  }
  assert.equal(applyEffectiveReview({ ...automatic, analysisId: 'new-analysis', reviews: [review('EXPECTED')] }).eligible, false);
  for (const runStatus of ['INVALID', 'REJECTED', 'PENDING']) {
    assert.equal(applyEffectiveReview({ ...automatic, runStatus, reviews: [review('EXPECTED')] }).eligible, false);
  }
  assert.equal(automatic.analysisStatus, 'SUSPECT');
});

test('PostgreSQL review append, supersession, dedupe, identity binding and immutable trigger', {
  skip: !process.env.REVIEW_TEST_DATABASE_URL,
}, async () => {
  const db = new PrismaClient({ datasources: { db: { url: process.env.REVIEW_TEST_DATABASE_URL } } });
  const suffix = randomUUID();
  const hash = 'a'.repeat(64);
  try {
    const protocol = await db.benchmarkProtocol.create({ data: {
      protocolVersion: `test-${suffix}`, sourceSuiteVersion: 'test-only', minimumClientVersion: 'client/0.3.0',
      canonicalRecipeRules: {}, canonicalOutputRules: {}, metricWorkerVersion: 'test-worker',
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
      payloadHash: suffix, status: 'SUSPECT',
    } });
    const artifact = await db.artifact.create({ data: { benchmarkRunId: run.id, role: 'ENCODED', sha256: hash, byteSize: 123, storageState: 'VERIFIED' } });
    const analysis = await db.qualityAnalysis.create({ data: {
      benchmarkRunId: run.id, artifactId: artifact.id, status: 'SUSPECT', metricModelId: 'test-model',
      analysisWorkerVersion: 'test-worker', analysisProvenance: { testOnly: true }, completedAt: new Date(), vmafMean: 92.4,
    } });
    const input = {
      benchmarkRunId: run.id, artifactId: artifact.id, artifactSha256: hash, metricModelId: 'test-model', analysisWorkerVersion: 'test-worker',
      decision: 'EXPECTED', rationale: 'Synthetic operator fixture: not a human calibration review.', evidenceLinks: ['https://example.invalid/test-only'],
    };
    const [first, duplicate] = await Promise.all([
      appendEvidenceReview(db, analysis.id, 'test-operator', input), appendEvidenceReview(db, analysis.id, 'test-operator', input),
    ]);
    assert.equal(first.id, duplicate.id);
    assert.equal(await db.evidenceReview.count({ where: { analysisId: analysis.id } }), 1);
    assert.equal((await db.artifact.findUnique({ where: { id: artifact.id } })).storageState, 'RETAINED');
    const original = await db.qualityAnalysis.findUnique({ where: { id: analysis.id } });
    assert.equal(original.status, 'SUSPECT');
    assert.equal(original.vmafMean, 92.4);
    assert.equal(original.recomputePending, true);
    await assert.rejects(appendEvidenceReview(db, analysis.id, 'test-operator', { ...input, artifactSha256: 'b'.repeat(64) }), /identity/);
    await assert.rejects(db.evidenceReview.update({ where: { id: first.id }, data: { rationale: 'mutated' } }), /append-only/);
    await assert.rejects(db.evidenceReview.delete({ where: { id: first.id } }), /append-only/);
    const revoked = await appendEvidenceReview(db, analysis.id, 'test-operator', { ...input, decision: 'REVOKE', supersedesId: first.id });
    assert.ok(revoked.createdAt > first.createdAt);
    await assert.rejects(appendEvidenceReview(db, analysis.id, 'test-operator', { ...input, decision: 'REJECT', supersedesId: first.id }), /current review head/);
    assert.equal(applyEffectiveReview({ ...automatic, analysisId: analysis.id, reviews: [first, revoked] }).eligible, false);
  } finally { await db.$disconnect(); }
});
