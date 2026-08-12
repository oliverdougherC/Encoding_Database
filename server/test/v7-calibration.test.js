import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  CALIBRATION_EVIDENCE_SCHEMA_VERSION,
  assertCalibrationReadyForFreeze,
  assessCalibrationEvidence,
  buildCalibrationEvidenceHash,
  buildCalibrationReviewHash,
  parseCalibrationEvidence,
} from '../dist/v7/calibration.js';

const reviewer = {
  reviewerId: 'reviewer-encoding-expert-1',
  expertise: 'Production video encoding and codec evaluation',
  reviewedAt: '2026-08-12T10:00:00.000Z',
};

function evidence(index, overrides = {}) {
  const implementation = index < 5 ? 'libx264' : 'videotoolbox';
  const hardware = implementation === 'videotoolbox' ? 'videotoolbox' : 'software';
  return {
    evidenceId: `evidence-${index}`,
    partition: index % 2 === 0 ? 'HOLDOUT' : 'CALIBRATION',
    benchmarkRunId: `run-${index}`,
    artifactId: `artifact-${index}`,
    artifactSha256: index.toString(16).padStart(64, '0'),
    artifactStorageState: 'RETAINED',
    qualityAnalysisId: `analysis-${index}`,
    analysisWorkerVersion: 'authoritative-analysis/v1',
    recipeFingerprint: `recipe-${implementation}-${index % 4 < 2 ? 'low' : 'high'}`,
    environmentFingerprint: `environment-${hardware}-${index % 2}`,
    machineSourceId: index % 2 === 0 ? 'machine-b' : 'machine-a',
    workloadId: 'sports-action-960x540-24p',
    contentClass: 'high-motion-sports',
    encoderFamily: implementation === 'libx264' ? 'h264' : 'h264-hardware',
    encoderImplementation: implementation,
    hardwareFamily: hardware,
    nativeRateControl: implementation === 'libx264'
      ? { mode: 'crf', qualityValue: index % 4 < 2 ? 30 : 18 }
      : { mode: 'vbr', targetBitrateKbps: index % 4 < 2 ? 1200 : 5000 },
    preset: 'fast',
    runStatus: 'ACCEPTED',
    analysisStatus: 'COMPLETE',
    vmafMean: 90 + index,
    vmafP5: 88 + index,
    xpsnr: 36 + index,
    videoBitrateBps: 1_000_000 + (index * 100_000),
    realTimeRatio: 2 + (index / 10),
    ...overrides,
  };
}

function decision(scenario, index) {
  return {
    comparisonId: `decision-${scenario.toLowerCase()}`,
    scenario,
    candidateEvidenceIds: [`evidence-${index}`, `evidence-${index + 1}`],
    selectedEvidenceId: `evidence-${index + 1}`,
    reviewer,
    rationale: `The selected recipe is the defensible ${scenario.toLowerCase()} choice for this controlled comparison.`,
  };
}

function completeDocument() {
  const corpus = Array.from({ length: 8 }, (_, index) => evidence(index + 1));
  const document = {
    schemaVersion: CALIBRATION_EVIDENCE_SCHEMA_VERSION,
    calibrationVersion: 'test-calibration/v1',
    status: 'COMPLETE',
    benchmarkProtocolVersion: '7.0',
    sourceSuiteVersion: 'encodingdb-test-suite-v1',
    qualityModelId: 'vmaf-v1-sdr-sd',
    scoreFormulaVersion: '7.0',
    generatedAt: '2026-08-12T10:00:00.000Z',
    corpus,
    goldenDecisions: [
      decision('BALANCED', 1),
      decision('QUALITY', 3),
      decision('STORAGE', 5),
      decision('REALTIME', 7),
    ],
    holdoutEvaluations: ['HARDWARE_FAMILY', 'ENCODER_FAMILY', 'CONTENT_CLASS', 'RECIPE_RANGE'].map((dimension, index) => ({
      evaluationId: `holdout-${dimension.toLowerCase()}`,
      dimension,
      evidenceIds: ['evidence-2', 'evidence-4', 'evidence-6', 'evidence-8'],
      scenario: ['BALANCED', 'QUALITY', 'STORAGE', 'REALTIME'][index],
      predictedTopEvidenceId: 'evidence-8',
      recommendationAccepted: true,
      reviewer,
      rationale: `The held-out ${dimension.toLowerCase()} recommendation generalized without a systematic ranking failure.`,
    })),
    topResultReviews: [
      ['encoder:libx264', 'evidence-4'],
      ['encoder:videotoolbox', 'evidence-8'],
      ['hardware:videotoolbox', 'evidence-8'],
    ].map(([familyKey, evidenceId], index) => ({
      reviewId: `top-${index}`,
      familyKey,
      evidenceId,
      wouldChooseFirst: true,
      reviewer,
      rationale: `A knowledgeable encoder user would select this top-ranked ${familyKey} result under the declared scenario.`,
    })),
    metricSanityReviews: ['DISAGREEMENT', 'GRAIN_OR_NOISE', 'DARK_OR_GRADIENT', 'LOCALIZED_TAIL'].map((caseType, index) => ({
      reviewId: `sanity-${caseType.toLowerCase()}`,
      caseType,
      evidenceIds: [`evidence-${index + 1}`],
      disposition: 'EXPECTED',
      reviewer,
      rationale: `The ${caseType.toLowerCase()} diagnostic was inspected and behaves consistently with the retained frame distribution.`,
    })),
    freeze: {
      scoreContextArtifactPath: 'server/config/reference-contexts/production-v7.json',
      scoreContextHash: 'a'.repeat(64),
      evidencePolicyVersion: 'recommendation-evidence/v7-calibrated-v1',
      qualityExponent: 2.4,
      bitrateReferenceVmafAnchor: 90,
      speedCurveRate: 1.2,
      speedSaturationRealtime: 4,
      calibrationRationale: 'The retained calibration decisions, holdouts, and human top-result reviews support these transparent constants.',
      frozenAt: '2026-08-12T11:00:00.000Z',
    },
    reviewHash: '',
    evidenceHash: '',
  };
  document.reviewHash = buildCalibrationReviewHash(document);
  document.evidenceHash = buildCalibrationEvidenceHash(document);
  return document;
}

const requirements = {
  requiredContentClasses: ['high-motion-sports'],
  requiredSoftwareImplementations: ['libx264'],
  minimumHardwareFamilies: 1,
  minimumMachineSources: 2,
  minimumRatePointsPerWorkloadImplementation: 2,
};

test('complete reviewed evidence can pass the explicit production-freeze gate', () => {
  const assessment = assertCalibrationReadyForFreeze(completeDocument(), requirements);
  assert.equal(assessment.readyForProductionFreeze, true);
  assert.equal(assessment.errors.length, 0);
});

test('draft evidence reports missing real hardware, reviewers, holdouts, and freeze instead of self-certifying', () => {
  const document = completeDocument();
  document.status = 'DRAFT';
  document.corpus = document.corpus.slice(0, 1);
  document.goldenDecisions = [];
  document.holdoutEvaluations = [];
  document.topResultReviews = [];
  document.metricSanityReviews = [];
  document.freeze = null;
  document.evidenceHash = buildCalibrationEvidenceHash(document);
  const assessment = assessCalibrationEvidence(document);
  assert.equal(assessment.readyForProductionFreeze, false);
  assert.ok(assessment.errors.some((finding) => finding.code === 'missing_software_implementation'));
  assert.ok(assessment.errors.some((finding) => finding.code === 'hardware_family_coverage'));
  assert.ok(assessment.errors.some((finding) => finding.code === 'missing_golden_scenario'));
  assert.ok(assessment.errors.some((finding) => finding.code === 'missing_holdout_dimension'));
  assert.ok(assessment.errors.some((finding) => finding.code === 'freeze_record'));
  assert.ok(assessment.warnings.some((finding) => finding.code === 'draft_status'));
  assert.throws(() => assertCalibrationReadyForFreeze(document), /not ready for production freeze/);
});

test('the same benchmark run cannot leak between calibration and holdout partitions', () => {
  const document = completeDocument();
  document.corpus[1].benchmarkRunId = document.corpus[0].benchmarkRunId;
  document.evidenceHash = buildCalibrationEvidenceHash(document);
  const assessment = assessCalibrationEvidence(document, requirements);
  assert.ok(assessment.errors.some((finding) => finding.code === 'partition_leakage'));
});

test('canonical evidence hash detects edits after reviewer sign-off', () => {
  const document = completeDocument();
  document.goldenDecisions[0].rationale = 'This was changed after the evidence hash was calculated and reviewer sign-off was recorded.';
  const assessment = assessCalibrationEvidence(document, requirements);
  assert.ok(assessment.errors.some((finding) => finding.code === 'evidence_hash'));
});

test('placeholder decisions and rejected holdouts cannot freeze production policy', () => {
  const document = completeDocument();
  document.goldenDecisions[0].reviewer = null;
  document.holdoutEvaluations[0].recommendationAccepted = false;
  document.evidenceHash = buildCalibrationEvidenceHash(document);
  const assessment = assessCalibrationEvidence(document, requirements);
  assert.ok(assessment.errors.some((finding) => finding.code === 'golden_review'));
  assert.ok(assessment.errors.some((finding) => finding.code === 'holdout_review'));
  assert.equal(assessment.readyForProductionFreeze, false);
});

test('checked-in Apple pilot binds exact retained evidence while remaining impossible to freeze', () => {
  const document = parseCalibrationEvidence(readFileSync(
    new URL('../config/calibration/pla-87-apple-m4-pro-pilot-2026-08-12.draft.json', import.meta.url),
    'utf8',
  ));
  const assessment = assessCalibrationEvidence(document);
  assert.equal(document.status, 'DRAFT');
  assert.equal(document.corpus.length, 96);
  assert.equal(assessment.calculatedEvidenceHash, document.evidenceHash);
  assert.deepEqual(assessment.coverage.contentClasses, [
    'animation-flat-fields',
    'dark-gradients-shadows',
    'film-grain-noise',
    'fine-natural-detail',
    'high-motion-sports',
    'screen-text',
    'talking-head',
  ]);
  assert.deepEqual(assessment.coverage.encoderImplementations, ['libx264', 'libx265', 'videotoolbox']);
  assert.equal(assessment.coverage.machineSources.length, 1);
  assert.equal(assessment.coverage.holdoutEvidenceCount, 0);
  assert.equal(assessment.coverage.suspectEvidenceCount, 18);
  assert.ok(assessment.errors.some((finding) => finding.code === 'missing_software_implementation'));
  assert.ok(assessment.errors.some((finding) => finding.code === 'machine_source_coverage'));
  assert.ok(assessment.errors.some((finding) => finding.code === 'missing_golden_scenario'));
  assert.equal(assessment.readyForProductionFreeze, false);
});
