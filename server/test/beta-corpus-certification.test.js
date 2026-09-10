import assert from 'node:assert/strict';
import test from 'node:test';
import { validateBetaSnapshot, LEGACY_SUITE_REFERENCE, serializeEvidence } from '../scripts/verify-beta-corpus.mjs';
test('evidence serialization preserves exact Prisma memory integers', () => {
  const bytes = 2n ** 60n + 1n;
  const result = JSON.parse(serializeEvidence({ environment: { physicalMemoryBytes: bytes }, score: null, samples: 2 }));
  assert.equal(result.environment.physicalMemoryBytes, '1152921504606846977');
  assert.equal(result.score, null);
  assert.equal(result.samples, 2);
});
function fixture() {
  const clips = Array.from({ length: 7 }, (_, i) => ({ id: `real-${i}`, contentClass: `class-${i}`, sha256: 'a'.repeat(64), acquisition: { kind: 'retained-original' }, source: { reviewed: true, redistributionApproved: true }, media: { frameCount: 240 } }));
  const runs = clips.flatMap(c => [1, 2].map(n => ({ id: `${c.id}-${n}`, workloadId: c.id, repetitionIndex: n, status: 'ACCEPTED', testClip: { sha256: c.sha256, suiteVersion: 'v1', clipKey: c.id }, inputHash: c.sha256, derivedMembers: [], recipeId: 'recipe', environmentId: 'env', benchmarkProtocolId: 'protocol', artifacts: [{ id: `${c.id}-${n}-artifact`, role: 'ENCODED', storageState: 'RETAINED', sha256: 'b'.repeat(64), byteSize: 42, diskVerification: { sha256: 'b'.repeat(64), byteSize: 42 } }], qualityAnalyses: [{ id: `${c.id}-${n}-analysis`, artifactId: `${c.id}-${n}-artifact`, status: 'COMPLETE', analysisWorkerVersion: 'worker', analysisProvenance: { pipelineVersion: 'encodingdb-artifact-pipeline/v1', contractVersion: 'contract', modelSha256: 'c'.repeat(64), referencePath: '/reference' }, vmafDistribution: { frameCount: 240 }, vmafMean: 95, vmafP5: 91, videoBitrateBps: 2000 }] })));
  const rows = clips.map(c => ({ workloadId: c.id, recipe: { id: 'recipe' }, environment: { id: 'env' }, versions: { benchmarkProtocolId: 'protocol' }, sampleCounts: { accepted: 2 }, pl: { total: null, components: null }, status: { scoring: 'UNSCORED_NO_PUBLIC_DERIVED_RESULT' } }));
  return { manifest: { suiteVersion: 'v1', clips }, snapshot: { legacyRejection: { status: 404, response: { error: 'Canonical suite clip could not be resolved by clipKey or sha256' }, acceptedOldRunCount: 0, createdPayloadCount: 0, source: LEGACY_SUITE_REFERENCE, request: { testClip: LEGACY_SUITE_REFERENCE } }, runs, serverRows: rows, frontendRows: structuredClone(rows), frontendPage: { ok: true }, plConfiguration: { testOnlyEnabled: false, referenceBitrates: '', referenceVersion: '', referencePath: '' }, uploadInterruptionEvidence: { injectedFailures: 1, uploadAttempts: [{ injected: true, status: 503, benchmarkRunId: 'real-0-1' }] }, reanalysis: { status: 202, idempotent: true, benchmarkRunId: 'real-0-1', qualityAnalysisId: 'real-0-1-analysis' } } };
}
test('accepts a complete unscored evidence snapshot', () => { const f = fixture(); assert.equal(validateBetaSnapshot(f.snapshot, f.manifest), true); });
for (const [name, mutate, message] of [
  ['synthetic references', f => { f.manifest.clips[0].acquisition.kind = 'generated'; }, /Nonfinal/],
  ['missing repeated measurements', f => { f.snapshot.runs.splice(1, 1); }, /Repeated/],
  ['changed canonical hash', f => { f.snapshot.runs[0].inputHash = 'd'.repeat(64); }, /identity/],
  ['missing retained bytes', f => { delete f.snapshot.runs[0].artifacts[0].diskVerification; }, /Retained bytes/],
  ['incomplete frame distribution', f => { f.snapshot.runs[0].qualityAnalyses[0].vmafDistribution.frameCount = 1; }, /distribution/],
  ['generic schema rejection', f => { f.snapshot.legacyRejection.status = 400; f.snapshot.legacyRejection.response.error = 'Invalid payload'; }, /Legacy submission/],
  ['accepted legacy run', f => { f.snapshot.legacyRejection.acceptedOldRunCount = 1; }, /Legacy submission/],
  ['PL path enabled', f => { f.snapshot.plConfiguration.referencePath = '/test/context.json'; }, /PL must/],
  ['PL context enabled', f => { f.snapshot.plConfiguration.testOnlyEnabled = true; }, /PL must/],
  ['PL unexpectedly available', f => { f.snapshot.serverRows[0].pl.total = 1; }, /unscored/],
  ['frontend missing row', f => { f.snapshot.frontendRows.shift(); }, /frontend lacks/],
  ['unrecovered interruption', f => { f.snapshot.uploadInterruptionEvidence.uploadAttempts[0].benchmarkRunId = 'missing'; }, /Interrupted/],
  ['failed reanalysis idempotence', f => { f.snapshot.reanalysis.idempotent = false; }, /idempotence/],
]) test(`rejects ${name}`, () => { const f = fixture(); mutate(f); assert.throws(() => validateBetaSnapshot(f.snapshot, f.manifest), message); });
