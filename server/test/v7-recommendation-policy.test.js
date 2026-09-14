import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DEFAULT_RECOMMENDATION_EVIDENCE_POLICY } from '../dist/v7/aggregation.js';
import { canonicalJsonString, sha256Hex } from '../dist/v7/persistence.js';
import { buildScoringBehaviorHash, loadRecommendationEvidencePolicyForContext } from '../dist/v7/recommendationPolicy.js';

test('deployed hash-bound policy survives reload and rejects mismatch without promoting sparse fallback', () => {
  const root = mkdtempSync(path.join(os.tmpdir(), 'encodingdb-policy-test-'));
  try {
    const policy = { ...DEFAULT_RECOMMENDATION_EVIDENCE_POLICY, policyStatus: 'CALIBRATED', policyVersion: 'TEST ONLY policy' };
    const context = { scoringBehaviorHash: buildScoringBehaviorHash(), contextVersion: 'test-context', formulaVersion: '7.0', qualityModelId: 'test-model', transformConstants: { qualityExponent: 2.4 }, provenance: { sourceMode: 'retained-benchmark-evidence' }, activation: { stage: 'PRODUCTION', productionActivationAllowed: true, calibrationReviewHash: 'a'.repeat(64) }, recommendationEvidencePolicy: policy, recommendationEvidencePolicyHash: sha256Hex(canonicalJsonString(policy)) };
    context.hash = sha256Hex(canonicalJsonString(context));
    const filename = path.join(root, 'context.json'); writeFileSync(filename, JSON.stringify(context));
    const record = { ...context, workloadId: 'test-workload', referenceFrontier: { contextHash: context.hash, recommendationEvidencePolicy: policy, recommendationEvidencePolicyHash: context.recommendationEvidencePolicyHash } };
    assert.equal(loadRecommendationEvidencePolicyForContext(record, {}).policyStatus, 'PROVISIONAL_UNCALIBRATED');
    assert.deepEqual(loadRecommendationEvidencePolicyForContext(record, { PL_V7_REFERENCE_CONTEXT_PATH: filename }), policy);
    assert.deepEqual(loadRecommendationEvidencePolicyForContext(record, { PL_V7_REFERENCE_CONTEXT_PATH: filename }), policy);
    assert.throws(() => loadRecommendationEvidencePolicyForContext({ ...record, contextVersion: 'different' }, { PL_V7_REFERENCE_CONTEXT_PATH: filename }), /incompatible/);
    context.recommendationEvidencePolicy.tiers.high.minimumIndependentSources = 1;
    writeFileSync(filename, JSON.stringify(context));
    assert.throws(() => loadRecommendationEvidencePolicyForContext(record, { PL_V7_REFERENCE_CONTEXT_PATH: filename }), /hash mismatch/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
