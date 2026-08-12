import type { Prisma } from '@prisma/client';
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DEFAULT_ANALYZER_VERSION } from './artifacts.js';

export const PUBLIC_CORPUS_READ_MODEL_VERSION = 'v7-public-corpus-direct-read-model/v2' as const;

export type PublicCorpusScoringStatus =
  | 'PUBLIC'
  | 'UNSCORED_NO_PUBLIC_DERIVED_RESULT';

export type PublicCorpusSortKey =
  | 'cpuModel'
  | 'gpuModel'
  | 'codec'
  | 'preset'
  | 'fps'
  | 'vmaf'
  | 'fileSizeBytes'
  | 'videoBitrateBps'
  | 'samples';

export interface PublicCorpusRateControl {
  requestedMode: string;
  effectiveMode: string;
  qualityValue: number | null;
  targetBitrateKbps: number | null;
  maxBitrateKbps: number | null;
  bufferSizeKbits: number | null;
  label: string;
}

export interface PublicCorpusRow {
  id: string;
  createdAt: string;
  cpuModel: string;
  gpuModel: string | null;
  ramGB: number | null;
  os: string;
  codec: string;
  codecFamily: string;
  encoderName: string;
  preset: string;
  fps: number | null;
  vmaf: number | null;
  vmafP5: number | null;
  fileSizeBytes: number | null;
  videoBitrateBps: number | null;
  sourceFps: number | null;
  realTimeRatio: number | null;
  samples: number;
  workloadId: string;
  recipe: {
    id: string;
    fingerprint: string;
    encoderVersion: string | null;
    tune: string | null;
    profile: string | null;
    level: string | null;
    tier: string | null;
    pixelFormat: string;
    bitDepth: number;
    chromaSubsampling: string;
    rateControl: PublicCorpusRateControl;
  };
  environment: {
    id: string;
    fingerprint: string;
    cpuArchitecture: string;
    physicalCoreCount: number | null;
    logicalThreadCount: number | null;
    gpuModel: string | null;
    selectedAccelerator: string | null;
    driverVersion: string | null;
    osName: string;
    osVersion: string;
    ffmpegBuildFingerprint: string;
    ffmpegVersion: string;
    clientVersion: string;
  };
  versions: {
    aggregatorVersion: string;
    benchmarkProtocolId: string;
    benchmarkProtocolVersion: string;
    sourceSuiteVersion: string;
    qualityModelId: string | null;
    formulaVersion: string | null;
    scoreContextId: string | null;
    referenceContextVersion: string | null;
    analysisWorkerVersion: string | null;
  };
  status: {
    benchmarkProtocol: 'ACTIVE';
    artifactState: 'VERIFIED' | 'RETAINED' | 'MIXED_VERIFIED_RETAINED';
    centerBasis: 'accepted' | 'suspect';
    scoring: PublicCorpusScoringStatus;
    evidenceTier: 'PROVISIONAL' | 'LOW' | 'MEDIUM' | 'HIGH';
    eligibleForDefaultRecommendation: boolean;
  };
  sampleCounts: {
    accepted: number;
    suspect: number;
    rejected: number;
    invalid: number;
    repetitions: number;
    independentSources: number | null;
    machines: number | null;
    contributors: number | null;
  };
  performance: {
    encodeFps: number | null;
    realTimeRatio: number | null;
  };
  quality: {
    vmafMean: number | null;
    vmafP5: number | null;
    qualityModelId: string | null;
  };
  bitrate: {
    videoBitrateBps: number | null;
    fileSizeBytes: number | null;
    workloadReferenceBitrateBps: number | null;
  };
  confidence: {
    available: boolean;
    lower: number | null;
    upper: number | null;
    width: number | null;
    unavailableReason: string | null;
  };
  pl: {
    total: number | null;
    components: {
      quality: number | null;
      bitrate: number | null;
      speed: number | null;
    } | null;
  };
}

type EncodedArtifactState = 'VERIFIED' | 'RETAINED';
type ServerAnalysisStatus = 'COMPLETE' | 'SUSPECT';

export type PublicCorpusBenchmarkRunRecord = Prisma.BenchmarkRunGetPayload<{
  include: {
    benchmarkProtocol: true;
    recipe: true;
    environment: true;
    artifacts: true;
    qualityAnalyses: true;
  };
}>;

export type PublicCorpusDerivedResultRecord = Prisma.DerivedResultGetPayload<{
  include: {
    benchmarkProtocol: true;
    recipe: true;
    environment: true;
    scoreContext: true;
  };
}>;

type DirectEvidenceRecord = {
  run: PublicCorpusBenchmarkRunRecord;
  artifact: NonNullable<ReturnType<typeof selectPrimaryEncodedArtifact>>;
  analysis: NonNullable<ReturnType<typeof selectLatestEligibleServerAnalysis>>;
};

type PublicCorpusSortOrder = {
  sortKey: PublicCorpusSortKey | 'createdAt';
  dir: 'asc' | 'desc';
};

const PUBLIC_REFERENCE_CONTEXT_DIRECTORY = new URL('../../config/reference-contexts/', import.meta.url);
const HARDWARE_ENCODER_SUFFIXES = ['_videotoolbox', '_nvenc', '_qsv', '_amf', '_vaapi', '_v4l2m2m', '_omx'];
const ENCODED_ARTIFACT_STATES: readonly EncodedArtifactState[] = ['VERIFIED', 'RETAINED'] as const;
const ELIGIBLE_ANALYSIS_STATUSES: readonly ServerAnalysisStatus[] = ['COMPLETE', 'SUSPECT'] as const;

let cachedPublicReferenceContextVersions: ReadonlySet<string> | null = null;

function asFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function containsInsensitive(value: string): { contains: string; mode: 'insensitive' } {
  return { contains: value, mode: 'insensitive' };
}

function stableNumericValues(values: ReadonlyArray<number | null | undefined>): number[] {
  return values
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
    .sort((left, right) => left - right);
}

function median(values: ReadonlyArray<number | null | undefined>): number | null {
  const sorted = stableNumericValues(values);
  if (!sorted.length) return null;
  const midpoint = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1
    ? sorted[midpoint]!
    : (sorted[midpoint - 1]! + sorted[midpoint]!) / 2;
}

function directEvidenceKey(record: DirectEvidenceRecord): string {
  return [
    record.run.benchmarkProtocolId,
    record.run.workloadId,
    record.run.recipeId,
    record.run.environmentId,
    record.analysis.metricModelId,
  ].join('::');
}

function repetitionKey(record: DirectEvidenceRecord): string {
  return record.run.repetitionGroupId?.trim() || record.run.id;
}

function independentSourceKey(record: DirectEvidenceRecord): string {
  return `${record.run.environment.fingerprint}::${record.run.campaignId?.trim() || 'unknown-campaign'}`;
}

function sortByCreatedDesc<T extends { createdAt: Date }>(records: readonly T[]): T[] {
  return [...records].sort((left, right) => right.createdAt.getTime() - left.createdAt.getTime());
}

function selectPrimaryEncodedArtifact(run: PublicCorpusBenchmarkRunRecord) {
  const candidates = sortByCreatedDesc(run.artifacts.filter((artifact) => (
    artifact.role === 'ENCODED'
    && ENCODED_ARTIFACT_STATES.includes(artifact.storageState as EncodedArtifactState)
  )));
  return candidates.find((artifact) => artifact.storageState === 'RETAINED') ?? candidates[0] ?? null;
}

function selectLatestEligibleServerAnalysis(run: PublicCorpusBenchmarkRunRecord) {
  const candidates = sortByCreatedDesc(run.qualityAnalyses.filter((analysis) => (
    ELIGIBLE_ANALYSIS_STATUSES.includes(analysis.status as ServerAnalysisStatus)
  )));
  if (candidates.length === 0) return null;
  const metricWorkerVersion = run.benchmarkProtocol.metricWorkerVersion?.trim() || null;
  const exactProtocol = metricWorkerVersion == null
    ? []
    : candidates.filter((analysis) => analysis.analysisWorkerVersion === metricWorkerVersion);
  if (exactProtocol.length > 0) return exactProtocol[0]!;
  const canonicalDefault = candidates.filter((analysis) => analysis.analysisWorkerVersion === DEFAULT_ANALYZER_VERSION);
  if (canonicalDefault.length > 0) return canonicalDefault[0]!;
  const authoritativePrefix = candidates.filter((analysis) => analysis.analysisWorkerVersion.startsWith('authoritative-analysis/'));
  if (authoritativePrefix.length > 0) return authoritativePrefix[0]!;
  return null;
}

function buildRateControlLabel(record: PublicCorpusBenchmarkRunRecord): PublicCorpusRateControl {
  const requestedMode = String(record.recipe.requestedRateControlMode);
  const effectiveMode = String(record.recipe.effectiveRateControlMode);
  const qualityValue = record.recipe.effectiveQualityValue
    ?? record.recipe.requestedQualityValue
    ?? null;
  const targetBitrateKbps = record.recipe.effectiveTargetBitrateKbps
    ?? record.recipe.requestedTargetBitrateKbps
    ?? null;
  const maxBitrateKbps = record.recipe.effectiveMaxBitrateKbps
    ?? record.recipe.requestedMaxBitrateKbps
    ?? null;
  const bufferSizeKbits = record.recipe.effectiveBufferSizeKbits
    ?? record.recipe.requestedBufferSizeKbits
    ?? null;
  const bitrateControlled = effectiveMode.includes('BITRATE') || effectiveMode === 'VBR' || effectiveMode === 'CBR';
  const details = bitrateControlled && targetBitrateKbps != null
    ? `${effectiveMode} ${targetBitrateKbps} kbps`
    : qualityValue != null
      ? `${effectiveMode} ${qualityValue}`
      : effectiveMode;
  const limits = [
    maxBitrateKbps != null ? `max ${maxBitrateKbps} kbps` : null,
    bufferSizeKbits != null ? `buffer ${bufferSizeKbits} kbit` : null,
  ].filter((value): value is string => value != null);
  return {
    requestedMode,
    effectiveMode,
    qualityValue,
    targetBitrateKbps,
    maxBitrateKbps,
    bufferSizeKbits,
    label: limits.length > 0 ? `${details} (${limits.join(', ')})` : details,
  };
}

function classifyEvidenceTier(
  acceptedRunCount: number,
  independentSourceCount: number,
  publicConfidenceWidth: number | null,
): PublicCorpusRow['status']['evidenceTier'] {
  if (acceptedRunCount < 2 || independentSourceCount < 2) return 'PROVISIONAL';
  let tier: PublicCorpusRow['status']['evidenceTier'] = 'LOW';
  if (acceptedRunCount >= 3 && independentSourceCount >= 2 && publicConfidenceWidth != null && publicConfidenceWidth <= 8) {
    tier = 'MEDIUM';
  }
  if (acceptedRunCount >= 5 && independentSourceCount >= 3 && publicConfidenceWidth != null && publicConfidenceWidth <= 4) {
    tier = 'HIGH';
  }
  return tier;
}

function buildArtifactState(records: readonly DirectEvidenceRecord[]): PublicCorpusRow['status']['artifactState'] {
  const states = new Set(records.map((record) => record.artifact.storageState));
  if (states.size > 1) return 'MIXED_VERIFIED_RETAINED';
  return states.has('RETAINED') ? 'RETAINED' : 'VERIFIED';
}

function normalizeSortKey(sort: string | undefined): PublicCorpusSortOrder['sortKey'] {
  switch (sort) {
    case 'cpuModel':
    case 'gpuModel':
    case 'codec':
    case 'preset':
    case 'fps':
    case 'vmaf':
    case 'fileSizeBytes':
    case 'videoBitrateBps':
    case 'samples':
      return sort;
    default:
      return 'createdAt';
  }
}

function compareNullableNumbers(left: number | null, right: number | null, dir: 'asc' | 'desc'): number {
  if (left == null && right == null) return 0;
  if (left == null) return 1;
  if (right == null) return -1;
  return dir === 'asc' ? left - right : right - left;
}

function compareNullableText(left: string | null | undefined, right: string | null | undefined, dir: 'asc' | 'desc'): number {
  const normalizedLeft = left ?? '';
  const normalizedRight = right ?? '';
  return dir === 'asc'
    ? normalizedLeft.localeCompare(normalizedRight)
    : normalizedRight.localeCompare(normalizedLeft);
}

function directDerivedKey(record: PublicCorpusDerivedResultRecord): string {
  return [
    record.benchmarkProtocolId,
    record.workloadId,
    record.recipeId,
    record.environmentId,
    record.scoreContext.qualityModelId,
  ].join('::');
}

function buildPublicDerivedResultMap(
  records: readonly PublicCorpusDerivedResultRecord[],
  publicReferenceContextVersions: ReadonlySet<string>,
): ReadonlyMap<string, PublicCorpusDerivedResultRecord> {
  const rows = records
    .filter((record) => publicReferenceContextVersions.has(record.scoreContext.contextVersion))
    .sort((left, right) => right.createdAt.getTime() - left.createdAt.getTime());
  const byKey = new Map<string, PublicCorpusDerivedResultRecord>();
  for (const record of rows) {
    const key = directDerivedKey(record);
    if (!byKey.has(key)) byKey.set(key, record);
  }
  return byKey;
}

function buildCenterBasisRecords(records: readonly DirectEvidenceRecord[]): readonly DirectEvidenceRecord[] {
  const accepted = records.filter((record) => record.run.status === 'ACCEPTED' && record.analysis.status === 'COMPLETE');
  return accepted.length > 0 ? accepted : records;
}

function deriveSourceFps(records: readonly DirectEvidenceRecord[]): number | null {
  const sourceFps = median(records.map((record) => record.run.sourceFps));
  return sourceFps != null && sourceFps > 0 ? sourceFps : null;
}

export function getPublicReferenceContextVersions(): ReadonlySet<string> {
  if (cachedPublicReferenceContextVersions) return cachedPublicReferenceContextVersions;
  const directoryPath = fileURLToPath(PUBLIC_REFERENCE_CONTEXT_DIRECTORY);
  const versions = new Set<string>();
  for (const fileName of readdirSync(directoryPath).filter((entry) => entry.endsWith('.context.json')).sort()) {
    const raw = JSON.parse(readFileSync(path.join(directoryPath, fileName), 'utf8')) as {
      contextVersion?: unknown;
      activation?: { productionActivationAllowed?: unknown };
    };
    if (raw.activation?.productionActivationAllowed === true && typeof raw.contextVersion === 'string' && raw.contextVersion.trim()) {
      versions.add(raw.contextVersion.trim());
    }
  }
  cachedPublicReferenceContextVersions = versions;
  return cachedPublicReferenceContextVersions;
}

export function buildPublicCorpusWhere(query: Record<string, string | undefined>): Prisma.BenchmarkRunWhereInput {
  const where: Prisma.BenchmarkRunWhereInput = {
    status: { in: ['ACCEPTED', 'SUSPECT'] },
    benchmarkProtocol: { state: 'ACTIVE' },
    artifacts: {
      some: {
        role: 'ENCODED',
        storageState: { in: [...ENCODED_ARTIFACT_STATES] },
      },
    },
  };
  const andFilters: Prisma.BenchmarkRunWhereInput[] = [];

  if (query.cpu?.trim()) {
    andFilters.push({ environment: { cpuModel: containsInsensitive(query.cpu.trim()) } });
  }
  if (query.gpu?.trim()) {
    andFilters.push({ environment: { gpuModel: containsInsensitive(query.gpu.trim()) } });
  }
  if (query.preset?.trim()) {
    andFilters.push({ recipe: { preset: containsInsensitive(query.preset.trim()) } });
  }
  if (query.encoderType === 'hardware' || query.encoderType === 'software') {
    const hardwareMatchers = HARDWARE_ENCODER_SUFFIXES.map((suffix) => ({
      recipe: { encoderImplementation: { endsWith: suffix } },
    }));
    andFilters.push(query.encoderType === 'hardware'
      ? { OR: hardwareMatchers }
      : { NOT: { OR: hardwareMatchers } });
  }
  if (query.search?.trim()) {
    const search = query.search.trim();
    andFilters.push({
      OR: [
        { workloadId: containsInsensitive(search) },
        { environment: { cpuModel: containsInsensitive(search) } },
        { environment: { gpuModel: containsInsensitive(search) } },
        { environment: { osName: containsInsensitive(search) } },
        { environment: { osVersion: containsInsensitive(search) } },
        { recipe: { encoderImplementation: containsInsensitive(search) } },
        { recipe: { codecFamily: containsInsensitive(search) } },
        { recipe: { preset: containsInsensitive(search) } },
      ],
    });
  }

  if (andFilters.length > 0) where.AND = andFilters;
  return where;
}

export function buildPublicCorpusOrderBy(
  sort: string | undefined,
  dir: 'asc' | 'desc',
): PublicCorpusSortOrder {
  return {
    sortKey: normalizeSortKey(sort),
    dir,
  };
}

export function sortPublicCorpusRows(
  rows: readonly PublicCorpusRow[],
  order: PublicCorpusSortOrder,
): PublicCorpusRow[] {
  return [...rows].sort((left, right) => {
    switch (order.sortKey) {
      case 'cpuModel':
        return compareNullableText(left.cpuModel, right.cpuModel, order.dir) || compareNullableText(left.id, right.id, 'asc');
      case 'gpuModel':
        return compareNullableText(left.gpuModel, right.gpuModel, order.dir) || compareNullableText(left.id, right.id, 'asc');
      case 'codec':
        return compareNullableText(left.encoderName, right.encoderName, order.dir) || compareNullableText(left.id, right.id, 'asc');
      case 'preset':
        return compareNullableText(left.preset, right.preset, order.dir) || compareNullableText(left.id, right.id, 'asc');
      case 'fps':
        return compareNullableNumbers(left.performance.encodeFps ?? left.fps, right.performance.encodeFps ?? right.fps, order.dir) || compareNullableText(left.id, right.id, 'asc');
      case 'vmaf':
        return compareNullableNumbers(left.quality.vmafMean ?? left.vmaf, right.quality.vmafMean ?? right.vmaf, order.dir) || compareNullableText(left.id, right.id, 'asc');
      case 'fileSizeBytes':
        return compareNullableNumbers(left.bitrate.fileSizeBytes ?? left.fileSizeBytes, right.bitrate.fileSizeBytes ?? right.fileSizeBytes, order.dir) || compareNullableText(left.id, right.id, 'asc');
      case 'videoBitrateBps':
        return compareNullableNumbers(left.bitrate.videoBitrateBps ?? left.videoBitrateBps, right.bitrate.videoBitrateBps ?? right.videoBitrateBps, order.dir) || compareNullableText(left.id, right.id, 'asc');
      case 'samples':
        return compareNullableNumbers(left.sampleCounts.accepted, right.sampleCounts.accepted, order.dir) || compareNullableText(left.id, right.id, 'asc');
      case 'createdAt':
      default:
        return compareNullableNumbers(Date.parse(left.createdAt), Date.parse(right.createdAt), order.dir) || compareNullableText(left.id, right.id, 'asc');
    }
  });
}

export function extractDirectEvidenceRecords(
  runs: readonly PublicCorpusBenchmarkRunRecord[],
): DirectEvidenceRecord[] {
  return runs.flatMap((run) => {
    const artifact = selectPrimaryEncodedArtifact(run);
    const analysis = selectLatestEligibleServerAnalysis(run);
    if (!artifact || !analysis) return [];
    return [{ run, artifact, analysis }];
  });
}

export function buildPublicCorpusRows(input: {
  runs: readonly PublicCorpusBenchmarkRunRecord[];
  derivedResults?: readonly PublicCorpusDerivedResultRecord[];
  publicReferenceContextVersions?: ReadonlySet<string>;
}): PublicCorpusRow[] {
  const evidenceRecords = extractDirectEvidenceRecords(input.runs);
  const byKey = new Map<string, DirectEvidenceRecord[]>();
  for (const record of evidenceRecords) {
    const key = directEvidenceKey(record);
    const bucket = byKey.get(key) ?? [];
    bucket.push(record);
    byKey.set(key, bucket);
  }

  const publicReferenceContextVersions = input.publicReferenceContextVersions ?? getPublicReferenceContextVersions();
  const publicDerivedResults = buildPublicDerivedResultMap(input.derivedResults ?? [], publicReferenceContextVersions);

  return [...byKey.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, records]) => {
      const newestRecord = sortByCreatedDesc(records.map((record) => record.run))[0]!;
      const centerBasisRecords = buildCenterBasisRecords(records);
      const acceptedRecords = records.filter((record) => record.run.status === 'ACCEPTED' && record.analysis.status === 'COMPLETE');
      const suspectRecords = records.filter((record) => !(record.run.status === 'ACCEPTED' && record.analysis.status === 'COMPLETE'));
      const centerFps = median(centerBasisRecords.map((record) => record.run.encodeFps));
      const centerSourceFps = deriveSourceFps(centerBasisRecords);
      const centerRealTimeRatio = centerFps != null && centerSourceFps != null && centerSourceFps > 0 ? centerFps / centerSourceFps : null;
      const centerVmafMean = median(centerBasisRecords.map((record) => record.analysis.vmafMean));
      const centerVmafP5 = median(centerBasisRecords.map((record) => record.analysis.vmafP5));
      const centerVideoBitrateBps = median(centerBasisRecords.map((record) => record.analysis.videoBitrateBps));
      const centerFileSizeBytes = median(centerBasisRecords.map((record) => (
        asFiniteNumber(record.analysis.fileSizeBytes) ?? asFiniteNumber(record.artifact.byteSize)
      )));
      const publicDerivedResult = publicDerivedResults.get(key) ?? null;
      const publicConfidenceWidth = publicDerivedResult?.confidenceLower != null && publicDerivedResult.confidenceUpper != null
        ? publicDerivedResult.confidenceUpper - publicDerivedResult.confidenceLower
        : null;
      const acceptedIndependentSources = new Set(acceptedRecords.map(independentSourceKey)).size;
      const evidenceTier = classifyEvidenceTier(acceptedRecords.length, acceptedIndependentSources, publicConfidenceWidth);
      const qualityModelId = records[0]?.analysis.metricModelId ?? null;
      return {
        id: key,
        createdAt: newestRecord.createdAt.toISOString(),
        cpuModel: newestRecord.environment.cpuModel,
        gpuModel: newestRecord.environment.gpuModel ?? null,
        ramGB: newestRecord.environment.physicalCoreCount ?? newestRecord.environment.logicalThreadCount ?? null,
        os: `${newestRecord.environment.osName} ${newestRecord.environment.osVersion}`.trim(),
        codec: newestRecord.recipe.codecFamily,
        codecFamily: newestRecord.recipe.codecFamily,
        encoderName: newestRecord.recipe.encoderImplementation,
        preset: newestRecord.recipe.preset ?? 'default',
        fps: centerFps,
        vmaf: centerVmafMean,
        vmafP5: centerVmafP5,
        fileSizeBytes: centerFileSizeBytes == null ? null : Math.round(centerFileSizeBytes),
        videoBitrateBps: centerVideoBitrateBps,
        sourceFps: centerSourceFps,
        realTimeRatio: centerRealTimeRatio,
        samples: acceptedRecords.length,
        workloadId: newestRecord.workloadId,
        recipe: {
          id: newestRecord.recipeId,
          fingerprint: newestRecord.recipe.fingerprint,
          encoderVersion: newestRecord.recipe.encoderVersion ?? null,
          tune: newestRecord.recipe.tune ?? null,
          profile: newestRecord.recipe.profile ?? null,
          level: newestRecord.recipe.level ?? null,
          tier: newestRecord.recipe.tier ?? null,
          pixelFormat: newestRecord.recipe.pixelFormat,
          bitDepth: newestRecord.recipe.bitDepth,
          chromaSubsampling: newestRecord.recipe.chromaSubsampling,
          rateControl: buildRateControlLabel(newestRecord),
        },
        environment: {
          id: newestRecord.environmentId,
          fingerprint: newestRecord.environment.fingerprint,
          cpuArchitecture: newestRecord.environment.cpuArchitecture,
          physicalCoreCount: newestRecord.environment.physicalCoreCount ?? null,
          logicalThreadCount: newestRecord.environment.logicalThreadCount ?? null,
          gpuModel: newestRecord.environment.gpuModel ?? null,
          selectedAccelerator: newestRecord.environment.selectedAccelerator ?? null,
          driverVersion: newestRecord.environment.driverVersion ?? null,
          osName: newestRecord.environment.osName,
          osVersion: newestRecord.environment.osVersion,
          ffmpegBuildFingerprint: newestRecord.environment.ffmpegBuildFingerprint,
          ffmpegVersion: newestRecord.environment.ffmpegVersion,
          clientVersion: newestRecord.environment.clientVersion,
        },
        versions: {
          aggregatorVersion: publicDerivedResult?.aggregatorVersion ?? PUBLIC_CORPUS_READ_MODEL_VERSION,
          benchmarkProtocolId: newestRecord.benchmarkProtocolId,
          benchmarkProtocolVersion: newestRecord.benchmarkProtocol.protocolVersion,
          sourceSuiteVersion: newestRecord.benchmarkProtocol.sourceSuiteVersion,
          qualityModelId,
          formulaVersion: publicDerivedResult?.scoreContext.formulaVersion ?? null,
          scoreContextId: publicDerivedResult?.scoreContextId ?? null,
          referenceContextVersion: publicDerivedResult?.scoreContext.contextVersion ?? null,
          analysisWorkerVersion: newestRecord.benchmarkProtocol.metricWorkerVersion || (records[0]?.analysis.analysisWorkerVersion ?? null),
        },
        status: {
          benchmarkProtocol: 'ACTIVE',
          artifactState: buildArtifactState(records),
          centerBasis: acceptedRecords.length > 0 ? 'accepted' : 'suspect',
          scoring: publicDerivedResult ? 'PUBLIC' : 'UNSCORED_NO_PUBLIC_DERIVED_RESULT',
          evidenceTier,
          eligibleForDefaultRecommendation: publicDerivedResult?.evidenceSummary != null
            && typeof publicDerivedResult.evidenceSummary === 'object'
            && !Array.isArray(publicDerivedResult.evidenceSummary)
            && (publicDerivedResult.evidenceSummary as Record<string, unknown>).eligibleForDefaultRecommendation === true,
        },
        sampleCounts: {
          accepted: acceptedRecords.length,
          suspect: suspectRecords.length,
          rejected: 0,
          invalid: 0,
          repetitions: new Set(records.map(repetitionKey)).size,
          independentSources: acceptedRecords.length > 0 ? acceptedIndependentSources : new Set(records.map(independentSourceKey)).size,
          machines: 1,
          contributors: null,
        },
        performance: {
          encodeFps: centerFps,
          realTimeRatio: centerRealTimeRatio,
        },
        quality: {
          vmafMean: centerVmafMean,
          vmafP5: centerVmafP5,
          qualityModelId,
        },
        bitrate: {
          videoBitrateBps: centerVideoBitrateBps,
          fileSizeBytes: centerFileSizeBytes == null ? null : Math.round(centerFileSizeBytes),
          workloadReferenceBitrateBps: publicDerivedResult?.scoreContext.workloadReferenceBitrateBps ?? null,
        },
        confidence: {
          available: publicDerivedResult?.confidenceLower != null && publicDerivedResult?.confidenceUpper != null,
          lower: publicDerivedResult?.confidenceLower ?? null,
          upper: publicDerivedResult?.confidenceUpper ?? null,
          width: publicConfidenceWidth,
          unavailableReason: publicDerivedResult == null
            ? 'No matching production-activatable DerivedResult has been published for this workload identity.'
            : publicConfidenceWidth == null
              ? 'Confidence interval unavailable for this public aggregate scope.'
              : null,
        },
        pl: {
          total: publicDerivedResult?.plTotal ?? null,
          components: publicDerivedResult == null ? null : {
            quality: publicDerivedResult.plQuality ?? null,
            bitrate: publicDerivedResult.plBitrate ?? null,
            speed: publicDerivedResult.plSpeed ?? null,
          },
        },
      };
    });
}
