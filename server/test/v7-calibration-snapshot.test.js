import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { randomUUID, createHash } from 'node:crypto';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { PrismaClient } from '@prisma/client';
import { exportCalibrationSnapshot, importCalibrationSnapshot } from '../../scripts/calibration-evidence-snapshot.mjs';
import { withReadOnlyCalibrationEvidence } from '../../scripts/activate-pl-v7-production.mjs';

async function seed(db, root, suffix, label, sharedFingerprint) {
  const protocol = await db.benchmarkProtocol.create({ data: { protocolVersion: '7.1', sourceSuiteVersion: label === 'b' ? 'encodingdb-validation-holdouts-v1' : `TEST ONLY ${label}`, minimumClientVersion: 'client/0.3.0', canonicalRecipeRules: {}, canonicalOutputRules: {}, metricWorkerVersion: suffix } });
  const clip = await db.testClip.create({ data: { suiteId: label + suffix, suiteVersion: label === 'b' ? 'encodingdb-validation-holdouts-v1' : `TEST ONLY ${label}`, manifestVersion: 'test', clipKey: label + suffix, displayName: 'TEST ONLY snapshot fixture', workloadId: label + suffix, contentClass: 'talking-head', sourceProvenance: { testOnly: true }, sha256: label + suffix, byteSize: 1, exactFrameCount: 720, exactDurationSeconds: 30, frameRateNumerator: 24, frameRateDenominator: 1, width: 1920, height: 1080, pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0' } });
  const recipe = await db.recipe.create({ data: { fingerprint: sharedFingerprint, canonicalJson: {}, codecFamily: 'h264', encoderImplementation: 'libx264', pixelFormat: 'yuv420p', bitDepth: 8, chromaSubsampling: '4:2:0', requestedRateControlMode: 'CRF', effectiveRateControlMode: 'CRF', requestedRateControl: {}, effectiveRateControl: {} } });
  const environment = await db.environment.create({ data: { fingerprint: sharedFingerprint, canonicalJson: {}, cpuModel: 'TEST ONLY', cpuArchitecture: 'x86_64', osName: 'test', osVersion: 'test', physicalMemoryBytes: 1073741824n, ffmpegBuildFingerprint: 'test', ffmpegVersion: 'test', clientVersion: 'client/0.3.0' } });
  const run = await db.benchmarkRun.create({ data: { benchmarkProtocolId: protocol.id, testClipId: clip.id, workloadId: clip.workloadId, recipeId: recipe.id, environmentId: environment.id, payloadHash: label + suffix, physicalSourceId: 'same-test-source', encodeTimerBoundary: 'ffmpeg-process-v1', status: label === 'a' ? 'ACCEPTED' : 'SUSPECT', encodeWallTimeMs: 1000, encodeFps: 720, sourceFps: 24, realTimeRatio: 30 } });
  const bytes = Buffer.from(`TEST ONLY encoded-object-${label}-${suffix}`); const digest = createHash('sha256').update(bytes).digest('hex');
  await mkdir(root, { recursive: true }); await writeFile(path.join(root, digest), bytes);
  const artifact = await db.artifact.create({ data: { benchmarkRunId: run.id, role: 'ENCODED', sha256: digest, byteSize: bytes.length, storageState: label === 'a' ? 'RETAINED' : 'VERIFIED', storageProvider: 'localfs', storageKey: digest, storageUrl: path.join(root, digest) } });
  const analysis = await db.qualityAnalysis.create({ data: { benchmarkRunId: run.id, artifactId: artifact.id, status: label === 'a' ? 'COMPLETE' : 'SUSPECT', metricModelId: 'TEST ONLY MODEL', analysisWorkerVersion: suffix, analysisProvenance: { testOnly: true }, completedAt: new Date(), vmafMean: label === 'a' ? 95.125 : 88.75, vmafP5: 80, xpsnr: 36, videoBitrateBps: 1000000 } });
  let review;
  if (label === 'b') review = await db.evidenceReview.create({ data: { analysisId: analysis.id, benchmarkRunId: run.id, artifactId: artifact.id, artifactSha256: digest, metricModelId: analysis.metricModelId, analysisWorkerVersion: analysis.analysisWorkerVersion, reviewerId: 'TEST ONLY snapshot fixture, not human judgment', decision: 'INVESTIGATE', rationale: 'TEST ONLY snapshot preservation fixture, not an actual perceptual decision.', evidenceLinks: ['https://example.invalid/test-only'] } });
  return { protocol, recipe, environment, run, artifact, analysis, review };
}

test('two real PostgreSQL evidence namespaces combine without changing measured IDs, hashes or flags; external activation binding is read-only', { skip: !process.env.SNAPSHOT_SOURCE_A_URL || !process.env.SNAPSHOT_SOURCE_B_URL || !process.env.SNAPSHOT_COMBINED_URL }, async () => {
  const clients = [process.env.SNAPSHOT_SOURCE_A_URL, process.env.SNAPSHOT_SOURCE_B_URL, process.env.SNAPSHOT_COMBINED_URL].map(url => new PrismaClient({ datasources: { db: { url } } }));
  const [a, b, combined] = clients; const root = await mkdtemp(path.join(os.tmpdir(), 'encodingdb-calibration-snapshot-')); const suffix = randomUUID();
  try {
    const first = await seed(a, path.join(root, 'a'), suffix, 'a', `shared-${suffix}`);
    const second = await seed(b, path.join(root, 'b'), suffix, 'b', `shared-${suffix}`);
    await exportCalibrationSnapshot(a, { runIds: [first.run.id], sourceRoot: path.join(root, 'a'), output: path.join(root, 'snapshot-a') });
    await exportCalibrationSnapshot(b, { runIds: [second.run.id], sourceRoot: path.join(root, 'b'), output: path.join(root, 'snapshot-b') });
    const storage = path.join(root, 'combined');
    await importCalibrationSnapshot(combined, { snapshotDirectory: path.join(root, 'snapshot-a'), storageRoot: storage });
    const restored = await importCalibrationSnapshot(combined, { snapshotDirectory: path.join(root, 'snapshot-b'), storageRoot: storage });
    assert.deepEqual(restored.preservedRunIds, [second.run.id]); assert.deepEqual(restored.preservedAnalysisIds, [second.analysis.id]); assert.deepEqual(restored.preservedArtifactIds, [second.artifact.id]);
    assert.equal(restored.dimensionAliases.recipes[second.recipe.id], first.recipe.id);
    assert.equal((await combined.qualityAnalysis.findUnique({ where: { id: second.analysis.id } })).status, 'SUSPECT');
    assert.equal((await combined.evidenceReview.findUnique({ where: { id: second.review.id } })).decision, 'INVESTIGATE');
    assert.equal((await combined.qualityAnalysis.findUnique({ where: { id: first.analysis.id } })).vmafMean, 95.125);
    assert.equal((await combined.environment.findUnique({ where: { id: first.environment.id } })).physicalMemoryBytes, 1073741824n);
    await importCalibrationSnapshot(combined, { snapshotDirectory: path.join(root, 'snapshot-a'), storageRoot: storage });
    assert.equal(await combined.benchmarkRun.count({ where: { id: { in: [first.run.id, second.run.id] } } }), 2);
    await writeFile(path.join(root, 'protocols.json'), JSON.stringify([first.protocol.id, second.protocol.id]));
    assert.throws(() => execFileSync(process.execPath, [fileURLToPath(new URL('../../scripts/generate-calibration-evidence.mjs', import.meta.url)), '--benchmark-protocol-ids', path.join(root, 'protocols.json'), '--quality-model-id', 'TEST ONLY MODEL', '--calibration-version', 'TEST ONLY snapshot rehearsal', '--output', path.join(root, 'draft.json')], { env: { ...process.env, DATABASE_URL: process.env.SNAPSHOT_COMBINED_URL } }), /No retained authoritative calibration evidence/);
    const readCount = await withReadOnlyCalibrationEvidence(combined, a, async tx => {
      assert.equal((await tx.$queryRawUnsafe('SHOW transaction_read_only'))[0].transaction_read_only, 'on');
      return tx.qualityAnalysis.count({ where: { id: { in: [first.analysis.id, second.analysis.id] } } });
    });
    assert.equal(readCount, 2);
    await assert.rejects(withReadOnlyCalibrationEvidence(combined, a, tx => tx.benchmarkRun.update({ where: { id: first.run.id }, data: { status: 'INVALID' } })), /read-only transaction/);
    await writeFile(path.join(root, 'snapshot-b', 'objects', second.artifact.sha256), 'tampered');
    await assert.rejects(importCalibrationSnapshot(combined, { snapshotDirectory: path.join(root, 'snapshot-b'), storageRoot: storage }), /object hash or size mismatch/);
    assert.equal((await a.benchmarkRun.findUnique({ where: { id: first.run.id } })).status, 'ACCEPTED');
    assert.equal((await combined.benchmarkRun.findUnique({ where: { id: first.run.id } })).status, 'ACCEPTED');
  } finally { await Promise.all(clients.map(client => client.$disconnect())); await rm(root, { recursive: true, force: true }); }
});
