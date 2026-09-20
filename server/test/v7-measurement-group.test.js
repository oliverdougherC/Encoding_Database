import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { PrismaClient, Prisma } from '@prisma/client';
import { CANONICAL_MEASUREMENT_RULES, evaluateMeasurementGroup, loadMeasurementGroupEligibility, parseMeasurementGroupReceipt, measurementGroupStateHashSql, measurementGroupScopeForDerived, receiptWallTimesEqual, receiptsEquivalent } from '../dist/v7/measurementGroup.js';
import { DEFAULT_RECOMMENDATION_EVIDENCE_POLICY, rebuildDerivedResultAggregateFromAnalyses, persistDerivedResultAggregate } from '../dist/v7/aggregation.js';
import { loadPublicCorpusPage } from '../dist/v7/corpusQuery.js';
import { loadRetainedReferenceEvidence } from '../dist/v7/referenceContext.js';
import { verifyCalibrationRetainedEvidence } from '../dist/v7/calibrationRetention.js';
import { createPrismaArtifactPipelinePersistence } from '../dist/v7/artifacts.js';
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
const receipt = (times, group = 'group', campaign = 'campaign') => ({ schemaVersion: 'encodingdb-measurement-group/v1', campaignId: campaign, repetitionGroupId: group, completed: true, countedAttempts: times.map((ms, index) => ({ repetitionIndex: index + 1, encodeWallTimeMs: ms })) });
function group(times = [1000, 1001], source = 'physical-source-1') {
  const shared = receipt(times);
  return times.map((ms, index) => ({ id: `${source}-${index}`, benchmarkProtocolId: 'protocol', testClipId: 'clip', workloadId: 'workload', recipeId: 'recipe', environmentId: 'environment', physicalSourceId: source, campaignId: 'campaign', repetitionGroupId: 'group', repetitionIndex: index + 1,
    preRunEnvironmentCheck: { snapshot: { telemetry_sources: 'cpu_psutil_thread_window_v1', background_cpu_pct: 0 }, measurementGroup: shared }, status: 'ACCEPTED', encodeTimerBoundary: 'ffmpeg-process-v1', inputHash: 'a'.repeat(64), encodeWallTimeMs: ms, sourceFrameCount: 240, encodedFrameCount: 240, sourceFps: 24, encodeFps: 240000 / ms, realTimeRatio: 10000 / ms,
    benchmarkProtocol: { protocolVersion: '7.1', canonicalRecipeRules: CANONICAL_MEASUREMENT_RULES }, testClip: { sha256: 'a'.repeat(64), exactFrameCount: 240, exactDurationSeconds: 10, frameRateNumerator: 24, frameRateDenominator: 1 },
    qualityAnalyses: [{ id: `analysis-${source}-${index}`, createdAt: new Date(), metricModelId: 'model', analysisWorkerVersion: 'worker', status: 'COMPLETE', analysisProvenance: { workerBuildFingerprint: 'b'.repeat(64) }, evidenceReviews: [], artifact: { id: `artifact-${source}-${index}`, benchmarkRunId: `${source}-${index}`, role: 'ENCODED', storageState: 'RETAINED', sha256: 'c'.repeat(64), byteSize: 100, storageProvider: 'localfs', storageKey: 'object', storageUrl: '/retained/object' } }],
  }));
}
const check = rows => evaluateMeasurementGroup(rows[0], rows, { metricModelId: 'model', analysisWorkerVersion: 'worker' });
function aggregate(groups, protocolVersion = '7.1') {
  const analyses = groups.flatMap(rows => { const verified = check(rows); return rows.map(run => ({ benchmarkRunId: run.id, qualityAnalysisId: run.qualityAnalyses[0].id, analysisWorkerVersion: 'worker', benchmarkRunStatus: 'ACCEPTED', qualityAnalysisStatus: 'COMPLETE', encodeFps: run.encodeFps, sourceFps: 24, videoBitrateBps: 1000000, fileSizeBytes: 1250000, vmafMean: 95, vmafP5: 90, physicalSourceId: run.physicalSourceId, repetitionGroupId: run.repetitionGroupId, measurementGroup: verified })); });
  return rebuildDerivedResultAggregateFromAnalyses({ identity: { kind: 'workload', benchmarkProtocolId: 'protocol', protocolVersion, sourceSuiteVersion: 'suite', workloadId: 'workload', recipeId: 'recipe', recipeFingerprint: 'recipe', environmentId: 'environment', environmentFingerprint: 'environment', scoreContextId: 'context', scoreContextVersion: 'context', qualityModelId: 'model', formulaVersion: '7.0' }, scoreContext: { workloadId: 'workload', workloadReferenceBitrateBps: 1000000 }, evidencePolicy: { ...DEFAULT_RECOMMENDATION_EVIDENCE_POLICY, policyStatus: 'CALIBRATED' }, analyses });
}

test('complete canonical group eligibility derives timing, exact members and current retained review state', () => {
  assert.equal(check(group()).eligible, true);
  for (const [name, change, pattern] of [
    ['missing', rows => { delete rows[0].preRunEnvironmentCheck.measurementGroup; }, /missing/],
    ['missing sampler', rows => { delete rows[1].preRunEnvironmentCheck.snapshot; }, /background-observation/],
    ['old sampler', rows => { rows[1].preRunEnvironmentCheck.snapshot.telemetry_sources = 'cpu_psutil'; }, /background-observation/],
    ['missing observation', rows => { delete rows[1].preRunEnvironmentCheck.snapshot.background_cpu_pct; }, /background-observation/],
    ['null observation', rows => { rows[1].preRunEnvironmentCheck.snapshot.background_cpu_pct = null; }, /background-observation/],
    ['nonfinite observation', rows => { rows[1].preRunEnvironmentCheck.snapshot.background_cpu_pct = Infinity; }, /background-observation/],
    ['partial upload', rows => rows.pop(), /incomplete/],
    ['pending analysis', rows => { rows[1].qualityAnalyses = []; }, /missing/],
    ['mixed summary', rows => { rows[1].preRunEnvironmentCheck.measurementGroup = receipt([1000, 1001.0001]); }, /inconsistent/],
    ['wrong exact elapsed', rows => { rows[1].encodeWallTimeMs += 0.000001; }, /inconsistent/],
    ['wrong timing tuple', rows => { rows[1].encodeFps = 1; }, /timing/],
    ['mixed model', rows => { rows[1].qualityAnalyses[0].metricModelId = 'other'; }, /mixed/],
    ['mixed worker', rows => { rows[1].qualityAnalyses[0].analysisWorkerVersion = 'other'; }, /mixed/],
    ['mixed build', rows => { rows[1].qualityAnalyses[0].analysisProvenance.workerBuildFingerprint = 'd'.repeat(64); }, /build/],
    ['mixed cohort', rows => { rows[1].environmentId = 'other'; }, /identity/],
    ['review suspended sibling', rows => { rows[1].qualityAnalyses[0].evidenceReviews = [{ id: 'review', analysisId: rows[1].qualityAnalyses[0].id, decision: 'INVESTIGATE', createdAt: new Date() }]; }, /ineligible/],
    ['nonretained', rows => { rows[1].qualityAnalyses[0].artifact.storageState = 'UPLOADED'; }, /ineligible/],
  ]) { const rows = structuredClone(group()); change(rows); const result = check(rows); assert.equal(result.eligible, false, name); assert.match(result.reason, pattern, name); }
  const rows = group();
  rows[1].preRunEnvironmentCheck.snapshot = { telemetry_sources: 'cpu_psutil, cpu_psutil_blocking_window_v1', background_cpu_pct: 0 };
  assert.equal(check(rows).eligible, true, 'successful blocking fallback and measured idle zero qualify');
  assert.throws(() => parseMeasurementGroupReceipt({ ...receipt([1000, 1001]), stable: true }, rows[0]));
  assert.throws(() => parseMeasurementGroupReceipt({ ...receipt([1000, 1001]), countedAttempts: [{ repetitionIndex: 1, encodeWallTimeMs: 1000 }, { repetitionIndex: 1, encodeWallTimeMs: 1001 }] }));
});

test('three unstable four-attempt groups cannot manufacture HIGH confidence or PL from identical source medians', () => {
  const groups = [1, 2, 3].map(source => group([1000, 1030.507, 1000, 1000], `source-${source}`));
  assert.equal(check(groups[0]).reason, 'unstable-timing');
  assert.ok(check(groups[0]).relativeSpread > 0.03);
  const result = aggregate(groups);
  assert.equal(result.derivedResult.acceptedRunCount, 12, 'raw valid individual measurements remain visible');
  assert.equal(result.derivedResult.plTotal, null);
  assert.equal(result.evidence.tier, 'PROVISIONAL');
  assert.equal(result.evidence.eligibleForDefaultRecommendation, false);
  assert.deepEqual(result.members, []);
  const stable = aggregate([1, 2, 3].map(source => group([1000, 1001], `source-${source}`)));
  assert.ok(stable.derivedResult.plTotal > 0);
  assert.equal(stable.evidence.eligibleForDefaultRecommendation, true);
  const legacy = aggregate(groups, '7.0');
  assert.ok(legacy.derivedResult.plTotal > 0, 'historical formula evaluation is not retroactively rewritten');
});

test('receipt comparison survives the 15-significant-digit jsonb round trip and still rejects real differences', () => {
  // This is the exact observed round trip: Prisma serializes JSON floats as
  // 15-significant-digit decimal text, so 1473.9108999999999 reads back as 1473.9109.
  assert.equal(receiptWallTimesEqual(1473.9109, 1473.9108999999999), true);
  assert.equal(receiptWallTimesEqual(1473.9108999999999, 1473.9109), true);
  assert.equal(receiptWallTimesEqual(1473.9108999999999, 1473.9108999999999), true);
  // Genuine attempts differ by milliseconds; a 1 ms difference is not round-trip noise.
  assert.equal(receiptWallTimesEqual(1473.9109, 1474.9109), false);
  assert.equal(receiptWallTimesEqual(0.5, 0.5005), false);
  const exact = receipt([1458.0055, 1473.9108999999999]);
  const stored = receipt([1458.0055, 1473.9109]);
  assert.equal(receiptsEquivalent(exact, stored), true, 'sealed receipt equals its stored round trip');
  assert.equal(receiptsEquivalent(exact, receipt([1458.0055, 1500])), false, 'different measured attempt still contradicts');
  assert.equal(receiptsEquivalent(exact, receipt([1458.0055, 1473.9108999999999], 'other-group')), false);
  // A stored round trip still binds the run whose elapsed time it records.
  const member = group([1458.0055, 1473.9108999999999])[1];
  member.preRunEnvironmentCheck = { snapshot: member.preRunEnvironmentCheck.snapshot, measurementGroup: stored };
  assert.doesNotThrow(() => parseMeasurementGroupReceipt(stored, member));
  assert.throws(() => parseMeasurementGroupReceipt(stored, { ...member, encodeWallTimeMs: 2000 }));
});

const dbUrl = process.env.MEASUREMENT_GROUP_TEST_DATABASE_URL ?? process.env.CALIBRATION_TEST_DATABASE_URL;
test('live complete-group verification is independent of frontier subset, validates sibling bytes, and rechecks later reviews', { skip: !dbUrl }, async () => {
  const db = new PrismaClient({ datasources: { db: { url: dbUrl } } });
  const root = await mkdtemp(path.join(os.tmpdir(), 'group-evidence-'));
  const suffix = crypto.randomUUID();
  const bytes = Buffer.from(`Synthetic retained object ${suffix}`); const sha = hash(bytes);
  await writeFile(path.join(root, 'retained.bin'), bytes);
  try {
    const protocol = await db.benchmarkProtocol.create({ data: { protocolVersion: '7.1', sourceSuiteVersion: 'TEST ONLY', minimumClientVersion: 'client/0.3.0', metricWorkerVersion: suffix, canonicalRecipeRules: CANONICAL_MEASUREMENT_RULES, canonicalOutputRules: {} } });
    const clip = await db.testClip.create({ data: { suiteId: suffix, suiteVersion: 'TEST ONLY', manifestVersion: 'TEST ONLY', clipKey: suffix, displayName: 'TEST ONLY', workloadId: suffix, contentClass: 'talking-head', sourceProvenance: {}, sha256: hash(suffix), byteSize: 1, exactFrameCount: 240, exactDurationSeconds: 10, frameRateNumerator: 24, frameRateDenominator: 1, width: 1920, height: 1080, pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0' } });
    const recipe = await db.recipe.create({ data: { fingerprint: suffix, canonicalJson: {}, codecFamily: 'h264', encoderImplementation: 'libx264', pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0', requestedRateControlMode: 'CRF', effectiveRateControlMode: 'CRF', requestedRateControl: {}, effectiveRateControl: {} } });
    const environment = await db.environment.create({ data: { fingerprint: suffix, canonicalJson: {}, cpuModel: 'TEST ONLY', cpuArchitecture: 'arm64', osName: 'test', osVersion: 'test', ffmpegBuildFingerprint: suffix, ffmpegVersion: 'test', clientVersion: 'client/0.3.0' } });
    const shared = receipt([24000, 24001], suffix, suffix);
    const runs = [], analyses = [], artifacts = [];
    const input = index => ({ benchmarkProtocolId: protocol.id, testClipId: clip.id, workloadId: suffix, recipeId: recipe.id, environmentId: environment.id, payloadHash: hash(`${suffix}-${index}`), physicalSourceId: suffix, campaignId: suffix, repetitionGroupId: suffix, repetitionIndex: index + 1, encodeTimerBoundary: 'ffmpeg-process-v1', inputHash: clip.sha256, encodeWallTimeMs: 24000 + index, encodeFps: 240000 / (24000 + index), sourceFps: 24, realTimeRatio: 10000 / (24000 + index), sourceFrameCount: 240, encodedFrameCount: 240, preRunEnvironmentCheck: { snapshot: { telemetry_sources: 'cpu_psutil_thread_window_v1', background_cpu_pct: 0 }, measurementGroup: shared }, artifact: { role: 'ENCODED', sha256: sha, byteSize: bytes.length } });
    const persistence = createPrismaArtifactPipelinePersistence(db);
    for (let index = 0; index < 2; index++) {
      const created = await persistence.createOrFetchRun(input(index));
      runs.push(await db.benchmarkRun.update({ where: { id: created.bundle.run.id }, data: { status: 'ACCEPTED' } }));
      artifacts.push(await db.artifact.update({ where: { id: created.bundle.artifact.id }, data: { storageState: 'RETAINED', storageProvider: 'localfs', storageKey: 'retained.bin', storageUrl: path.join(root, 'retained.bin') } }));
      analyses.push(await db.qualityAnalysis.create({ data: { id: `namespaced-${suffix}-${index === 0 ? '\uE000' : '\u{10000}'}`, benchmarkRunId: runs[index].id, artifactId: artifacts[index].id, status: 'COMPLETE', metricModelId: 'test-model', analysisWorkerVersion: 'authoritative-analysis/test-worker', analysisProvenance: { workerBuildFingerprint: 'b'.repeat(64) }, vmafMean: 95, vmafP5: 90, xpsnr: 37, videoBitrateBps: 1000000 } }));
      const verified = await loadMeasurementGroupEligibility(db, runs[0], { metricModelId: 'test-model' });
      assert.equal(verified.eligible, index === 1);
    }
    await assert.rejects(persistence.createOrFetchRun({ ...input(0), payloadHash: hash('different-key') }), /already has an immutable run/);
    await assert.rejects(persistence.createOrFetchRun({ ...input(1), payloadHash: hash('extra-index'), repetitionIndex: 3, preRunEnvironmentCheck: { snapshot: { telemetry_sources: 'cpu_psutil_thread_window_v1', background_cpu_pct: 0 }, measurementGroup: receipt([1000, 1001, 1002], suffix, suffix) } }), /receipt does not bind|receipt is immutable/);
    // Regression: a sealed receipt must stay valid after a sibling's elapsed time has
    // made the 15-significant-digit JSONB round trip (observed live as "Measurement
    // group completed receipt is immutable" rejections of byte-identical sealed receipts).
    const g2 = `${suffix}-precision`;
    const sealed = receipt([1458.0055, 1473.9108999999999], g2, g2);
    const sealedInput = (index, wall) => ({ ...input(index), payloadHash: hash(`precision-${index}-${suffix}`), physicalSourceId: g2, campaignId: g2, repetitionGroupId: g2, repetitionIndex: index + 1, encodeWallTimeMs: wall, encodeFps: 240000 / wall, realTimeRatio: 10000 / wall, preRunEnvironmentCheck: { snapshot: { telemetry_sources: 'cpu_psutil_thread_window_v1', background_cpu_pct: 0 }, measurementGroup: sealed } });
    const sibling = await persistence.createOrFetchRun(sealedInput(1, 1473.9108999999999));
    assert.equal(sibling.created, true);
    const storedSibling = await db.benchmarkRun.findUnique({ where: { id: sibling.bundle.run.id } });
    assert.equal(storedSibling.preRunEnvironmentCheck.measurementGroup.countedAttempts[1].encodeWallTimeMs, 1473.9109, 'documented Prisma 15-significant-digit round trip');
    const replay = await persistence.createOrFetchRun(sealedInput(0, 1458.0055));
    assert.equal(replay.created, true, 'sealed receipt remains valid against its stored round trip');
    await assert.rejects(persistence.createOrFetchRun({ ...sealedInput(0, 1458.0055), payloadHash: hash(`unbound-${suffix}`), repetitionIndex: 3, preRunEnvironmentCheck: { snapshot: { telemetry_sources: 'cpu_psutil_thread_window_v1', background_cpu_pct: 0 } } }), /must all carry the completed group receipt/);
    const loaded = await loadRetainedReferenceEvidence(db, { benchmarkProtocolId: protocol.id, qualityModelId: 'test-model', suiteVersion: 'TEST ONLY' });
    assert.equal(loaded.length, 2);
    const evidence = { evidenceId: analyses[0].id, qualityAnalysisId: analyses[0].id, benchmarkRunId: runs[0].id, artifactId: artifacts[0].id, artifactSha256: sha, artifactStorageState: 'RETAINED', analysisWorkerVersion: 'authoritative-analysis/test-worker', recipeFingerprint: suffix, environmentFingerprint: suffix, machineSourceId: suffix, workloadId: suffix, contentClass: 'talking-head', hardwareFamily: 'software', encoderFamily: 'h264', encoderImplementation: 'libx264', nativeRateControl: {}, preset: 'unspecified', runStatus: 'ACCEPTED', analysisStatus: 'COMPLETE', vmafMean: 95, vmafP5: 90, xpsnr: 37, videoBitrateBps: 1000000, realTimeRatio: 10000 / 24000 };
    const document = { corpus: [evidence], metricSanityReviews: [], qualityModelId: 'test-model', benchmarkProtocolVersion: '7.1', sourceSuiteVersion: 'TEST ONLY' };
    assert.equal((await verifyCalibrationRetainedEvidence(db, document, root)).verifiedAnalyses, 1, 'frontier subset one verifies complete underlying two-run group');
    const context = await db.scoreContext.create({ data: { benchmarkProtocolId: protocol.id, formulaVersion: '7.0', contextVersion: suffix, workloadId: suffix, qualityModelId: 'test-model', workloadReferenceBitrateBps: 1000000, transformConstants: {} } });
    async function rebuildPublic(targetRecipe = recipe) {
      const current = await db.benchmarkRun.findMany({ where: { benchmarkProtocolId: protocol.id, recipeId: targetRecipe.id }, include: { qualityAnalyses: { orderBy: [{ createdAt: 'desc' }, { id: 'desc' }], take: 1 } } });
      const mapped = [];
      for (const run of current) {
        const analysis = run.qualityAnalyses[0]; if (!analysis) continue;
        mapped.push({ benchmarkRunId: run.id, qualityAnalysisId: analysis.id, analysisWorkerVersion: analysis.analysisWorkerVersion, benchmarkRunStatus: run.status, qualityAnalysisStatus: analysis.status,
          encodeFps: run.encodeFps, sourceFps: run.sourceFps, videoBitrateBps: analysis.videoBitrateBps, fileSizeBytes: bytes.length, vmafMean: analysis.vmafMean, vmafP5: analysis.vmafP5,
          physicalSourceId: run.physicalSourceId, repetitionGroupId: run.repetitionGroupId, measurementGroup: await loadMeasurementGroupEligibility(db, run, { metricModelId: 'test-model' }) });
      }
      return persistDerivedResultAggregate(db, { identity: { kind: 'workload', benchmarkProtocolId: protocol.id, protocolVersion: '7.1', sourceSuiteVersion: 'TEST ONLY', workloadId: suffix, testClipId: clip.id, recipeId: targetRecipe.id, recipeFingerprint: targetRecipe.fingerprint, environmentId: environment.id, environmentFingerprint: environment.fingerprint, scoreContextId: context.id, scoreContextVersion: context.contextVersion, qualityModelId: 'test-model', formulaVersion: '7.0' },
        scoreContext: { workloadId: suffix, workloadReferenceBitrateBps: 1000000 }, evidencePolicy: { ...DEFAULT_RECOMMENDATION_EVIDENCE_POLICY, policyStatus: 'CALIBRATED' }, analyses: mapped });
    }
    const publicId = `${protocol.id}::${suffix}::${recipe.id}::${environment.id}::test-model`;
    const page = async () => (await loadPublicCorpusPage(db, {}, { take: 1, id: publicId, publicReferenceContextVersions: new Set([context.contextVersion]) })).rows[0];
    const initial = await rebuildPublic();
    assert.equal((await page()).pl.total, initial.derivedResult.plTotal);
    const badTimes = [2400, 2473.2168, 2400, 2400];
    const badReceipt = receipt(badTimes, `${suffix}-unstable`, suffix);
    for (const [index, ms] of badTimes.entries()) {
      const created = await persistence.createOrFetchRun({ ...input(0), payloadHash: hash(`${suffix}-unstable-${index}`), physicalSourceId: `${suffix}-other`, repetitionGroupId: badReceipt.repetitionGroupId, repetitionIndex: index + 1, encodeWallTimeMs: ms, encodeFps: 240000 / ms, realTimeRatio: 10000 / ms, preRunEnvironmentCheck: { snapshot: { telemetry_sources: 'cpu_psutil_thread_window_v1', background_cpu_pct: 0 }, measurementGroup: badReceipt } });
      await db.benchmarkRun.update({ where: { id: created.bundle.run.id }, data: { status: 'ACCEPTED' } });
      await db.artifact.update({ where: { id: created.bundle.artifact.id }, data: { storageState: 'RETAINED', storageProvider: 'localfs', storageKey: 'retained.bin', storageUrl: path.join(root, 'retained.bin') } });
      await db.qualityAnalysis.create({ data: { benchmarkRunId: created.bundle.run.id, artifactId: created.bundle.artifact.id, status: 'COMPLETE', metricModelId: 'test-model', analysisWorkerVersion: 'authoritative-analysis/test-worker', analysisProvenance: { workerBuildFingerprint: 'b'.repeat(64) }, vmafMean: 70, vmafP5: 60, videoBitrateBps: 1000000 } });
    }
    assert.equal((await page()).pl.total, null, 'new raw membership invalidates old scoring snapshot until refresh');
    const mixed = await rebuildPublic();
    const publicMixed = await page();
    assert.equal(publicMixed.sampleCounts.accepted, 6);
    assert.equal(publicMixed.pl.total, mixed.derivedResult.plTotal);
    assert.equal(publicMixed.fps, mixed.derivedResult.centerEncodeFps);
    assert.equal(publicMixed.vmaf, 95, 'displayed quality follows stable scoring subset, not raw median 70');
    assert.equal(publicMixed.status.centerBasis, 'eligible-stable-groups');
    assert.equal((await db.derivedResultMember.count({ where: { derivedResultId: mixed.derivedResultId } })), 2, 'unstable rows never become scoring members');
    const orderedIds = (await db.$queryRawUnsafe('SELECT "qualityAnalysisId" AS id FROM "DerivedResultMember" WHERE "derivedResultId" = $1 ORDER BY "qualityAnalysisId" COLLATE "C"', mixed.derivedResultId)).map(row => row.id);
    assert.notDeepEqual(orderedIds, [...orderedIds].sort(), 'mixed namespaced Unicode IDs exercise SQL byte order versus JS UTF16 order');
    const otherRecipe = await db.recipe.create({ data: { fingerprint: `${suffix}-alternate`, canonicalJson: {}, codecFamily: 'h264', encoderImplementation: 'libx264', preset: 'alternate', pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0', requestedRateControlMode: 'CRF', effectiveRateControlMode: 'CRF', requestedRateControl: {}, effectiveRateControl: {} } });
    const alternateReceipt = receipt([4800, 4801], `${suffix}-alternate`, suffix);
    for (let index = 0; index < 2; index++) {
      const ms = 4800 + index;
      const created = await persistence.createOrFetchRun({ ...input(0), recipeId: otherRecipe.id, payloadHash: hash(`${suffix}-alternate-${index}`), repetitionGroupId: alternateReceipt.repetitionGroupId, repetitionIndex: index + 1, encodeWallTimeMs: ms, encodeFps: 240000 / ms, realTimeRatio: 10000 / ms, preRunEnvironmentCheck: { snapshot: { telemetry_sources: 'cpu_psutil_thread_window_v1', background_cpu_pct: 0 }, measurementGroup: alternateReceipt } });
      await db.benchmarkRun.update({ where: { id: created.bundle.run.id }, data: { status: 'ACCEPTED' } });
      await db.artifact.update({ where: { id: created.bundle.artifact.id }, data: { storageState: 'RETAINED', storageProvider: 'localfs', storageKey: 'retained.bin', storageUrl: path.join(root, 'retained.bin') } });
      await db.qualityAnalysis.create({ data: { benchmarkRunId: created.bundle.run.id, artifactId: created.bundle.artifact.id, status: 'COMPLETE', metricModelId: 'test-model', analysisWorkerVersion: 'authoritative-analysis/test-worker', analysisProvenance: { workerBuildFingerprint: 'b'.repeat(64) }, vmafMean: 85, vmafP5: 75, videoBitrateBps: 1000000 } });
    }
    const otherProjection = await rebuildPublic(otherRecipe);
    const otherPublicId = `${protocol.id}::${suffix}::${otherRecipe.id}::${environment.id}::test-model`;
    const untouchedOther = await db.derivedResult.findUnique({ where: { id: otherProjection.derivedResultId } });
    const unchangedOriginal = await db.derivedResult.findUnique({ where: { id: mixed.derivedResultId } });
    for (const sort of ['fps', 'vmaf']) {
      const sorted = await loadPublicCorpusPage(db, { search: suffix, sort, dir: 'desc' }, { take: 1, publicReferenceContextVersions: new Set([context.contextVersion]) });
      assert.equal(sorted.totalCount, 2);
      assert.equal(sorted.rows[0].id, sort === 'fps' ? otherPublicId : publicId, 'pagination sorts by displayed stable-group centers, not lower raw diagnostic medians');
    }
    await db.qualityAnalysis.update({ where: { id: analyses[0].id }, data: { recomputePending: true, lastError: 'bookkeeping only' } });
    assert.equal((await page()).pl.total, mixed.derivedResult.plTotal, 'bookkeeping does not invalidate group qualification');
    assert.equal((await db.$queryRawUnsafe('SELECT count(*)::int AS count FROM "DerivedResultGroupDependency" WHERE "derivedResultId" = $1 AND "invalidatedAt" IS NOT NULL', mixed.derivedResultId))[0].count, 0);
    let releaseGroup, groupLocked;
    const groupReady = new Promise(resolve => { groupLocked = resolve; });
    const groupRelease = new Promise(resolve => { releaseGroup = resolve; });
    const frozenGroup = db.$transaction(async tx => { await tx.$executeRawUnsafe('SELECT encodingdb_lock_measurement_groups($1::jsonb)', JSON.stringify([[suffix, suffix, suffix]])); groupLocked(); await groupRelease; });
    await groupReady;
    let extraCommitted = false;
    const pendingExtra = db.benchmarkRun.create({ data: { benchmarkProtocolId: protocol.id, testClipId: clip.id, workloadId: suffix, recipeId: recipe.id, environmentId: environment.id, physicalSourceId: suffix, campaignId: suffix, repetitionGroupId: suffix, repetitionIndex: 3, payloadHash: crypto.randomUUID(), preRunEnvironmentCheck: { snapshot: { telemetry_sources: 'cpu_psutil_thread_window_v1', background_cpu_pct: 0 }, measurementGroup: shared } } }).then(row => { extraCommitted = true; return row; });
    await new Promise(resolve => setTimeout(resolve, 50));
    assert.equal(extraCommitted, false, 'source mutations wait for an in-flight group qualification lock');
    releaseGroup(); await frozenGroup;
    const extra = await pendingExtra;

    const crossed = await loadPublicCorpusPage(db, { search: suffix, sort: 'fps', dir: 'desc' }, { take: 1, publicReferenceContextVersions: new Set([context.contextVersion]) });
    assert.equal(crossed.rows[0].id, publicId, 'stale off-page A must cross above B when its diagnostic fallback is faster');
    assert.ok(Math.abs(crossed.rows[0].fps - (100 + 240000 / 2473.2168) / 2) < 1e-10);
    assert.equal(crossed.rows[0].pl.total, null);
    assert.equal(crossed.rows[0].status.centerBasis, 'accepted');
    assert.deepEqual(await db.derivedResult.findUnique({ where: { id: otherProjection.derivedResultId } }), untouchedOther, 'unrelated group projection stays unchanged');
    assert.deepEqual(await db.derivedResult.findUnique({ where: { id: mixed.derivedResultId } }), unchangedOriginal, 'durable dependency invalidation preserves original derived values and membership');
    assert.equal((await page()).pl.total, null, 'a non-accepted extra sibling changes the full group-state certificate even when accepted membership is unchanged');
    await db.benchmarkRun.delete({ where: { id: extra.id } });
    await rebuildPublic();
    assert.equal((await page()).pl.total, mixed.derivedResult.plTotal);
    await db.benchmarkRun.update({ where: { id: runs[1].id }, data: { preRunEnvironmentCheck: { measurementGroup: shared, snapshot: { telemetry_sources: 'cpu_psutil', background_cpu_pct: 0 } } } });
    const oldSamplerPage = await loadPublicCorpusPage(db, { search: suffix, sort: 'fps', dir: 'desc' }, { take: 1, publicReferenceContextVersions: new Set([context.contextVersion]) });
    assert.equal(oldSamplerPage.rows[0].id, publicId, 'sampler provenance invalidates off-page qualification before sorting');
    assert.equal(oldSamplerPage.rows[0].pl.total, null);
    await assert.rejects(verifyCalibrationRetainedEvidence(db, document, root), /missing-corrected-background-observation/);
    await db.benchmarkRun.update({ where: { id: runs[1].id }, data: { preRunEnvironmentCheck: input(1).preRunEnvironmentCheck } });
    await rebuildPublic();
    assert.equal((await page()).pl.total, mixed.derivedResult.plTotal);
    // Two independent qualified groups exercise partial dependency loss while another remains.
    const coverageRecipe = await db.recipe.create({ data: { fingerprint: `${suffix}-coverage`, canonicalJson: {}, codecFamily: 'h264', encoderImplementation: 'libx264', preset: 'coverage-test', pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0', requestedRateControlMode: 'CRF', effectiveRateControlMode: 'CRF', requestedRateControl: {}, effectiveRateControl: {} } });
    for (const groupIndex of [0, 1]) for (const repetitionIndex of [1, 2]) {
      const groupId = `${suffix}-coverage-${groupIndex}`;
      const created = await persistence.createOrFetchRun({ ...input(repetitionIndex - 1), recipeId: coverageRecipe.id, payloadHash: hash(`${groupId}-${repetitionIndex}`), physicalSourceId: groupId, repetitionGroupId: groupId,
        preRunEnvironmentCheck: { snapshot: { telemetry_sources: 'cpu_psutil_thread_window_v1', background_cpu_pct: 0 }, measurementGroup: receipt([24000, 24001], groupId, suffix) } });
      await db.benchmarkRun.update({ where: { id: created.bundle.run.id }, data: { status: 'ACCEPTED' } });
      await db.artifact.update({ where: { id: created.bundle.artifact.id }, data: { storageState: 'RETAINED', storageProvider: 'localfs', storageKey: 'retained.bin', storageUrl: path.join(root, 'retained.bin') } });
      await db.qualityAnalysis.create({ data: { benchmarkRunId: created.bundle.run.id, artifactId: created.bundle.artifact.id, status: 'COMPLETE', metricModelId: 'test-model', analysisWorkerVersion: 'authoritative-analysis/test-worker', analysisProvenance: { workerBuildFingerprint: 'b'.repeat(64) }, vmafMean: 95, vmafP5: 90, videoBitrateBps: 1000000 } });
    }
    const coverage = await rebuildPublic(coverageRecipe);
    const coverageId = Prisma.sql`${coverage.derivedResultId}::text`;
    const oldScope = Prisma.sql`EXISTS (SELECT 1 FROM "DerivedResultMember" member JOIN "BenchmarkRun" counted ON counted.id = member."benchmarkRunId" WHERE member."derivedResultId" = ${coverageId} AND counted."physicalSourceId" = r."physicalSourceId" AND counted."campaignId" = r."campaignId" AND counted."repetitionGroupId" = r."repetitionGroupId")`;
    const scopeProof = async () => {
      const newScope = measurementGroupScopeForDerived(coverageId);
      const [proof] = await db.$queryRaw(Prisma.sql`SELECT
        (SELECT array_agg(r.id ORDER BY r.id COLLATE "C") FROM "BenchmarkRun" r WHERE ${oldScope}) AS "oldIds",
        (SELECT array_agg(r.id ORDER BY r.id COLLATE "C") FROM "BenchmarkRun" r WHERE ${newScope}) AS "newIds",
        ${measurementGroupStateHashSql(oldScope)} AS "oldHash", ${measurementGroupStateHashSql(newScope)} AS "newHash"`);
      return proof;
    };
    const storedCoverage = await db.derivedResult.findUniqueOrThrow({ where: { id: coverage.derivedResultId }, include: { members: true } });
    const readCoverage = async () => (await loadPublicCorpusPage(db, {}, { take: 1, id: `${protocol.id}::${suffix}::${coverageRecipe.id}::${environment.id}::test-model`, publicReferenceContextVersions: new Set([context.contextVersion]) })).rows[0];
    const baselineProof = await scopeProof();
    assert.equal(baselineProof.oldIds.length, 4);
    assert.deepEqual(baselineProof.newIds, baselineProof.oldIds);
    assert.equal(baselineProof.newHash, baselineProof.oldHash);
    assert.equal(baselineProof.newHash, storedCoverage.evidenceSummary.measurementGroupSnapshot.stateHash);
    assert.equal(storedCoverage.evidenceSummary.measurementGroupSnapshot.version, 'measurement-group-state/v3');
    assert.equal((await readCoverage()).pl.total, coverage.derivedResult.plTotal);
    // An empty extra key selects no rows; its only effect is conservative future invalidation.
    const emptyGroup = `${suffix}-empty-dependency`;
    await db.$executeRaw(Prisma.sql`INSERT INTO "DerivedResultGroupDependency" ("derivedResultId","physicalSourceId","campaignId","repetitionGroupId") VALUES (${coverageId},${emptyGroup},${suffix},${emptyGroup})`);
    assert.deepEqual(await scopeProof(), baselineProof);
    assert.equal((await readCoverage()).pl.total, coverage.derivedResult.plTotal);
    const emptyRun = { ...input(0) }; delete emptyRun.artifact;
    const emptyArrival = await db.benchmarkRun.create({ data: { ...emptyRun, recipeId: coverageRecipe.id, payloadHash: hash(emptyGroup), physicalSourceId: emptyGroup, repetitionGroupId: emptyGroup } });
    assert.equal((await readCoverage()).pl.total, null, 'an arrival under an extra empty key conservatively withdraws eligibility');
    await db.benchmarkRun.delete({ where: { id: emptyArrival.id } });
    await db.$executeRaw(Prisma.sql`DELETE FROM "DerivedResultGroupDependency" WHERE "derivedResultId" = ${coverageId} AND "repetitionGroupId" = ${emptyGroup}`);
    const dependencies = await db.$queryRaw(Prisma.sql`SELECT * FROM "DerivedResultGroupDependency" WHERE "derivedResultId" = ${coverageId}`);
    assert.equal(dependencies.length, 2);
    const restoreDependency = dependency => db.$executeRaw(Prisma.sql`INSERT INTO "DerivedResultGroupDependency" ("derivedResultId","physicalSourceId","campaignId","repetitionGroupId") VALUES (${coverageId},${dependency.physicalSourceId},${dependency.campaignId},${dependency.repetitionGroupId})`);
    await db.$executeRaw(Prisma.sql`DELETE FROM "DerivedResultGroupDependency" WHERE "derivedResultId" = ${coverageId} AND "repetitionGroupId" = ${dependencies[0].repetitionGroupId}`);
    assert.notEqual((await scopeProof()).newHash, baselineProof.oldHash);
    assert.equal((await readCoverage()).pl.total, null, 'partial dependency loss cannot publish PL');
    assert.ok((await db.derivedResult.findUniqueOrThrow({ where: { id: coverage.derivedResultId } })).invalidatedAt);
    await restoreDependency(dependencies[0]);
    await db.derivedResult.update({ where: { id: coverage.derivedResultId }, data: { invalidatedAt: null, invalidationReason: null } });
    assert.equal((await readCoverage()).pl.total, coverage.derivedResult.plTotal);
    await restoreDependency({ physicalSourceId: suffix, campaignId: suffix, repetitionGroupId: alternateReceipt.repetitionGroupId });
    assert.equal((await scopeProof()).newIds.length, 6, 'extra dependency includes cross-recipe siblings instead of hiding them');
    assert.equal((await readCoverage()).pl.total, null, 'extra run coverage cannot publish PL');
    await db.$executeRaw(Prisma.sql`DELETE FROM "DerivedResultGroupDependency" WHERE "derivedResultId" = ${coverageId} AND "repetitionGroupId" = ${alternateReceipt.repetitionGroupId}`);
    await db.derivedResult.update({ where: { id: coverage.derivedResultId }, data: { invalidatedAt: null, invalidationReason: null } });
    await db.$executeRaw(Prisma.sql`DELETE FROM "DerivedResultGroupDependency" WHERE "derivedResultId" = ${coverageId}`);
    assert.equal((await readCoverage()).pl.total, null, 'complete dependency loss fails the pre-sort eligibility fence');
    for (const dependency of dependencies) await restoreDependency(dependency);
    assert.deepEqual(await scopeProof(), baselineProof);
    assert.equal((await readCoverage()).pl.total, coverage.derivedResult.plTotal);
    const afterCoverage = await db.derivedResult.findUniqueOrThrow({ where: { id: coverage.derivedResultId }, include: { members: true } });
    assert.equal(afterCoverage.plTotal, storedCoverage.plTotal);
    assert.deepEqual(afterCoverage.evidenceSummary, storedCoverage.evidenceSummary, 'coverage faults never rewrite the version3 certificate');
    assert.deepEqual(afterCoverage.members, storedCoverage.members, 'coverage faults never rewrite historical members');
    const suspendedReview = await db.evidenceReview.create({ data: { id: crypto.randomUUID(), analysisId: analyses[1].id, benchmarkRunId: runs[1].id, artifactId: artifacts[1].id, artifactSha256: sha, metricModelId: 'test-model', analysisWorkerVersion: 'authoritative-analysis/test-worker', reviewerId: 'SYNTHETIC TEST NOT HUMAN', decision: 'INVESTIGATE', rationale: 'Synthetic sibling-review regression', evidenceLinks: [] } });
    await assert.rejects(verifyCalibrationRetainedEvidence(db, document, root), /ineligible-member/);
    assert.equal((await page()).pl.total, null, 'sibling review immediately invalidates the published group certificate');
    assert.equal((await loadRetainedReferenceEvidence(db, { benchmarkProtocolId: protocol.id, qualityModelId: 'test-model', suiteVersion: 'TEST ONLY' })).filter(row => row.recipeId === recipe.id).length, 0);
    await db.evidenceReview.create({ data: { id: crypto.randomUUID(), createdAt: new Date(suspendedReview.createdAt.getTime() + 1), supersedesId: suspendedReview.id, analysisId: analyses[1].id, benchmarkRunId: runs[1].id, artifactId: artifacts[1].id, artifactSha256: sha, metricModelId: 'test-model', analysisWorkerVersion: 'authoritative-analysis/test-worker', reviewerId: 'SYNTHETIC TEST NOT HUMAN', decision: 'REVOKE', rationale: 'Synthetic review revocation', evidenceLinks: [] } });
    await db.artifact.update({ where: { id: artifacts[1].id }, data: { storageKey: 'missing.bin', storageUrl: path.join(root, 'missing.bin') } });
    await assert.rejects(verifyCalibrationRetainedEvidence(db, document, root), /missing-or-corrupt-retained-group-object/);
  } finally { await db.$disconnect(); await rm(root, { recursive: true, force: true }); }
});
