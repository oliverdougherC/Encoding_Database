import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CANONICAL_DISTORTED_INPUT_INDEX,
  CANONICAL_REFERENCE_INPUT_INDEX,
  buildAuthoritativeQualityAnalysisRecord,
  parsePsnrReport,
  parseSsimReport,
  parseXpsnrReport,
  resolveQualityAnalysisExecutionPlan,
} from '../dist/qualityAnalysis.js';

function buildVmafReport(scores, { aggregateMeanOffset = 0 } = {}) {
  const mean = scores.reduce((sum, score) => sum + score, 0) / scores.length;
  return JSON.stringify({
    version: '2.3.1',
    pooled_metrics: {
      vmaf: {
        mean: mean + aggregateMeanOffset,
      },
    },
    frames: scores.map((score, frameNum) => ({
      frameNum,
      metrics: {
        VMAF_score: score,
      },
    })),
  });
}

test('execution plan pins VMAF v1 analysis context and canonical input order', () => {
  const plan = resolveQualityAnalysisExecutionPlan(
    { width: 1920, height: 1080, frameRate: 60, dynamicRange: 'sdr' },
    '/tmp/vmaf_v1.0.16_3d0h.json',
  );

  assert.equal(plan.metricModelId, 'vmaf-v1-sdr-1080p-hfr');
  assert.equal(plan.qualityContextId, 'vmaf-v1-sdr-1080p-hfr-yuv420p10le');
  assert.equal(plan.distortedInputIndex, CANONICAL_DISTORTED_INPUT_INDEX);
  assert.equal(plan.referenceInputIndex, CANONICAL_REFERENCE_INPUT_INDEX);
  assert.match(plan.filterGraph, /\[0:v\].*format=pix_fmts=yuv420p10le\[distorted\]/);
  assert.match(plan.filterGraph, /\[1:v\].*format=pix_fmts=yuv420p10le\[reference\]/);
  assert.match(plan.filterGraph, /libvmaf=model='path=\/tmp\/vmaf_v1\.0\.16_3d0h\.json'/);
  assert.doesNotMatch(plan.filterGraph, /v0\.6\.1/);
});

test('pristine fixture yields high mean, high P5, and deterministic diagnostics provenance', () => {
  const scores = Array.from({ length: 20 }, (_, index) => 99 - ((index % 3) * 0.1));
  const result = buildAuthoritativeQualityAnalysisRecord({
    analysisWorkerVersion: 'test-worker/1.0.0',
    source: { width: 1920, height: 1080, frameRate: 24, dynamicRange: 'sdr' },
    metricModelPath: '/models/vmaf_v1.0.16_3d0h.json',
    vmafReport: buildVmafReport(scores, { aggregateMeanOffset: 1.25 }),
    xpsnrReport: '[Parsed_xpsnr_0] XPSNR average: 48.125 min: 41.2',
    ssimReport: '[Parsed_ssim_0] SSIM Y:0.998 U:0.999 V:0.999 All:0.9985 (28.0021)',
    psnrReport: '[Parsed_psnr_0] PSNR y:51.9 u:52.1 v:52.2 average:52.012 min:48.8 max:inf',
    ffmpegVersion: 'ffmpeg-n6.1',
  });

  assert.equal(result.metricModelId, 'vmaf-v1-sdr-1080p');
  assert.equal(result.analysisProvenance.frameRateClass, 'standard');
  assert.equal(result.vmafDistribution.frameCount, 20);
  assert.equal(result.worstFrameIndex, 2);
  assert.equal(result.worstFrameTimestampMs, 83);
  assert.ok(result.vmafMean > 98.8);
  assert.ok(result.vmafP5 >= 98.8);
  assert.ok(result.vpl > 98.8);
  assert.equal(result.metricDisagreement.flagged, false);
  assert.equal(result.xpsnr, 48.125);
  assert.equal(result.ssim, 0.9985);
  assert.equal(result.psnr, 52.012);
  assert.equal(result.analysisProvenance.diagnosticParsers.xpsnr, 'ffmpeg-xpsnr-average-v1');
  assert.equal(result.analysisProvenance.ffmpegVersion, 'ffmpeg-n6.1');
  assert.equal(result.belowThresholdFractions['95.000000'].count, 0);
  assert.equal(result.analysisProvenance.numericPolicy.percentileMethod, 'nearest-rank-lower-tail');
});

test('intentionally degraded fixture remains internally consistent and lowers canonical quality', () => {
  const degraded = Array.from({ length: 24 }, (_, index) => 75 - ((index % 5) * 1.5));
  const result = buildAuthoritativeQualityAnalysisRecord({
    analysisWorkerVersion: 'test-worker/1.0.0',
    source: { width: 1280, height: 720, frameRate: 30, dynamicRange: 'sdr' },
    metricModelPath: '/models/vmaf_v1.0.16_3d0h.json',
    vmafReport: buildVmafReport(degraded),
    xpsnrReport: '[Parsed_xpsnr_0] XPSNR average: 29.8 min: 22.1',
    ssimReport: '[Parsed_ssim_0] SSIM Y:0.934 U:0.940 V:0.942 All:0.9360 (11.9)',
    psnrReport: '[Parsed_psnr_0] PSNR y:31.9 u:32.1 v:31.8 average:31.97 min:24.2 max:38.0',
  });

  assert.equal(result.metricModelId, 'vmaf-v1-sdr-720p');
  assert.ok(result.vmafMean < 73.5);
  assert.ok(result.vmafP5 <= result.vmafMean);
  assert.ok(result.vpl < result.vmafMean);
  assert.equal(result.belowThresholdFractions['80.000000'].count, degraded.length);
  assert.equal(result.metricDisagreement.flagged, false);
});

test('localized bad segment drops P5 and V_PL much harder than the mean', () => {
  const mostlyStrong = Array.from({ length: 38 }, (_, index) => 95.4 - ((index % 4) * 0.15));
  const localizedBad = [...mostlyStrong, 45, 40];
  const result = buildAuthoritativeQualityAnalysisRecord({
    analysisWorkerVersion: 'test-worker/1.0.0',
    source: { width: 1920, height: 1080, frameRate: 60, dynamicRange: 'sdr' },
    metricModelPath: '/models/vmaf_v1.0.16_3d0h.json',
    vmafReport: buildVmafReport(localizedBad),
    xpsnrReport: '[Parsed_xpsnr_0] XPSNR average: 30.0 min: 18.2',
    ssimReport: '[Parsed_ssim_0] SSIM Y:0.985 U:0.986 V:0.987 All:0.9854 (18.4)',
    psnrReport: '[Parsed_psnr_0] PSNR y:34.1 u:34.3 v:34.2 average:34.22 min:21.0 max:44.0',
  });

  assert.ok(result.vmafMean > 92);
  assert.equal(result.vmafP5, 45);
  assert.ok(result.vpl < result.vmafMean - 6);
  assert.equal(result.worstFrameIndex, 39);
  assert.equal(result.worstFrameTimestampMs, 650);
  assert.equal(result.belowThresholdFractions['80.000000'].count, 2);
  assert.equal(result.metricDisagreement.flagged, true);
});

test('reversed-reference fixture is rejected before canonical analysis parsing', () => {
  assert.throws(() => buildAuthoritativeQualityAnalysisRecord({
    analysisWorkerVersion: 'test-worker/1.0.0',
    source: { width: 1920, height: 1080, frameRate: 24, dynamicRange: 'sdr' },
    metricModelPath: '/models/vmaf_v1.0.16_3d0h.json',
    observedInputOrder: { distortedInputIndex: 1, referenceInputIndex: 0 },
    vmafReport: buildVmafReport([98, 98, 98, 98]),
  }), /Canonical VMAF input order requires distorted=0 and reference=1/);
});

test('diagnostic parsers stay deterministic for finite and inf-style outputs', () => {
  assert.deepEqual(parseXpsnrReport('[Parsed_xpsnr_0] XPSNR average: 41.125').value, 41.125);
  assert.deepEqual(parseSsimReport('[Parsed_ssim_0] SSIM Y:0.98 U:0.99 V:0.99 All:0.9812').value, 0.9812);
  assert.deepEqual(parsePsnrReport('[Parsed_psnr_0] PSNR y:51 u:51 v:51 average:inf').value, 100);
});
