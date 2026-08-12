import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  buildReferenceContextFromRetainedEvidence,
  buildGeneralScopeWorkloadId,
  buildReferenceContextFromSweep,
  buildScoreContextSeedRecords,
  loadRetainedReferenceEvidence,
  loadReferenceContext,
  persistGeneralDerivedResultFromWorkloadEvidence,
  persistScoreContextsFromReferenceContext,
  recomputeReferenceScores,
} from '../dist/v7/referenceContext.js';

const sweepFixturePath = new URL('../config/reference-sweeps/test-only.synthetic.encodingdb-test-suite-v1.vmaf-v1-sdr-sd.json', import.meta.url);
const contextFixturePath = new URL('../config/reference-contexts/test-only.synthetic.encodingdb-test-suite-v1.vmaf-v1-sdr-sd.context.json', import.meta.url);

function loadSweepFixture() {
  return JSON.parse(readFileSync(sweepFixturePath, 'utf8'));
}

function buildEvidenceForAllWorkloads(context, environmentId, recipeId = 'recipe-1') {
  return context.workloads.map((workload, index) => ({
    benchmarkRunId: `${environmentId}-${workload.workloadId}`,
    benchmarkProtocolVersion: context.benchmarkProtocolVersion,
    sourceSuiteVersion: context.sourceSuiteVersion,
    workloadId: workload.workloadId,
    testClipId: `clip-${index + 1}`,
    contentClass: workload.contentClass,
    recipeId,
    recipeFingerprint: `${recipeId}-fingerprint`,
    environmentId,
    environmentFingerprint: `${environmentId}-fingerprint`,
    qualityModelId: context.qualityModelId,
    benchmarkRunStatus: 'ACCEPTED',
    qualityAnalysisStatus: 'COMPLETE',
    encodeFps: 72 + index,
    sourceFps: 24,
    videoBitrateBps: Math.round(workload.workloadReferenceBitrateBps * 0.92),
    fileSizeBytes: 1_000_000 + index * 10_000,
    vmafMean: 92,
    vmafP5: 88,
  }));
}

function buildRetainedReferenceEvidenceFixture() {
  const synthetic = loadReferenceContext(contextFixturePath);
  return synthetic.workloads.flatMap((workload, index) => ([
    {
      benchmarkRunId: `run-${index + 1}-a`,
      benchmarkProtocolId: 'proto-1',
      benchmarkProtocolVersion: 'EDB-2026.1',
      sourceSuiteVersion: synthetic.sourceSuiteVersion,
      workloadId: workload.workloadId,
      testClipId: `clip-${index + 1}`,
      contentClass: workload.contentClass,
      benchmarkRunStatus: 'ACCEPTED',
      payloadHash: `${String(index + 1).padStart(64, 'a')}`.slice(0, 64),
      recipeId: 'recipe-1',
      recipeFingerprint: 'recipe-fingerprint',
      environmentId: 'env-1',
      environmentFingerprint: 'environment-fingerprint',
      artifactId: `artifact-${index + 1}-a`,
      artifactRole: 'ENCODED',
      artifactStorageState: 'RETAINED',
      artifactSha256: `${String(index + 1).padStart(64, 'b')}`.slice(0, 64),
      qualityAnalysisId: `analysis-${index + 1}-a`,
      qualityAnalysisStatus: 'COMPLETE',
      analysisWorkerVersion: 'authoritative-analysis/v1',
      qualityModelId: 'vmaf-v1-sdr-sd',
      videoBitrateBps: Math.round(workload.workloadReferenceBitrateBps * 0.78),
      vmafMean: 86.5,
    },
    {
      benchmarkRunId: `run-${index + 1}-b`,
      benchmarkProtocolId: 'proto-1',
      benchmarkProtocolVersion: 'EDB-2026.1',
      sourceSuiteVersion: synthetic.sourceSuiteVersion,
      workloadId: workload.workloadId,
      testClipId: `clip-${index + 1}`,
      contentClass: workload.contentClass,
      benchmarkRunStatus: 'ACCEPTED',
      payloadHash: `${String(index + 1).padStart(64, 'c')}`.slice(0, 64),
      recipeId: 'recipe-1',
      recipeFingerprint: 'recipe-fingerprint',
      environmentId: 'env-1',
      environmentFingerprint: 'environment-fingerprint',
      artifactId: `artifact-${index + 1}-b`,
      artifactRole: 'ENCODED',
      artifactStorageState: 'RETAINED',
      artifactSha256: `${String(index + 1).padStart(64, 'd')}`.slice(0, 64),
      qualityAnalysisId: `analysis-${index + 1}-b`,
      qualityAnalysisStatus: 'COMPLETE',
      analysisWorkerVersion: 'authoritative-analysis/v1',
      qualityModelId: 'vmaf-v1-sdr-sd',
      videoBitrateBps: Math.round(workload.workloadReferenceBitrateBps * 1.08),
      vmafMean: 92.4,
    },
  ]));
}

test('reference context generation is deterministic and order-invariant', () => {
  const sweep = loadSweepFixture();
  const left = buildReferenceContextFromSweep(sweep);
  const reordered = {
    ...sweep,
    requiredWorkloads: [...sweep.requiredWorkloads].reverse(),
    requiredContentClasses: [...sweep.requiredContentClasses].reverse(),
    samples: [...sweep.samples].reverse(),
  };
  const right = buildReferenceContextFromSweep(reordered);
  const fixture = loadReferenceContext(contextFixturePath);

  assert.deepEqual(left, right);
  assert.deepEqual(left, fixture);
  assert.equal(fixture.activation.stage, 'TEST_ONLY_PROVISIONAL');
  assert.equal(fixture.activation.productionActivationAllowed, false);
});

test('reference context generation rejects workloads whose frontier cannot bracket VMAF 90', () => {
  const sweep = loadSweepFixture();
  const broken = {
    ...sweep,
    samples: sweep.samples.filter((sample) => sample.sampleId !== 'sports-av1-26' && sample.sampleId !== 'sports-vp9-22'),
  };

  assert.throws(
    () => buildReferenceContextFromSweep(broken),
    /Incomplete reference frontier for sports-action-960x540-24p; cannot bracket VMAF 90/,
  );
});

test('recomputation is invariant to unrelated rows and preserves environment scope', () => {
  const context = loadReferenceContext(contextFixturePath);
  const envA = buildEvidenceForAllWorkloads(context, 'env-a');
  const sportsRow = envA.find((entry) => entry.workloadId === 'sports-action-960x540-24p');
  assert.ok(sportsRow);
  const envB = [{
    ...sportsRow,
    benchmarkRunId: 'env-b-sports-action',
    environmentId: 'env-b',
    environmentFingerprint: 'env-b-fingerprint',
  }];
  const unrelated = [{
    ...envA[1],
    benchmarkRunId: 'ignored-protocol',
    benchmarkProtocolVersion: 'EDB-2025.9',
  }, {
    ...envA[2],
    benchmarkRunId: 'ignored-status',
    benchmarkRunStatus: 'INVALID',
  }];

  const forward = recomputeReferenceScores([...envA, ...envB, ...unrelated], context);
  const reversed = recomputeReferenceScores([...unrelated, ...envB, ...envA].reverse(), context);

  assert.deepEqual(forward, reversed);
  assert.equal(forward.scoreContexts.length, 7);

  const sportsResults = forward.derivedResults.filter((result) => result.kind === 'WORKLOAD' && result.workloadId === 'sports-action-960x540-24p');
  assert.equal(sportsResults.length, 2);
  assert.deepEqual(sportsResults.map((result) => result.environmentId).sort(), ['env-a', 'env-b']);
});

test('general PL requires full equal-class coverage and stays hardware-scoped', () => {
  const context = loadReferenceContext(contextFixturePath);
  const completeEnv = buildEvidenceForAllWorkloads(context, 'env-complete');
  const partialEnv = buildEvidenceForAllWorkloads(context, 'env-partial').slice(0, 6);

  const result = recomputeReferenceScores([...completeEnv, ...partialEnv], context);
  const generalResults = result.derivedResults.filter((entry) => entry.kind === 'GENERAL');

  assert.equal(generalResults.length, 1);
  assert.equal(generalResults[0].environmentId, 'env-complete');
  assert.equal(generalResults[0].workloadId, buildGeneralScopeWorkloadId(context.sourceSuiteVersion));
  assert.equal(generalResults[0].contributingWorkloadIds.length, context.generalPolicy.requiredContentClasses.length);
});

test('retained authoritative evidence generation is deterministic and retains provenance IDs and hashes', async () => {
  const synthetic = loadReferenceContext(contextFixturePath);
  const evidence = buildRetainedReferenceEvidenceFixture();
  const left = buildReferenceContextFromRetainedEvidence({
    benchmarkProtocolId: 'proto-1',
    benchmarkProtocolVersion: 'EDB-2026.1',
    sourceSuiteVersion: synthetic.sourceSuiteVersion,
    qualityModelId: 'vmaf-v1-sdr-sd',
    contextVersion: 'pl-v7-reference-context-2026b',
    formulaVersion: '7.0',
    targetMetricValue: 90,
    qualityExponent: 2.4,
    speedCurveRate: 1.2,
    speedSaturationRealtime: 4,
    requiredWorkloads: synthetic.workloads.map((workload) => ({ workloadId: workload.workloadId, contentClass: workload.contentClass })),
    requiredContentClasses: synthetic.generalPolicy.requiredContentClasses,
    evidence,
  });
  const right = buildReferenceContextFromRetainedEvidence({
    benchmarkProtocolId: 'proto-1',
    benchmarkProtocolVersion: 'EDB-2026.1',
    sourceSuiteVersion: synthetic.sourceSuiteVersion,
    qualityModelId: 'vmaf-v1-sdr-sd',
    contextVersion: 'pl-v7-reference-context-2026b',
    formulaVersion: '7.0',
    targetMetricValue: 90,
    qualityExponent: 2.4,
    speedCurveRate: 1.2,
    speedSaturationRealtime: 4,
    requiredWorkloads: [...synthetic.workloads].reverse().map((workload) => ({ workloadId: workload.workloadId, contentClass: workload.contentClass })),
    requiredContentClasses: [...synthetic.generalPolicy.requiredContentClasses].reverse(),
    evidence: [...evidence].reverse(),
  });

  assert.deepEqual(left, right);
  assert.equal(left.activation.stage, 'PRODUCTION');
  assert.equal(left.provenance.sourceMode, 'retained-benchmark-evidence');
  assert.equal(left.qualityModelId, 'vmaf-v1-sdr-sd');
  assert.equal(left.workloads[0].referenceFrontier[0].evidence[0].artifactSha256?.length, 64);
  assert.match(left.workloads[0].referenceFrontier[0].evidence[0].qualityAnalysisId, /^analysis-/);
});

test('loadRetainedReferenceEvidence selects retained ENCODED artifacts plus latest authoritative analyses', async () => {
  const rows = await loadRetainedReferenceEvidence({
    benchmarkRun: {
      async findMany() {
        return [{
          id: 'run-1',
          benchmarkProtocolId: 'proto-1',
          workloadId: 'sports-action-960x540-24p',
          testClipId: 'clip-1',
          status: 'ACCEPTED',
          payloadHash: 'a'.repeat(64),
          benchmarkProtocol: {
            protocolVersion: 'EDB-2026.1',
            sourceSuiteVersion: 'encodingdb-test-suite-v1',
          },
          testClip: {
            contentClass: 'high-motion-sports',
            suiteVersion: 'encodingdb-test-suite-v1',
          },
          recipe: { fingerprint: 'recipe-fingerprint' },
          environment: { fingerprint: 'environment-fingerprint' },
          artifacts: [{
            id: 'artifact-1',
            role: 'ENCODED',
            storageState: 'RETAINED',
            sha256: 'b'.repeat(64),
          }],
          qualityAnalyses: [{
            id: 'analysis-2',
            metricModelId: 'vmaf-v1-sdr-sd',
            status: 'COMPLETE',
            analysisWorkerVersion: 'worker-v2',
            videoBitrateBps: 2_700_000,
            vmafMean: 91.2,
          }, {
            id: 'analysis-1',
            metricModelId: 'vmaf-v1-sdr-sd',
            status: 'COMPLETE',
            analysisWorkerVersion: 'worker-v1',
            videoBitrateBps: 2_600_000,
            vmafMean: 90.5,
          }],
        }];
      },
    },
  }, {
    benchmarkProtocolId: 'proto-1',
    qualityModelId: 'vmaf-v1-sdr-sd',
    suiteVersion: 'encodingdb-test-suite-v1',
  });

  assert.equal(rows.length, 1);
  assert.equal(rows[0].qualityAnalysisId, 'analysis-2');
  assert.equal(rows[0].artifactStorageState, 'RETAINED');
});

test('score-context seeds include workload and GENERAL rows and reject provisional activation by default', async () => {
  const synthetic = loadReferenceContext(contextFixturePath);
  const seeds = buildScoreContextSeedRecords(synthetic, 'proto-1');
  assert.equal(seeds.length, 8);
  assert.equal(seeds.filter((seed) => seed.kind === 'GENERAL').length, 1);
  assert.equal(seeds.find((seed) => seed.kind === 'GENERAL')?.workloadId, buildGeneralScopeWorkloadId(synthetic.sourceSuiteVersion));

  await assert.rejects(
    () => persistScoreContextsFromReferenceContext({
      scoreContext: { async upsert() { return { id: 'score-1' }; } },
      async $transaction(fn) { return fn(this); },
    }, synthetic, 'proto-1'),
    /cannot be activated in production persistence/,
  );
});

test('persistGeneralDerivedResultFromWorkloadEvidence persists GENERAL only with complete workload coverage', async () => {
  const calls = [];
  const generalId = await persistGeneralDerivedResultFromWorkloadEvidence({
    scoreContext: {
      async findFirst() {
        return {
          id: 'general-score',
          benchmarkProtocolId: 'proto-1',
          formulaVersion: '7.0',
          contextVersion: 'ctx-v2',
          workloadId: 'general-suite:encodingdb-test-suite-v1',
          qualityModelId: 'vmaf-v1-sdr-sd',
          workloadReferenceBitrateBps: 1_000_000,
          referenceFrontier: {
            generalPolicy: {
              requiredContentClasses: [
                'animation-flat-fields',
                'dark-gradients-shadows',
                'film-grain-noise',
                'fine-natural-detail',
                'high-motion-sports',
                'screen-text',
                'talking-head',
              ],
            },
          },
        };
      },
    },
    derivedResult: {
      async findMany() {
        const synthetic = loadReferenceContext(contextFixturePath);
        return synthetic.workloads.map((workload, index) => ({
          id: `derived-${index + 1}`,
          benchmarkProtocolId: 'proto-1',
          workloadId: workload.workloadId,
          recipeId: 'recipe-1',
          environmentId: 'env-1',
          acceptedRunCount: 1,
          suspectRunCount: 0,
          rejectedRunCount: 0,
          invalidRunCount: 0,
          repetitionCount: 1,
          plTotal: 70 + index,
          confidenceLower: 68 + index,
          confidenceUpper: 72 + index,
          evidenceTier: 'LOW',
          scoreContextId: `score-${index + 1}`,
          testClip: { contentClass: workload.contentClass },
          members: [{
            benchmarkRunId: `run-${index + 1}`,
            qualityAnalysisId: `analysis-${index + 1}`,
          }],
        }));
      },
      async upsert(args) {
        calls.push(['upsert', args]);
        return { id: 'general-derived' };
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
    async $transaction(fn) {
      return fn(this);
    },
  }, {
    benchmarkProtocolId: 'proto-1',
    protocolVersion: 'EDB-2026.1',
    sourceSuiteVersion: 'encodingdb-test-suite-v1',
    contextVersion: 'ctx-v2',
    formulaVersion: '7.0',
    qualityModelId: 'vmaf-v1-sdr-sd',
    recipeId: 'recipe-1',
    recipeFingerprint: 'recipe-fingerprint',
    environmentId: 'env-1',
    environmentFingerprint: 'environment-fingerprint',
  });

  assert.equal(generalId, 'general-derived');
  assert.deepEqual(calls.map(([name]) => name), ['upsert', 'deleteMany', 'createMany']);
  assert.equal(calls[0][1].create.kind, 'GENERAL');
  assert.equal(calls[0][1].create.workloadId, 'general-suite:encodingdb-test-suite-v1');
  assert.equal(calls[2][1].data.length, 7);
});
