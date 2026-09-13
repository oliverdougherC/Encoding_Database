import crypto from 'node:crypto';

export const RATE_CONTROL_MODES = ['crf', 'cq', 'icq', 'cqp', 'qp', 'vbr', 'cbr', 'abr', 'other'] as const;
export type RateControlMode = typeof RATE_CONTROL_MODES[number];

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface RateControlSettings {
  mode: RateControlMode | string;
  qualityValue?: number | null;
  targetBitrateKbps?: number | null;
  maxBitrateKbps?: number | null;
  bufferSizeKbits?: number | null;
  qmin?: number | null;
  qmax?: number | null;
  extras?: JsonObject | null;
}

export interface RecipeIdentityInput {
  codecFamily: string;
  encoderImplementation: string;
  encoderVersion?: string | null;
  preset?: string | null;
  tune?: string | null;
  profile?: string | null;
  level?: string | null;
  tier?: string | null;
  pixelFormat: string;
  bitDepth: number;
  chromaSubsampling: string;
  containerFormat?: string | null;
  videoCodecTag?: string | null;
  requestedRateControl: RateControlSettings;
  effectiveRateControl: RateControlSettings;
  requestedOutputSettings?: JsonObject | null;
  effectiveOutputSettings?: JsonObject | null;
  normalizedRequestedOptions?: JsonObject | null;
  normalizedEffectiveOptions?: JsonObject | null;
  gopSize?: number | null;
  keyframeInterval?: number | null;
  bFrames?: number | null;
  frameReordering?: boolean | null;
  lookahead?: number | null;
  filmGrainSynthesis?: JsonObject | null;
  majorTools?: JsonObject | null;
}

export interface EnvironmentIdentityInput {
  cpuModel: string;
  cpuArchitecture: string;
  physicalCoreCount?: number | null;
  logicalThreadCount?: number | null;
  physicalMemoryBytes?: number | null;
  gpuModel?: string | null;
  selectedAcceleratorId?: string | null;
  selectedAccelerator?: string | null;
  driverVersion?: string | null;
  osName: string;
  osVersion: string;
  ffmpegBuildFingerprint: string;
  ffmpegVersion: string;
  encoderVersion?: string | null;
  clientVersion: string;
}

export interface AggregationCompatibilityIdentity {
  protocolVersion: string;
  sourceSuiteVersion: string;
  workloadId: string;
  recipeFingerprint: string;
  environmentFingerprint: string;
  formulaVersion: string;
  scoreContextVersion: string;
  qualityModelId: string;
}

export interface DerivedResultRecomputationSpec {
  protocolVersion: string;
  sourceSuiteVersion: string;
  workloadId: string;
  recipeFingerprint: string;
  environmentFingerprint: string;
  formulaVersion: string;
  scoreContextVersion: string;
  qualityModelId: string;
  scopeKey: string;
  includedStatuses: ReadonlyArray<'accepted' | 'suspect' | 'rejected'>;
  aggregatorVersion: string;
  selectedAnalysisIds: ReadonlyArray<string>;
  analysisWorkerVersions: ReadonlyArray<string>;
}

export interface FingerprintResult<TNormalized> {
  normalized: TNormalized;
  canonicalJson: string;
  fingerprint: string;
}

type CanonicalRecipeIdentity = {
  codecFamily: string;
  encoderImplementation: string;
  encoderVersion: string | null;
  preset: string | null;
  tune: string | null;
  profile: string | null;
  level: string | null;
  tier: string | null;
  pixelFormat: string;
  bitDepth: number;
  chromaSubsampling: string;
  containerFormat: string | null;
  videoCodecTag: string | null;
  requestedRateControl: CanonicalRateControlSettings;
  effectiveRateControl: CanonicalRateControlSettings;
  requestedOutputSettings: JsonObject | null;
  effectiveOutputSettings: JsonObject | null;
  normalizedRequestedOptions: JsonObject | null;
  normalizedEffectiveOptions: JsonObject | null;
  gopSize: number | null;
  keyframeInterval: number | null;
  bFrames: number | null;
  frameReordering: boolean | null;
  lookahead: number | null;
  filmGrainSynthesis: JsonObject | null;
  majorTools: JsonObject | null;
};

type CanonicalEnvironmentIdentity = {
  cpuModel: string;
  cpuArchitecture: string;
  physicalCoreCount: number | null;
  logicalThreadCount: number | null;
  physicalMemoryBytes: number | null;
  gpuModel: string | null;
  selectedAcceleratorId: string | null;
  selectedAccelerator: string | null;
  driverVersion: string | null;
  osName: string;
  osVersion: string;
  ffmpegBuildFingerprint: string;
  ffmpegVersion: string;
  encoderVersion: string | null;
  clientVersion: string;
};

type CanonicalRateControlSettings = {
  mode: RateControlMode;
  qualityValue: number | null;
  targetBitrateKbps: number | null;
  maxBitrateKbps: number | null;
  bufferSizeKbits: number | null;
  qmin: number | null;
  qmax: number | null;
  extras: JsonObject | null;
};

const MODE_ALIASES: Record<string, RateControlMode> = {
  abr: 'abr',
  cbr: 'cbr',
  constqp: 'cqp',
  constant_qp: 'cqp',
  constantqp: 'cqp',
  cq: 'cq',
  cqp: 'cqp',
  crf: 'crf',
  icq: 'icq',
  other: 'other',
  qp: 'qp',
  quality: 'cq',
  vbr: 'vbr',
};

const ARCHITECTURE_ALIASES: Record<string, string> = {
  aarch64: 'arm64',
  amd64: 'x86_64',
  arm64: 'arm64',
  x64: 'x86_64',
  x86_64: 'x86_64',
};

function trimText(value: string): string {
  return value.trim().replace(/\s+/g, ' ');
}

function normalizeTextToken(value: string): string {
  return trimText(value).toLowerCase();
}

function normalizeOptionalText(value: string | null | undefined, lowercase = false): string | null {
  if (value == null) return null;
  const trimmed = trimText(value);
  if (!trimmed) return null;
  return lowercase ? trimmed.toLowerCase() : trimmed;
}

function normalizeRequiredText(value: string, fieldName: string, lowercase = false): string {
  const normalized = normalizeOptionalText(value, lowercase);
  if (!normalized) {
    throw new Error(`${fieldName} is required`);
  }
  return normalized;
}

function normalizeNumber(value: number | null | undefined, fieldName: string): number | null {
  if (value == null) return null;
  if (!Number.isFinite(value)) {
    throw new Error(`${fieldName} must be finite when provided`);
  }
  return value;
}

function normalizeInteger(value: number | null | undefined, fieldName: string): number | null {
  const normalized = normalizeNumber(value, fieldName);
  if (normalized == null) return null;
  if (!Number.isInteger(normalized)) {
    throw new Error(`${fieldName} must be an integer when provided`);
  }
  return normalized;
}

function normalizeJsonValue(value: JsonValue): JsonValue {
  if (Array.isArray(value)) {
    return value.map(normalizeJsonValue);
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, normalizeJsonValue((value as JsonObject)[key]!)]),
    );
  }
  if (typeof value === 'string') {
    return trimText(value);
  }
  return value;
}

function normalizeJsonObject(value: JsonObject | null | undefined): JsonObject | null {
  if (value == null) return null;
  return normalizeJsonValue(value) as JsonObject;
}

function normalizeRateControlSettings(input: RateControlSettings): CanonicalRateControlSettings {
  const aliasKey = normalizeTextToken(String(input.mode || ''));
  const mode = MODE_ALIASES[aliasKey];
  if (!mode) {
    throw new Error(`Unsupported rate-control mode: ${input.mode}`);
  }

  return {
    mode,
    qualityValue: normalizeNumber(input.qualityValue, 'qualityValue'),
    targetBitrateKbps: normalizeInteger(input.targetBitrateKbps, 'targetBitrateKbps'),
    maxBitrateKbps: normalizeInteger(input.maxBitrateKbps, 'maxBitrateKbps'),
    bufferSizeKbits: normalizeInteger(input.bufferSizeKbits, 'bufferSizeKbits'),
    qmin: normalizeInteger(input.qmin, 'qmin'),
    qmax: normalizeInteger(input.qmax, 'qmax'),
    extras: normalizeJsonObject(input.extras),
  };
}

export function canonicalizeJson(value: JsonValue): JsonValue {
  return normalizeJsonValue(value);
}

export function canonicalJsonString(value: JsonValue): string {
  return JSON.stringify(canonicalizeJson(value));
}

export function sha256Hex(input: string): string {
  return crypto.createHash('sha256').update(input).digest('hex');
}

export function normalizeRecipeIdentity(input: RecipeIdentityInput): CanonicalRecipeIdentity {
  return {
    codecFamily: normalizeRequiredText(input.codecFamily, 'codecFamily', true),
    encoderImplementation: normalizeRequiredText(input.encoderImplementation, 'encoderImplementation', true),
    encoderVersion: normalizeOptionalText(input.encoderVersion),
    preset: normalizeOptionalText(input.preset, true),
    tune: normalizeOptionalText(input.tune, true),
    profile: normalizeOptionalText(input.profile, true),
    level: normalizeOptionalText(input.level, true),
    tier: normalizeOptionalText(input.tier, true),
    pixelFormat: normalizeRequiredText(input.pixelFormat, 'pixelFormat', true),
    bitDepth: normalizeInteger(input.bitDepth, 'bitDepth') ?? (() => { throw new Error('bitDepth is required'); })(),
    chromaSubsampling: normalizeRequiredText(input.chromaSubsampling, 'chromaSubsampling', true),
    containerFormat: normalizeOptionalText(input.containerFormat, true),
    videoCodecTag: normalizeOptionalText(input.videoCodecTag, true),
    requestedRateControl: normalizeRateControlSettings(input.requestedRateControl),
    effectiveRateControl: normalizeRateControlSettings(input.effectiveRateControl),
    requestedOutputSettings: normalizeJsonObject(input.requestedOutputSettings),
    effectiveOutputSettings: normalizeJsonObject(input.effectiveOutputSettings),
    normalizedRequestedOptions: normalizeJsonObject(input.normalizedRequestedOptions),
    normalizedEffectiveOptions: normalizeJsonObject(input.normalizedEffectiveOptions),
    gopSize: normalizeInteger(input.gopSize, 'gopSize'),
    keyframeInterval: normalizeInteger(input.keyframeInterval, 'keyframeInterval'),
    bFrames: normalizeInteger(input.bFrames, 'bFrames'),
    frameReordering: input.frameReordering == null ? null : Boolean(input.frameReordering),
    lookahead: normalizeInteger(input.lookahead, 'lookahead'),
    filmGrainSynthesis: normalizeJsonObject(input.filmGrainSynthesis),
    majorTools: normalizeJsonObject(input.majorTools),
  };
}

export function normalizeEnvironmentIdentity(input: EnvironmentIdentityInput): CanonicalEnvironmentIdentity {
  const rawArchitecture = normalizeRequiredText(input.cpuArchitecture, 'cpuArchitecture', true);
  const cpuArchitecture = ARCHITECTURE_ALIASES[rawArchitecture] ?? rawArchitecture;

  return {
    cpuModel: normalizeRequiredText(input.cpuModel, 'cpuModel'),
    cpuArchitecture,
    physicalCoreCount: normalizeInteger(input.physicalCoreCount, 'physicalCoreCount'),
    logicalThreadCount: normalizeInteger(input.logicalThreadCount, 'logicalThreadCount'),
    physicalMemoryBytes: normalizeInteger(input.physicalMemoryBytes, 'physicalMemoryBytes'),
    gpuModel: normalizeOptionalText(input.gpuModel),
    selectedAcceleratorId: normalizeOptionalText(input.selectedAcceleratorId, true),
    selectedAccelerator: normalizeOptionalText(input.selectedAccelerator),
    driverVersion: normalizeOptionalText(input.driverVersion),
    osName: normalizeRequiredText(input.osName, 'osName', true),
    osVersion: normalizeRequiredText(input.osVersion, 'osVersion', true),
    ffmpegBuildFingerprint: normalizeRequiredText(input.ffmpegBuildFingerprint, 'ffmpegBuildFingerprint'),
    ffmpegVersion: normalizeRequiredText(input.ffmpegVersion, 'ffmpegVersion'),
    encoderVersion: normalizeOptionalText(input.encoderVersion),
    clientVersion: normalizeRequiredText(input.clientVersion, 'clientVersion'),
  };
}

export function buildRecipeFingerprint(input: RecipeIdentityInput): FingerprintResult<CanonicalRecipeIdentity> {
  const normalized = normalizeRecipeIdentity(input);
  const canonicalJson = canonicalJsonString(normalized);
  return {
    normalized,
    canonicalJson,
    fingerprint: sha256Hex(canonicalJson),
  };
}

export function buildEnvironmentFingerprint(input: EnvironmentIdentityInput): FingerprintResult<CanonicalEnvironmentIdentity> {
  const normalized = normalizeEnvironmentIdentity(input);
  const canonicalJson = canonicalJsonString(normalized);
  return {
    normalized,
    canonicalJson,
    fingerprint: sha256Hex(canonicalJson),
  };
}

export function buildAggregationCompatibilityKey(identity: AggregationCompatibilityIdentity): string {
  return canonicalJsonString({
    protocolVersion: normalizeRequiredText(identity.protocolVersion, 'protocolVersion'),
    sourceSuiteVersion: normalizeRequiredText(identity.sourceSuiteVersion, 'sourceSuiteVersion'),
    workloadId: normalizeRequiredText(identity.workloadId, 'workloadId'),
    recipeFingerprint: normalizeRequiredText(identity.recipeFingerprint, 'recipeFingerprint'),
    environmentFingerprint: normalizeRequiredText(identity.environmentFingerprint, 'environmentFingerprint'),
    formulaVersion: normalizeRequiredText(identity.formulaVersion, 'formulaVersion'),
    scoreContextVersion: normalizeRequiredText(identity.scoreContextVersion, 'scoreContextVersion'),
    qualityModelId: normalizeRequiredText(identity.qualityModelId, 'qualityModelId'),
  });
}

export function areAggregationCompatible(
  left: AggregationCompatibilityIdentity,
  right: AggregationCompatibilityIdentity,
): boolean {
  return buildAggregationCompatibilityKey(left) === buildAggregationCompatibilityKey(right);
}

export function buildDerivedResultScopeKey(kind: 'clip' | 'workload' | 'general', identity: {
  workloadId: string;
  testClipId?: string | null;
}): string {
  const workloadId = normalizeRequiredText(identity.workloadId, 'workloadId');
  if (kind === 'clip') {
    const testClipId = normalizeOptionalText(identity.testClipId);
    if (!testClipId) {
      throw new Error('testClipId is required for clip scope');
    }
    return `clip:${workloadId}:${testClipId}`;
  }
  if (kind === 'workload') {
    return `workload:${workloadId}`;
  }
  return `general:${workloadId}`;
}

/**
 * Persist this spec verbatim with each derived result so future scoring or
 * analysis changes can rebuild the aggregate from immutable run evidence.
 */
export function buildDerivedResultRecomputationSpec(
  spec: DerivedResultRecomputationSpec,
): DerivedResultRecomputationSpec {
  return {
    protocolVersion: normalizeRequiredText(spec.protocolVersion, 'protocolVersion'),
    sourceSuiteVersion: normalizeRequiredText(spec.sourceSuiteVersion, 'sourceSuiteVersion'),
    workloadId: normalizeRequiredText(spec.workloadId, 'workloadId'),
    recipeFingerprint: normalizeRequiredText(spec.recipeFingerprint, 'recipeFingerprint'),
    environmentFingerprint: normalizeRequiredText(spec.environmentFingerprint, 'environmentFingerprint'),
    formulaVersion: normalizeRequiredText(spec.formulaVersion, 'formulaVersion'),
    scoreContextVersion: normalizeRequiredText(spec.scoreContextVersion, 'scoreContextVersion'),
    qualityModelId: normalizeRequiredText(spec.qualityModelId, 'qualityModelId'),
    scopeKey: normalizeRequiredText(spec.scopeKey, 'scopeKey'),
    includedStatuses: [...spec.includedStatuses],
    aggregatorVersion: normalizeRequiredText(spec.aggregatorVersion, 'aggregatorVersion'),
    selectedAnalysisIds: [...spec.selectedAnalysisIds].map((value) => normalizeRequiredText(value, 'selectedAnalysisId')).sort(),
    analysisWorkerVersions: [...new Set(spec.analysisWorkerVersions.map((value) => normalizeRequiredText(value, 'analysisWorkerVersion')))].sort(),
  };
}
