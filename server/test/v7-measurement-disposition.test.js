import test from 'node:test';
import assert from 'node:assert/strict';
import { ArtifactPipelineService, applyReportedMeasurementValidity, mergeArtifactPipelineConfig } from '../dist/v7/artifacts.js';
import { applyEffectiveReview } from '../dist/v7/reviews.js';

const valid = () => Object.fromEntries(['overallValidity', 'environmentValidity', 'structuralValidity'].map(key => [key, { state: 'valid', reasons: [] }]));
const goodMetrics = { metricModelId: 'installed-model', analysisWorkerVersion: 'installed-worker', analysisStatus: 'COMPLETE', analysisProvenance: { automatedMetricFlag: false }, runStatus: 'ACCEPTED', runStatusReason: null, artifactState: 'RETAINED', artifactStateReason: null };

test('good pixels cannot erase suspect, invalid or missing client measurement evidence', async () => {
  for (const [name, precheck, expected] of [
    ['valid', valid(), 'ACCEPTED'],
    ['environment suspect', { ...valid(), environmentValidity: { state: 'suspect', reasons: [{ severity: 'suspect', message: 'Background CPU activity' }] } }, 'SUSPECT'],
    ['overall invalid', { ...valid(), overallValidity: { state: 'invalid' } }, 'INVALID'],
    ['structural invalid', { ...valid(), structuralValidity: { state: 'invalid' } }, 'INVALID'],
    ['unknown', { ...valid(), structuralValidity: { state: 'unknown' } }, 'SUSPECT'],
    ['missing', null, 'SUSPECT'],
    ['contradictory reason', { ...valid(), environmentValidity: { state: 'valid', reasons: [{ severity: 'invalid' }] } }, 'INVALID'],
  ]) {
    let stored;
    const service = new ArtifactPipelineService({ saveAuthoritativeAnalysis: async input => { stored = input.result; return { qualityAnalyses: [] }; } }, { analyze: async () => ({ ...goodMetrics }) }, mergeArtifactPipelineConfig(), {}, undefined);
    await service.processQueuedAnalysis({ run: { id: 'run', preRunEnvironmentCheck: precheck }, artifact: { id: 'artifact', storageUrl: '/owned/file' } }, { id: 'analysis', leaseToken: 'owned', metricModelId: 'installed-model', analysisWorkerVersion: 'installed-worker' });
    assert.equal(stored.runStatus, expected, name);
    assert.equal(stored.analysisStatus, 'COMPLETE', 'automated pixel metrics remain complete');
    assert.equal(stored.analysisProvenance.automatedMetricFlag, false);
    assert.deepEqual(stored.analysisProvenance.reportedMeasurementValidity.reported, precheck);
    assert.equal(stored.artifactState, expected === 'ACCEPTED' ? 'RETAINED' : 'VERIFIED');
    if (expected === 'INVALID') assert.equal(applyEffectiveReview({ runStatus: stored.runStatus, analysisStatus: stored.analysisStatus, artifactState: stored.artifactState, analysisId: 'analysis', reviews: [{ id: 'review', analysisId: 'analysis', decision: 'EXPECTED', createdAt: new Date() }] }).eligible, false);
  }
  const metricSuspect = { ...goodMetrics, runStatus: 'SUSPECT', analysisStatus: 'SUSPECT', runStatusReason: 'Metric disagreement', artifactState: 'VERIFIED' };
  assert.equal(applyReportedMeasurementValidity(metricSuspect, valid()).runStatus, 'SUSPECT');
});
