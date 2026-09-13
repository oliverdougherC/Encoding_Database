import {
  canonicalizeJson,
  type JsonObject,
} from './persistence.js';

export const ENERGY_DOMAIN_TYPES = [
  'gpu-board',
  'cpu-package',
  'cpu-core',
  'dram',
  'soc-package',
  'system',
  'other',
] as const;
export const ENERGY_COUNTER_STATES = [
  'valid',
  'wrap',
  'reset',
  'unsupported',
  'error',
] as const;
export const ENERGY_COUNTER_UNITS = [
  'joules',
  'millijoules',
  'microjoules',
  'nanojoules',
] as const;
export const DECODE_BENCHMARK_STATUSES = [
  'complete',
  'deferred',
  'unsupported',
  'error',
] as const;
export const DECODE_CACHE_DISCIPLINES = [
  'bounded',
  'cold',
  'warm',
  'documented',
] as const;
export const DECODE_EXECUTION_MODES = [
  'software',
  'hardware',
  'hybrid',
] as const;

export type EnergyDomainType = typeof ENERGY_DOMAIN_TYPES[number];
export type EnergyCounterState = typeof ENERGY_COUNTER_STATES[number];
export type EnergyCounterUnit = typeof ENERGY_COUNTER_UNITS[number];
export type DecodeBenchmarkStatus = typeof DECODE_BENCHMARK_STATUSES[number];
export type DecodeCacheDiscipline = typeof DECODE_CACHE_DISCIPLINES[number];
export type DecodeExecutionMode = typeof DECODE_EXECUTION_MODES[number];

export interface EnergyDomainInput {
  domain: EnergyDomainType | string;
  domainLabel?: string | null;
  collector: string;
  collectorVersion?: string | null;
  source?: string | null;
  counterUnit?: EnergyCounterUnit | string | null;
  counterState?: EnergyCounterState | string | null;
  startCounter?: number | null;
  endCounter?: number | null;
  counterRolloverValue?: number | null;
  error?: string | null;
}

export interface NormalizeEnergyDomainsOptions {
  measurements?: readonly EnergyDomainInput[] | null;
  sourceFrameCount?: number | null;
  sourceDurationSeconds?: number | null;
}

export interface NormalizedEnergyDomain extends JsonObject {
  domain: EnergyDomainType;
  domainLabel: string;
  collector: string;
  collectorVersion: string | null;
  source: string | null;
  counterUnit: EnergyCounterUnit | null;
  counterState: EnergyCounterState;
  startCounter: number | null;
  endCounter: number | null;
  counterRolloverValue: number | null;
  deltaJoules: number | null;
  joulesPerFrame: number | null;
  joulesPerSourceSecond: number | null;
  compatibleMeasurement: boolean;
  error: string | null;
}

export interface DecodeBenchmarkInput {
  status: DecodeBenchmarkStatus | string;
  decoderImplementation?: string | null;
  decoderVersion?: string | null;
  toolchainFingerprint?: string | null;
  executionMode?: DecodeExecutionMode | string | null;
  cacheDiscipline?: DecodeCacheDiscipline | string | null;
  wallTimeMs?: number | null;
  decodeFps?: number | null;
  sourceFps?: number | null;
  cpuTimeMs?: number | null;
  peakRssBytes?: number | null;
  notes?: string | null;
  deferredReason?: string | null;
}

export interface NormalizedDecodeBenchmark extends JsonObject {
  status: DecodeBenchmarkStatus;
  decoderImplementation: string | null;
  decoderVersion: string | null;
  toolchainFingerprint: string | null;
  executionMode: DecodeExecutionMode | null;
  cacheDiscipline: DecodeCacheDiscipline | null;
  wallTimeMs: number | null;
  decodeFps: number | null;
  sourceFps: number | null;
  realTimeMultiple: number | null;
  cpuTimeMs: number | null;
  peakRssBytes: number | null;
  notes: string | null;
  deferredReason: string | null;
}

function requireText(value: string, fieldName: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new Error(`${fieldName} is required`);
  }
  return trimmed;
}

function optionalText(value: string | null | undefined): string | null {
  if (value == null) return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function optionalFiniteNumber(value: number | null | undefined, fieldName: string): number | null {
  if (value == null) return null;
  if (!Number.isFinite(value)) {
    throw new Error(`${fieldName} must be finite when provided`);
  }
  return value;
}

function optionalPositiveNumber(value: number | null | undefined, fieldName: string): number | null {
  const normalized = optionalFiniteNumber(value, fieldName);
  if (normalized == null) return null;
  if (normalized <= 0) {
    throw new Error(`${fieldName} must be positive when provided`);
  }
  return normalized;
}

function normalizeEnumValue<T extends readonly string[]>(
  value: string | null | undefined,
  allowed: T,
  fieldName: string,
): T[number] | null {
  if (value == null) return null;
  const normalized = value.trim().toLowerCase();
  if (!normalized) return null;
  if (!allowed.includes(normalized)) {
    throw new Error(`${fieldName} must be one of ${allowed.join(', ')}`);
  }
  return normalized as T[number];
}

function roundMetric(value: number | null): number | null {
  if (value == null) return null;
  return Number(value.toFixed(9));
}

function energyUnitScale(unit: EnergyCounterUnit): number {
  if (unit === 'joules') return 1;
  if (unit === 'millijoules') return 1 / 1_000;
  if (unit === 'microjoules') return 1 / 1_000_000;
  return 1 / 1_000_000_000;
}

function computeDeltaJoules(
  state: EnergyCounterState,
  unit: EnergyCounterUnit | null,
  startCounter: number | null,
  endCounter: number | null,
  counterRolloverValue: number | null,
): number | null {
  if (state === 'unsupported' || state === 'error' || state === 'reset') {
    return null;
  }
  if (unit == null) {
    throw new Error('counterUnit is required for compatible energy counters');
  }
  if (startCounter == null || endCounter == null) {
    throw new Error('startCounter and endCounter are required for compatible energy counters');
  }
  const scale = energyUnitScale(unit);
  if (state === 'valid') {
    if (endCounter < startCounter) {
      throw new Error('endCounter must be greater than or equal to startCounter when counterState=valid');
    }
    return roundMetric((endCounter - startCounter) * scale);
  }
  if (counterRolloverValue == null) {
    throw new Error('counterRolloverValue is required when counterState=wrap');
  }
  if (counterRolloverValue <= startCounter || counterRolloverValue <= endCounter) {
    throw new Error('counterRolloverValue must be greater than both counters when counterState=wrap');
  }
  return roundMetric(((counterRolloverValue - startCounter) + endCounter) * scale);
}

export function normalizeEnergyDomains(
  options: NormalizeEnergyDomainsOptions,
): readonly NormalizedEnergyDomain[] | null {
  if (options.measurements == null) return null;

  const sourceFrameCount = optionalPositiveNumber(options.sourceFrameCount, 'sourceFrameCount');
  const sourceDurationSeconds = optionalPositiveNumber(options.sourceDurationSeconds, 'sourceDurationSeconds');
  return options.measurements.map((measurement, index) => {
    const domain = normalizeEnumValue(measurement.domain, ENERGY_DOMAIN_TYPES, `measurements[${index}].domain`);
    if (domain == null) {
      throw new Error(`measurements[${index}].domain is required`);
    }
    const collector = requireText(measurement.collector, `measurements[${index}].collector`);
    const counterState = normalizeEnumValue(
      measurement.counterState ?? 'valid',
      ENERGY_COUNTER_STATES,
      `measurements[${index}].counterState`,
    );
    if (counterState == null) {
      throw new Error(`measurements[${index}].counterState is required`);
    }
    const counterUnit = normalizeEnumValue(
      measurement.counterUnit,
      ENERGY_COUNTER_UNITS,
      `measurements[${index}].counterUnit`,
    );
    const startCounter = optionalFiniteNumber(measurement.startCounter, `measurements[${index}].startCounter`);
    const endCounter = optionalFiniteNumber(measurement.endCounter, `measurements[${index}].endCounter`);
    const counterRolloverValue = optionalPositiveNumber(
      measurement.counterRolloverValue,
      `measurements[${index}].counterRolloverValue`,
    );
    const deltaJoules = computeDeltaJoules(counterState, counterUnit, startCounter, endCounter, counterRolloverValue);
    const normalized: NormalizedEnergyDomain = canonicalizeJson({
      domain,
      domainLabel: requireText(
        measurement.domainLabel ?? `${collector}:${domain}`,
        `measurements[${index}].domainLabel`,
      ),
      collector,
      collectorVersion: optionalText(measurement.collectorVersion),
      source: optionalText(measurement.source),
      counterUnit,
      counterState,
      startCounter,
      endCounter,
      counterRolloverValue,
      deltaJoules,
      joulesPerFrame: deltaJoules == null || sourceFrameCount == null ? null : roundMetric(deltaJoules / sourceFrameCount),
      joulesPerSourceSecond: deltaJoules == null || sourceDurationSeconds == null
        ? null
        : roundMetric(deltaJoules / sourceDurationSeconds),
      compatibleMeasurement: deltaJoules != null,
      error: optionalText(measurement.error),
    }) as NormalizedEnergyDomain;
    return normalized;
  });
}

export function normalizeDecodeBenchmark(
  input: DecodeBenchmarkInput | null | undefined,
): NormalizedDecodeBenchmark | null {
  if (input == null) return null;

  const status = normalizeEnumValue(input.status, DECODE_BENCHMARK_STATUSES, 'status');
  if (status == null) {
    throw new Error('status is required');
  }
  const wallTimeMs = optionalPositiveNumber(input.wallTimeMs, 'wallTimeMs');
  const decodeFps = optionalPositiveNumber(input.decodeFps, 'decodeFps');
  const sourceFps = optionalPositiveNumber(input.sourceFps, 'sourceFps');
  const cpuTimeMs = optionalPositiveNumber(input.cpuTimeMs, 'cpuTimeMs');
  const peakRssBytes = optionalPositiveNumber(input.peakRssBytes, 'peakRssBytes');
  const executionMode = normalizeEnumValue(input.executionMode, DECODE_EXECUTION_MODES, 'executionMode');
  const cacheDiscipline = normalizeEnumValue(input.cacheDiscipline, DECODE_CACHE_DISCIPLINES, 'cacheDiscipline');
  const deferredReason = optionalText(input.deferredReason);

  if (status === 'complete') {
    requireText(input.decoderImplementation ?? '', 'decoderImplementation');
    requireText(input.toolchainFingerprint ?? '', 'toolchainFingerprint');
    if (executionMode == null) {
      throw new Error('executionMode is required when status=complete');
    }
    if (cacheDiscipline == null) {
      throw new Error('cacheDiscipline is required when status=complete');
    }
    if (wallTimeMs == null || decodeFps == null || sourceFps == null) {
      throw new Error('wallTimeMs, decodeFps, and sourceFps are required when status=complete');
    }
  } else if (deferredReason == null) {
    throw new Error(`deferredReason is required when status=${status}`);
  }

  return canonicalizeJson({
    status,
    decoderImplementation: optionalText(input.decoderImplementation),
    decoderVersion: optionalText(input.decoderVersion),
    toolchainFingerprint: optionalText(input.toolchainFingerprint),
    executionMode,
    cacheDiscipline,
    wallTimeMs,
    decodeFps,
    sourceFps,
    realTimeMultiple: decodeFps == null || sourceFps == null ? null : roundMetric(decodeFps / sourceFps),
    cpuTimeMs,
    peakRssBytes,
    notes: optionalText(input.notes),
    deferredReason,
  }) as NormalizedDecodeBenchmark;
}
