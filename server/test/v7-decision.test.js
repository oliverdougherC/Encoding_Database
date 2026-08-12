import test from 'node:test';
import assert from 'node:assert/strict';
import { buildDecisionPayload } from '../dist/v7/decision.js';

function candidate(overrides) {
  return {
    rowId: 'row-a',
    encoderName: 'libx265',
    codecFamily: 'hevc',
    preset: 'slow',
    crf: 24,
    contentClass: 'mixed',
    resolution: '1080p',
    passes: 1,
    workloadId: 'mixed-1080p',
    hardwareContext: {
      environmentId: 'env-a',
      environmentFingerprint: 'fp-a',
      cpuModel: 'CPU A',
      gpuModel: '',
      ramGB: 16,
      os: 'Linux 1',
    },
    sampleCount: 6,
    avgFps: 60,
    avgVmaf: 95,
    avgVmafP5: 94,
    avgVideoBitrateBps: 4_000_000,
    avgSourceFps: 30,
    plScore: 80,
    canonical: { quality: 0.8, bitrate: 0.8, speed: 0.8 },
    context: {
      formulaVersion: '7.0',
      benchmarkProtocolVersion: 'benchmark-protocol-v1',
      sourceSuiteVersion: 'encodingdb-test-suite-v1',
      qualityModelId: 'vmaf-v1',
      referenceContextVersion: 'reference-frontier-v1',
      workloadReferenceBitrateBps: 4_000_000,
    },
    confidenceLower: 78,
    confidenceUpper: 82,
    evidenceTier: 'HIGH',
    eligibleForDefaultRecommendation: true,
    ...overrides,
  };
}

test('Balanced Fit uses the stored canonical PL total and preserves canonical ordering', () => {
  const higherCanonical = candidate({
    rowId: 'canonical-high',
    plScore: 88,
    canonical: { quality: 0.7, bitrate: 0.95, speed: 0.8 },
  });
  const lowerCanonical = candidate({
    rowId: 'canonical-low',
    plScore: 81,
    canonical: { quality: 0.95, bitrate: 0.65, speed: 0.7 },
  });
  const payload = buildDecisionPayload([lowerCanonical, higherCanonical], {
    selectedMode: 'balanced',
    selectedEnvironmentId: 'env-a',
  });

  assert.deepEqual(payload.rows.map((row) => row.rowId), ['canonical-high', 'canonical-low']);
  assert.equal(payload.rows[0].fit.modes.balanced.score, 88);
  assert.equal(payload.recommendation.rowId, 'canonical-high');
});

test('environment key is the immutable fingerprint, not a display hardware tuple', () => {
  const first = candidate({ rowId: 'first' });
  const second = candidate({
    rowId: 'second',
    hardwareContext: { ...first.hardwareContext, environmentId: 'env-b', environmentFingerprint: 'fp-b' },
  });
  const payload = buildDecisionPayload([first, second], { selectedMode: 'balanced' });

  assert.notEqual(payload.rows[0].hardwareKey, payload.rows[1].hardwareKey);
  assert.deepEqual(payload.environmentScope.available.map((environment) => environment.environmentFingerprint), ['fp-a', 'fp-b']);
});
