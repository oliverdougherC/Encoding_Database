import { canonicalJsonString, sha256Hex } from './persistence.js';

export const CALIBRATION_EVIDENCE_SCHEMA_VERSION = 'pl-v7-calibration-evidence/v1' as const;
export const CALIBRATION_SCENARIOS = ['BALANCED', 'QUALITY', 'STORAGE', 'REALTIME'] as const;
export const HOLDOUT_DIMENSIONS = ['HARDWARE_FAMILY', 'ENCODER_FAMILY', 'CONTENT_CLASS', 'RECIPE_RANGE'] as const;
export const METRIC_SANITY_CASES = ['DISAGREEMENT', 'GRAIN_OR_NOISE', 'DARK_OR_GRADIENT', 'LOCALIZED_TAIL'] as const;
export const REQUIRED_V1_CONTENT_CLASSES = [
  'high-motion-sports',
  'fine-natural-detail',
  'film-grain-noise',
  'dark-gradients-shadows',
  'animation-flat-fields',
  'screen-text',
  'talking-head',
] as const;

export type CalibrationStatus = 'DRAFT' | 'COMPLETE';
export type CalibrationPartition = 'CALIBRATION' | 'HOLDOUT';
export type CalibrationScenario = typeof CALIBRATION_SCENARIOS[number];
export type HoldoutDimension = typeof HOLDOUT_DIMENSIONS[number];
export type MetricSanityCase = typeof METRIC_SANITY_CASES[number];

export interface CalibrationEvidenceRecord {
  evidenceId: string;
  partition: CalibrationPartition;
  benchmarkRunId: string;
  artifactId: string;
  artifactSha256: string;
  artifactStorageState: 'RETAINED' | 'VERIFIED';
  qualityAnalysisId: string;
  analysisWorkerVersion: string;
  recipeFingerprint: string;
  environmentFingerprint: string;
  machineSourceId: string;
  workloadId: string;
  contentClass: string;
  encoderFamily: string;
  encoderImplementation: string;
  hardwareFamily: string;
  nativeRateControl: Record<string, unknown>;
  preset: string;
  runStatus: 'ACCEPTED' | 'SUSPECT';
  analysisStatus: 'COMPLETE' | 'SUSPECT';
  vmafMean: number;
  vmafP5: number;
  xpsnr: number;
  videoBitrateBps: number;
  realTimeRatio: number;
}

export interface KnowledgeableReviewer {
  reviewerId: string;
  expertise: string;
  reviewedAt: string;
}

export interface GoldenDecision {
  comparisonId: string;
  scenario: CalibrationScenario;
  candidateEvidenceIds: readonly string[];
  selectedEvidenceId: string | null;
  reviewer: KnowledgeableReviewer | null;
  rationale: string | null;
}

export interface HoldoutEvaluation {
  evaluationId: string;
  dimension: HoldoutDimension;
  evidenceIds: readonly string[];
  scenario: CalibrationScenario;
  predictedTopEvidenceId: string;
  recommendationAccepted: boolean | null;
  reviewer: KnowledgeableReviewer | null;
  rationale: string | null;
}

export interface TopResultReview {
  reviewId: string;
  familyKey: string;
  evidenceId: string;
  wouldChooseFirst: boolean | null;
  reviewer: KnowledgeableReviewer | null;
  rationale: string | null;
}

export interface MetricSanityReview {
  reviewId: string;
  caseType: MetricSanityCase;
  evidenceIds: readonly string[];
  disposition: 'EXPECTED' | 'INVESTIGATE' | 'EXCLUDE' | null;
  reviewer: KnowledgeableReviewer | null;
  rationale: string | null;
}

export interface CalibrationFreezeRecord {
  scoreContextArtifactPath: string;
  scoreContextHash: string;
  evidencePolicyVersion: string;
  qualityExponent: number;
  bitrateReferenceVmafAnchor: number;
  speedCurveRate: number;
  speedSaturationRealtime: number;
  calibrationRationale: string;
  frozenAt: string;
}

export interface CalibrationEvidenceDocument {
  schemaVersion: typeof CALIBRATION_EVIDENCE_SCHEMA_VERSION;
  calibrationVersion: string;
  status: CalibrationStatus;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  qualityModelId: string;
  scoreFormulaVersion: string;
  generatedAt: string;
  corpus: readonly CalibrationEvidenceRecord[];
  goldenDecisions: readonly GoldenDecision[];
  holdoutEvaluations: readonly HoldoutEvaluation[];
  topResultReviews: readonly TopResultReview[];
  metricSanityReviews: readonly MetricSanityReview[];
  freeze: CalibrationFreezeRecord | null;
  reviewHash: string;
  evidenceHash: string;
}

export interface CalibrationRequirements {
  requiredContentClasses: readonly string[];
  requiredSoftwareImplementations: readonly string[];
  minimumHardwareFamilies: number;
  minimumMachineSources: number;
  minimumRatePointsPerWorkloadImplementation: number;
}

export interface CalibrationFinding {
  code: string;
  message: string;
}

export interface CalibrationAssessment {
  readyForProductionFreeze: boolean;
  calculatedEvidenceHash: string;
  errors: readonly CalibrationFinding[];
  warnings: readonly CalibrationFinding[];
  coverage: {
    contentClasses: readonly string[];
    encoderImplementations: readonly string[];
    hardwareFamilies: readonly string[];
    machineSources: readonly string[];
    calibrationEvidenceCount: number;
    holdoutEvidenceCount: number;
    suspectEvidenceCount: number;
  };
}

export const DEFAULT_CALIBRATION_REQUIREMENTS: CalibrationRequirements = {
  requiredContentClasses: REQUIRED_V1_CONTENT_CLASSES,
  requiredSoftwareImplementations: ['libx264', 'libx265', 'libsvtav1'],
  minimumHardwareFamilies: 2,
  minimumMachineSources: 2,
  minimumRatePointsPerWorkloadImplementation: 2,
};

function normalizedUnique(values: readonly string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].sort();
}

function validSha256(value: string): boolean {
  return /^[0-9a-f]{64}$/.test(value);
}

function validReviewer(reviewer: KnowledgeableReviewer | null): boolean {
  if (!reviewer) return false;
  return reviewer.reviewerId.trim().length > 0
    && reviewer.expertise.trim().length >= 12
    && !Number.isNaN(new Date(reviewer.reviewedAt).getTime());
}

function validRationale(value: string | null): boolean {
  return typeof value === 'string' && value.trim().length >= 20;
}

function evidenceHashPayload(document: CalibrationEvidenceDocument): Omit<CalibrationEvidenceDocument, 'evidenceHash'> {
  const { evidenceHash: _ignored, ...payload } = document;
  return payload;
}

export function buildCalibrationReviewHash(document: CalibrationEvidenceDocument): string {
  const { freeze: _freeze, reviewHash: _reviewHash, evidenceHash: _evidenceHash, ...reviewPayload } = document;
  return sha256Hex(canonicalJsonString(reviewPayload as never));
}

export function buildCalibrationEvidenceHash(document: CalibrationEvidenceDocument): string {
  return sha256Hex(canonicalJsonString(evidenceHashPayload(document) as never));
}

function addFinding(target: CalibrationFinding[], code: string, message: string): void {
  if (!target.some((finding) => finding.code === code && finding.message === message)) {
    target.push({ code, message });
  }
}

export function assessCalibrationEvidence(
  document: CalibrationEvidenceDocument,
  requirements: CalibrationRequirements = DEFAULT_CALIBRATION_REQUIREMENTS,
): CalibrationAssessment {
  const errors: CalibrationFinding[] = [];
  const warnings: CalibrationFinding[] = [];
  const corpus = Array.isArray(document.corpus) ? document.corpus : [];
  const evidenceById = new Map<string, CalibrationEvidenceRecord>();
  const runPartitions = new Map<string, Set<CalibrationPartition>>();

  if (document.schemaVersion !== CALIBRATION_EVIDENCE_SCHEMA_VERSION) {
    addFinding(errors, 'schema_version', `Expected ${CALIBRATION_EVIDENCE_SCHEMA_VERSION}`);
  }
  for (const field of ['calibrationVersion', 'benchmarkProtocolVersion', 'sourceSuiteVersion', 'qualityModelId', 'scoreFormulaVersion'] as const) {
    if (!String(document[field] ?? '').trim()) addFinding(errors, `missing_${field}`, `${field} is required`);
  }
  if (Number.isNaN(new Date(document.generatedAt).getTime())) {
    addFinding(errors, 'generated_at', 'generatedAt must be an ISO-8601 timestamp');
  }

  for (const evidence of corpus) {
    if (!evidence.evidenceId?.trim()) {
      addFinding(errors, 'evidence_id', 'Every corpus record requires evidenceId');
      continue;
    }
    if (evidenceById.has(evidence.evidenceId)) {
      addFinding(errors, 'duplicate_evidence_id', `Duplicate evidenceId ${evidence.evidenceId}`);
    }
    evidenceById.set(evidence.evidenceId, evidence);
    const partitions = runPartitions.get(evidence.benchmarkRunId) ?? new Set<CalibrationPartition>();
    partitions.add(evidence.partition);
    runPartitions.set(evidence.benchmarkRunId, partitions);
    if (!validSha256(evidence.artifactSha256)) {
      addFinding(errors, 'artifact_hash', `Evidence ${evidence.evidenceId} has an invalid artifact SHA-256`);
    }
    if (evidence.runStatus === 'ACCEPTED' && evidence.artifactStorageState !== 'RETAINED') {
      addFinding(errors, 'artifact_retention', `Accepted evidence ${evidence.evidenceId} does not reference a RETAINED artifact`);
    }
    for (const field of ['benchmarkRunId', 'artifactId', 'qualityAnalysisId', 'analysisWorkerVersion', 'recipeFingerprint', 'environmentFingerprint', 'machineSourceId', 'workloadId', 'contentClass', 'encoderFamily', 'encoderImplementation', 'hardwareFamily', 'preset'] as const) {
      if (!String(evidence[field] ?? '').trim()) {
        addFinding(errors, 'incomplete_evidence_identity', `Evidence ${evidence.evidenceId} is missing ${field}`);
      }
    }
    for (const [field, value] of Object.entries({
      vmafMean: evidence.vmafMean,
      vmafP5: evidence.vmafP5,
      xpsnr: evidence.xpsnr,
      videoBitrateBps: evidence.videoBitrateBps,
      realTimeRatio: evidence.realTimeRatio,
    })) {
      if (!Number.isFinite(value) || value <= 0) {
        addFinding(errors, 'invalid_metric', `Evidence ${evidence.evidenceId} has invalid ${field}`);
      }
    }
    if ((evidence.runStatus === 'SUSPECT') !== (evidence.analysisStatus === 'SUSPECT')) {
      addFinding(errors, 'status_mismatch', `Evidence ${evidence.evidenceId} run/analysis status disagree`);
    }
  }
  for (const [runId, partitions] of runPartitions) {
    if (partitions.size > 1) {
      addFinding(errors, 'partition_leakage', `Benchmark run ${runId} appears in calibration and holdout partitions`);
    }
  }

  const classes = normalizedUnique(corpus.map((entry) => entry.contentClass));
  const implementations = normalizedUnique(corpus.map((entry) => entry.encoderImplementation));
  const hardwareFamilies = normalizedUnique(corpus.map((entry) => entry.hardwareFamily).filter((value) => value !== 'software'));
  const machineSources = normalizedUnique(corpus.map((entry) => entry.machineSourceId));
  for (const contentClass of requirements.requiredContentClasses) {
    if (!classes.includes(contentClass)) addFinding(errors, 'missing_content_class', `Missing canonical content class ${contentClass}`);
  }
  for (const implementation of requirements.requiredSoftwareImplementations) {
    if (!implementations.includes(implementation)) addFinding(errors, 'missing_software_implementation', `Missing required software implementation ${implementation}`);
  }
  if (hardwareFamilies.length < requirements.minimumHardwareFamilies) {
    addFinding(errors, 'hardware_family_coverage', `Need at least ${requirements.minimumHardwareFamilies} real hardware families; found ${hardwareFamilies.length}`);
  }
  if (machineSources.length < requirements.minimumMachineSources) {
    addFinding(errors, 'machine_source_coverage', `Need at least ${requirements.minimumMachineSources} independent machine sources; found ${machineSources.length}`);
  }

  const rateGroups = new Map<string, Set<string>>();
  for (const evidence of corpus.filter((entry) => entry.runStatus === 'ACCEPTED')) {
    const key = `${evidence.workloadId}\u241f${evidence.encoderImplementation}`;
    const fingerprints = rateGroups.get(key) ?? new Set<string>();
    fingerprints.add(evidence.recipeFingerprint);
    rateGroups.set(key, fingerprints);
  }
  const hardwareImplementations = normalizedUnique(corpus
    .filter((entry) => entry.hardwareFamily !== 'software')
    .map((entry) => entry.encoderImplementation));
  const implementationsRequiringCurves = normalizedUnique([
    ...requirements.requiredSoftwareImplementations,
    ...hardwareImplementations,
  ]);
  const workloadByClass = new Map<string, string>();
  for (const evidence of corpus) workloadByClass.set(evidence.contentClass, evidence.workloadId);
  for (const implementation of implementationsRequiringCurves) {
    for (const contentClass of requirements.requiredContentClasses) {
      const workloadId = workloadByClass.get(contentClass);
      if (!workloadId) continue;
      const key = `${workloadId}\u241f${implementation}`;
      const fingerprints = rateGroups.get(key) ?? new Set<string>();
      if (fingerprints.size < requirements.minimumRatePointsPerWorkloadImplementation) {
        addFinding(errors, 'rate_quality_coverage', `${key} has ${fingerprints.size} accepted recipe point(s); need ${requirements.minimumRatePointsPerWorkloadImplementation}`);
      }
    }
  }
  for (const [key, fingerprints] of rateGroups) {
    if (implementationsRequiringCurves.some((implementation) => key.endsWith(`\u241f${implementation}`))) continue;
    if (fingerprints.size < requirements.minimumRatePointsPerWorkloadImplementation) {
      addFinding(errors, 'rate_quality_coverage', `${key} has ${fingerprints.size} accepted recipe point(s); need ${requirements.minimumRatePointsPerWorkloadImplementation}`);
    }
  }

  const decisions: readonly GoldenDecision[] = Array.isArray(document.goldenDecisions) ? document.goldenDecisions : [];
  for (const scenario of CALIBRATION_SCENARIOS) {
    if (!decisions.some((decision) => decision.scenario === scenario)) {
      addFinding(errors, 'missing_golden_scenario', `Missing golden decision for ${scenario}`);
    }
  }
  for (const decision of decisions) {
    const candidates = normalizedUnique(decision.candidateEvidenceIds);
    if (candidates.length < 2 || candidates.length > 3) {
      addFinding(errors, 'golden_candidate_count', `${decision.comparisonId} must compare two or three distinct candidates`);
    }
    if (candidates.some((id) => !evidenceById.has(id))) {
      addFinding(errors, 'golden_unknown_evidence', `${decision.comparisonId} references unknown evidence`);
    }
    if (!decision.selectedEvidenceId || !candidates.includes(decision.selectedEvidenceId)) {
      addFinding(errors, 'golden_selection', `${decision.comparisonId} lacks a selected candidate from its comparison set`);
    }
    if (!validReviewer(decision.reviewer) || !validRationale(decision.rationale)) {
      addFinding(errors, 'golden_review', `${decision.comparisonId} lacks knowledgeable reviewer identity/expertise/rationale`);
    }
  }

  const holdouts: readonly HoldoutEvaluation[] = Array.isArray(document.holdoutEvaluations) ? document.holdoutEvaluations : [];
  for (const dimension of HOLDOUT_DIMENSIONS) {
    if (!holdouts.some((evaluation) => evaluation.dimension === dimension)) {
      addFinding(errors, 'missing_holdout_dimension', `Missing holdout evaluation for ${dimension}`);
    }
  }
  for (const evaluation of holdouts) {
    const referenced = evaluation.evidenceIds.map((id) => evidenceById.get(id));
    if (!referenced.length || referenced.some((entry) => !entry || entry.partition !== 'HOLDOUT')) {
      addFinding(errors, 'holdout_partition', `${evaluation.evaluationId} must reference only known HOLDOUT evidence`);
    }
    if (!evaluation.evidenceIds.includes(evaluation.predictedTopEvidenceId)) {
      addFinding(errors, 'holdout_prediction', `${evaluation.evaluationId} top prediction is outside its evidence set`);
    }
    if (evaluation.recommendationAccepted !== true || !validReviewer(evaluation.reviewer) || !validRationale(evaluation.rationale)) {
      addFinding(errors, 'holdout_review', `${evaluation.evaluationId} is not an accepted knowledgeable-reviewer holdout result`);
    }
  }

  const topReviews: readonly TopResultReview[] = Array.isArray(document.topResultReviews) ? document.topResultReviews : [];
  const requiredFamilyKeys = normalizedUnique(corpus.flatMap((entry) => [
    `encoder:${entry.encoderImplementation}`,
    ...(entry.hardwareFamily === 'software' ? [] : [`hardware:${entry.hardwareFamily}`]),
  ]));
  for (const familyKey of requiredFamilyKeys) {
    const review = topReviews.find((entry) => entry.familyKey === familyKey);
    if (!review || review.wouldChooseFirst !== true || !evidenceById.has(review.evidenceId)
      || !validReviewer(review.reviewer) || !validRationale(review.rationale)) {
      addFinding(errors, 'top_result_review', `Missing affirmative knowledgeable top-result review for ${familyKey}`);
    }
  }

  const sanityReviews: readonly MetricSanityReview[] = Array.isArray(document.metricSanityReviews) ? document.metricSanityReviews : [];
  for (const caseType of METRIC_SANITY_CASES) {
    if (!sanityReviews.some((review) => review.caseType === caseType)) {
      addFinding(errors, 'missing_metric_sanity_case', `Missing metric sanity review for ${caseType}`);
    }
  }
  const reviewedSanityEvidence = new Set(sanityReviews.flatMap((review) => review.evidenceIds));
  for (const evidence of corpus.filter((entry) => entry.runStatus === 'SUSPECT')) {
    if (!reviewedSanityEvidence.has(evidence.evidenceId)) {
      addFinding(errors, 'unreviewed_suspect', `Suspect evidence ${evidence.evidenceId} lacks metric-sanity adjudication`);
    }
  }
  for (const review of sanityReviews) {
    if (review.evidenceIds.some((id) => !evidenceById.has(id)) || review.disposition == null
      || !validReviewer(review.reviewer) || !validRationale(review.rationale)) {
      addFinding(errors, 'metric_sanity_review', `${review.reviewId} is incomplete or references unknown evidence`);
    }
  }

  if (!document.freeze) {
    addFinding(errors, 'freeze_record', 'Production score-context and evidence-policy freeze record is missing');
  } else {
    const freeze = document.freeze;
    if (!freeze.scoreContextArtifactPath.endsWith('.json') || !validSha256(freeze.scoreContextHash)
      || !freeze.evidencePolicyVersion.trim() || !validRationale(freeze.calibrationRationale)
      || Number.isNaN(new Date(freeze.frozenAt).getTime())) {
      addFinding(errors, 'freeze_record', 'Production freeze record is incomplete or invalid');
    }
    for (const [field, value] of Object.entries({
      qualityExponent: freeze.qualityExponent,
      bitrateReferenceVmafAnchor: freeze.bitrateReferenceVmafAnchor,
      speedCurveRate: freeze.speedCurveRate,
      speedSaturationRealtime: freeze.speedSaturationRealtime,
    })) {
      if (!Number.isFinite(value) || value <= 0) addFinding(errors, 'freeze_parameter', `Invalid frozen ${field}`);
    }
  }

  const calculatedEvidenceHash = buildCalibrationEvidenceHash(document);
  const calculatedReviewHash = buildCalibrationReviewHash(document);
  if (!validSha256(document.reviewHash) || document.reviewHash !== calculatedReviewHash) {
    addFinding(errors, 'review_hash', 'Calibration review hash is missing or does not match the reviewed corpus/decisions payload');
  }
  if (!validSha256(document.evidenceHash) || document.evidenceHash !== calculatedEvidenceHash) {
    addFinding(errors, 'evidence_hash', 'Calibration evidence hash is missing or does not match the canonical document payload');
  }
  if (document.status !== 'COMPLETE') {
    addFinding(warnings, 'draft_status', 'Calibration evidence is explicitly DRAFT; production freeze is forbidden');
  }

  return {
    readyForProductionFreeze: document.status === 'COMPLETE' && errors.length === 0,
    calculatedEvidenceHash,
    errors,
    warnings,
    coverage: {
      contentClasses: classes,
      encoderImplementations: implementations,
      hardwareFamilies,
      machineSources,
      calibrationEvidenceCount: corpus.filter((entry) => entry.partition === 'CALIBRATION').length,
      holdoutEvidenceCount: corpus.filter((entry) => entry.partition === 'HOLDOUT').length,
      suspectEvidenceCount: corpus.filter((entry) => entry.runStatus === 'SUSPECT').length,
    },
  };
}

export function assertCalibrationReadyForFreeze(
  document: CalibrationEvidenceDocument,
  requirements: CalibrationRequirements = DEFAULT_CALIBRATION_REQUIREMENTS,
): CalibrationAssessment {
  const assessment = assessCalibrationEvidence(document, requirements);
  if (!assessment.readyForProductionFreeze) {
    const findings = [...assessment.errors, ...assessment.warnings].map((finding) => `${finding.code}: ${finding.message}`);
    throw new Error(`PL v7 calibration is not ready for production freeze:\n${findings.join('\n')}`);
  }
  return assessment;
}

export function parseCalibrationEvidence(raw: string): CalibrationEvidenceDocument {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    throw new Error(`Calibration evidence is not valid JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Calibration evidence must be a JSON object');
  }
  return parsed as CalibrationEvidenceDocument;
}
