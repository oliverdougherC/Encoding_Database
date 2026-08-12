import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DERIVED_RESULT_AGGREGATOR_VERSION,
  DEFAULT_RECOMMENDATION_EVIDENCE_POLICY,
  buildAggregateRunObservationsFromAnalyses,
  persistDerivedResultAggregate,
  rebuildDerivedResultAggregateFromAnalyses,
  rebuildDerivedResultAggregate,
} from '../dist/v7/aggregation.js';

test('default recommendation evidence policy stays explicitly provisional until PLA-87 calibration', () => {
  assert.match(DEFAULT_RECOMMENDATION_EVIDENCE_POLICY.policyVersion, /provisional-pre-calibration/);
  assert.equal(DEFAULT_RECOMMENDATION_EVIDENCE_POLICY.policyStatus, 'PROVISIONAL_UNCALIBRATED');
});

const identity = {
  kind: 'workload',
  benchmarkProtocolId: 'proto-1',
  protocolVersion: 'EDB-2026.1',
  sourceSuiteVersion: 'suite-v1',
  workloadId: 'sports-1080p',
  recipeId: 'recipe-1',
  recipeFingerprint: 'recipe-fp-1',
  environmentId: 'env-1',
  environmentFingerprint: 'env-fp-1',
  scoreContextId: 'score-1',
  scoreContextVersion: 'pl7-sports-v1',
  qualityModelId: 'vmaf-v1.0.16_3d0h',
  formulaVersion: '7.0',
};

const scoreContext = {
  workloadId: 'sports-1080p',
  workloadReferenceBitrateBps: 4_000_000,
};

const evidencePolicy = {
  policyVersion: 'recommendation-evidence/test-v1',
  policyStatus: 'CALIBRATED',
  defaultRecommendationMinimumTier: 'LOW',
  tiers: {
    low: {
      minimumAcceptedRuns: 2,
      minimumIndependentSources: 1,
      maximumPlConfidenceIntervalWidth: null,
    },
    medium: {
      minimumAcceptedRuns: 3,
      minimumIndependentSources: 2,
      maximumPlConfidenceIntervalWidth: 6,
    },
    high: {
      minimumAcceptedRuns: 3,
      minimumIndependentSources: 3,
      maximumPlConfidenceIntervalWidth: 1,
    },
  },
};

function buildAcceptedRun(id, overrides = {}) {
  return {
    benchmarkRunId: id,
    status: 'accepted',
    encodeFps: 60,
    sourceFps: 30,
    videoBitrateBps: 4_000_000,
    fileSizeBytes: 10_000_000,
    vmafMean: 94,
    vmafP5: 88,
    machineKey: 'machine-a',
    contributorKey: 'contributor-a',
    repetitionGroupId: `rep-${id}`,
    ...overrides,
  };
}

function aggregate(runs) {
  return rebuildDerivedResultAggregate({
    identity,
    scoreContext,
    evidencePolicy,
    runs,
    bootstrap: {
      iterations: 512,
      confidenceLevel: 0.95,
    },
  });
}

test('uncalibrated default policy never enables a public recommendation', () => {
  const result = rebuildDerivedResultAggregate({
    identity,
    scoreContext,
    evidencePolicy: DEFAULT_RECOMMENDATION_EVIDENCE_POLICY,
    runs: [
      buildAcceptedRun('run-a', { machineKey: 'machine-a', campaignId: 'campaign-a' }),
      buildAcceptedRun('run-b', { machineKey: 'machine-b', campaignId: 'campaign-b' }),
      buildAcceptedRun('run-c', { machineKey: 'machine-c', campaignId: 'campaign-c' }),
    ],
    bootstrap: { iterations: 128 },
  });

  assert.notEqual(result.evidence.tier, 'PROVISIONAL');
  assert.equal(result.evidence.policyStatus, 'PROVISIONAL_UNCALIBRATED');
  assert.equal(result.evidence.eligibleForDefaultRecommendation, false);
});

test('robust centers resist accepted outliers while suspect and invalid runs stay out of canonical PL', () => {
  const withExcludedEvidence = aggregate([
    buildAcceptedRun('run-a', { vmafMean: 95, vmafP5: 89, videoBitrateBps: 4_100_000, encodeFps: 61 }),
    buildAcceptedRun('run-b', { vmafMean: 94, vmafP5: 88, videoBitrateBps: 4_000_000, encodeFps: 60 }),
    buildAcceptedRun('run-c', { vmafMean: 10, vmafP5: 5, videoBitrateBps: 50_000_000, encodeFps: 10 }),
    buildAcceptedRun('run-suspect', {
      status: 'suspect',
      vmafMean: 1,
      vmafP5: 1,
      videoBitrateBps: 100_000_000,
      encodeFps: 1,
    }),
    buildAcceptedRun('run-invalid', {
      status: 'invalid',
      vmafMean: 1,
      vmafP5: 1,
      videoBitrateBps: 100_000_000,
      encodeFps: 1,
    }),
  ]);

  const acceptedOnly = aggregate([
    buildAcceptedRun('run-a', { vmafMean: 95, vmafP5: 89, videoBitrateBps: 4_100_000, encodeFps: 61 }),
    buildAcceptedRun('run-b', { vmafMean: 94, vmafP5: 88, videoBitrateBps: 4_000_000, encodeFps: 60 }),
    buildAcceptedRun('run-c', { vmafMean: 10, vmafP5: 5, videoBitrateBps: 50_000_000, encodeFps: 10 }),
  ]);

  assert.equal(withExcludedEvidence.derivedResult.centerVmafMean, 94);
  assert.equal(withExcludedEvidence.derivedResult.centerVmafP5, 88);
  assert.equal(withExcludedEvidence.derivedResult.centerEncodeFps, 60);
  assert.equal(withExcludedEvidence.derivedResult.centerVideoBitrateBps, 4_100_000);
  assert.equal(withExcludedEvidence.derivedResult.plTotal, acceptedOnly.derivedResult.plTotal);
  assert.equal(withExcludedEvidence.derivedResult.confidenceLower, acceptedOnly.derivedResult.confidenceLower);
  assert.equal(withExcludedEvidence.derivedResult.confidenceUpper, acceptedOnly.derivedResult.confidenceUpper);
  assert.equal(withExcludedEvidence.evidence.suspectRunCount, 1);
  assert.equal(withExcludedEvidence.evidence.invalidRunCount, 1);
  assert.deepEqual(withExcludedEvidence.members, ['run-a', 'run-b', 'run-c']);
});

test('one run and repeated same-machine/campaign runs remain provisional with unavailable confidence', () => {
  const single = aggregate([
    buildAcceptedRun('run-a'),
  ]);

  const repeatedSameMachine = aggregate([
    buildAcceptedRun('run-a', { contributorKey: 'contributor-a', machineKey: 'machine-a' }),
    buildAcceptedRun('run-b', { contributorKey: 'contributor-a', machineKey: 'machine-a' }),
    buildAcceptedRun('run-c', { contributorKey: 'contributor-a', machineKey: 'machine-a' }),
  ]);

  assert.equal(single.derivedResult.plTotal, repeatedSameMachine.derivedResult.plTotal);
  assert.equal(single.evidence.tier, 'PROVISIONAL');
  assert.equal(single.evidence.eligibleForDefaultRecommendation, false);
  assert.equal(repeatedSameMachine.evidence.tier, 'PROVISIONAL');
  assert.equal(repeatedSameMachine.evidence.eligibleForDefaultRecommendation, false);
  assert.equal(repeatedSameMachine.evidence.independentSourceCount, 1);
  assert.equal(repeatedSameMachine.evidence.repetitionCount, 3);
  assert.equal(single.confidenceIntervals.plTotal.method, 'unavailable');
  assert.equal(single.confidenceIntervals.plTotal.lower, null);
  assert.equal(single.confidenceIntervals.plTotal.upper, null);
  assert.equal(repeatedSameMachine.confidenceIntervals.plTotal.method, 'unavailable');
  assert.equal(repeatedSameMachine.confidenceIntervals.plTotal.width, null);
  assert.equal(repeatedSameMachine.evidence.bootstrapIterations, 0);
});

test('independent runs raise evidence tier without changing the point estimate', () => {
  const repeatedSameMachine = aggregate([
    buildAcceptedRun('run-a', { contributorKey: 'contributor-a', machineKey: 'machine-a' }),
    buildAcceptedRun('run-b', { contributorKey: 'contributor-a', machineKey: 'machine-a' }),
    buildAcceptedRun('run-c', { contributorKey: 'contributor-a', machineKey: 'machine-a' }),
  ]);

  const independent = aggregate([
    buildAcceptedRun('run-a', { contributorKey: 'contributor-a', machineKey: 'machine-a' }),
    buildAcceptedRun('run-b', { contributorKey: 'contributor-b', machineKey: 'machine-b' }),
    buildAcceptedRun('run-c', { contributorKey: 'contributor-c', machineKey: 'machine-c' }),
  ]);

  assert.equal(independent.derivedResult.plTotal, repeatedSameMachine.derivedResult.plTotal);
  assert.equal(independent.evidence.independentSourceCount, 3);
  assert.equal(independent.evidence.machineCount, 3);
  assert.equal(independent.evidence.contributorCount, 3);
  assert.equal(independent.evidence.tier, 'HIGH');
  assert.equal(independent.evidence.eligibleForDefaultRecommendation, true);
});

test('rebuild is deterministic and returns a derived-result-ready recomputation payload', () => {
  const first = aggregate([
    buildAcceptedRun('run-b', { vmafMean: 93, vmafP5: 87, encodeFps: 59 }),
    buildAcceptedRun('run-a', { vmafMean: 95, vmafP5: 89, encodeFps: 61 }),
    buildAcceptedRun('run-c', {
      status: 'rejected',
      vmafMean: 40,
      vmafP5: 35,
      videoBitrateBps: 20_000_000,
      encodeFps: 20,
    }),
  ]);

  const second = aggregate([
    buildAcceptedRun('run-c', {
      status: 'rejected',
      vmafMean: 40,
      vmafP5: 35,
      videoBitrateBps: 20_000_000,
      encodeFps: 20,
    }),
    buildAcceptedRun('run-a', { vmafMean: 95, vmafP5: 89, encodeFps: 61 }),
    buildAcceptedRun('run-b', { vmafMean: 93, vmafP5: 87, encodeFps: 59 }),
  ]);

  assert.deepEqual(first, second);
  assert.equal(first.derivedResult.aggregatorVersion, DERIVED_RESULT_AGGREGATOR_VERSION);
  assert.equal(first.derivedResult.scopeKey, 'workload:sports-1080p');
  assert.deepEqual(first.derivedResult.recomputationSpec, {
    protocolVersion: 'EDB-2026.1',
    sourceSuiteVersion: 'suite-v1',
    workloadId: 'sports-1080p',
    recipeFingerprint: 'recipe-fp-1',
    environmentFingerprint: 'env-fp-1',
    formulaVersion: '7.0',
    scoreContextVersion: 'pl7-sports-v1',
    qualityModelId: 'vmaf-v1.0.16_3d0h',
    scopeKey: 'workload:sports-1080p',
    includedStatuses: ['accepted', 'suspect', 'rejected'],
    aggregatorVersion: DERIVED_RESULT_AGGREGATOR_VERSION,
    selectedAnalysisIds: [],
    analysisWorkerVersions: [],
  });
  assert.equal(first.derivedResult.invalidRunCount, 0);
  assert.equal(first.derivedResult.evidenceSummary.invalidRunCount, 0);
  assert.equal(first.derivedResult.confidenceIntervals.plTotal.method, 'unavailable');
  assert.equal(first.derivedResult.dispersion.plTotal.sampleCount, 2);
});

test('cluster bootstrap resamples independent machine/campaign centers rather than raw repeats', () => {
  const result = aggregate([
    buildAcceptedRun('a-1', { machineKey: 'machine-a', campaignId: 'campaign-a', vmafMean: 90 }),
    buildAcceptedRun('a-2', { machineKey: 'machine-a', campaignId: 'campaign-a', vmafMean: 92 }),
    buildAcceptedRun('a-3', { machineKey: 'machine-a', campaignId: 'campaign-a', vmafMean: 94 }),
    buildAcceptedRun('b-1', { machineKey: 'machine-b', campaignId: 'campaign-b', vmafMean: 98 }),
  ]);

  assert.equal(result.evidence.independentSourceCount, 2);
  assert.equal(result.derivedResult.centerVmafMean, 95);
  assert.equal(result.confidenceIntervals.vmafMean.method, 'cluster-bootstrap-percentile');
  assert.ok(result.confidenceIntervals.vmafMean.width > 0);
});

test('analysis records rebuild with explicit invalid counts and preserve accepted membership only', () => {
  const result = rebuildDerivedResultAggregateFromAnalyses({
    identity,
    scoreContext,
    evidencePolicy,
    analyses: [
      {
        qualityAnalysisId: 'analysis-a',
        analysisWorkerVersion: 'worker-v1',
        benchmarkRunId: 'run-a',
        benchmarkRunStatus: 'ACCEPTED',
        qualityAnalysisStatus: 'COMPLETE',
        encodeFps: 61,
        sourceFps: 30,
        videoBitrateBps: 4_100_000,
        fileSizeBytes: 10_100_000,
        vmafMean: 95,
        vmafP5: 89,
        machineKey: 'machine-a',
        contributorKey: 'contributor-a',
        repetitionGroupId: 'rep-a',
      },
      {
        qualityAnalysisId: 'analysis-b',
        analysisWorkerVersion: 'worker-v1',
        benchmarkRunId: 'run-b',
        benchmarkRunStatus: 'SUSPECT',
        qualityAnalysisStatus: 'COMPLETE',
        encodeFps: 50,
        sourceFps: 30,
        videoBitrateBps: 4_500_000,
        fileSizeBytes: 11_000_000,
        vmafMean: 90,
        vmafP5: 80,
        machineKey: 'machine-a',
        contributorKey: 'contributor-a',
        repetitionGroupId: 'rep-b',
      },
      {
        qualityAnalysisId: 'analysis-c',
        analysisWorkerVersion: 'worker-v1',
        benchmarkRunId: 'run-c',
        benchmarkRunStatus: 'INVALID',
        qualityAnalysisStatus: 'FAILED',
        encodeFps: 10,
        sourceFps: 30,
        videoBitrateBps: 40_000_000,
        fileSizeBytes: 99_000_000,
        vmafMean: 10,
        vmafP5: 5,
      },
    ],
  });

  assert.deepEqual(result.members, ['run-a']);
  assert.equal(result.evidence.acceptedRunCount, 1);
  assert.equal(result.evidence.suspectRunCount, 1);
  assert.equal(result.evidence.invalidRunCount, 1);
  assert.equal(result.derivedResult.invalidRunCount, 1);
});

test('analysis status mapping excludes pending and preserves ordering', () => {
  const observations = buildAggregateRunObservationsFromAnalyses([
    {
      qualityAnalysisId: 'analysis-c',
      analysisWorkerVersion: 'worker-v1',
      benchmarkRunId: 'run-c',
      benchmarkRunStatus: 'INVALID',
      qualityAnalysisStatus: 'FAILED',
      encodeFps: null,
      sourceFps: null,
      videoBitrateBps: null,
      fileSizeBytes: null,
      vmafMean: null,
      vmafP5: null,
    },
    {
      qualityAnalysisId: 'analysis-a',
      analysisWorkerVersion: 'worker-v1',
      benchmarkRunId: 'run-a',
      benchmarkRunStatus: 'PENDING',
      qualityAnalysisStatus: 'PENDING',
      encodeFps: null,
      sourceFps: null,
      videoBitrateBps: null,
      fileSizeBytes: null,
      vmafMean: null,
      vmafP5: null,
    },
    {
      qualityAnalysisId: 'analysis-b',
      analysisWorkerVersion: 'worker-v1',
      benchmarkRunId: 'run-b',
      benchmarkRunStatus: 'REJECTED',
      qualityAnalysisStatus: 'REJECTED',
      encodeFps: null,
      sourceFps: null,
      videoBitrateBps: null,
      fileSizeBytes: null,
      vmafMean: null,
      vmafP5: null,
    },
  ]);

  assert.deepEqual(observations.map((entry) => [entry.benchmarkRunId, entry.status]), [
    ['run-b', 'rejected'],
    ['run-c', 'invalid'],
  ]);
});

test('persistDerivedResultAggregate upserts derived rows and rewrites member links', async () => {
  const calls = [];
  const tx = {
    derivedResult: {
      async upsert(args) {
        calls.push(['upsert', args]);
        return { id: 'derived-1' };
      },
    },
    derivedResultMember: {
      async deleteMany(args) {
        calls.push(['deleteMany', args]);
      },
      async createMany(args) {
        calls.push(['createMany', args]);
      },
    },
  };
  const client = {
    async $transaction(fn) {
      return fn(tx);
    },
  };

  const result = await persistDerivedResultAggregate(client, {
    identity,
    scoreContext,
    evidencePolicy,
    analyses: [
      {
        qualityAnalysisId: 'analysis-a',
        analysisWorkerVersion: 'worker-v1',
        benchmarkRunId: 'run-a',
        benchmarkRunStatus: 'ACCEPTED',
        qualityAnalysisStatus: 'COMPLETE',
        encodeFps: 61,
        sourceFps: 30,
        videoBitrateBps: 4_100_000,
        fileSizeBytes: 10_100_000,
        vmafMean: 95,
        vmafP5: 89,
        machineKey: 'machine-a',
        contributorKey: 'contributor-a',
        repetitionGroupId: 'rep-a',
      },
    ],
  });

  assert.equal(result.derivedResultId, 'derived-1');
  assert.deepEqual(calls.map(([name]) => name), ['upsert', 'deleteMany', 'createMany']);
  assert.equal(calls[0][1].create.invalidRunCount, 0);
  assert.equal(calls[0][1].create.evidenceSummary.invalidRunCount, 0);
  assert.equal(calls[0][1].create.confidenceIntervals.plTotal.method, 'unavailable');
  assert.deepEqual(calls[2][1].data, [{
    derivedResultId: 'derived-1',
    benchmarkRunId: 'run-a',
    qualityAnalysisId: 'analysis-a',
  }]);
});
