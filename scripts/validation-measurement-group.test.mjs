import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validationMeasurementGroup } from './validation-measurement-group.mjs';
const root=new URL('../docs/collection-readiness/holdouts/timing-phase1/',import.meta.url);
const result=crf=>JSON.parse(readFileSync(new URL(`screen-x264-crf${crf}-campaign.json`,root))).campaign.recipeResults[0];
test('real stable group preserves exact measured milliseconds and excludes warmup',()=>{const r=result(28),g=validationMeasurementGroup(r);assert.equal(g.countedAttempts.length,2);assert.equal(g.countedAttempts[0].encodeWallTimeMs,r.runs[1].timing.elapsed_s * 1000);assert.equal(g.countedAttempts[1].encodeWallTimeMs,r.runs[2].timing.elapsed_s * 1000);assert.equal(g.completed,true);assert.equal('stable' in g,false);});
test('real unstable group retains all four measured attempts without a claimed pass',()=>{const r=result(18),g=validationMeasurementGroup(r);assert.equal(r.stability.stable,false);assert.equal(g.countedAttempts.length,4);assert.equal('stable' in g,false);});
test('rejects truncated, duplicate, invalid and cross-group counted attempts',()=>{for(const mutate of [r=>r.runs.splice(2),r=>r.runs[2].schedule.repetition_index=r.runs[1].schedule.repetition_index,r=>r.runs[1].overallValidity.state='invalid',r=>r.runs[1].schedule.campaign_id='different',r=>r.measuredRunsCompleted=0,r=>delete r.measuredRunsCompleted,r=>delete r.measuredRunsRequired]){const r=result(28);mutate(r);assert.throws(()=>validationMeasurementGroup(r));}});

test('affected real receipts cannot pass corrected CPU provenance admission', async () => {
  const { assertObservedValidationCpu } = await import('./validation-measurement-group.mjs');
  for (const run of result(28).runs.filter(run => run.countedForStability)) assert.throws(() => assertObservedValidationCpu(run), /fresh CPU sampler provenance/);
});

test('CPU provenance admits observed zero and rejects unavailable or legacy samples (unit fixtures)', async () => {
  const { assertObservedValidationCpu } = await import('./validation-measurement-group.mjs');
  for (const marker of ['cpu_psutil_thread_window_v1', 'cpu_psutil_blocking_window_v1']) {
    assert.doesNotThrow(() => assertObservedValidationCpu({ environmentSnapshot: { telemetry_sources: `host,${marker}`, background_cpu_pct: 0 } }));
  }
  for (const value of [null, undefined, NaN, Infinity, -1, 101]) assert.throws(() => assertObservedValidationCpu({ environmentSnapshot: { telemetry_sources: 'cpu_psutil_thread_window_v1', background_cpu_pct: value } }));
  assert.throws(() => assertObservedValidationCpu({ environmentSnapshot: { telemetry_sources: 'cpu_psutil', background_cpu_pct: 0 } }));
});
