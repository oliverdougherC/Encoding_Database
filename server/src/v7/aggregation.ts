import {
  buildAggregationCompatibilityKey,
  buildDerivedResultRecomputationSpec,
  buildDerivedResultScopeKey,
  sha256Hex,
  type JsonObject,
  type DerivedResultRecomputationSpec,
} from './persistence.js';
import {
  computePlScoreV7,
  type PlScoreV7Context,
} from '../plScore.js';
import type {
  Prisma,
  PrismaClient,
} from '@prisma/client';

export const DERIVED_RESULT_AGGREGATOR_VERSION = 'derived-result-aggregation/v2-cluster-bootstrap' as const;
export const DEFAULT_BOOTSTRAP_ITERATIONS = 2000 as const;
export const DEFAULT_BOOTSTRAP_CONFIDENCE_LEVEL = 0.95 as const;
export const MIN_BOOTSTRAP_SAMPLE_SIZE = 2 as const;

export type EvidenceTier = 'PROVISIONAL' | 'LOW' | 'MEDIUM' | 'HIGH';
export type AggregateRunStatus = 'accepted' | 'suspect' | 'rejected' | 'invalid';
export type DerivedResultKind = 'clip' | 'workload' | 'general';
export type KeyMetricName =
  | 'plTotal'
  | 'plQuality'
  | 'plBitrate'
  | 'plSpeed'
  | 'vmafMean'
  | 'vmafP5'
  | 'encodeFps'
  | 'realTimeRatio'
  | 'videoBitrateBps'
  | 'fileSizeBytes';

export interface EvidenceTierRule {
  minimumAcceptedRuns: number;
  minimumIndependentSources: number;
  maximumPlConfidenceIntervalWidth: number | null;
}

export interface RecommendationEvidencePolicy {
  policyVersion: string;
  policyStatus: 'PROVISIONAL_UNCALIBRATED' | 'CALIBRATED';
  defaultRecommendationMinimumTier: EvidenceTier;
  tiers: {
    low: EvidenceTierRule;
    medium: EvidenceTierRule;
    high: EvidenceTierRule;
  };
}

export interface AggregateIdentity {
  kind: DerivedResultKind;
  benchmarkProtocolId: string;
  protocolVersion: string;
  sourceSuiteVersion: string;
  workloadId: string;
  testClipId?: string | null;
  recipeId: string;
  recipeFingerprint: string;
  environmentId: string;
  environmentFingerprint: string;
  scoreContextId: string;
  scoreContextVersion: string;
  qualityModelId: string;
  formulaVersion: string;
}

export interface AggregateRunObservation {
  benchmarkRunId: string;
  status: AggregateRunStatus;
  encodeFps: number | null;
  sourceFps: number | null;
  videoBitrateBps: number | null;
  fileSizeBytes: number | null;
  vmafMean: number | null;
  vmafP5: number | null;
  contributorKey?: string | null;
  machineKey?: string | null;
  campaignId?: string | null;
  repetitionGroupId?: string | null;
}

export interface BootstrapPolicy {
  iterations?: number;
  confidenceLevel?: number;
  seed?: string | null;
  minSampleSize?: number;
}

export interface MetricInterval {
  lower: number | null;
  upper: number | null;
  width: number | null;
  confidenceLevel: number;
  method: 'cluster-bootstrap-percentile' | 'unavailable';
}

export interface DispersionSummary {
  sampleCount: number;
  median: number | null;
  minimum: number | null;
  maximum: number | null;
  q1: number | null;
  q3: number | null;
  iqr: number | null;
}

export interface DerivedResultPersistenceShape {
  kind: 'CLIP' | 'WORKLOAD' | 'GENERAL';
  scopeKey: string;
  benchmarkProtocolId: string;
  workloadId: string;
  testClipId: string | null;
  recipeId: string;
  environmentId: string;
  scoreContextId: string;
  aggregatorVersion: string;
  acceptedRunCount: number;
  suspectRunCount: number;
  rejectedRunCount: number;
  invalidRunCount: number;
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
  confidenceLower: number | null;
  confidenceUpper: number | null;
  evidenceTier: EvidenceTier;
  evidenceSummary: JsonObject;
  confidenceIntervals: JsonObject;
  dispersion: JsonObject;
  recomputationSpec: DerivedResultRecomputationSpec;
}

export interface RebuildDerivedResultAggregateInput {
  identity: AggregateIdentity;
  scoreContext: PlScoreV7Context;
  evidencePolicy: RecommendationEvidencePolicy;
  runs: ReadonlyArray<AggregateRunObservation>;
  bootstrap?: BootstrapPolicy;
  selectedAnalysisIds?: ReadonlyArray<string>;
  analysisWorkerVersions?: ReadonlyArray<string>;
}

export interface RebuildDerivedResultAggregateOutput {
  compatibilityKey: string;
  scopeKey: string;
  derivedResult: DerivedResultPersistenceShape;
  members: ReadonlyArray<string>;
  evidence: {
    policyVersion: string;
    policyStatus: 'PROVISIONAL_UNCALIBRATED' | 'CALIBRATED';
    tier: EvidenceTier;
    eligibleForDefaultRecommendation: boolean;
    acceptedRunCount: number;
    plEligibleAcceptedRunCount: number;
    suspectRunCount: number;
    rejectedRunCount: number;
    invalidRunCount: number;
    repetitionCount: number;
    independentSourceCount: number;
    machineCount: number;
    contributorCount: number;
    bootstrapSeed: string;
    bootstrapIterations: number;
    confidenceLevel: number;
  };
  confidenceIntervals: Record<KeyMetricName, MetricInterval>;
  dispersion: Record<KeyMetricName, DispersionSummary>;
  rebuild: {
    selectedRunIds: ReadonlyArray<string>;
    acceptedRunIds: ReadonlyArray<string>;
    plEligibleAcceptedRunIds: ReadonlyArray<string>;
    suspectRunIds: ReadonlyArray<string>;
    rejectedRunIds: ReadonlyArray<string>;
    invalidRunIds: ReadonlyArray<string>;
    recomputationSpec: DerivedResultRecomputationSpec;
  };
}

export interface AggregateAnalysisRecord {
  qualityAnalysisId: string;
  analysisWorkerVersion: string;
  benchmarkRunId: string;
  benchmarkRunStatus: 'ACCEPTED' | 'SUSPECT' | 'REJECTED' | 'INVALID' | 'PENDING';
  qualityAnalysisStatus: 'COMPLETE' | 'SUSPECT' | 'REJECTED' | 'FAILED' | 'PENDING';
  encodeFps: number | null;
  sourceFps: number | null;
  videoBitrateBps: number | null;
  fileSizeBytes: number | null;
  vmafMean: number | null;
  vmafP5: number | null;
  contributorKey?: string | null;
  machineKey?: string | null;
  campaignId?: string | null;
  repetitionGroupId?: string | null;
}

export interface RebuildDerivedResultAggregateFromAnalysesInput
  extends Omit<RebuildDerivedResultAggregateInput, 'runs'> {
  analyses: ReadonlyArray<AggregateAnalysisRecord>;
}

export interface PersistedDerivedResultAggregate extends RebuildDerivedResultAggregateOutput {
  derivedResultId: string;
}

type NumericMetricSnapshot = {
  vmafMean: number | null;
  vmafP5: number | null;
  encodeFps: number | null;
  sourceFps: number | null;
  realTimeRatio: number | null;
  videoBitrateBps: number | null;
  fileSizeBytes: number | null;
  plQuality: number | null;
  plBitrate: number | null;
  plSpeed: number | null;
  plTotal: number | null;
};

type CanonicalAcceptedRun = AggregateRunObservation & {
  benchmarkRunId: string;
  contributorKey: string | null;
  machineKey: string | null;
  campaignId: string | null;
  repetitionGroupId: string | null;
};

const TIER_ORDER: Record<EvidenceTier, number> = {
  PROVISIONAL: 0,
  LOW: 1,
  MEDIUM: 2,
  HIGH: 3,
};

export const DEFAULT_RECOMMENDATION_EVIDENCE_POLICY: RecommendationEvidencePolicy = {
  policyVersion: 'recommendation-evidence/provisional-pre-calibration-v1',
  policyStatus: 'PROVISIONAL_UNCALIBRATED',
  defaultRecommendationMinimumTier: 'LOW',
  tiers: {
    low: {
      minimumAcceptedRuns: 2,
      minimumIndependentSources: 2,
      maximumPlConfidenceIntervalWidth: null,
    },
    medium: {
      minimumAcceptedRuns: 3,
      minimumIndependentSources: 2,
      maximumPlConfidenceIntervalWidth: 8,
    },
    high: {
      minimumAcceptedRuns: 5,
      minimumIndependentSources: 3,
      maximumPlConfidenceIntervalWidth: 4,
    },
  },
};

function normalizeFiniteNumber(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function requireText(value: string, fieldName: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new Error(`${fieldName} is required`);
  }
  return trimmed;
}

function ensurePositiveInteger(value: number | undefined, fieldName: string, fallback: number): number {
  const candidate = value ?? fallback;
  if (!Number.isInteger(candidate) || candidate <= 0) {
    throw new Error(`${fieldName} must be a positive integer`);
  }
  return candidate;
}

function ensureConfidenceLevel(value: number | undefined): number {
  const candidate = value ?? DEFAULT_BOOTSTRAP_CONFIDENCE_LEVEL;
  if (!(candidate > 0 && candidate < 1)) {
    throw new Error('confidenceLevel must be between 0 and 1');
  }
  return candidate;
}

function normalizeEvidencePolicy(policy: RecommendationEvidencePolicy): RecommendationEvidencePolicy {
  const normalized: RecommendationEvidencePolicy = {
    policyVersion: requireText(policy.policyVersion, 'policyVersion'),
    policyStatus: policy.policyStatus,
    defaultRecommendationMinimumTier: policy.defaultRecommendationMinimumTier,
    tiers: {
      low: normalizeEvidenceTierRule(policy.tiers.low, 'low'),
      medium: normalizeEvidenceTierRule(policy.tiers.medium, 'medium'),
      high: normalizeEvidenceTierRule(policy.tiers.high, 'high'),
    },
  };

  if (TIER_ORDER[normalized.defaultRecommendationMinimumTier] < TIER_ORDER.LOW) {
    throw new Error('defaultRecommendationMinimumTier cannot be below LOW');
  }
  if (!['PROVISIONAL_UNCALIBRATED', 'CALIBRATED'].includes(normalized.policyStatus)) {
    throw new Error('policyStatus must be PROVISIONAL_UNCALIBRATED or CALIBRATED');
  }

  return normalized;
}

function normalizeEvidenceTierRule(rule: EvidenceTierRule, label: 'low' | 'medium' | 'high'): EvidenceTierRule {
  if (!Number.isInteger(rule.minimumAcceptedRuns) || rule.minimumAcceptedRuns < 1) {
    throw new Error(`${label}.minimumAcceptedRuns must be a positive integer`);
  }
  if (!Number.isInteger(rule.minimumIndependentSources) || rule.minimumIndependentSources < 1) {
    throw new Error(`${label}.minimumIndependentSources must be a positive integer`);
  }
  if (rule.maximumPlConfidenceIntervalWidth != null && (!Number.isFinite(rule.maximumPlConfidenceIntervalWidth) || rule.maximumPlConfidenceIntervalWidth < 0)) {
    throw new Error(`${label}.maximumPlConfidenceIntervalWidth must be null or a non-negative finite number`);
  }
  return {
    minimumAcceptedRuns: rule.minimumAcceptedRuns,
    minimumIndependentSources: rule.minimumIndependentSources,
    maximumPlConfidenceIntervalWidth: rule.maximumPlConfidenceIntervalWidth,
  };
}

function quantileLinear(sorted: readonly number[], quantile: number): number | null {
  if (!sorted.length) return null;
  if (sorted.length === 1) return sorted[0]!;
  const clamped = Math.max(0, Math.min(1, quantile));
  const index = (sorted.length - 1) * clamped;
  const lowerIndex = Math.floor(index);
  const upperIndex = Math.ceil(index);
  if (lowerIndex === upperIndex) {
    return sorted[lowerIndex]!;
  }
  const weight = index - lowerIndex;
  return sorted[lowerIndex]! + ((sorted[upperIndex]! - sorted[lowerIndex]!) * weight);
}

function median(values: readonly number[]): number | null {
  return quantileLinear(values, 0.5);
}

function stableNumericValues(values: ReadonlyArray<number | null | undefined>): number[] {
  return values
    .map((value) => normalizeFiniteNumber(value))
    .filter((value): value is number => value != null)
    .sort((left, right) => left - right);
}

function buildDispersionSummary(values: ReadonlyArray<number | null | undefined>): DispersionSummary {
  const sorted = stableNumericValues(values);
  const q1 = quantileLinear(sorted, 0.25);
  const medianValue = quantileLinear(sorted, 0.5);
  const q3 = quantileLinear(sorted, 0.75);
  return {
    sampleCount: sorted.length,
    median: medianValue,
    minimum: sorted[0] ?? null,
    maximum: sorted[sorted.length - 1] ?? null,
    q1,
    q3,
    iqr: q1 == null || q3 == null ? null : q3 - q1,
  };
}

function createSeededPrng(seedMaterial: string): () => number {
  const hash = sha256Hex(seedMaterial);
  let a = Number.parseInt(hash.slice(0, 8), 16) >>> 0;
  let b = Number.parseInt(hash.slice(8, 16), 16) >>> 0;
  let c = Number.parseInt(hash.slice(16, 24), 16) >>> 0;
  let d = Number.parseInt(hash.slice(24, 32), 16) >>> 0;

  return () => {
    a >>>= 0;
    b >>>= 0;
    c >>>= 0;
    d >>>= 0;
    const t = (a + b + d) >>> 0;
    d = (d + 1) >>> 0;
    a = b ^ (b >>> 9);
    b = (c + (c << 3)) >>> 0;
    c = ((c << 21) | (c >>> 11)) >>> 0;
    c = (c + t) >>> 0;
    return (t >>> 0) / 4294967296;
  };
}

function runIndependentSourceKey(run: CanonicalAcceptedRun): string {
  // Repeats from one machine/campaign are a measurement cluster, not independent
  // evidence. Missing provenance is deliberately grouped as unknown rather than
  // promoted to one independent source per run.
  return `${run.machineKey ?? 'unknown-machine'}::${run.campaignId ?? 'unknown-campaign'}`;
}

function runRepetitionKey(run: CanonicalAcceptedRun): string {
  return run.repetitionGroupId ?? run.benchmarkRunId;
}

function collapseIndependentClusters(
  runs: ReadonlyArray<CanonicalAcceptedRun>,
): CanonicalAcceptedRun[] {
  const clusters = new Map<string, CanonicalAcceptedRun[]>();
  for (const run of runs) {
    const key = runIndependentSourceKey(run);
    const members = clusters.get(key) ?? [];
    members.push(run);
    clusters.set(key, members);
  }
  return [...clusters.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([clusterKey, members]) => ({
      benchmarkRunId: `cluster:${clusterKey}`,
      status: 'accepted',
      encodeFps: median(stableNumericValues(members.map((run) => run.encodeFps))),
      sourceFps: median(stableNumericValues(members.map((run) => run.sourceFps))),
      videoBitrateBps: median(stableNumericValues(members.map((run) => run.videoBitrateBps))),
      fileSizeBytes: median(stableNumericValues(members.map((run) => run.fileSizeBytes))),
      vmafMean: median(stableNumericValues(members.map((run) => run.vmafMean))),
      vmafP5: median(stableNumericValues(members.map((run) => run.vmafP5))),
      contributorKey: null,
      machineKey: members[0]?.machineKey ?? null,
      campaignId: members[0]?.campaignId ?? null,
      repetitionGroupId: clusterKey,
    }));
}

function canonicalizeRun(run: AggregateRunObservation): CanonicalAcceptedRun {
  return {
    ...run,
    benchmarkRunId: requireText(run.benchmarkRunId, 'benchmarkRunId'),
    contributorKey: run.contributorKey?.trim() || null,
    machineKey: run.machineKey?.trim() || null,
    campaignId: run.campaignId?.trim() || null,
    repetitionGroupId: run.repetitionGroupId?.trim() || null,
    encodeFps: normalizeFiniteNumber(run.encodeFps),
    sourceFps: normalizeFiniteNumber(run.sourceFps),
    videoBitrateBps: normalizeFiniteNumber(run.videoBitrateBps),
    fileSizeBytes: normalizeFiniteNumber(run.fileSizeBytes),
    vmafMean: normalizeFiniteNumber(run.vmafMean),
    vmafP5: normalizeFiniteNumber(run.vmafP5),
  };
}

function computeRunRealtimeRatio(run: Pick<CanonicalAcceptedRun, 'encodeFps' | 'sourceFps'>): number | null {
  if (run.encodeFps == null || run.sourceFps == null || run.encodeFps <= 0 || run.sourceFps <= 0) {
    return null;
  }
  return run.encodeFps / run.sourceFps;
}

function computeCenteredSnapshot(
  runs: ReadonlyArray<CanonicalAcceptedRun>,
  context: PlScoreV7Context,
): NumericMetricSnapshot {
  const vmafMean = median(stableNumericValues(runs.map((run) => run.vmafMean)));
  const vmafP5 = median(stableNumericValues(runs.map((run) => run.vmafP5)));
  const encodeFps = median(stableNumericValues(runs.map((run) => run.encodeFps)));
  const videoBitrateBps = median(stableNumericValues(runs.map((run) => run.videoBitrateBps)));
  const fileSizeBytes = median(stableNumericValues(runs.map((run) => run.fileSizeBytes)));
  const sourceFps = median(stableNumericValues(runs.map((run) => run.sourceFps)));
  const realtimeRatio = encodeFps != null && sourceFps != null && sourceFps > 0 ? encodeFps / sourceFps : null;
  const pl = computePlScoreV7({
    vmafMean,
    vmafP5,
    videoBitrateBps,
    encodeFps,
    sourceFps,
  }, context);

  return {
    vmafMean,
    vmafP5,
    encodeFps,
    sourceFps,
    realTimeRatio: realtimeRatio,
    videoBitrateBps,
    fileSizeBytes,
    plQuality: pl?.quality ?? null,
    plBitrate: pl?.bitrate ?? null,
    plSpeed: pl?.speed ?? null,
    plTotal: pl?.total ?? null,
  };
}

function buildMetricIntervals(
  snapshots: ReadonlyArray<NumericMetricSnapshot>,
  pointSnapshot: NumericMetricSnapshot,
  confidenceLevel: number,
): Record<KeyMetricName, MetricInterval> {
  return {
    plTotal: buildMetricInterval(snapshots.map((value) => value.plTotal), pointSnapshot.plTotal, confidenceLevel),
    plQuality: buildMetricInterval(snapshots.map((value) => value.plQuality), pointSnapshot.plQuality, confidenceLevel),
    plBitrate: buildMetricInterval(snapshots.map((value) => value.plBitrate), pointSnapshot.plBitrate, confidenceLevel),
    plSpeed: buildMetricInterval(snapshots.map((value) => value.plSpeed), pointSnapshot.plSpeed, confidenceLevel),
    vmafMean: buildMetricInterval(snapshots.map((value) => value.vmafMean), pointSnapshot.vmafMean, confidenceLevel),
    vmafP5: buildMetricInterval(snapshots.map((value) => value.vmafP5), pointSnapshot.vmafP5, confidenceLevel),
    encodeFps: buildMetricInterval(snapshots.map((value) => value.encodeFps), pointSnapshot.encodeFps, confidenceLevel),
    realTimeRatio: buildMetricInterval(snapshots.map((value) => value.realTimeRatio), pointSnapshot.realTimeRatio, confidenceLevel),
    videoBitrateBps: buildMetricInterval(snapshots.map((value) => value.videoBitrateBps), pointSnapshot.videoBitrateBps, confidenceLevel),
    fileSizeBytes: buildMetricInterval(snapshots.map((value) => value.fileSizeBytes), pointSnapshot.fileSizeBytes, confidenceLevel),
  };
}

function buildMetricInterval(
  values: ReadonlyArray<number | null | undefined>,
  pointValue: number | null,
  confidenceLevel: number,
): MetricInterval {
  const sorted = stableNumericValues(values);
  if (sorted.length === 0 || pointValue == null) {
    return {
      lower: null,
      upper: null,
      width: null,
      confidenceLevel,
      method: 'unavailable',
    };
  }
  const alpha = (1 - confidenceLevel) / 2;
  const lower = quantileLinear(sorted, alpha);
  const upper = quantileLinear(sorted, 1 - alpha);
  return {
    lower,
    upper,
    width: lower == null || upper == null ? null : upper - lower,
    confidenceLevel,
    method: 'cluster-bootstrap-percentile',
  };
}

function classifyEvidenceTier(
  policy: RecommendationEvidencePolicy,
  acceptedRunCount: number,
  independentSourceCount: number,
  plConfidenceWidth: number | null,
): EvidenceTier {
  if (independentSourceCount < 2 || plConfidenceWidth == null) return 'PROVISIONAL';
  let tier: EvidenceTier = 'PROVISIONAL';
  if (meetsEvidenceTierRule(policy.tiers.low, acceptedRunCount, independentSourceCount, plConfidenceWidth)) {
    tier = 'LOW';
  }
  if (meetsEvidenceTierRule(policy.tiers.medium, acceptedRunCount, independentSourceCount, plConfidenceWidth)) {
    tier = 'MEDIUM';
  }
  if (meetsEvidenceTierRule(policy.tiers.high, acceptedRunCount, independentSourceCount, plConfidenceWidth)) {
    tier = 'HIGH';
  }
  return tier;
}

function meetsEvidenceTierRule(
  rule: EvidenceTierRule,
  acceptedRunCount: number,
  independentSourceCount: number,
  plConfidenceWidth: number | null,
): boolean {
  if (acceptedRunCount < rule.minimumAcceptedRuns) return false;
  if (independentSourceCount < rule.minimumIndependentSources) return false;
  if (rule.maximumPlConfidenceIntervalWidth == null) return true;
  return plConfidenceWidth != null && plConfidenceWidth <= rule.maximumPlConfidenceIntervalWidth;
}

function buildDispersionSummaries(
  snapshots: ReadonlyArray<NumericMetricSnapshot>,
): Record<KeyMetricName, DispersionSummary> {
  return {
    plTotal: buildDispersionSummary(snapshots.map((value) => value.plTotal)),
    plQuality: buildDispersionSummary(snapshots.map((value) => value.plQuality)),
    plBitrate: buildDispersionSummary(snapshots.map((value) => value.plBitrate)),
    plSpeed: buildDispersionSummary(snapshots.map((value) => value.plSpeed)),
    vmafMean: buildDispersionSummary(snapshots.map((value) => value.vmafMean)),
    vmafP5: buildDispersionSummary(snapshots.map((value) => value.vmafP5)),
    encodeFps: buildDispersionSummary(snapshots.map((value) => value.encodeFps)),
    realTimeRatio: buildDispersionSummary(snapshots.map((value) => value.realTimeRatio)),
    videoBitrateBps: buildDispersionSummary(snapshots.map((value) => value.videoBitrateBps)),
    fileSizeBytes: buildDispersionSummary(snapshots.map((value) => value.fileSizeBytes)),
  };
}

function metricIntervalsToJson(
  intervals: Record<KeyMetricName, MetricInterval>,
): JsonObject {
  return Object.fromEntries(
    Object.entries(intervals).map(([key, interval]) => [key, {
      lower: interval.lower,
      upper: interval.upper,
      width: interval.width,
      confidenceLevel: interval.confidenceLevel,
      method: interval.method,
    }]),
  ) as JsonObject;
}

function dispersionToJson(
  dispersion: Record<KeyMetricName, DispersionSummary>,
): JsonObject {
  return Object.fromEntries(
    Object.entries(dispersion).map(([key, summary]) => [key, {
      sampleCount: summary.sampleCount,
      median: summary.median,
      minimum: summary.minimum,
      maximum: summary.maximum,
      q1: summary.q1,
      q3: summary.q3,
      iqr: summary.iqr,
    }]),
  ) as JsonObject;
}

function evidenceSummaryToJson(
  evidence: RebuildDerivedResultAggregateOutput['evidence'],
): JsonObject {
  return {
    policyVersion: evidence.policyVersion,
    policyStatus: evidence.policyStatus,
    tier: evidence.tier,
    eligibleForDefaultRecommendation: evidence.eligibleForDefaultRecommendation,
    acceptedRunCount: evidence.acceptedRunCount,
    plEligibleAcceptedRunCount: evidence.plEligibleAcceptedRunCount,
    suspectRunCount: evidence.suspectRunCount,
    rejectedRunCount: evidence.rejectedRunCount,
    invalidRunCount: evidence.invalidRunCount,
    repetitionCount: evidence.repetitionCount,
    independentSourceCount: evidence.independentSourceCount,
    machineCount: evidence.machineCount,
    contributorCount: evidence.contributorCount,
    bootstrapSeed: evidence.bootstrapSeed,
    bootstrapIterations: evidence.bootstrapIterations,
    confidenceLevel: evidence.confidenceLevel,
  };
}

function toPrismaJson(value: unknown): Prisma.InputJsonValue {
  return value as unknown as Prisma.InputJsonValue;
}

function mapAnalysisStatus(record: AggregateAnalysisRecord): AggregateRunStatus | null {
  if (record.benchmarkRunStatus === 'PENDING') return null;
  if (record.benchmarkRunStatus === 'INVALID' || record.qualityAnalysisStatus === 'FAILED' || record.qualityAnalysisStatus === 'PENDING') {
    return 'invalid';
  }
  if (record.benchmarkRunStatus === 'REJECTED' || record.qualityAnalysisStatus === 'REJECTED') {
    return 'rejected';
  }
  if (record.benchmarkRunStatus === 'SUSPECT' || record.qualityAnalysisStatus === 'SUSPECT') {
    return 'suspect';
  }
  if (record.benchmarkRunStatus === 'ACCEPTED' && record.qualityAnalysisStatus === 'COMPLETE') {
    return 'accepted';
  }
  return null;
}

function buildAggregateRunObservation(
  record: AggregateAnalysisRecord,
): AggregateRunObservation | null {
  const status = mapAnalysisStatus(record);
  if (status == null) return null;
  return {
    benchmarkRunId: record.benchmarkRunId,
    status,
    encodeFps: record.encodeFps,
    sourceFps: record.sourceFps,
    videoBitrateBps: record.videoBitrateBps,
    fileSizeBytes: record.fileSizeBytes,
    vmafMean: record.vmafMean,
    vmafP5: record.vmafP5,
    contributorKey: record.contributorKey ?? null,
    machineKey: record.machineKey ?? null,
    campaignId: record.campaignId ?? null,
    repetitionGroupId: record.repetitionGroupId ?? null,
  };
}

export function buildAggregateRunObservationsFromAnalyses(
  analyses: ReadonlyArray<AggregateAnalysisRecord>,
): readonly AggregateRunObservation[] {
  return analyses
    .map(buildAggregateRunObservation)
    .filter((record): record is AggregateRunObservation => record != null)
    .sort((left, right) => left.benchmarkRunId.localeCompare(right.benchmarkRunId));
}

function enumKind(kind: DerivedResultKind): 'CLIP' | 'WORKLOAD' | 'GENERAL' {
  if (kind === 'clip') return 'CLIP';
  if (kind === 'workload') return 'WORKLOAD';
  return 'GENERAL';
}

function buildBootstrapSnapshots(
  runs: ReadonlyArray<CanonicalAcceptedRun>,
  context: PlScoreV7Context,
  iterations: number,
  seed: string,
): NumericMetricSnapshot[] {
  // Confidence intervals estimate between-cluster uncertainty. A single
  // machine/campaign cannot support that estimate, regardless of repeat count.
  if (runs.length < 2 || iterations < 1) return [];

  const prng = createSeededPrng(seed);
  const snapshots: NumericMetricSnapshot[] = [];
  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const sample: CanonicalAcceptedRun[] = [];
    for (let index = 0; index < runs.length; index += 1) {
      const sampledIndex = Math.floor(prng() * runs.length);
      sample.push(runs[sampledIndex]!);
    }
    snapshots.push(computeCenteredSnapshot(sample, context));
  }
  return snapshots;
}

export function rebuildDerivedResultAggregate(
  input: RebuildDerivedResultAggregateInput,
): RebuildDerivedResultAggregateOutput {
  const policy = normalizeEvidencePolicy(input.evidencePolicy);
  const identity = {
    benchmarkProtocolId: requireText(input.identity.benchmarkProtocolId, 'benchmarkProtocolId'),
    protocolVersion: requireText(input.identity.protocolVersion, 'protocolVersion'),
    sourceSuiteVersion: requireText(input.identity.sourceSuiteVersion, 'sourceSuiteVersion'),
    workloadId: requireText(input.identity.workloadId, 'workloadId'),
    testClipId: input.identity.testClipId?.trim() || null,
    recipeId: requireText(input.identity.recipeId, 'recipeId'),
    recipeFingerprint: requireText(input.identity.recipeFingerprint, 'recipeFingerprint'),
    environmentId: requireText(input.identity.environmentId, 'environmentId'),
    environmentFingerprint: requireText(input.identity.environmentFingerprint, 'environmentFingerprint'),
    scoreContextId: requireText(input.identity.scoreContextId, 'scoreContextId'),
    scoreContextVersion: requireText(input.identity.scoreContextVersion, 'scoreContextVersion'),
    qualityModelId: requireText(input.identity.qualityModelId, 'qualityModelId'),
    formulaVersion: requireText(input.identity.formulaVersion, 'formulaVersion'),
    kind: input.identity.kind,
  };

  const scopeKey = buildDerivedResultScopeKey(identity.kind, {
    workloadId: identity.workloadId,
    testClipId: identity.testClipId,
  });
  const compatibilityKey = buildAggregationCompatibilityKey({
    protocolVersion: identity.protocolVersion,
    sourceSuiteVersion: identity.sourceSuiteVersion,
    workloadId: identity.workloadId,
    recipeFingerprint: identity.recipeFingerprint,
    environmentFingerprint: identity.environmentFingerprint,
    formulaVersion: identity.formulaVersion,
    scoreContextVersion: identity.scoreContextVersion,
    qualityModelId: identity.qualityModelId,
  });

  const runs = [...input.runs]
    .map(canonicalizeRun)
    .sort((left, right) => left.benchmarkRunId.localeCompare(right.benchmarkRunId));

  const acceptedRuns = runs.filter((run) => run.status === 'accepted');
  const suspectRuns = runs.filter((run) => run.status === 'suspect');
  const rejectedRuns = runs.filter((run) => run.status === 'rejected');
  const invalidRuns = runs.filter((run) => run.status === 'invalid');
  const plEligibleAcceptedRuns = acceptedRuns.filter((run) => (
    run.vmafMean != null
    && run.vmafP5 != null
    && run.encodeFps != null
    && run.sourceFps != null
    && run.videoBitrateBps != null
  ));

  const independentClusters = collapseIndependentClusters(plEligibleAcceptedRuns);
  const pointSnapshot = computeCenteredSnapshot(independentClusters, input.scoreContext);
  const bootstrapIterations = independentClusters.length >= (input.bootstrap?.minSampleSize ?? MIN_BOOTSTRAP_SAMPLE_SIZE)
    ? ensurePositiveInteger(input.bootstrap?.iterations, 'iterations', DEFAULT_BOOTSTRAP_ITERATIONS)
    : 0;
  const confidenceLevel = ensureConfidenceLevel(input.bootstrap?.confidenceLevel);
  const bootstrapSeed = sha256Hex(JSON.stringify({
    aggregatorVersion: DERIVED_RESULT_AGGREGATOR_VERSION,
    compatibilityKey,
    scopeKey,
    policyVersion: policy.policyVersion,
    explicitSeed: input.bootstrap?.seed ?? null,
    acceptedRunIds: plEligibleAcceptedRuns.map((run) => run.benchmarkRunId),
    independentClusterKeys: independentClusters.map((run) => run.repetitionGroupId),
  }));
  const bootstrapSnapshots = buildBootstrapSnapshots(
    independentClusters,
    input.scoreContext,
    bootstrapIterations,
    bootstrapSeed,
  );
  const confidenceIntervals = buildMetricIntervals(bootstrapSnapshots, pointSnapshot, confidenceLevel);
  const dispersion = buildDispersionSummaries(plEligibleAcceptedRuns.map((run) => {
    const realtimeRatio = computeRunRealtimeRatio(run);
    const pl = computePlScoreV7({
      vmafMean: run.vmafMean,
      vmafP5: run.vmafP5,
      videoBitrateBps: run.videoBitrateBps,
      encodeFps: run.encodeFps,
      sourceFps: run.sourceFps,
    }, input.scoreContext);
    return {
      vmafMean: run.vmafMean,
      vmafP5: run.vmafP5,
      encodeFps: run.encodeFps,
      sourceFps: run.sourceFps,
      realTimeRatio: realtimeRatio,
      videoBitrateBps: run.videoBitrateBps,
      fileSizeBytes: run.fileSizeBytes,
      plQuality: pl?.quality ?? null,
      plBitrate: pl?.bitrate ?? null,
      plSpeed: pl?.speed ?? null,
      plTotal: pl?.total ?? null,
    };
  }));

  const acceptedRunIds = acceptedRuns.map((run) => run.benchmarkRunId);
  const repetitionCount = new Set(acceptedRuns.map(runRepetitionKey)).size;
  const independentSourceCount = collapseIndependentClusters(acceptedRuns).length;
  const machineCount = new Set(acceptedRuns.map((run) => run.machineKey ?? 'unknown-machine')).size;
  const contributorCount = new Set(acceptedRuns.map((run) => run.contributorKey ?? 'unknown-contributor')).size;
  const evidenceTier = classifyEvidenceTier(
    policy,
    acceptedRuns.length,
    independentSourceCount,
    confidenceIntervals.plTotal.width,
  );
  const eligibleForDefaultRecommendation = policy.policyStatus === 'CALIBRATED'
    && TIER_ORDER[evidenceTier] >= TIER_ORDER[policy.defaultRecommendationMinimumTier];
  const evidence = {
    policyVersion: policy.policyVersion,
    policyStatus: policy.policyStatus,
    tier: evidenceTier,
    eligibleForDefaultRecommendation,
    acceptedRunCount: acceptedRuns.length,
    plEligibleAcceptedRunCount: plEligibleAcceptedRuns.length,
    suspectRunCount: suspectRuns.length,
    rejectedRunCount: rejectedRuns.length,
    invalidRunCount: invalidRuns.length,
    repetitionCount,
    independentSourceCount,
    machineCount,
    contributorCount,
    bootstrapSeed,
    bootstrapIterations,
    confidenceLevel,
  } as const;
  const recomputationSpec = buildDerivedResultRecomputationSpec({
    protocolVersion: identity.protocolVersion,
    sourceSuiteVersion: identity.sourceSuiteVersion,
    workloadId: identity.workloadId,
    recipeFingerprint: identity.recipeFingerprint,
    environmentFingerprint: identity.environmentFingerprint,
    formulaVersion: identity.formulaVersion,
    scoreContextVersion: identity.scoreContextVersion,
    qualityModelId: identity.qualityModelId,
    scopeKey,
    includedStatuses: ['accepted', 'suspect', 'rejected'],
    aggregatorVersion: DERIVED_RESULT_AGGREGATOR_VERSION,
    selectedAnalysisIds: [...(input.selectedAnalysisIds ?? [])].sort((left, right) => left.localeCompare(right)),
    analysisWorkerVersions: [...new Set(input.analysisWorkerVersions ?? [])].sort((left, right) => left.localeCompare(right)),
  });

  return {
    compatibilityKey,
    scopeKey,
    derivedResult: {
      kind: enumKind(identity.kind),
      scopeKey,
      benchmarkProtocolId: identity.benchmarkProtocolId,
      workloadId: identity.workloadId,
      testClipId: identity.testClipId,
      recipeId: identity.recipeId,
      environmentId: identity.environmentId,
      scoreContextId: identity.scoreContextId,
      aggregatorVersion: DERIVED_RESULT_AGGREGATOR_VERSION,
      acceptedRunCount: acceptedRuns.length,
      suspectRunCount: suspectRuns.length,
      rejectedRunCount: rejectedRuns.length,
      invalidRunCount: invalidRuns.length,
      repetitionCount,
      centerEncodeFps: pointSnapshot.encodeFps,
      centerRealTimeRatio: pointSnapshot.realTimeRatio,
      centerVideoBitrateBps: pointSnapshot.videoBitrateBps,
      centerFileSizeBytes: pointSnapshot.fileSizeBytes,
      centerVmafMean: pointSnapshot.vmafMean,
      centerVmafP5: pointSnapshot.vmafP5,
      plQuality: pointSnapshot.plQuality,
      plBitrate: pointSnapshot.plBitrate,
      plSpeed: pointSnapshot.plSpeed,
      plTotal: pointSnapshot.plTotal,
      confidenceLower: confidenceIntervals.plTotal.lower,
      confidenceUpper: confidenceIntervals.plTotal.upper,
      evidenceTier,
      evidenceSummary: evidenceSummaryToJson(evidence),
      confidenceIntervals: metricIntervalsToJson(confidenceIntervals),
      dispersion: dispersionToJson(dispersion),
      recomputationSpec,
    },
    members: acceptedRunIds,
    evidence,
    confidenceIntervals,
    dispersion,
    rebuild: {
      selectedRunIds: runs.map((run) => run.benchmarkRunId),
      acceptedRunIds,
      plEligibleAcceptedRunIds: plEligibleAcceptedRuns.map((run) => run.benchmarkRunId),
      suspectRunIds: suspectRuns.map((run) => run.benchmarkRunId),
      rejectedRunIds: rejectedRuns.map((run) => run.benchmarkRunId),
      invalidRunIds: invalidRuns.map((run) => run.benchmarkRunId),
      recomputationSpec,
    },
  };
}

export function rebuildDerivedResultAggregateFromAnalyses(
  input: RebuildDerivedResultAggregateFromAnalysesInput,
): RebuildDerivedResultAggregateOutput {
  return rebuildDerivedResultAggregate({
    ...input,
    runs: buildAggregateRunObservationsFromAnalyses(input.analyses),
    selectedAnalysisIds: input.analyses.map((analysis) => analysis.qualityAnalysisId),
    analysisWorkerVersions: input.analyses.map((analysis) => analysis.analysisWorkerVersion),
  });
}

export type DerivedResultPersistenceClient = Pick<PrismaClient, '$transaction'> | Prisma.TransactionClient;

function buildDerivedResultUniqueWhere(
  derivedResult: DerivedResultPersistenceShape,
): Prisma.DerivedResultWhereUniqueInput {
  return {
    kind_benchmarkProtocolId_recipeId_environmentId_scoreContextId_scopeKey: {
      kind: derivedResult.kind,
      benchmarkProtocolId: derivedResult.benchmarkProtocolId,
      recipeId: derivedResult.recipeId,
      environmentId: derivedResult.environmentId,
      scoreContextId: derivedResult.scoreContextId,
      scopeKey: derivedResult.scopeKey,
    },
  };
}

function buildDerivedResultCreateInput(
  derivedResult: DerivedResultPersistenceShape,
): Prisma.DerivedResultCreateInput {
  return {
    kind: derivedResult.kind,
    scopeKey: derivedResult.scopeKey,
    aggregatorVersion: derivedResult.aggregatorVersion,
    acceptedRunCount: derivedResult.acceptedRunCount,
    suspectRunCount: derivedResult.suspectRunCount,
    rejectedRunCount: derivedResult.rejectedRunCount,
    invalidRunCount: derivedResult.invalidRunCount,
    repetitionCount: derivedResult.repetitionCount,
    centerEncodeFps: derivedResult.centerEncodeFps,
    centerRealTimeRatio: derivedResult.centerRealTimeRatio,
    centerVideoBitrateBps: derivedResult.centerVideoBitrateBps,
    centerFileSizeBytes: derivedResult.centerFileSizeBytes,
    centerVmafMean: derivedResult.centerVmafMean,
    centerVmafP5: derivedResult.centerVmafP5,
    plQuality: derivedResult.plQuality,
    plBitrate: derivedResult.plBitrate,
    plSpeed: derivedResult.plSpeed,
    plTotal: derivedResult.plTotal,
    confidenceLower: derivedResult.confidenceLower,
    confidenceUpper: derivedResult.confidenceUpper,
    evidenceTier: derivedResult.evidenceTier,
    evidenceSummary: toPrismaJson(derivedResult.evidenceSummary),
    confidenceIntervals: toPrismaJson(derivedResult.confidenceIntervals),
    dispersion: toPrismaJson(derivedResult.dispersion),
    recomputationSpec: toPrismaJson(derivedResult.recomputationSpec),
    benchmarkProtocol: { connect: { id: derivedResult.benchmarkProtocolId } },
    workloadId: derivedResult.workloadId,
    recipe: { connect: { id: derivedResult.recipeId } },
    environment: { connect: { id: derivedResult.environmentId } },
    scoreContext: { connect: { id: derivedResult.scoreContextId } },
    ...(derivedResult.testClipId == null ? {} : { testClip: { connect: { id: derivedResult.testClipId } } }),
  };
}

function buildDerivedResultUpdateInput(
  derivedResult: DerivedResultPersistenceShape,
): Prisma.DerivedResultUpdateInput {
  return {
    workloadId: derivedResult.workloadId,
    aggregatorVersion: derivedResult.aggregatorVersion,
    acceptedRunCount: derivedResult.acceptedRunCount,
    suspectRunCount: derivedResult.suspectRunCount,
    rejectedRunCount: derivedResult.rejectedRunCount,
    invalidRunCount: derivedResult.invalidRunCount,
    repetitionCount: derivedResult.repetitionCount,
    centerEncodeFps: derivedResult.centerEncodeFps,
    centerRealTimeRatio: derivedResult.centerRealTimeRatio,
    centerVideoBitrateBps: derivedResult.centerVideoBitrateBps,
    centerFileSizeBytes: derivedResult.centerFileSizeBytes,
    centerVmafMean: derivedResult.centerVmafMean,
    centerVmafP5: derivedResult.centerVmafP5,
    plQuality: derivedResult.plQuality,
    plBitrate: derivedResult.plBitrate,
    plSpeed: derivedResult.plSpeed,
    plTotal: derivedResult.plTotal,
    confidenceLower: derivedResult.confidenceLower,
    confidenceUpper: derivedResult.confidenceUpper,
    evidenceTier: derivedResult.evidenceTier,
    evidenceSummary: toPrismaJson(derivedResult.evidenceSummary),
    confidenceIntervals: toPrismaJson(derivedResult.confidenceIntervals),
    dispersion: toPrismaJson(derivedResult.dispersion),
    recomputationSpec: toPrismaJson(derivedResult.recomputationSpec),
    testClip: derivedResult.testClipId == null
      ? { disconnect: true }
      : { connect: { id: derivedResult.testClipId } },
  };
}

export async function persistDerivedResultRecord(
  client: DerivedResultPersistenceClient,
  derivedResult: DerivedResultPersistenceShape,
  members: ReadonlyArray<{ benchmarkRunId: string; qualityAnalysisId: string }>,
): Promise<string> {
  const write = async (tx: Prisma.TransactionClient): Promise<string> => {
    const persisted = await tx.derivedResult.upsert({
      where: buildDerivedResultUniqueWhere(derivedResult),
      create: buildDerivedResultCreateInput(derivedResult),
      update: buildDerivedResultUpdateInput(derivedResult),
    });
    await tx.derivedResultMember.deleteMany({
      where: { derivedResultId: persisted.id },
    });
    if (members.length > 0) {
      await tx.derivedResultMember.createMany({
        data: members.map(({ benchmarkRunId, qualityAnalysisId }) => ({
          derivedResultId: persisted.id,
          benchmarkRunId,
          qualityAnalysisId,
        })),
      });
    }
    return persisted.id;
  };

  return '$transaction' in client
    ? await client.$transaction((tx) => write(tx))
    : await write(client);
}

export async function persistDerivedResultAggregate(
  client: DerivedResultPersistenceClient,
  input: RebuildDerivedResultAggregateFromAnalysesInput,
): Promise<PersistedDerivedResultAggregate> {
  const rebuilt = rebuildDerivedResultAggregateFromAnalyses(input);

  const derivedResultId = await persistDerivedResultRecord(
    client,
    rebuilt.derivedResult,
    input.analyses
      .filter((analysis) => rebuilt.members.includes(analysis.benchmarkRunId))
      .map((analysis) => ({
        benchmarkRunId: analysis.benchmarkRunId,
        qualityAnalysisId: analysis.qualityAnalysisId,
      })),
  );

  return {
    ...rebuilt,
    derivedResultId,
  };
}
