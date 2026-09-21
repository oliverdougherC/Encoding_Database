import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DEFAULT_RECOMMENDATION_EVIDENCE_POLICY } from '../dist/v7/aggregation.js';
import { canonicalJsonString, sha256Hex } from '../dist/v7/persistence.js';
import { buildScoringBehaviorManifest, buildScoringBehaviorHash, loadRecommendationEvidencePolicyForContext } from '../dist/v7/recommendationPolicy.js';

test('deployed hash-bound policy survives reload and rejects mismatch without promoting sparse fallback', () => {
  const root = mkdtempSync(path.join(os.tmpdir(), 'encodingdb-policy-test-'));
  try {
    const policy = { ...DEFAULT_RECOMMENDATION_EVIDENCE_POLICY, policyStatus: 'CALIBRATED', policyVersion: 'TEST ONLY policy' };
    const context = { workloads: [{ workloadId: 'test-workload', workloadReferenceBitrateBps: 1000000, referenceFrontier: [] }], scoringBehaviorHash: buildScoringBehaviorHash(), contextVersion: 'test-context', formulaVersion: '7.0', qualityModelId: 'test-model', transformConstants: { qualityExponent: 2.4 }, provenance: { sourceMode: 'retained-benchmark-evidence' }, activation: { stage: 'PRODUCTION', productionActivationAllowed: true, calibrationReviewHash: 'a'.repeat(64) }, recommendationEvidencePolicy: policy, recommendationEvidencePolicyHash: sha256Hex(canonicalJsonString(policy)) };
    context.hash = sha256Hex(canonicalJsonString(context));
    const filename = path.join(root, 'context.json'); writeFileSync(filename, JSON.stringify(context));
    const record = { ...context, workloadReferenceBitrateBps: 1000000, workloadId: 'test-workload', referenceFrontier: { referenceFrontier: [], contextHash: context.hash, recommendationEvidencePolicy: policy, recommendationEvidencePolicyHash: context.recommendationEvidencePolicyHash } };
    assert.equal(loadRecommendationEvidencePolicyForContext(record, {}).policyStatus, 'PROVISIONAL_UNCALIBRATED');
    assert.deepEqual(loadRecommendationEvidencePolicyForContext(record, { PL_V7_REFERENCE_CONTEXT_PATH: filename }), policy);
    assert.deepEqual(loadRecommendationEvidencePolicyForContext(record, { PL_V7_REFERENCE_CONTEXT_PATH: filename }), policy);
    assert.throws(() => loadRecommendationEvidencePolicyForContext({ ...record, contextVersion: 'different' }, { PL_V7_REFERENCE_CONTEXT_PATH: filename }), /incompatible/);
    context.recommendationEvidencePolicy.tiers.high.minimumIndependentSources = 1;
    writeFileSync(filename, JSON.stringify(context));
    assert.throws(() => loadRecommendationEvidencePolicyForContext(record, { PL_V7_REFERENCE_CONTEXT_PATH: filename }), /hash mismatch/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});


test('aggregation-only implementation changes invalidate the reviewed behavior manifest', () => {
  const baseline = buildScoringBehaviorManifest((module) => `compiled original ${module}`);
  const changed = buildScoringBehaviorManifest((module) => module === './aggregation.js' ? 'different source bootstrap and center rule' : `compiled original ${module}`);
  assert.notEqual(sha256Hex(canonicalJsonString(baseline)), sha256Hex(canonicalJsonString(changed)));
  assert.deepEqual(baseline.filter(entry => entry.module !== './aggregation.js'), changed.filter(entry => entry.module !== './aggregation.js'));
  for (const module of ['./referenceContext.js', './reviews.js', './persistence.js', './recommendationPolicy.js', './calibrationRanking.js']) {
    assert.ok(baseline.some(entry => entry.module === module));
  }
});
