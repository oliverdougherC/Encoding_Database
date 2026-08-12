import { readFileSync } from 'node:fs';

import type { Prisma, PrismaClient } from '@prisma/client';

import { computePlScoreV7 } from '../plScore.js';
import {
  persistDerivedResultRecord,
  type DerivedResultPersistenceClient,
  type DerivedResultPersistenceShape,
} from './aggregation.js';
import {
  buildDerivedResultRecomputationSpec,
  buildDerivedResultScopeKey,
  canonicalJsonString,
  sha256Hex,
} from './persistence.js';
import { loadAuthoritativeSuiteManifest, type SuiteV1Manifest } from './suite.js';

export const CONTROLLED_REFERENCE_SWEEP_SCHEMA_VERSION = 'pl-reference-sweep-v1' as const;
export const REFERENCE_CONTEXT_SCHEMA_VERSION = 'pl-reference-context-v1' as const;
export const REFERENCE_CONTEXT_FORMULA_VERSION = '7.0' as const;
export const GENERAL_PL_WEIGHTING = 'equal-class-geometric-mean' as const;
export const GENERAL_SCOPE_WORKLOAD_PREFIX = 'general-suite:' as const;
export const DEFAULT_REFERENCE_CONTEXT_AGGREGATOR_VERSION = 'pl-v7-derived-v1' as const;

export type IncludedDerivedStatus = 'accepted' | 'suspect' | 'rejected';
export type BenchmarkRunDecision = 'ACCEPTED' | 'SUSPECT' | 'REJECTED' | 'INVALID' | 'PENDING';
export type QualityAnalysisDecision = 'COMPLETE' | 'SUSPECT' | 'REJECTED' | 'FAILED' | 'PENDING';
export type EvidenceTier = 'PROVISIONAL' | 'LOW' | 'MEDIUM' | 'HIGH';
export type ReferenceContextSourceMode = 'synthetic-controlled-sweep' | 'retained-benchmark-evidence';
export type ReferenceContextActivationStage = 'TEST_ONLY_PROVISIONAL' | 'PRODUCTION';

export interface ReferenceSweepWorkload {
  workloadId: string;
  contentClass: string;
}

export interface ControlledReferenceSweepSample {
  sampleId: string;
  workloadId: string;
  codecFamily: string;
  encoderImplementation: string;
  videoBitrateBps: number;
  vmafMean: number;
}

export interface ControlledReferenceSweep {
  schemaVersion: typeof CONTROLLED_REFERENCE_SWEEP_SCHEMA_VERSION | string;
  sweepVersion: string;
  contextVersion: string;
  formulaVersion: string;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  qualityModelId: string;
  targetMetric: 'vmafMean' | string;
  targetMetricValue: number;
  bitrateInterpolation: 'log-linear' | string;
  qualityExponent: number;
  speedCurveRate: number;
  speedSaturationRealtime: number;
  requiredWorkloads: readonly ReferenceSweepWorkload[];
  requiredContentClasses: readonly string[];
  samples: readonly ControlledReferenceSweepSample[];
}

export interface RetainedReferenceEvidenceRecord {
  benchmarkRunId: string;
  benchmarkProtocolId: string;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  workloadId: string;
  testClipId: string;
  contentClass: string;
  benchmarkRunStatus: BenchmarkRunDecision;
  payloadHash: string;
  recipeId: string;
  recipeFingerprint: string;
  environmentId: string;
  environmentFingerprint: string;
  artifactId: string;
  artifactRole: 'ENCODED' | string;
  artifactStorageState: 'RETAINED' | string;
  artifactSha256: string;
  qualityAnalysisId: string;
  qualityAnalysisStatus: QualityAnalysisDecision;
  analysisWorkerVersion: string;
  qualityModelId: string;
  videoBitrateBps: number | null;
  vmafMean: number | null;
}

export interface BuildRetainedReferenceContextInput {
  benchmarkProtocolId: string;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  qualityModelId: string;
  contextVersion: string;
  formulaVersion: string;
  targetMetricValue: number;
  qualityExponent: number;
  speedCurveRate: number;
  speedSaturationRealtime: number;
  requiredWorkloads: readonly ReferenceSweepWorkload[];
  requiredContentClasses: readonly string[];
  evidence: readonly RetainedReferenceEvidenceRecord[];
}

export interface LoadRetainedReferenceEvidenceOptions {
  benchmarkProtocolId: string;
  qualityModelId: string;
  suiteVersion?: string;
}

export interface GenerateReferenceContextFromDatabaseOptions {
  benchmarkProtocolId: string;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  qualityModelId: string;
  contextVersion: string;
  formulaVersion?: string;
  targetMetricValue?: number;
  qualityExponent?: number;
  speedCurveRate?: number;
  speedSaturationRealtime?: number;
  suiteManifest?: SuiteV1Manifest;
}

export interface ReferenceFrontierEvidence {
  kind: 'synthetic-sample' | 'retained-run-analysis';
  referenceId: string;
  sampleId: string | null;
  benchmarkRunId: string | null;
  payloadHash: string | null;
  artifactId: string | null;
  artifactSha256: string | null;
  qualityAnalysisId: string | null;
  analysisWorkerVersion: string | null;
}

export interface ReferenceFrontierPoint {
  bitrateBps: number;
  vmafMean: number;
  evidence: readonly ReferenceFrontierEvidence[];
}

export interface WorkloadReferenceContextEntry {
  workloadId: string;
  contentClass: string;
  workloadReferenceBitrateBps: number;
  referenceFrontier: readonly ReferenceFrontierPoint[];
}

export interface ReferenceContext {
  schemaVersion: typeof REFERENCE_CONTEXT_SCHEMA_VERSION;
  contextVersion: string;
  formulaVersion: string;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  qualityModelId: string;
  targetMetric: 'vmafMean';
  targetMetricValue: number;
  bitrateInterpolation: 'log-linear';
  transformConstants: {
    qualityExponent: number;
    speedCurveRate: number;
    speedSaturationRealtime: number;
  };
  generalPolicy: {
    requiresCompleteCoverage: true;
    weighting: typeof GENERAL_PL_WEIGHTING;
    requiredContentClasses: readonly string[];
  };
  activation: {
    stage: ReferenceContextActivationStage;
    productionActivationAllowed: boolean;
    note: string;
  };
  provenance: {
    sourceMode: ReferenceContextSourceMode;
    sourceVersion: string;
    inputHash: string;
    inputRecordCount: number;
    sourceIdHash: string;
  };
  workloads: readonly WorkloadReferenceContextEntry[];
  hash: string;
}

export interface RetainedAnalysisRecord {
  qualityAnalysisId?: string | null;
  analysisWorkerVersion?: string | null;
  benchmarkRunId: string;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  workloadId: string;
  testClipId: string;
  contentClass: string;
  recipeId: string;
  recipeFingerprint?: string | null;
  environmentId: string;
  environmentFingerprint?: string | null;
  qualityModelId: string;
  benchmarkRunStatus: BenchmarkRunDecision;
  qualityAnalysisStatus: QualityAnalysisDecision;
  encodeFps: number | null;
  sourceFps: number | null;
  realTimeRatio?: number | null;
  videoBitrateBps: number | null;
  fileSizeBytes: number | null;
  vmafMean: number | null;
  vmafP5: number | null;
}

export interface ScoreContextReadyRecord {
  contextVersion: string;
  formulaVersion: string;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  qualityModelId: string;
  workloadId: string;
  contentClass: string;
  workloadReferenceBitrateBps: number;
  transformConstants: ReferenceContext['transformConstants'];
  referenceFrontier: readonly ReferenceFrontierPoint[];
  contextHash: string;
}

export interface DerivedResultReadyRecord {
  kind: 'WORKLOAD' | 'GENERAL';
  scopeKey: string;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  formulaVersion: string;
  scoreContextVersion: string;
  qualityModelId: string;
  workloadId: string;
  contentClass: string | null;
  recipeId: string;
  environmentId: string;
  acceptedRunCount: number;
  suspectRunCount: number;
  rejectedRunCount: number;
  repetitionCount: number;
  centerEncodeFps: number | null;
  centerRealTimeRatio: number | null;
  centerVideoBitrateBps: number | null;
  centerFileSizeBytes: number | null;
  centerVmafMean: number | null;
  centerVmafP5: number | null;
  plQuality: number | null;
  plBitrate: number | null;
  plSpeed: number | null;
  plTotal: number | null;
  evidenceTier: EvidenceTier;
  memberBenchmarkRunIds: readonly string[];
  contributingWorkloadIds: readonly string[];
  recomputationSpec: ReturnType<typeof buildDerivedResultRecomputationSpec>;
}

export interface RecomputeReferenceScoresOptions {
  includedStatuses?: readonly IncludedDerivedStatus[];
  aggregatorVersion?: string;
}

export interface RecomputeReferenceScoresResult {
  scoreContexts: readonly ScoreContextReadyRecord[];
  derivedResults: readonly DerivedResultReadyRecord[];
}

export interface ScoreContextSeedRecord {
  kind: 'WORKLOAD' | 'GENERAL';
  benchmarkProtocolId: string;
  formulaVersion: string;
  contextVersion: string;
  workloadId: string;
  contentClass: string | null;
  qualityModelId: string;
  workloadReferenceBitrateBps: number;
  transformConstants: ReferenceContext['transformConstants'];
  referenceFrontier: Record<string, unknown>;
}

export interface PersistScoreContextsOptions {
  allowTestOnlyActivation?: boolean;
}

export interface PersistedScoreContextRecord {
  id: string;
  kind: 'WORKLOAD' | 'GENERAL';
  workloadId: string;
}

export interface PersistGeneralDerivedResultOptions {
  benchmarkProtocolId: string;
  protocolVersion: string;
  sourceSuiteVersion: string;
  contextVersion: string;
  formulaVersion: string;
  qualityModelId: string;
  recipeId: string;
  recipeFingerprint: string;
  environmentId: string;
  environmentFingerprint: string;
}

type PersistGeneralDerivedResultClient = DerivedResultPersistenceClient & {
  scoreContext: {
    findFirst(args: Prisma.ScoreContextFindFirstArgs): Promise<{
      id: string;
      benchmarkProtocolId: string;
      formulaVersion: string;
      contextVersion: string;
      workloadId: string;
      qualityModelId: string;
      workloadReferenceBitrateBps: number;
      referenceFrontier: Prisma.JsonValue | null;
    } | null>;
  };
  derivedResult: {
    findMany(args: Prisma.DerivedResultFindManyArgs): Promise<Array<{
      id: string;
      benchmarkProtocolId: string;
      workloadId: string;
      recipeId: string;
      environmentId: string;
      acceptedRunCount: number;
      suspectRunCount: number;
      rejectedRunCount: number;
      invalidRunCount: number;
      repetitionCount: number;
      plTotal: number | null;
      confidenceLower: number | null;
      confidenceUpper: number | null;
      evidenceTier: EvidenceTier;
      scoreContextId: string;
      testClip: { contentClass: string } | null;
      members: Array<{ benchmarkRunId: string; qualityAnalysisId: string }>;
    }>>;
  };
};

interface NormalizedSweepWorkload {
  workloadId: string;
  contentClass: string;
}

interface NormalizedSweepSample {
  sampleId: string;
  workloadId: string;
  codecFamily: string;
  encoderImplementation: string;
  videoBitrateBps: number;
  vmafMean: number;
}

interface NormalizedControlledReferenceSweep {
  schemaVersion: typeof CONTROLLED_REFERENCE_SWEEP_SCHEMA_VERSION;
  sweepVersion: string;
  contextVersion: string;
  formulaVersion: string;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  qualityModelId: string;
  targetMetric: 'vmafMean';
  targetMetricValue: number;
  bitrateInterpolation: 'log-linear';
  qualityExponent: number;
  speedCurveRate: number;
  speedSaturationRealtime: number;
  requiredWorkloads: readonly NormalizedSweepWorkload[];
  requiredContentClasses: readonly string[];
  samples: readonly NormalizedSweepSample[];
}

interface NormalizedRetainedReferenceEvidenceRecord {
  benchmarkRunId: string;
  benchmarkProtocolId: string;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  workloadId: string;
  testClipId: string;
  contentClass: string;
  payloadHash: string;
  recipeId: string;
  recipeFingerprint: string;
  environmentId: string;
  environmentFingerprint: string;
  artifactId: string;
  artifactSha256: string;
  qualityAnalysisId: string;
  analysisWorkerVersion: string;
  qualityModelId: string;
  videoBitrateBps: number;
  vmafMean: number;
}

interface NormalizedRetainedReferenceContextInput {
  benchmarkProtocolId: string;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  qualityModelId: string;
  contextVersion: string;
  formulaVersion: string;
  targetMetricValue: number;
  qualityExponent: number;
  speedCurveRate: number;
  speedSaturationRealtime: number;
  requiredWorkloads: readonly NormalizedSweepWorkload[];
  requiredContentClasses: readonly string[];
  evidence: readonly NormalizedRetainedReferenceEvidenceRecord[];
}

interface AggregatedFrontierPoint {
  bitrateBps: number;
  vmafMean: number;
  evidence: ReferenceFrontierEvidence[];
}

type FilteredEvidence = RetainedAnalysisRecord & {
  normalizedStatus: IncludedDerivedStatus;
  scoreContext: ScoreContextReadyRecord;
};

interface BuiltGeneralDerivedResult {
  derivedResult: DerivedResultPersistenceShape;
  members: ReadonlyArray<{ benchmarkRunId: string; qualityAnalysisId: string }>;
}

const EPSILON = 1e-9;
const EVIDENCE_TIER_ORDER: Record<EvidenceTier, number> = {
  PROVISIONAL: 0,
  LOW: 1,
  MEDIUM: 2,
  HIGH: 3,
};

function compareText(left: string, right: string): number {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function normalizeText(value: string, fieldName: string): string {
  const normalized = value.trim();
  if (!normalized) {
    throw new Error(`${fieldName} is required`);
  }
  return normalized;
}

function normalizeFinitePositive(value: number, fieldName: string): number {
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${fieldName} must be a finite positive number`);
  }
  return value;
}

function normalizeFinite(value: number, fieldName: string): number {
  if (!Number.isFinite(value)) {
    throw new Error(`${fieldName} must be finite`);
  }
  return value;
}

function average(values: readonly number[]): number | null {
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function roundMetric(value: number | null): number | null {
  if (value == null) return null;
  return Number(value.toFixed(6));
}

function canonicalGeometricMean(values: readonly number[]): number | null {
  if (!values.length) return null;
  if (values.some((value) => !Number.isFinite(value) || value <= 0)) {
    return null;
  }
  return Math.exp(values.reduce((sum, value) => sum + Math.log(value), 0) / values.length);
}

function canonicalGeometricMeanZeroToHundred(values: readonly number[]): number | null {
  const mean = canonicalGeometricMean(values.map((value) => value / 100));
  return mean == null ? null : 100 * mean;
}

function normalizeIncludedStatuses(values: readonly IncludedDerivedStatus[] | undefined): readonly IncludedDerivedStatus[] {
  const normalized = [...new Set((values ?? ['accepted']).map((value) => normalizeText(value, 'includedStatus').toLowerCase() as IncludedDerivedStatus))];
  for (const value of normalized) {
    if (value !== 'accepted' && value !== 'suspect' && value !== 'rejected') {
      throw new Error(`Unsupported included status: ${value}`);
    }
  }
  return normalized.sort(compareText);
}

function normalizeBenchmarkStatus(status: BenchmarkRunDecision): IncludedDerivedStatus | null {
  if (status === 'ACCEPTED') return 'accepted';
  if (status === 'SUSPECT') return 'suspect';
  if (status === 'REJECTED') return 'rejected';
  return null;
}

function qualityAnalysisUsable(status: QualityAnalysisDecision): boolean {
  return status === 'COMPLETE' || status === 'SUSPECT' || status === 'REJECTED';
}

function deriveEvidenceTier(accepted: number, suspect: number, rejected: number): EvidenceTier {
  if (accepted >= 3 && suspect === 0 && rejected === 0) return 'HIGH';
  if (accepted >= 2 && rejected === 0) return 'MEDIUM';
  if (accepted >= 1) return 'LOW';
  return 'PROVISIONAL';
}

function minimumEvidenceTier(values: readonly EvidenceTier[]): EvidenceTier {
  return [...values].sort((left, right) => EVIDENCE_TIER_ORDER[left] - EVIDENCE_TIER_ORDER[right])[0] ?? 'PROVISIONAL';
}

function toCanonicalJsonValue<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function hashContextPayload(value: Omit<ReferenceContext, 'hash'>): string {
  return sha256Hex(canonicalJsonString(toCanonicalJsonValue(value) as never));
}

function sourceIdHashFromEvidence(evidence: readonly ReferenceFrontierEvidence[]): string {
  const ids = evidence
    .map((entry) => entry.referenceId)
    .sort(compareText);
  return sha256Hex(canonicalJsonString(ids as never));
}

function buildUnavailableMetricInterval(confidenceLevel: number): Record<string, number | string | null> {
  return {
    lower: null,
    upper: null,
    width: null,
    confidenceLevel,
    method: 'unavailable',
  };
}

function quantileLinear(sorted: readonly number[], quantile: number): number | null {
  if (!sorted.length) return null;
  if (sorted.length === 1) return sorted[0] ?? null;
  const index = (sorted.length - 1) * Math.max(0, Math.min(1, quantile));
  const lowerIndex = Math.floor(index);
  const upperIndex = Math.ceil(index);
  if (lowerIndex === upperIndex) return sorted[lowerIndex] ?? null;
  const weight = index - lowerIndex;
  return (sorted[lowerIndex] ?? 0) + (((sorted[upperIndex] ?? 0) - (sorted[lowerIndex] ?? 0)) * weight);
}

function buildDispersion(values: readonly number[]): Record<string, number | null> {
  const sorted = [...values].filter((value) => Number.isFinite(value)).sort((left, right) => left - right);
  const q1 = quantileLinear(sorted, 0.25);
  const q3 = quantileLinear(sorted, 0.75);
  return {
    sampleCount: sorted.length,
    median: quantileLinear(sorted, 0.5),
    minimum: sorted[0] ?? null,
    maximum: sorted[sorted.length - 1] ?? null,
    q1,
    q3,
    iqr: q1 == null || q3 == null ? null : q3 - q1,
  };
}

function suiteWorkloadsFromManifest(manifest: SuiteV1Manifest): readonly ReferenceSweepWorkload[] {
  return manifest.clips.map((clip) => ({
    workloadId: clip.id,
    contentClass: clip.contentClass,
  }));
}

function buildInputHash(input: NormalizedControlledReferenceSweep | NormalizedRetainedReferenceContextInput): string {
  return sha256Hex(canonicalJsonString(toCanonicalJsonValue(input) as never));
}

function normalizeSweepInput(input: ControlledReferenceSweep): NormalizedControlledReferenceSweep {
  if (normalizeText(input.schemaVersion, 'schemaVersion') !== CONTROLLED_REFERENCE_SWEEP_SCHEMA_VERSION) {
    throw new Error(`Unsupported reference sweep schema: ${input.schemaVersion}`);
  }
  if (normalizeText(input.targetMetric, 'targetMetric') !== 'vmafMean') {
    throw new Error(`Unsupported target metric: ${input.targetMetric}`);
  }
  if (normalizeText(input.bitrateInterpolation, 'bitrateInterpolation') !== 'log-linear') {
    throw new Error(`Unsupported bitrate interpolation: ${input.bitrateInterpolation}`);
  }

  const requiredWorkloads = input.requiredWorkloads
    .map((entry) => ({
      workloadId: normalizeText(entry.workloadId, 'requiredWorkloads.workloadId'),
      contentClass: normalizeText(entry.contentClass, 'requiredWorkloads.contentClass'),
    }))
    .sort((left, right) => compareText(left.contentClass, right.contentClass) || compareText(left.workloadId, right.workloadId));
  const requiredContentClasses = [...new Set(
    input.requiredContentClasses.map((value) => normalizeText(value, 'requiredContentClasses')),
  )].sort(compareText);
  const samples = input.samples
    .map((sample) => ({
      sampleId: normalizeText(sample.sampleId, 'samples.sampleId'),
      workloadId: normalizeText(sample.workloadId, 'samples.workloadId'),
      codecFamily: normalizeText(sample.codecFamily, 'samples.codecFamily').toLowerCase(),
      encoderImplementation: normalizeText(sample.encoderImplementation, 'samples.encoderImplementation').toLowerCase(),
      videoBitrateBps: normalizeFinitePositive(sample.videoBitrateBps, 'samples.videoBitrateBps'),
      vmafMean: normalizeFinite(sample.vmafMean, 'samples.vmafMean'),
    }))
    .sort((left, right) =>
      compareText(left.workloadId, right.workloadId)
      || left.videoBitrateBps - right.videoBitrateBps
      || left.vmafMean - right.vmafMean
      || compareText(left.sampleId, right.sampleId));

  if (!requiredWorkloads.length) {
    throw new Error('requiredWorkloads must not be empty');
  }
  if (!requiredContentClasses.length) {
    throw new Error('requiredContentClasses must not be empty');
  }

  const seenWorkloads = new Set<string>();
  for (const workload of requiredWorkloads) {
    if (seenWorkloads.has(workload.workloadId)) {
      throw new Error(`Duplicate required workload: ${workload.workloadId}`);
    }
    seenWorkloads.add(workload.workloadId);
    if (!requiredContentClasses.includes(workload.contentClass)) {
      throw new Error(`Required workload ${workload.workloadId} uses undeclared content class ${workload.contentClass}`);
    }
  }

  return {
    schemaVersion: CONTROLLED_REFERENCE_SWEEP_SCHEMA_VERSION,
    sweepVersion: normalizeText(input.sweepVersion, 'sweepVersion'),
    contextVersion: normalizeText(input.contextVersion, 'contextVersion'),
    formulaVersion: normalizeText(input.formulaVersion, 'formulaVersion'),
    benchmarkProtocolVersion: normalizeText(input.benchmarkProtocolVersion, 'benchmarkProtocolVersion'),
    sourceSuiteVersion: normalizeText(input.sourceSuiteVersion, 'sourceSuiteVersion'),
    qualityModelId: normalizeText(input.qualityModelId, 'qualityModelId'),
    targetMetric: 'vmafMean',
    targetMetricValue: normalizeFinitePositive(input.targetMetricValue, 'targetMetricValue'),
    bitrateInterpolation: 'log-linear',
    qualityExponent: normalizeFinitePositive(input.qualityExponent, 'qualityExponent'),
    speedCurveRate: normalizeFinitePositive(input.speedCurveRate, 'speedCurveRate'),
    speedSaturationRealtime: normalizeFinitePositive(input.speedSaturationRealtime, 'speedSaturationRealtime'),
    requiredWorkloads,
    requiredContentClasses,
    samples,
  };
}

function normalizeRetainedReferenceInput(input: BuildRetainedReferenceContextInput): NormalizedRetainedReferenceContextInput {
  const requiredWorkloads = input.requiredWorkloads
    .map((entry) => ({
      workloadId: normalizeText(entry.workloadId, 'requiredWorkloads.workloadId'),
      contentClass: normalizeText(entry.contentClass, 'requiredWorkloads.contentClass'),
    }))
    .sort((left, right) => compareText(left.contentClass, right.contentClass) || compareText(left.workloadId, right.workloadId));
  const requiredContentClasses = [...new Set(
    input.requiredContentClasses.map((value) => normalizeText(value, 'requiredContentClasses')),
  )].sort(compareText);

  const evidence = input.evidence
    .filter((record) =>
      record.benchmarkRunStatus === 'ACCEPTED'
      && record.artifactRole === 'ENCODED'
      && record.artifactStorageState === 'RETAINED'
      && record.qualityAnalysisStatus === 'COMPLETE')
    .map((record) => ({
      benchmarkRunId: normalizeText(record.benchmarkRunId, 'benchmarkRunId'),
      benchmarkProtocolId: normalizeText(record.benchmarkProtocolId, 'benchmarkProtocolId'),
      benchmarkProtocolVersion: normalizeText(record.benchmarkProtocolVersion, 'benchmarkProtocolVersion'),
      sourceSuiteVersion: normalizeText(record.sourceSuiteVersion, 'sourceSuiteVersion'),
      workloadId: normalizeText(record.workloadId, 'workloadId'),
      testClipId: normalizeText(record.testClipId, 'testClipId'),
      contentClass: normalizeText(record.contentClass, 'contentClass'),
      payloadHash: normalizeText(record.payloadHash, 'payloadHash'),
      recipeId: normalizeText(record.recipeId, 'recipeId'),
      recipeFingerprint: normalizeText(record.recipeFingerprint, 'recipeFingerprint'),
      environmentId: normalizeText(record.environmentId, 'environmentId'),
      environmentFingerprint: normalizeText(record.environmentFingerprint, 'environmentFingerprint'),
      artifactId: normalizeText(record.artifactId, 'artifactId'),
      artifactSha256: normalizeText(record.artifactSha256, 'artifactSha256'),
      qualityAnalysisId: normalizeText(record.qualityAnalysisId, 'qualityAnalysisId'),
      analysisWorkerVersion: normalizeText(record.analysisWorkerVersion, 'analysisWorkerVersion'),
      qualityModelId: normalizeText(record.qualityModelId, 'qualityModelId'),
      videoBitrateBps: normalizeFinitePositive(record.videoBitrateBps ?? Number.NaN, 'videoBitrateBps'),
      vmafMean: normalizeFinite(record.vmafMean ?? Number.NaN, 'vmafMean'),
    }))
    .sort((left, right) =>
      compareText(left.workloadId, right.workloadId)
      || left.videoBitrateBps - right.videoBitrateBps
      || left.vmafMean - right.vmafMean
      || compareText(left.qualityAnalysisId, right.qualityAnalysisId));

  if (!requiredWorkloads.length) {
    throw new Error('requiredWorkloads must not be empty');
  }
  if (!requiredContentClasses.length) {
    throw new Error('requiredContentClasses must not be empty');
  }
  if (!evidence.length) {
    throw new Error('No retained accepted benchmark evidence is available');
  }

  return {
    benchmarkProtocolId: normalizeText(input.benchmarkProtocolId, 'benchmarkProtocolId'),
    benchmarkProtocolVersion: normalizeText(input.benchmarkProtocolVersion, 'benchmarkProtocolVersion'),
    sourceSuiteVersion: normalizeText(input.sourceSuiteVersion, 'sourceSuiteVersion'),
    qualityModelId: normalizeText(input.qualityModelId, 'qualityModelId'),
    contextVersion: normalizeText(input.contextVersion, 'contextVersion'),
    formulaVersion: normalizeText(input.formulaVersion, 'formulaVersion'),
    targetMetricValue: normalizeFinitePositive(input.targetMetricValue, 'targetMetricValue'),
    qualityExponent: normalizeFinitePositive(input.qualityExponent, 'qualityExponent'),
    speedCurveRate: normalizeFinitePositive(input.speedCurveRate, 'speedCurveRate'),
    speedSaturationRealtime: normalizeFinitePositive(input.speedSaturationRealtime, 'speedSaturationRealtime'),
    requiredWorkloads,
    requiredContentClasses,
    evidence,
  };
}

function buildSyntheticEvidenceRef(sample: NormalizedSweepSample): ReferenceFrontierEvidence {
  return {
    kind: 'synthetic-sample',
    referenceId: sample.sampleId,
    sampleId: sample.sampleId,
    benchmarkRunId: null,
    payloadHash: null,
    artifactId: null,
    artifactSha256: null,
    qualityAnalysisId: null,
    analysisWorkerVersion: null,
  };
}

function buildRetainedEvidenceRef(record: NormalizedRetainedReferenceEvidenceRecord): ReferenceFrontierEvidence {
  return {
    kind: 'retained-run-analysis',
    referenceId: record.qualityAnalysisId,
    sampleId: null,
    benchmarkRunId: record.benchmarkRunId,
    payloadHash: record.payloadHash,
    artifactId: record.artifactId,
    artifactSha256: record.artifactSha256,
    qualityAnalysisId: record.qualityAnalysisId,
    analysisWorkerVersion: record.analysisWorkerVersion,
  };
}

function buildFrontierPoints<TSample extends { videoBitrateBps: number; vmafMean: number }>(
  samples: readonly TSample[],
  evidenceBuilder: (sample: TSample) => ReferenceFrontierEvidence,
): readonly ReferenceFrontierPoint[] {
  const grouped = new Map<number, AggregatedFrontierPoint>();
  for (const sample of samples) {
    const evidence = evidenceBuilder(sample);
    const existing = grouped.get(sample.videoBitrateBps);
    if (!existing) {
      grouped.set(sample.videoBitrateBps, {
        bitrateBps: sample.videoBitrateBps,
        vmafMean: sample.vmafMean,
        evidence: [evidence],
      });
      continue;
    }
    if (sample.vmafMean > existing.vmafMean + EPSILON) {
      existing.vmafMean = sample.vmafMean;
      existing.evidence = [evidence];
      continue;
    }
    if (Math.abs(sample.vmafMean - existing.vmafMean) <= EPSILON) {
      existing.evidence.push(evidence);
      existing.evidence.sort((left, right) => compareText(left.referenceId, right.referenceId));
    }
  }

  const sorted = [...grouped.values()]
    .sort((left, right) => left.bitrateBps - right.bitrateBps || compareText(left.evidence[0]?.referenceId ?? '', right.evidence[0]?.referenceId ?? ''));

  const frontier: ReferenceFrontierPoint[] = [];
  let bestQuality = -Infinity;
  for (const point of sorted) {
    if (point.vmafMean > bestQuality + EPSILON) {
      frontier.push({
        bitrateBps: point.bitrateBps,
        vmafMean: point.vmafMean,
        evidence: [...point.evidence].sort((left, right) => compareText(left.referenceId, right.referenceId)),
      });
      bestQuality = point.vmafMean;
    }
  }
  return frontier;
}

function interpolateReferenceBitrate(
  workloadId: string,
  frontier: readonly ReferenceFrontierPoint[],
  targetVmaf: number,
): number {
  for (const point of frontier) {
    if (Math.abs(point.vmafMean - targetVmaf) <= EPSILON) {
      return point.bitrateBps;
    }
  }

  for (let index = 1; index < frontier.length; index += 1) {
    const lower = frontier[index - 1]!;
    const upper = frontier[index]!;
    if (lower.vmafMean + EPSILON >= upper.vmafMean) continue;
    if (lower.vmafMean < targetVmaf && upper.vmafMean > targetVmaf) {
      const t = (targetVmaf - lower.vmafMean) / (upper.vmafMean - lower.vmafMean);
      const bitrate = Math.exp(Math.log(lower.bitrateBps) + t * (Math.log(upper.bitrateBps) - Math.log(lower.bitrateBps)));
      return Number(bitrate.toFixed(6));
    }
  }

  throw new Error(`Incomplete reference frontier for ${workloadId}; cannot bracket VMAF ${targetVmaf}`);
}

export function buildGeneralScopeWorkloadId(sourceSuiteVersion: string): string {
  return `${GENERAL_SCOPE_WORKLOAD_PREFIX}${normalizeText(sourceSuiteVersion, 'sourceSuiteVersion')}`;
}

function buildReferenceContextFromWorkloads(params: {
  contextVersion: string;
  formulaVersion: string;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  qualityModelId: string;
  targetMetricValue: number;
  qualityExponent: number;
  speedCurveRate: number;
  speedSaturationRealtime: number;
  requiredWorkloads: readonly NormalizedSweepWorkload[];
  requiredContentClasses: readonly string[];
  activation: ReferenceContext['activation'];
  provenance: ReferenceContext['provenance'];
  frontiers: ReadonlyMap<string, readonly ReferenceFrontierPoint[]>;
}): ReferenceContext {
  const workloads = params.requiredWorkloads.map((workload) => {
    const frontier = params.frontiers.get(workload.workloadId) ?? [];
    if (frontier.length < 2) {
      throw new Error(`Incomplete reference frontier for ${workload.workloadId}; at least two frontier points are required`);
    }
    return {
      workloadId: workload.workloadId,
      contentClass: workload.contentClass,
      workloadReferenceBitrateBps: interpolateReferenceBitrate(
        workload.workloadId,
        frontier,
        params.targetMetricValue,
      ),
      referenceFrontier: frontier,
    };
  });

  const contextWithoutHash = {
    schemaVersion: REFERENCE_CONTEXT_SCHEMA_VERSION,
    contextVersion: params.contextVersion,
    formulaVersion: params.formulaVersion,
    benchmarkProtocolVersion: params.benchmarkProtocolVersion,
    sourceSuiteVersion: params.sourceSuiteVersion,
    qualityModelId: params.qualityModelId,
    targetMetric: 'vmafMean' as const,
    targetMetricValue: params.targetMetricValue,
    bitrateInterpolation: 'log-linear' as const,
    transformConstants: {
      qualityExponent: params.qualityExponent,
      speedCurveRate: params.speedCurveRate,
      speedSaturationRealtime: params.speedSaturationRealtime,
    },
    generalPolicy: {
      requiresCompleteCoverage: true as const,
      weighting: GENERAL_PL_WEIGHTING,
      requiredContentClasses: params.requiredContentClasses,
    },
    activation: params.activation,
    provenance: params.provenance,
    workloads,
  };

  return {
    ...contextWithoutHash,
    hash: hashContextPayload(contextWithoutHash),
  };
}

export function buildReferenceContextFromSweep(input: ControlledReferenceSweep): ReferenceContext {
  const normalized = normalizeSweepInput(input);
  const inputHash = buildInputHash(normalized);
  const frontiers = new Map<string, readonly ReferenceFrontierPoint[]>();

  for (const workload of normalized.requiredWorkloads) {
    const workloadSamples = normalized.samples.filter((sample) => sample.workloadId === workload.workloadId);
    if (!workloadSamples.length) {
      throw new Error(`Missing controlled sweep samples for workload ${workload.workloadId}`);
    }
    frontiers.set(
      workload.workloadId,
      buildFrontierPoints(workloadSamples, buildSyntheticEvidenceRef),
    );
  }

  const sourceIdHash = sha256Hex(canonicalJsonString(
    normalized.samples.map((sample) => sample.sampleId).sort(compareText) as never,
  ));

  return buildReferenceContextFromWorkloads({
    contextVersion: normalized.contextVersion,
    formulaVersion: normalized.formulaVersion,
    benchmarkProtocolVersion: normalized.benchmarkProtocolVersion,
    sourceSuiteVersion: normalized.sourceSuiteVersion,
    qualityModelId: normalized.qualityModelId,
    targetMetricValue: normalized.targetMetricValue,
    qualityExponent: normalized.qualityExponent,
    speedCurveRate: normalized.speedCurveRate,
    speedSaturationRealtime: normalized.speedSaturationRealtime,
    requiredWorkloads: normalized.requiredWorkloads,
    requiredContentClasses: normalized.requiredContentClasses,
    activation: {
      stage: 'TEST_ONLY_PROVISIONAL',
      productionActivationAllowed: false,
      note: 'Synthetic controlled sweep fixture for tests and local development only; not retained authoritative public PL evidence.',
    },
    provenance: {
      sourceMode: 'synthetic-controlled-sweep',
      sourceVersion: normalized.sweepVersion,
      inputHash,
      inputRecordCount: normalized.samples.length,
      sourceIdHash,
    },
    frontiers,
  });
}

export function buildReferenceContextFromRetainedEvidence(input: BuildRetainedReferenceContextInput): ReferenceContext {
  const normalized = normalizeRetainedReferenceInput(input);
  const inputHash = buildInputHash(normalized);
  const frontiers = new Map<string, readonly ReferenceFrontierPoint[]>();

  for (const workload of normalized.requiredWorkloads) {
    const workloadEvidence = normalized.evidence.filter((record) => record.workloadId === workload.workloadId);
    if (!workloadEvidence.length) {
      throw new Error(`Missing retained authoritative evidence for workload ${workload.workloadId}`);
    }
    const mismatchedClass = workloadEvidence.find((record) => record.contentClass !== workload.contentClass);
    if (mismatchedClass) {
      throw new Error(`Retained evidence for ${workload.workloadId} uses mismatched content class ${mismatchedClass.contentClass}`);
    }
    frontiers.set(
      workload.workloadId,
      buildFrontierPoints(workloadEvidence, buildRetainedEvidenceRef),
    );
  }

  const sourceIdHash = sha256Hex(canonicalJsonString(
    normalized.evidence.map((record) => ({
      benchmarkRunId: record.benchmarkRunId,
      artifactId: record.artifactId,
      qualityAnalysisId: record.qualityAnalysisId,
      artifactSha256: record.artifactSha256,
    })) as never,
  ));

  return buildReferenceContextFromWorkloads({
    contextVersion: normalized.contextVersion,
    formulaVersion: normalized.formulaVersion,
    benchmarkProtocolVersion: normalized.benchmarkProtocolVersion,
    sourceSuiteVersion: normalized.sourceSuiteVersion,
    qualityModelId: normalized.qualityModelId,
    targetMetricValue: normalized.targetMetricValue,
    qualityExponent: normalized.qualityExponent,
    speedCurveRate: normalized.speedCurveRate,
    speedSaturationRealtime: normalized.speedSaturationRealtime,
    requiredWorkloads: normalized.requiredWorkloads,
    requiredContentClasses: normalized.requiredContentClasses,
    activation: {
      stage: 'PRODUCTION',
      productionActivationAllowed: true,
      note: 'Generated from retained accepted BenchmarkRun, retained ENCODED Artifact, and authoritative COMPLETE QualityAnalysis evidence.',
    },
    provenance: {
      sourceMode: 'retained-benchmark-evidence',
      sourceVersion: normalized.benchmarkProtocolId,
      inputHash,
      inputRecordCount: normalized.evidence.length,
      sourceIdHash,
    },
    frontiers,
  });
}

export function parseReferenceContext(raw: string): ReferenceContext {
  const parsed = JSON.parse(raw) as ReferenceContext;
  if (normalizeText(parsed.schemaVersion, 'schemaVersion') !== REFERENCE_CONTEXT_SCHEMA_VERSION) {
    throw new Error(`Unsupported reference context schema: ${parsed.schemaVersion}`);
  }
  const { hash, ...payload } = parsed;
  if (hashContextPayload(payload as Omit<ReferenceContext, 'hash'>) !== hash) {
    throw new Error(`Reference context hash mismatch: expected ${parsed.hash}`);
  }
  if (parsed.activation.stage === 'TEST_ONLY_PROVISIONAL' && parsed.activation.productionActivationAllowed) {
    throw new Error('Test-only provisional reference contexts must not allow production activation');
  }
  return parsed;
}

export function loadReferenceContext(filePath: string): ReferenceContext {
  return parseReferenceContext(readFileSync(filePath, 'utf8'));
}

type ReferenceEvidenceLoaderClient = Pick<PrismaClient, 'benchmarkRun'> | Prisma.TransactionClient;

export async function loadRetainedReferenceEvidence(
  client: ReferenceEvidenceLoaderClient,
  options: LoadRetainedReferenceEvidenceOptions,
): Promise<readonly RetainedReferenceEvidenceRecord[]> {
  const suiteVersion = options.suiteVersion ?? loadAuthoritativeSuiteManifest().suiteVersion;
  const runs = await client.benchmarkRun.findMany({
    where: {
      benchmarkProtocolId: options.benchmarkProtocolId,
      status: 'ACCEPTED',
      testClip: {
        suiteVersion,
      },
      artifacts: {
        some: {
          role: 'ENCODED',
          storageState: 'RETAINED',
          sha256: { not: null },
        },
      },
      qualityAnalyses: {
        some: {
          metricModelId: options.qualityModelId,
          status: 'COMPLETE',
          videoBitrateBps: { not: null },
          vmafMean: { not: null },
        },
      },
    },
    include: {
      benchmarkProtocol: true,
      testClip: true,
      recipe: true,
      environment: true,
      artifacts: {
        where: {
          role: 'ENCODED',
          storageState: 'RETAINED',
          sha256: { not: null },
        },
        orderBy: [
          { updatedAt: 'desc' },
          { id: 'desc' },
        ],
      },
      qualityAnalyses: {
        where: {
          metricModelId: options.qualityModelId,
          status: 'COMPLETE',
          videoBitrateBps: { not: null },
          vmafMean: { not: null },
        },
        orderBy: [
          { updatedAt: 'desc' },
          { id: 'desc' },
        ],
      },
    },
    orderBy: [
      { workloadId: 'asc' },
      { id: 'asc' },
    ],
  });

  return runs.flatMap((run) => {
    const artifact = run.artifacts[0];
    const analysis = run.qualityAnalyses[0];
    if (!artifact || !artifact.sha256 || !analysis || analysis.videoBitrateBps == null || analysis.vmafMean == null) {
      return [];
    }
    return [{
      benchmarkRunId: run.id,
      benchmarkProtocolId: run.benchmarkProtocolId,
      benchmarkProtocolVersion: run.benchmarkProtocol.protocolVersion,
      sourceSuiteVersion: run.benchmarkProtocol.sourceSuiteVersion,
      workloadId: run.workloadId,
      testClipId: run.testClipId,
      contentClass: run.testClip.contentClass,
      benchmarkRunStatus: run.status,
      payloadHash: run.payloadHash,
      recipeId: run.recipeId,
      recipeFingerprint: run.recipe.fingerprint,
      environmentId: run.environmentId,
      environmentFingerprint: run.environment.fingerprint,
      artifactId: artifact.id,
      artifactRole: artifact.role,
      artifactStorageState: artifact.storageState,
      artifactSha256: artifact.sha256,
      qualityAnalysisId: analysis.id,
      qualityAnalysisStatus: analysis.status,
      analysisWorkerVersion: analysis.analysisWorkerVersion,
      qualityModelId: analysis.metricModelId,
      videoBitrateBps: analysis.videoBitrateBps,
      vmafMean: analysis.vmafMean,
    }];
  }).sort((left, right) =>
    compareText(left.workloadId, right.workloadId)
    || (left.videoBitrateBps ?? 0) - (right.videoBitrateBps ?? 0)
    || (left.vmafMean ?? 0) - (right.vmafMean ?? 0)
    || compareText(left.qualityAnalysisId, right.qualityAnalysisId));
}

export async function generateReferenceContextFromDatabase(
  client: ReferenceEvidenceLoaderClient,
  options: GenerateReferenceContextFromDatabaseOptions,
): Promise<ReferenceContext> {
  const manifest = options.suiteManifest ?? loadAuthoritativeSuiteManifest();
  const evidence = await loadRetainedReferenceEvidence(client, {
    benchmarkProtocolId: options.benchmarkProtocolId,
    qualityModelId: options.qualityModelId,
    suiteVersion: manifest.suiteVersion,
  });
  return buildReferenceContextFromRetainedEvidence({
    benchmarkProtocolId: options.benchmarkProtocolId,
    benchmarkProtocolVersion: options.benchmarkProtocolVersion,
    sourceSuiteVersion: options.sourceSuiteVersion,
    qualityModelId: options.qualityModelId,
    contextVersion: options.contextVersion,
    formulaVersion: options.formulaVersion ?? REFERENCE_CONTEXT_FORMULA_VERSION,
    targetMetricValue: options.targetMetricValue ?? 90,
    qualityExponent: options.qualityExponent ?? 2.4,
    speedCurveRate: options.speedCurveRate ?? 1.2,
    speedSaturationRealtime: options.speedSaturationRealtime ?? 4,
    requiredWorkloads: suiteWorkloadsFromManifest(manifest),
    requiredContentClasses: manifest.requiredContentClasses,
    evidence,
  });
}

function buildScoreContextIndex(context: ReferenceContext): Map<string, ScoreContextReadyRecord> {
  const index = new Map<string, ScoreContextReadyRecord>();
  for (const workload of context.workloads) {
    index.set(workload.workloadId, {
      contextVersion: context.contextVersion,
      formulaVersion: context.formulaVersion,
      benchmarkProtocolVersion: context.benchmarkProtocolVersion,
      sourceSuiteVersion: context.sourceSuiteVersion,
      qualityModelId: context.qualityModelId,
      workloadId: workload.workloadId,
      contentClass: workload.contentClass,
      workloadReferenceBitrateBps: workload.workloadReferenceBitrateBps,
      transformConstants: context.transformConstants,
      referenceFrontier: workload.referenceFrontier,
      contextHash: context.hash,
    });
  }
  return index;
}

export function buildScoreContextSeedRecords(
  context: ReferenceContext,
  benchmarkProtocolId: string,
): readonly ScoreContextSeedRecord[] {
  const normalizedBenchmarkProtocolId = normalizeText(benchmarkProtocolId, 'benchmarkProtocolId');
  const generalReferenceBitrateBps = canonicalGeometricMean(
    context.workloads.map((workload) => workload.workloadReferenceBitrateBps),
  );
  if (generalReferenceBitrateBps == null) {
    throw new Error('General score context requires at least one positive workload reference bitrate');
  }

  const workloadSeeds = context.workloads.map((workload) => ({
    kind: 'WORKLOAD' as const,
    benchmarkProtocolId: normalizedBenchmarkProtocolId,
    formulaVersion: context.formulaVersion,
    contextVersion: context.contextVersion,
    workloadId: workload.workloadId,
    contentClass: workload.contentClass,
    qualityModelId: context.qualityModelId,
    workloadReferenceBitrateBps: workload.workloadReferenceBitrateBps,
    transformConstants: context.transformConstants,
    referenceFrontier: {
      workloadId: workload.workloadId,
      contentClass: workload.contentClass,
      referenceFrontier: workload.referenceFrontier,
      provenance: context.provenance,
      activation: context.activation,
    },
  }));

  const generalSeed: ScoreContextSeedRecord = {
    kind: 'GENERAL',
    benchmarkProtocolId: normalizedBenchmarkProtocolId,
    formulaVersion: context.formulaVersion,
    contextVersion: context.contextVersion,
    workloadId: buildGeneralScopeWorkloadId(context.sourceSuiteVersion),
    contentClass: null,
    qualityModelId: context.qualityModelId,
    workloadReferenceBitrateBps: Number(generalReferenceBitrateBps.toFixed(6)),
    transformConstants: context.transformConstants,
    referenceFrontier: {
      generalPolicy: context.generalPolicy,
      workloads: context.workloads.map((workload) => ({
        workloadId: workload.workloadId,
        contentClass: workload.contentClass,
        workloadReferenceBitrateBps: workload.workloadReferenceBitrateBps,
      })),
      provenance: context.provenance,
      activation: context.activation,
    },
  };

  return [...workloadSeeds, generalSeed];
}

type ScoreContextPersistenceClient = Pick<PrismaClient, '$transaction'> | Prisma.TransactionClient;

function toPrismaJson(value: unknown): Prisma.InputJsonValue {
  return value as Prisma.InputJsonValue;
}

export async function persistScoreContextsFromReferenceContext(
  client: ScoreContextPersistenceClient,
  context: ReferenceContext,
  benchmarkProtocolId: string,
  options: PersistScoreContextsOptions = {},
): Promise<readonly PersistedScoreContextRecord[]> {
  if (!context.activation.productionActivationAllowed && options.allowTestOnlyActivation !== true) {
    throw new Error(`Reference context ${context.contextVersion} is ${context.activation.stage} and cannot be activated in production persistence`);
  }

  const seeds = buildScoreContextSeedRecords(context, benchmarkProtocolId);
  const write = async (tx: Prisma.TransactionClient): Promise<PersistedScoreContextRecord[]> => {
    const persisted: PersistedScoreContextRecord[] = [];
    for (const seed of seeds) {
      const record = await tx.scoreContext.upsert({
        where: {
          formulaVersion_contextVersion_workloadId_qualityModelId: {
            formulaVersion: seed.formulaVersion,
            contextVersion: seed.contextVersion,
            workloadId: seed.workloadId,
            qualityModelId: seed.qualityModelId,
          },
        },
        create: {
          benchmarkProtocol: { connect: { id: seed.benchmarkProtocolId } },
          formulaVersion: seed.formulaVersion,
          contextVersion: seed.contextVersion,
          workloadId: seed.workloadId,
          qualityModelId: seed.qualityModelId,
          workloadReferenceBitrateBps: seed.workloadReferenceBitrateBps,
          transformConstants: toPrismaJson(seed.transformConstants),
          referenceFrontier: toPrismaJson(seed.referenceFrontier),
        },
        update: {
          benchmarkProtocol: { connect: { id: seed.benchmarkProtocolId } },
          workloadReferenceBitrateBps: seed.workloadReferenceBitrateBps,
          transformConstants: toPrismaJson(seed.transformConstants),
          referenceFrontier: toPrismaJson(seed.referenceFrontier),
        },
      });
      persisted.push({
        id: record.id,
        kind: seed.kind,
        workloadId: seed.workloadId,
      });
    }
    return persisted.sort((left, right) => compareText(left.workloadId, right.workloadId));
  };

  return '$transaction' in client
    ? client.$transaction((tx) => write(tx))
    : write(client);
}

function buildWorkloadResult(
  runs: readonly FilteredEvidence[],
  scoreContext: ScoreContextReadyRecord,
  context: ReferenceContext,
  aggregatorVersion: string,
  includedStatuses: readonly IncludedDerivedStatus[],
): DerivedResultReadyRecord | null {
  const validRuns = runs
    .filter((run) => run.workloadId === scoreContext.workloadId)
    .filter((run) => qualityAnalysisUsable(run.qualityAnalysisStatus))
    .map((run) => ({
      run,
      score: computePlScoreV7({
        vmafMean: run.vmafMean,
        vmafP5: run.vmafP5,
        videoBitrateBps: run.videoBitrateBps,
        encodeFps: run.encodeFps,
        sourceFps: run.sourceFps,
      }, {
        workloadId: scoreContext.workloadId,
        workloadReferenceBitrateBps: scoreContext.workloadReferenceBitrateBps,
        scoreFormulaVersion: REFERENCE_CONTEXT_FORMULA_VERSION,
        qualityExponent: scoreContext.transformConstants.qualityExponent,
        speedCurveRate: scoreContext.transformConstants.speedCurveRate,
        speedSaturationRealtime: scoreContext.transformConstants.speedSaturationRealtime,
      }),
    }))
    .filter((entry) => entry.score != null) as Array<{ run: FilteredEvidence; score: NonNullable<ReturnType<typeof computePlScoreV7>> }>;

  if (!validRuns.length) return null;

  const acceptedRunCount = validRuns.filter((entry) => entry.run.normalizedStatus === 'accepted').length;
  const suspectRunCount = validRuns.filter((entry) => entry.run.normalizedStatus === 'suspect').length;
  const rejectedRunCount = validRuns.filter((entry) => entry.run.normalizedStatus === 'rejected').length;
  const centerEncodeFps = average(validRuns.map((entry) => entry.run.encodeFps as number));
  const centerSourceFps = average(validRuns.map((entry) => entry.run.sourceFps as number));
  const centerVideoBitrateBps = average(validRuns.map((entry) => entry.run.videoBitrateBps as number));
  const centerVmafMean = average(validRuns.map((entry) => entry.run.vmafMean as number));
  const centerVmafP5 = average(validRuns.map((entry) => entry.run.vmafP5 as number));
  const centerFileSizeBytes = average(validRuns.map((entry) => entry.run.fileSizeBytes).filter((value): value is number => value != null));
  const centerScore = computePlScoreV7({
    vmafMean: centerVmafMean,
    vmafP5: centerVmafP5,
    videoBitrateBps: centerVideoBitrateBps,
    encodeFps: centerEncodeFps,
    sourceFps: centerSourceFps,
  }, {
    workloadId: scoreContext.workloadId,
    workloadReferenceBitrateBps: scoreContext.workloadReferenceBitrateBps,
    scoreFormulaVersion: REFERENCE_CONTEXT_FORMULA_VERSION,
    qualityExponent: scoreContext.transformConstants.qualityExponent,
    speedCurveRate: scoreContext.transformConstants.speedCurveRate,
    speedSaturationRealtime: scoreContext.transformConstants.speedSaturationRealtime,
  });
  if (!centerScore) return null;

  const first = validRuns[0]!.run;
  return {
    kind: 'WORKLOAD',
    scopeKey: buildDerivedResultScopeKey('workload', { workloadId: scoreContext.workloadId }),
    benchmarkProtocolVersion: context.benchmarkProtocolVersion,
    sourceSuiteVersion: context.sourceSuiteVersion,
    formulaVersion: context.formulaVersion,
    scoreContextVersion: context.contextVersion,
    qualityModelId: context.qualityModelId,
    workloadId: scoreContext.workloadId,
    contentClass: scoreContext.contentClass,
    recipeId: first.recipeId,
    environmentId: first.environmentId,
    acceptedRunCount,
    suspectRunCount,
    rejectedRunCount,
    repetitionCount: validRuns.length,
    centerEncodeFps: roundMetric(centerEncodeFps),
    centerRealTimeRatio: roundMetric(centerScore.realtimeRatio),
    centerVideoBitrateBps: roundMetric(centerVideoBitrateBps),
    centerFileSizeBytes: roundMetric(centerFileSizeBytes),
    centerVmafMean: roundMetric(centerVmafMean),
    centerVmafP5: roundMetric(centerVmafP5),
    plQuality: roundMetric(centerScore.quality),
    plBitrate: roundMetric(centerScore.bitrate),
    plSpeed: roundMetric(centerScore.speed),
    plTotal: roundMetric(centerScore.total),
    evidenceTier: deriveEvidenceTier(acceptedRunCount, suspectRunCount, rejectedRunCount),
    memberBenchmarkRunIds: validRuns.map((entry) => entry.run.benchmarkRunId).sort(compareText),
    contributingWorkloadIds: [scoreContext.workloadId],
    recomputationSpec: buildDerivedResultRecomputationSpec({
      protocolVersion: context.benchmarkProtocolVersion,
      sourceSuiteVersion: context.sourceSuiteVersion,
      workloadId: scoreContext.workloadId,
      recipeFingerprint: first.recipeFingerprint?.trim() || first.recipeId,
      environmentFingerprint: first.environmentFingerprint?.trim() || first.environmentId,
      formulaVersion: context.formulaVersion,
      scoreContextVersion: context.contextVersion,
      qualityModelId: context.qualityModelId,
      scopeKey: buildDerivedResultScopeKey('workload', { workloadId: scoreContext.workloadId }),
      includedStatuses,
      aggregatorVersion,
      selectedAnalysisIds: [...new Set(validRuns.map((entry) => entry.run.qualityAnalysisId).filter((value): value is string => typeof value === 'string' && value.length > 0))].sort(compareText),
      analysisWorkerVersions: [...new Set(validRuns.map((entry) => entry.run.analysisWorkerVersion).filter((value): value is string => typeof value === 'string' && value.length > 0))].sort(compareText),
    }),
  };
}

function buildGeneralResults(
  workloadResults: readonly DerivedResultReadyRecord[],
  context: ReferenceContext,
  aggregatorVersion: string,
  includedStatuses: readonly IncludedDerivedStatus[],
): readonly DerivedResultReadyRecord[] {
  const grouped = new Map<string, DerivedResultReadyRecord[]>();
  for (const result of workloadResults) {
    const key = `${result.recipeId}\u241F${result.environmentId}`;
    const bucket = grouped.get(key) ?? [];
    bucket.push(result);
    grouped.set(key, bucket);
  }

  const outputs: DerivedResultReadyRecord[] = [];
  for (const results of grouped.values()) {
    const byClass = new Map<string, number[]>();
    for (const result of results) {
      if (result.contentClass == null || result.plTotal == null) continue;
      const bucket = byClass.get(result.contentClass) ?? [];
      bucket.push(result.plTotal);
      byClass.set(result.contentClass, bucket);
    }

    const classScores: number[] = [];
    for (const contentClass of context.generalPolicy.requiredContentClasses) {
      const workloadScores = byClass.get(contentClass) ?? [];
      const classScore = canonicalGeometricMeanZeroToHundred(workloadScores);
      if (classScore == null) {
        classScores.length = 0;
        break;
      }
      classScores.push(classScore);
    }
    if (!classScores.length || classScores.length !== context.generalPolicy.requiredContentClasses.length) continue;

    const generalScore = canonicalGeometricMeanZeroToHundred(classScores);
    if (generalScore == null) continue;

    const first = results[0]!;
    outputs.push({
      kind: 'GENERAL',
      scopeKey: buildDerivedResultScopeKey('general', {
        workloadId: buildGeneralScopeWorkloadId(context.sourceSuiteVersion),
      }),
      benchmarkProtocolVersion: context.benchmarkProtocolVersion,
      sourceSuiteVersion: context.sourceSuiteVersion,
      formulaVersion: context.formulaVersion,
      scoreContextVersion: context.contextVersion,
      qualityModelId: context.qualityModelId,
      workloadId: buildGeneralScopeWorkloadId(context.sourceSuiteVersion),
      contentClass: null,
      recipeId: first.recipeId,
      environmentId: first.environmentId,
      acceptedRunCount: results.reduce((sum, result) => sum + result.acceptedRunCount, 0),
      suspectRunCount: results.reduce((sum, result) => sum + result.suspectRunCount, 0),
      rejectedRunCount: results.reduce((sum, result) => sum + result.rejectedRunCount, 0),
      repetitionCount: results.reduce((sum, result) => sum + result.repetitionCount, 0),
      centerEncodeFps: null,
      centerRealTimeRatio: null,
      centerVideoBitrateBps: null,
      centerFileSizeBytes: null,
      centerVmafMean: null,
      centerVmafP5: null,
      plQuality: null,
      plBitrate: null,
      plSpeed: null,
      plTotal: roundMetric(generalScore),
      evidenceTier: minimumEvidenceTier(results.map((result) => result.evidenceTier)),
      memberBenchmarkRunIds: [...new Set(results.flatMap((result) => result.memberBenchmarkRunIds))].sort(compareText),
      contributingWorkloadIds: [...new Set(results.map((result) => result.workloadId))].sort(compareText),
      recomputationSpec: buildDerivedResultRecomputationSpec({
        protocolVersion: context.benchmarkProtocolVersion,
        sourceSuiteVersion: context.sourceSuiteVersion,
        workloadId: buildGeneralScopeWorkloadId(context.sourceSuiteVersion),
        recipeFingerprint: first.recomputationSpec.recipeFingerprint,
        environmentFingerprint: first.recomputationSpec.environmentFingerprint,
        formulaVersion: context.formulaVersion,
        scoreContextVersion: context.contextVersion,
        qualityModelId: context.qualityModelId,
        scopeKey: buildDerivedResultScopeKey('general', {
          workloadId: buildGeneralScopeWorkloadId(context.sourceSuiteVersion),
        }),
        includedStatuses,
        aggregatorVersion,
        selectedAnalysisIds: [],
        analysisWorkerVersions: [],
      }),
    });
  }

  return outputs.sort((left, right) =>
    compareText(left.recipeId, right.recipeId)
    || compareText(left.environmentId, right.environmentId)
    || compareText(left.scopeKey, right.scopeKey));
}

export function recomputeReferenceScores(
  evidence: readonly RetainedAnalysisRecord[],
  context: ReferenceContext,
  options: RecomputeReferenceScoresOptions = {},
): RecomputeReferenceScoresResult {
  const includedStatuses = normalizeIncludedStatuses(options.includedStatuses);
  const aggregatorVersion = normalizeText(
    options.aggregatorVersion ?? DEFAULT_REFERENCE_CONTEXT_AGGREGATOR_VERSION,
    'aggregatorVersion',
  );
  const scoreContextIndex = buildScoreContextIndex(context);
  const filtered = evidence
    .map((record) => {
      const normalizedStatus = normalizeBenchmarkStatus(record.benchmarkRunStatus);
      if (!normalizedStatus || !includedStatuses.includes(normalizedStatus)) return null;
      if (record.benchmarkProtocolVersion !== context.benchmarkProtocolVersion) return null;
      if (record.sourceSuiteVersion !== context.sourceSuiteVersion) return null;
      if (record.qualityModelId !== context.qualityModelId) return null;
      const scoreContext = scoreContextIndex.get(record.workloadId);
      if (!scoreContext) return null;
      if (normalizeText(record.contentClass, 'contentClass') !== scoreContext.contentClass) return null;
      return {
        ...record,
        normalizedStatus,
        scoreContext,
      };
    })
    .filter((record): record is FilteredEvidence => record != null)
    .sort((left, right) =>
      compareText(left.recipeId, right.recipeId)
      || compareText(left.environmentId, right.environmentId)
      || compareText(left.workloadId, right.workloadId)
      || compareText(left.benchmarkRunId, right.benchmarkRunId));

  const grouped = new Map<string, FilteredEvidence[]>();
  for (const record of filtered) {
    const key = `${record.recipeId}\u241F${record.environmentId}\u241F${record.workloadId}`;
    const bucket = grouped.get(key) ?? [];
    bucket.push(record);
    grouped.set(key, bucket);
  }

  const workloadResults = [...grouped.values()]
    .map((runs) => buildWorkloadResult(
      runs,
      runs[0]!.scoreContext,
      context,
      aggregatorVersion,
      includedStatuses,
    ))
    .filter((result): result is DerivedResultReadyRecord => result != null)
    .sort((left, right) =>
      compareText(left.recipeId, right.recipeId)
      || compareText(left.environmentId, right.environmentId)
      || compareText(left.workloadId, right.workloadId));

  return {
    scoreContexts: [...scoreContextIndex.values()].sort((left, right) => compareText(left.workloadId, right.workloadId)),
    derivedResults: [
      ...workloadResults,
      ...buildGeneralResults(workloadResults, context, aggregatorVersion, includedStatuses),
    ],
  };
}

function buildGeneralDerivedResultFromWorkloadEvidence(input: {
  generalScoreContextId: string;
  benchmarkProtocolId: string;
  protocolVersion: string;
  sourceSuiteVersion: string;
  formulaVersion: string;
  scoreContextVersion: string;
  qualityModelId: string;
  recipeId: string;
  recipeFingerprint: string;
  environmentId: string;
  environmentFingerprint: string;
  requiredContentClasses: readonly string[];
  workloadResults: ReadonlyArray<{
    derivedResultId: string;
    workloadId: string;
    contentClass: string;
    acceptedRunCount: number;
    suspectRunCount: number;
    rejectedRunCount: number;
    invalidRunCount: number;
    repetitionCount: number;
    plTotal: number | null;
    confidenceLower: number | null;
    confidenceUpper: number | null;
    evidenceTier: EvidenceTier;
    memberAnalysisMembers: ReadonlyArray<{ benchmarkRunId: string; qualityAnalysisId: string }>;
  }>;
}): BuiltGeneralDerivedResult | null {
  const byClass = new Map<string, Array<(typeof input.workloadResults)[number]>>();
  for (const contentClass of input.requiredContentClasses) {
    byClass.set(contentClass, []);
  }
  for (const record of input.workloadResults) {
    const bucket = byClass.get(record.contentClass);
    if (bucket) bucket.push(record);
  }

  const classScores: number[] = [];
  const lowerScores: number[] = [];
  const upperScores: number[] = [];
  const contributingWorkloadIds: string[] = [];
  const contributingDerivedResultIds: string[] = [];
  const tiers: EvidenceTier[] = [];
  const memberAnalysisMap = new Map<string, { benchmarkRunId: string; qualityAnalysisId: string }>();

  for (const contentClass of input.requiredContentClasses) {
    const classResults = byClass.get(contentClass) ?? [];
    const classScore = canonicalGeometricMeanZeroToHundred(
      classResults.map((record) => record.plTotal).filter((value): value is number => value != null),
    );
    if (classScore == null) return null;
    classScores.push(classScore);
    for (const record of classResults) {
      if (record.confidenceLower != null && record.confidenceLower > 0) lowerScores.push(record.confidenceLower);
      if (record.confidenceUpper != null && record.confidenceUpper > 0) upperScores.push(record.confidenceUpper);
      tiers.push(record.evidenceTier);
      contributingWorkloadIds.push(record.workloadId);
      contributingDerivedResultIds.push(record.derivedResultId);
      for (const member of record.memberAnalysisMembers) {
        memberAnalysisMap.set(member.qualityAnalysisId, member);
      }
    }
  }

  const plTotal = canonicalGeometricMeanZeroToHundred(classScores);
  if (plTotal == null) return null;
  const confidenceLower = lowerScores.length === input.requiredContentClasses.length
    ? canonicalGeometricMeanZeroToHundred(lowerScores)
    : null;
  const confidenceUpper = upperScores.length === input.requiredContentClasses.length
    ? canonicalGeometricMeanZeroToHundred(upperScores)
    : null;
  const scopeKey = buildDerivedResultScopeKey('general', {
    workloadId: buildGeneralScopeWorkloadId(input.sourceSuiteVersion),
  });

  const evidenceSummary = {
    aggregation: GENERAL_PL_WEIGHTING,
    sourceRecordKind: 'persisted-workload-derived-results',
    requiredContentClasses: input.requiredContentClasses,
    coveredContentClasses: [...new Set(input.workloadResults.map((record) => record.contentClass))].sort(compareText),
    sourceDerivedResultIds: [...new Set(contributingDerivedResultIds)].sort(compareText),
    sourceWorkloadIds: [...new Set(contributingWorkloadIds)].sort(compareText),
    coverageComplete: true,
  };

  const confidenceIntervals = {
    plTotal: {
      lower: confidenceLower,
      upper: confidenceUpper,
      width: confidenceLower != null && confidenceUpper != null ? confidenceUpper - confidenceLower : null,
      confidenceLevel: 0.95,
      method: confidenceLower != null && confidenceUpper != null ? 'derived-geometric-mean' : 'unavailable',
    },
    plQuality: buildUnavailableMetricInterval(0.95),
    plBitrate: buildUnavailableMetricInterval(0.95),
    plSpeed: buildUnavailableMetricInterval(0.95),
    vmafMean: buildUnavailableMetricInterval(0.95),
    vmafP5: buildUnavailableMetricInterval(0.95),
    encodeFps: buildUnavailableMetricInterval(0.95),
    realTimeRatio: buildUnavailableMetricInterval(0.95),
    videoBitrateBps: buildUnavailableMetricInterval(0.95),
    fileSizeBytes: buildUnavailableMetricInterval(0.95),
  };

  const dispersion = {
    plTotal: buildDispersion(classScores),
    plQuality: { sampleCount: 0, median: null, minimum: null, maximum: null, q1: null, q3: null, iqr: null },
    plBitrate: { sampleCount: 0, median: null, minimum: null, maximum: null, q1: null, q3: null, iqr: null },
    plSpeed: { sampleCount: 0, median: null, minimum: null, maximum: null, q1: null, q3: null, iqr: null },
    vmafMean: { sampleCount: 0, median: null, minimum: null, maximum: null, q1: null, q3: null, iqr: null },
    vmafP5: { sampleCount: 0, median: null, minimum: null, maximum: null, q1: null, q3: null, iqr: null },
    encodeFps: { sampleCount: 0, median: null, minimum: null, maximum: null, q1: null, q3: null, iqr: null },
    realTimeRatio: { sampleCount: 0, median: null, minimum: null, maximum: null, q1: null, q3: null, iqr: null },
    videoBitrateBps: { sampleCount: 0, median: null, minimum: null, maximum: null, q1: null, q3: null, iqr: null },
    fileSizeBytes: { sampleCount: 0, median: null, minimum: null, maximum: null, q1: null, q3: null, iqr: null },
  };

  const derivedResult: DerivedResultPersistenceShape = {
    kind: 'GENERAL',
    scopeKey,
    benchmarkProtocolId: input.benchmarkProtocolId,
    workloadId: buildGeneralScopeWorkloadId(input.sourceSuiteVersion),
    testClipId: null,
    recipeId: input.recipeId,
    environmentId: input.environmentId,
    scoreContextId: input.generalScoreContextId,
    aggregatorVersion: DEFAULT_REFERENCE_CONTEXT_AGGREGATOR_VERSION,
    acceptedRunCount: input.workloadResults.reduce((sum, record) => sum + record.acceptedRunCount, 0),
    suspectRunCount: input.workloadResults.reduce((sum, record) => sum + record.suspectRunCount, 0),
    rejectedRunCount: input.workloadResults.reduce((sum, record) => sum + record.rejectedRunCount, 0),
    invalidRunCount: input.workloadResults.reduce((sum, record) => sum + record.invalidRunCount, 0),
    repetitionCount: input.workloadResults.reduce((sum, record) => sum + record.repetitionCount, 0),
    centerEncodeFps: null,
    centerRealTimeRatio: null,
    centerVideoBitrateBps: null,
    centerFileSizeBytes: null,
    centerVmafMean: null,
    centerVmafP5: null,
    plQuality: null,
    plBitrate: null,
    plSpeed: null,
    plTotal: roundMetric(plTotal),
    confidenceLower: roundMetric(confidenceLower),
    confidenceUpper: roundMetric(confidenceUpper),
    evidenceTier: minimumEvidenceTier(tiers),
    evidenceSummary: toCanonicalJsonValue(evidenceSummary) as never,
    confidenceIntervals: toCanonicalJsonValue(confidenceIntervals) as never,
    dispersion: toCanonicalJsonValue(dispersion) as never,
    recomputationSpec: buildDerivedResultRecomputationSpec({
      protocolVersion: input.protocolVersion,
      sourceSuiteVersion: input.sourceSuiteVersion,
      workloadId: buildGeneralScopeWorkloadId(input.sourceSuiteVersion),
      recipeFingerprint: input.recipeFingerprint,
      environmentFingerprint: input.environmentFingerprint,
      formulaVersion: input.formulaVersion,
      scoreContextVersion: input.scoreContextVersion,
      qualityModelId: input.qualityModelId,
      scopeKey,
      includedStatuses: ['accepted', 'suspect', 'rejected'],
      aggregatorVersion: DEFAULT_REFERENCE_CONTEXT_AGGREGATOR_VERSION,
      selectedAnalysisIds: [...new Set(input.workloadResults.flatMap((record) => record.memberAnalysisMembers.map((member) => member.qualityAnalysisId)))].sort(compareText),
      analysisWorkerVersions: [],
    }),
  };

  return {
    derivedResult,
    members: [...memberAnalysisMap.values()].sort((left, right) => compareText(left.qualityAnalysisId, right.qualityAnalysisId)),
  };
}

function requiredContentClassesFromGeneralReferenceFrontier(
  value: Prisma.JsonValue | null,
  fallbackSuiteVersion: string,
): readonly string[] {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const generalPolicy = (value as Record<string, unknown>).generalPolicy;
    if (generalPolicy && typeof generalPolicy === 'object' && !Array.isArray(generalPolicy)) {
      const required = (generalPolicy as Record<string, unknown>).requiredContentClasses;
      if (Array.isArray(required) && required.every((entry) => typeof entry === 'string')) {
        return [...required].map((entry) => normalizeText(entry, 'requiredContentClasses')).sort(compareText);
      }
    }
  }
  const manifest = loadAuthoritativeSuiteManifest();
  if (manifest.suiteVersion !== fallbackSuiteVersion) {
    throw new Error(`General score context is missing required content classes for suite ${fallbackSuiteVersion}`);
  }
  return [...manifest.requiredContentClasses].sort(compareText);
}

export async function persistGeneralDerivedResultFromWorkloadEvidence(
  client: PersistGeneralDerivedResultClient,
  options: PersistGeneralDerivedResultOptions,
): Promise<string | null> {
  const generalScoreContext = await client.scoreContext.findFirst({
    where: {
      benchmarkProtocolId: options.benchmarkProtocolId,
      formulaVersion: options.formulaVersion,
      contextVersion: options.contextVersion,
      workloadId: buildGeneralScopeWorkloadId(options.sourceSuiteVersion),
      qualityModelId: options.qualityModelId,
    },
  });
  if (!generalScoreContext) return null;

  const workloadResults = await client.derivedResult.findMany({
    where: {
      kind: 'WORKLOAD',
      benchmarkProtocolId: options.benchmarkProtocolId,
      recipeId: options.recipeId,
      environmentId: options.environmentId,
      scoreContext: {
        contextVersion: options.contextVersion,
        qualityModelId: options.qualityModelId,
      },
      acceptedRunCount: { gt: 0 },
    },
    include: {
      members: {
        select: {
          benchmarkRunId: true,
          qualityAnalysisId: true,
        },
      },
      testClip: true,
    },
    orderBy: [
      { workloadId: 'asc' },
      { id: 'asc' },
    ],
  });

  const requiredContentClasses = requiredContentClassesFromGeneralReferenceFrontier(
    generalScoreContext.referenceFrontier,
    options.sourceSuiteVersion,
  );

  const rebuilt = buildGeneralDerivedResultFromWorkloadEvidence({
    generalScoreContextId: generalScoreContext.id,
    benchmarkProtocolId: options.benchmarkProtocolId,
    protocolVersion: options.protocolVersion,
    sourceSuiteVersion: options.sourceSuiteVersion,
    formulaVersion: options.formulaVersion,
    scoreContextVersion: options.contextVersion,
    qualityModelId: options.qualityModelId,
    recipeId: options.recipeId,
    recipeFingerprint: options.recipeFingerprint,
    environmentId: options.environmentId,
    environmentFingerprint: options.environmentFingerprint,
    requiredContentClasses,
    workloadResults: workloadResults
      .map((row) => ({
        derivedResultId: row.id,
        workloadId: row.workloadId,
        contentClass: row.testClip?.contentClass ?? '',
        acceptedRunCount: row.acceptedRunCount,
        suspectRunCount: row.suspectRunCount,
        rejectedRunCount: row.rejectedRunCount,
        invalidRunCount: row.invalidRunCount,
        repetitionCount: row.repetitionCount,
        plTotal: row.plTotal,
        confidenceLower: row.confidenceLower,
        confidenceUpper: row.confidenceUpper,
        evidenceTier: row.evidenceTier,
        memberAnalysisMembers: row.members.map((member) => ({
          benchmarkRunId: member.benchmarkRunId,
          qualityAnalysisId: member.qualityAnalysisId,
        })),
      }))
      .filter((row) => row.contentClass.length > 0),
  });
  if (!rebuilt) return null;

  return persistDerivedResultRecord(client, rebuilt.derivedResult, rebuilt.members);
}
