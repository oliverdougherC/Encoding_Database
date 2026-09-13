import test from 'node:test';
import assert from 'node:assert/strict';

import {
  normalizeDecodeBenchmark,
  normalizeEnergyDomains,
} from '../dist/v7/telemetry.js';

test('normalizeEnergyDomains derives per-work energy only for compatible labeled counters', () => {
  const energy = normalizeEnergyDomains({
    measurements: [
      {
        domain: 'gpu-board',
        collector: 'nvml',
        collectorVersion: '12.1',
        source: 'nvml-total-energy',
        counterUnit: 'millijoules',
        counterState: 'valid',
        startCounter: 125_000,
        endCounter: 145_500,
      },
      {
        domain: 'cpu-package',
        domainLabel: 'rapl:package-0',
        collector: 'powercap',
        source: 'intel-rapl',
        counterUnit: 'microjoules',
        counterState: 'unsupported',
        error: 'collector unavailable',
      },
    ],
    sourceFrameCount: 300,
    sourceDurationSeconds: 10,
  });

  assert.equal(energy.length, 2);
  assert.equal(energy[0].domainLabel, 'nvml:gpu-board');
  assert.equal(energy[0].deltaJoules, 20.5);
  assert.equal(energy[0].joulesPerFrame, 0.068333333);
  assert.equal(energy[0].joulesPerSourceSecond, 2.05);
  assert.equal(energy[0].compatibleMeasurement, true);
  assert.equal(energy[1].domainLabel, 'rapl:package-0');
  assert.equal(energy[1].deltaJoules, null);
  assert.equal(energy[1].compatibleMeasurement, false);
});

test('normalizeEnergyDomains handles counter wrap and rejects mislabeled counters', () => {
  const wrapped = normalizeEnergyDomains({
    measurements: [{
      domain: 'system',
      collector: 'platform-energy',
      counterUnit: 'joules',
      counterState: 'wrap',
      startCounter: 990,
      endCounter: 25,
      counterRolloverValue: 1_000,
    }],
  });

  assert.equal(wrapped[0].deltaJoules, 35);

  assert.throws(() => normalizeEnergyDomains({
    measurements: [{
      domain: 'gpu-board',
      collector: 'nvml',
      counterState: 'valid',
      startCounter: 50,
      endCounter: 40,
      counterUnit: 'joules',
    }],
  }), /endCounter must be greater than or equal to startCounter/);
});

test('normalizeDecodeBenchmark distinguishes deterministic complete runs from deferred ones', () => {
  const complete = normalizeDecodeBenchmark({
    status: 'complete',
    decoderImplementation: 'ffmpeg-h264',
    decoderVersion: 'n7.1',
    toolchainFingerprint: 'ffmpeg-n7.1-libdav1d',
    executionMode: 'software',
    cacheDiscipline: 'bounded',
    wallTimeMs: 1_500,
    decodeFps: 120,
    sourceFps: 30,
    cpuTimeMs: 1_200,
    peakRssBytes: 250_000_000,
    notes: 'filesystem cache bounded via warmup discard',
  });

  const deferred = normalizeDecodeBenchmark({
    status: 'deferred',
    deferredReason: 'cross-platform bounded-cache methodology not frozen yet',
  });

  assert.equal(complete.realTimeMultiple, 4);
  assert.equal(complete.cacheDiscipline, 'bounded');
  assert.equal(deferred.status, 'deferred');
  assert.equal(deferred.realTimeMultiple, null);
});

test('normalizeDecodeBenchmark requires rationale for non-complete statuses', () => {
  assert.throws(() => normalizeDecodeBenchmark({
    status: 'unsupported',
  }), /deferredReason is required/);
});
