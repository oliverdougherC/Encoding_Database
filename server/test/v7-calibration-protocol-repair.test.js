import test from 'node:test';
import assert from 'node:assert/strict';
import { canonicalJsonString, sha256Hex } from '../dist/v7/persistence.js';
import { evaluateMeasurementGroup } from '../dist/v7/measurementGroup.js';
import { validationMeasurementGroup } from '../../scripts/validation-measurement-group.mjs';
import { repairValidationProtocolSnapshot } from '../../scripts/repair-calibration-protocol-snapshot.mjs';
const hash = value => sha256Hex(canonicalJsonString(value));
function fixture() {
  const source = { workloadId: 'validation-test-only', sourceSha256: 'b'.repeat(64) };
  const recipeJson = { codecFamily: 'h264', rateControlRequested: { mode: 'crf', qualityValue: 23 }, rateControlEffective: { mode: 'crf', qualityValue: 23 } };
  const environmentJson = { hardware: { cpuModel: 'TEST ONLY' }, runtime: {}, execution: {}, osName: 'test', osVersion: 'test' };
  const makeRecord = (phase,index,elapsed) => ({ schedule: { phase, repetition_index: index, campaign_id: 'test-campaign', recipe_id: 'test-recipe' }, countedForStability: phase === 'measured', overallValidity: { state: 'valid' }, environmentSnapshot: { background_cpu_pct: 1, telemetry_sources: 'cpu_psutil_thread_window_v1' }, timing: { start_monotonic_ns: 1e9, end_monotonic_ns: 1e9+elapsed*1e9, elapsed_s: elapsed, source_frame_count: 24, encoded_frame_count: 24, source_fps: 24, encode_fps: 24/elapsed, realtime_multiple: 1/elapsed }, metadata: { info: { artifactSha256: 'a'.repeat(64), encodeTimerBoundary: 'ffmpeg-process-v1', effectiveRecipeJson: JSON.stringify(recipeJson) } } });
  const records = [makeRecord('warmup',0,1),makeRecord('measured',1,1),makeRecord('measured',2,1.01)];
  const group = { runs: records, stability: { stable: true }, measuredRunsCounted: 2, measuredRunsRequired: 2, measuredRunsCompleted: 2 };
  const measurementGroup = validationMeasurementGroup(group);
  const document = { schemaVersion: 'encodingdb-controlled-validation-campaign/v1', validationOnly: true, protocolVersion: '7.1', protocolConfig: { version: '7.1', warmup_runs: 1, minimum_measured_runs: 2, max_adaptive_repeats: 2, stability_threshold_ratio: 0.03 }, source, sourceRegistrationHash: hash(source), physicalSourceId: 'test-physical-machine', ...environmentJson, campaign: { recipeResults: [group] } };
  const protocol = { id: 'test-original-protocol', protocolVersion: '7.1', sourceSuiteVersion: 'encodingdb-validation-holdouts-v1', metricWorkerVersion: 'authoritative-analysis/v2', canonicalRecipeRules: { validationOnly: true, warmupRuns: 1, minimumMeasuredRuns: 2 } };
  const recipe = { id: 'recipe', fingerprint: hash(recipeJson) }, environment = { id: 'environment', fingerprint: hash(environmentJson) };
  const clip = { id: 'clip', suiteVersion: protocol.sourceSuiteVersion, sha256: source.sourceSha256, exactFrameCount: 24, exactDurationSeconds: 1, frameRateNumerator: 24, frameRateDenominator: 1 };
  const runs = records.filter(r=>r.countedForStability).map(record => {
    const immutable = { schedule: record.schedule, timing: record.timing, measurementGroup, recipe: recipe.fingerprint, environment: environment.fingerprint, source: hash(source), physicalSourceId: document.physicalSourceId, artifact: record.metadata.info.artifactSha256 };
    return { id: `validation_${hash(record.schedule)}`, benchmarkProtocolId: protocol.id, testClipId: clip.id, workloadId: source.workloadId, recipeId: recipe.id, environmentId: environment.id, physicalSourceId: document.physicalSourceId, campaignId: record.schedule.campaign_id, repetitionGroupId: measurementGroup.repetitionGroupId, repetitionIndex: record.schedule.repetition_index, status: 'ACCEPTED', inputHash: source.sourceSha256, encodeTimerBoundary: 'ffmpeg-process-v1', encodeWallTimeMs: record.timing.elapsed_s*1000, sourceFrameCount: 24, encodedFrameCount: 24, sourceFps: 24, encodeFps: record.timing.encode_fps, realTimeRatio: record.timing.realtime_multiple, preRunEnvironmentCheck: { snapshot: record.environmentSnapshot, measurementGroup }, payloadHash: hash(immutable), immutablePayloadHash: hash(immutable) };
  });
  const artifacts = runs.map((run,index)=>({ id: `artifact-${index}`, benchmarkRunId: run.id, role: 'ENCODED', sha256: 'a'.repeat(64), byteSize: 1, storageState: 'RETAINED', storageProvider: 'localfs', storageKey: 'objects/a', storageUrl: '/test-only/objects/a' }));
  const analyses = runs.map((run,index)=>({ id: `analysis-${index}`, benchmarkRunId: run.id, artifactId: artifacts[index].id, status: 'COMPLETE', metricModelId: 'test-model', analysisWorkerVersion: 'authoritative-analysis/v2', analysisProvenance: { workerBuildFingerprint: 'f'.repeat(64) }, createdAt: '2026-01-01T00:00:00Z' }));
  const snapshot = { schemaVersion: 'encodingdb-calibration-evidence-snapshot/v1', tables: { protocols: [protocol], clips: [clip], recipes: [recipe], environments: [environment], runs, artifacts, analyses, reviews: [] }, objects: [] };
  snapshot.snapshotHash = hash(snapshot);
  return { snapshot, receipts: [{ document, sha256: hash(document), originalPath: '/test-only/original-receipt.json' }] };
}
function eligibility(snapshot) {
  const members = snapshot.tables.runs.map(run=>({ ...run, benchmarkProtocol: snapshot.tables.protocols.find(p=>p.id===run.benchmarkProtocolId), testClip: snapshot.tables.clips[0], qualityAnalyses: snapshot.tables.analyses.filter(a=>a.benchmarkRunId===run.id).map(a=>({ ...a, artifact: snapshot.tables.artifacts.find(f=>f.id===a.artifactId), evidenceReviews: [] })) }));
  return evaluateMeasurementGroup(members[0],members,{ metricModelId: 'test-model' });
}
function reseal(snapshot) { const { snapshotHash: _old, ...payload }=snapshot; snapshot.snapshotHash=hash(payload); }

test('missing-rule snapshot becomes group-eligible by explicit new protocol alias only', () => {
  const { snapshot, receipts }=fixture(), original=structuredClone(snapshot);
  assert.equal(eligibility(snapshot).reason,'incompatible-protocol');
  const repaired=repairValidationProtocolSnapshot(snapshot,receipts);
  assert.equal(eligibility(repaired).eligible,true);
  assert.deepEqual(snapshot,original); assert.deepEqual(repaired.tables.analyses,original.tables.analyses); assert.deepEqual(repaired.tables.artifacts,original.tables.artifacts);
  repaired.tables.runs.forEach((run,index)=>{const copy={...run,benchmarkProtocolId:original.tables.runs[index].benchmarkProtocolId};assert.deepEqual(copy,original.tables.runs[index]);});
  assert.notEqual(repaired.tables.protocols[0].id,snapshot.tables.protocols[0].id);
  assert.equal(repaired.protocolMetadataRepair.sourceSnapshotHash,snapshot.snapshotHash);
  assert.equal(repairValidationProtocolSnapshot(snapshot,receipts).snapshotHash,repaired.snapshotHash);
});
test('repair retains ineligible metric status rather than rehabilitating a suspect result',()=>{const {snapshot,receipts}=fixture();snapshot.tables.runs[0].status='SUSPECT';snapshot.tables.analyses[0].status='SUSPECT';reseal(snapshot);assert.equal(eligibility(repairValidationProtocolSnapshot(snapshot,receipts)).reason,'ineligible-member');});
test('conflicting original rule cannot be relabeled as a missing-rule repair',()=>{const {snapshot,receipts}=fixture();snapshot.tables.protocols[0].canonicalRecipeRules.stabilityThresholdRatio=0.2;reseal(snapshot);assert.throws(()=>repairValidationProtocolSnapshot(snapshot,receipts),/Conflicting existing rule/);});
test('altered measured payload hash prevents metadata repair',()=>{const {snapshot,receipts}=fixture();snapshot.tables.runs[0].payloadHash='0'.repeat(64);reseal(snapshot);assert.throws(()=>repairValidationProtocolSnapshot(snapshot,receipts),/payload hash/);});
test('snapshot must include every original counted group member',()=>{const {snapshot,receipts}=fixture();snapshot.tables.runs.pop();reseal(snapshot);assert.throws(()=>repairValidationProtocolSnapshot(snapshot,receipts),/omits a counted group member/);});
