import test from 'node:test';
import assert from 'node:assert/strict';
import { loadRecomputeInputs } from './activate-pl-v7-production.mjs';

test('activation verifies full persisted groups before filtering latest reviewed rows', async () => {
  const rows = [
    ['eligible-new', 'eligible', true], ['incomplete-new', 'incomplete', true],
    ['rejected-new', 'rejected', false], ['eligible-old', 'eligible', true],
  ].map(([id, benchmarkRunId, reviewEligible]) => ({
    id, benchmarkRunId, reviewEligible, metricModelId: 'model', evidenceReviews: [],
    artifact: { storageState: 'RETAINED' },
    benchmarkRun: { id: benchmarkRunId, benchmarkProtocol: { protocolVersion: '7.1' },
      testClip: {}, recipe: {}, environment: {} },
  }));
  const calls = [];
  const db = { qualityAnalysis: { findMany: async query => {
    assert.deepEqual(query.orderBy, [{ createdAt: 'desc' }, { id: 'desc' }]);
    return rows;
  } } };
  const output = await loadRecomputeInputs(db, 'protocol', { qualityModelId: 'model' }, {
    loadMeasurementGroupEligibility: async (client, run, options) => {
      assert.equal(client, db);
      assert.deepEqual(options, { metricModelId: 'model' });
      calls.push(run.id);
      return { eligible: run.id !== 'incomplete', reason: run.id === 'incomplete' ? 'MISSING_MEMBER' : null };
    },
    applyEffectiveReview: ({ analysisId }) => ({ eligible: rows.find(row => row.id === analysisId).reviewEligible }),
  });
  assert.deepEqual(calls, ['eligible', 'incomplete', 'rejected']);
  assert.deepEqual(output.map(row => row.qualityAnalysisId), ['eligible-new']);
  assert.equal(output[0].measurementGroup.eligible, true);
});
