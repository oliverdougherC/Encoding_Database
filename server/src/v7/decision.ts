export type CodecFamily = 'h264' | 'hevc' | 'av1' | 'vp9' | 'other';
export type EvidenceTier = 'PROVISIONAL' | 'LOW' | 'MEDIUM' | 'HIGH';
export type PlFitMode = 'balanced' | 'quality' | 'storage' | 'realtime' | 'custom';
export type BdRateMethod = 'piecewise-log-linear';

export interface DecisionHardwareContext {
  environmentId: string;
  environmentFingerprint: string;
  cpuModel: string;
  gpuModel: string;
  ramGB: number;
  os: string;
}

export interface DecisionContext {
  formulaVersion: string | null;
  benchmarkProtocolVersion: string | null;
  sourceSuiteVersion: string | null;
  qualityModelId: string | null;
  referenceContextVersion: string | null;
  workloadReferenceBitrateBps: number | null;
}

export interface CanonicalComponents {
  quality: number | null;
  bitrate: number | null;
  speed: number | null;
}

export interface NativeRateControl {
  requestedMode: string;
  effectiveMode: string;
  qualityValue: number | null;
  targetBitrateKbps: number | null;
  maxBitrateKbps: number | null;
  bufferSizeKbits: number | null;
  label: string;
}

export interface DecisionCandidate {
  rowId: string;
  encoderName: string;
  codecFamily: CodecFamily;
  preset: string;
  rateControl: NativeRateControl;
  contentClass: string;
  resolution: string;
  passes: number;
  workloadId: string;
  hardwareContext: DecisionHardwareContext;
  sampleCount: number;
  avgFps: number;
  avgVmaf: number | null;
  avgVmafP5: number | null;
  avgVideoBitrateBps: number | null;
  avgSourceFps: number | null;
  plScore: number | null;
  canonical: CanonicalComponents;
  context: DecisionContext;
  confidenceLower: number | null;
  confidenceUpper: number | null;
  evidenceTier: EvidenceTier;
  eligibleForDefaultRecommendation: boolean;
}

export interface DecisionConstraints {
  minimumQuality?: number | null;
  minimumRealtimeRatio?: number | null;
  maximumBitrateBps?: number | null;
  compatibleCodecFamilies?: CodecFamily[] | null;
  requireRecommendationEligibility?: boolean;
}

export interface DecisionWeights {
  quality: number;
  bitrate: number;
  speed: number;
}

export interface FitProfile {
  mode: PlFitMode;
  label: string;
  weights: DecisionWeights;
  constraints: DecisionConstraints;
}

export interface DecisionRequest {
  selectedMode: PlFitMode;
  selectedEnvironmentId?: string | null;
  selectedEnvironmentFingerprint?: string | null;
  customProfile?: Partial<{
    weights: Partial<DecisionWeights>;
    constraints: DecisionConstraints;
  }>;
}

export interface ConstraintStatus {
  passed: boolean;
  required: number | string | readonly string[] | boolean | null;
  actual: number | string | boolean | readonly string[] | null;
  reason: string | null;
}

export interface DecisionConstraintReport {
  minimumQuality: ConstraintStatus;
  minimumRealtimeRatio: ConstraintStatus;
  maximumBitrateBps: ConstraintStatus;
  compatibility: ConstraintStatus;
  recommendationEligibility: ConstraintStatus;
}

export interface FitEvaluation {
  mode: PlFitMode;
  label: string;
  eligible: boolean;
  score: number | null;
  rank: number;
  reasons: string[];
  weights: DecisionWeights;
  constraints: DecisionConstraintReport;
}

export interface ParetoStatus {
  available: boolean;
  efficient: boolean;
  frontierRank: number | null;
  dominatorRowIds: string[];
  dominatedRowIds: string[];
  unavailableReason: string | null;
  canonical: CanonicalComponents;
}

export interface BdRateStatus {
  available: boolean;
  valuePercent: number | null;
  versusRowId: string | null;
  versusLabel: string | null;
  method: BdRateMethod | null;
  matchedPointCount: number;
  overlapQualityRange: [number, number] | null;
  unavailableReason: string | null;
}

export interface DecisionEvidence {
  evidenceTier: EvidenceTier;
  provisional: boolean;
  eligibleForDefaultRecommendation: boolean;
  confidence: {
    available: boolean;
    lower: number | null;
    upper: number | null;
    width: number | null;
    unavailableReason: string | null;
  };
}

export interface DecisionRow extends DecisionCandidate {
  realtimeRatio: number | null;
  effectiveQuality: number | null;
  hardwareKey: string;
  hardwareLabel: string;
  fit: {
    selectedMode: PlFitMode;
    modes: Record<PlFitMode, FitEvaluation>;
    recommended: boolean;
    recommendationReason: string | null;
  };
  pareto: ParetoStatus;
  bdRate: BdRateStatus;
  evidence: DecisionEvidence;
}

export interface DecisionPayload {
  selectedMode: PlFitMode;
  profiles: Record<PlFitMode, FitProfile>;
  rows: DecisionRow[];
  recommendation: {
    rowId: string | null;
    label: string | null;
    reason: string | null;
  };
  environmentScope: {
    selectedEnvironmentId: string | null;
    selectedEnvironmentFingerprint: string | null;
    exact: boolean;
    available: Array<DecisionHardwareContext & { label: string }>;
  };
}

type CurvePoint = {
  quality: number;
  bitrateBps: number;
};

type CurveCandidate = Pick<
  DecisionCandidate,
  'rowId' | 'encoderName' | 'preset' | 'codecFamily' | 'workloadId' | 'hardwareContext' | 'avgVmaf' | 'avgVideoBitrateBps' | 'context'
>;

const MODE_ORDER: readonly PlFitMode[] = ['balanced', 'quality', 'storage', 'realtime', 'custom'] as const;
const EPSILON = 1e-9;

const PRESET_PROFILES: Record<Exclude<PlFitMode, 'custom'>, FitProfile> = {
  balanced: {
    mode: 'balanced',
    label: 'Balanced',
    weights: { quality: 0.5, bitrate: 0.3, speed: 0.2 },
    constraints: {
      minimumQuality: 90,
      minimumRealtimeRatio: 1,
      requireRecommendationEligibility: false,
    },
  },
  quality: {
    mode: 'quality',
    label: 'Quality',
    weights: { quality: 0.72, bitrate: 0.1, speed: 0.18 },
    constraints: {
      minimumQuality: 94,
      minimumRealtimeRatio: 0.75,
      requireRecommendationEligibility: false,
    },
  },
  storage: {
    mode: 'storage',
    label: 'Storage',
    weights: { quality: 0.28, bitrate: 0.56, speed: 0.16 },
    constraints: {
      minimumQuality: 90,
      maximumBitrateBps: 5_000_000,
      requireRecommendationEligibility: false,
    },
  },
  realtime: {
    mode: 'realtime',
    label: 'Realtime',
    weights: { quality: 0.2, bitrate: 0.1, speed: 0.7 },
    constraints: {
      minimumQuality: 88,
      minimumRealtimeRatio: 1,
      requireRecommendationEligibility: false,
    },
  },
};

function normalizeFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function normalizeWeights(weights: Partial<DecisionWeights> | undefined, fallback: DecisionWeights): DecisionWeights {
  const raw = {
    quality: normalizeFiniteNumber(weights?.quality) ?? fallback.quality,
    bitrate: normalizeFiniteNumber(weights?.bitrate) ?? fallback.bitrate,
    speed: normalizeFiniteNumber(weights?.speed) ?? fallback.speed,
  };
  const total = raw.quality + raw.bitrate + raw.speed;
  if (!(total > 0)) return fallback;
  return {
    quality: raw.quality / total,
    bitrate: raw.bitrate / total,
    speed: raw.speed / total,
  };
}

function buildCustomProfile(customProfile?: DecisionRequest['customProfile']): FitProfile {
  const base = PRESET_PROFILES.balanced;
  return {
    mode: 'custom',
    label: 'Custom',
    weights: normalizeWeights(customProfile?.weights, base.weights),
    constraints: {
      minimumQuality: customProfile?.constraints?.minimumQuality ?? base.constraints.minimumQuality ?? null,
      minimumRealtimeRatio: customProfile?.constraints?.minimumRealtimeRatio ?? base.constraints.minimumRealtimeRatio ?? null,
      maximumBitrateBps: customProfile?.constraints?.maximumBitrateBps ?? null,
      compatibleCodecFamilies: customProfile?.constraints?.compatibleCodecFamilies ?? null,
      requireRecommendationEligibility: customProfile?.constraints?.requireRecommendationEligibility ?? false,
    },
  };
}

export function buildFitProfiles(customProfile?: DecisionRequest['customProfile']): Record<PlFitMode, FitProfile> {
  return {
    balanced: PRESET_PROFILES.balanced,
    quality: PRESET_PROFILES.quality,
    storage: PRESET_PROFILES.storage,
    realtime: PRESET_PROFILES.realtime,
    custom: buildCustomProfile(customProfile),
  };
}

function buildHardwareKey(hardware: DecisionHardwareContext): string {
  return hardware.environmentFingerprint || hardware.environmentId;
}

function buildHardwareLabel(hardware: DecisionHardwareContext): string {
  const gpu = hardware.gpuModel.trim() ? hardware.gpuModel : 'CPU-only';
  return `${hardware.cpuModel} / ${gpu} / ${hardware.os}`;
}

function deriveRealtimeRatio(candidate: DecisionCandidate): number | null {
  if (!(candidate.avgSourceFps != null && candidate.avgSourceFps > 0)) return null;
  return candidate.avgFps / candidate.avgSourceFps;
}

function deriveEffectiveQuality(candidate: DecisionCandidate): number | null {
  if (candidate.avgVmaf == null) return null;
  const tail = candidate.avgVmafP5 ?? candidate.avgVmaf;
  return (candidate.avgVmaf * 0.85) + (tail * 0.15);
}

function buildConfidence(candidate: DecisionCandidate): DecisionEvidence['confidence'] {
  const lower = normalizeFiniteNumber(candidate.confidenceLower);
  const upper = normalizeFiniteNumber(candidate.confidenceUpper);
  if (lower == null || upper == null || upper < lower) {
    return {
      available: false,
      lower: null,
      upper: null,
      width: null,
      unavailableReason: 'Confidence interval unavailable for this aggregate scope.',
    };
  }
  return {
    available: true,
    lower,
    upper,
    width: upper - lower,
    unavailableReason: null,
  };
}

function metricStatus(
  passed: boolean,
  required: ConstraintStatus['required'],
  actual: ConstraintStatus['actual'],
  reason: string | null,
): ConstraintStatus {
  return { passed, required, actual, reason };
}

function evaluateConstraints(candidate: DecisionCandidate, profile: FitProfile): {
  eligible: boolean;
  reasons: string[];
  report: DecisionConstraintReport;
  realtimeRatio: number | null;
  effectiveQuality: number | null;
} {
  const realtimeRatio = deriveRealtimeRatio(candidate);
  const effectiveQuality = deriveEffectiveQuality(candidate);
  const reasons: string[] = [];

  const minimumQuality = profile.constraints.minimumQuality ?? null;
  const minimumQualityPassed = minimumQuality == null || (effectiveQuality != null && effectiveQuality >= minimumQuality);
  const minimumQualityReason = minimumQualityPassed ? null : `Needs effective quality >= ${minimumQuality}.`;
  if (minimumQualityReason) reasons.push(minimumQualityReason);

  const minimumRealtimeRatio = profile.constraints.minimumRealtimeRatio ?? null;
  const minimumRealtimePassed = minimumRealtimeRatio == null || (realtimeRatio != null && realtimeRatio >= minimumRealtimeRatio);
  const minimumRealtimeReason = minimumRealtimePassed ? null : `Needs realtime ratio >= ${minimumRealtimeRatio}.`;
  if (minimumRealtimeReason) reasons.push(minimumRealtimeReason);

  const maximumBitrateBps = profile.constraints.maximumBitrateBps ?? null;
  const maximumBitratePassed = maximumBitrateBps == null || (candidate.avgVideoBitrateBps != null && candidate.avgVideoBitrateBps <= maximumBitrateBps);
  const maximumBitrateReason = maximumBitratePassed ? null : `Needs bitrate <= ${maximumBitrateBps} bps.`;
  if (maximumBitrateReason) reasons.push(maximumBitrateReason);

  const compatibleCodecFamilies = profile.constraints.compatibleCodecFamilies ?? null;
  const compatibilityPassed = compatibleCodecFamilies == null || compatibleCodecFamilies.includes(candidate.codecFamily);
  const compatibilityReason = compatibilityPassed ? null : `Codec ${candidate.codecFamily} is outside the allowed compatibility set.`;
  if (compatibilityReason) reasons.push(compatibilityReason);

  const requireRecommendationEligibility = profile.constraints.requireRecommendationEligibility === true;
  const recommendationEligibilityPassed = !requireRecommendationEligibility || candidate.eligibleForDefaultRecommendation;
  const recommendationEligibilityReason = recommendationEligibilityPassed
    ? null
    : 'Recommendation evidence is below the required eligibility threshold.';
  if (recommendationEligibilityReason) reasons.push(recommendationEligibilityReason);

  return {
    eligible: reasons.length === 0,
    reasons,
    realtimeRatio,
    effectiveQuality,
    report: {
      minimumQuality: metricStatus(minimumQualityPassed, minimumQuality, effectiveQuality, minimumQualityReason),
      minimumRealtimeRatio: metricStatus(minimumRealtimePassed, minimumRealtimeRatio, realtimeRatio, minimumRealtimeReason),
      maximumBitrateBps: metricStatus(maximumBitratePassed, maximumBitrateBps, candidate.avgVideoBitrateBps, maximumBitrateReason),
      compatibility: metricStatus(
        compatibilityPassed,
        compatibleCodecFamilies,
        candidate.codecFamily,
        compatibilityReason,
      ),
      recommendationEligibility: metricStatus(
        recommendationEligibilityPassed,
        requireRecommendationEligibility,
        candidate.eligibleForDefaultRecommendation,
        recommendationEligibilityReason,
      ),
    },
  };
}

function geometricWeightedScore(components: CanonicalComponents, weights: DecisionWeights): number | null {
  const values = [components.quality, components.bitrate, components.speed];
  if (values.some((value) => value == null || value < 0)) return null;
  const q = Math.max(components.quality ?? 0, EPSILON);
  const b = Math.max(components.bitrate ?? 0, EPSILON);
  const s = Math.max(components.speed ?? 0, EPSILON);
  const total = Math.exp(
    (Math.log(q) * weights.quality)
    + (Math.log(b) * weights.bitrate)
    + (Math.log(s) * weights.speed)
  );
  return Number((total * 100).toFixed(4));
}

function compareCanonical(left: CanonicalComponents, right: CanonicalComponents): number {
  return (right.quality ?? -1) - (left.quality ?? -1)
    || (right.bitrate ?? -1) - (left.bitrate ?? -1)
    || (right.speed ?? -1) - (left.speed ?? -1);
}

function dominates(left: CanonicalComponents, right: CanonicalComponents): boolean {
  if (left.quality == null || left.bitrate == null || left.speed == null) return false;
  if (right.quality == null || right.bitrate == null || right.speed == null) return false;
  const notWorse = left.quality >= right.quality - EPSILON
    && left.bitrate >= right.bitrate - EPSILON
    && left.speed >= right.speed - EPSILON;
  const strictlyBetter = left.quality > right.quality + EPSILON
    || left.bitrate > right.bitrate + EPSILON
    || left.speed > right.speed + EPSILON;
  return notWorse && strictlyBetter;
}

function frontierLayers(candidates: ReadonlyArray<DecisionCandidate>): Map<string, number> {
  const remaining = new Map(candidates.map((candidate) => [candidate.rowId, candidate]));
  const layers = new Map<string, number>();
  let layer = 0;
  while (remaining.size > 0) {
    const current = Array.from(remaining.values());
    const efficient = current.filter((candidate) => current.every((other) => (
      other.rowId === candidate.rowId || !dominates(other.canonical, candidate.canonical)
    )));
    if (efficient.length === 0) {
      break;
    }
    for (const candidate of efficient) {
      layers.set(candidate.rowId, layer);
      remaining.delete(candidate.rowId);
    }
    layer += 1;
  }
  return layers;
}

function buildParetoMap(candidates: ReadonlyArray<DecisionCandidate>): Map<string, ParetoStatus> {
  const layers = frontierLayers(candidates);
  const map = new Map<string, ParetoStatus>();
  for (const candidate of candidates) {
    const available = candidate.canonical.quality != null
      && candidate.canonical.bitrate != null
      && candidate.canonical.speed != null;
    const dominatorRowIds = available
      ? candidates.filter((other) => other.rowId !== candidate.rowId && dominates(other.canonical, candidate.canonical)).map((row) => row.rowId)
      : [];
    const dominatedRowIds = available
      ? candidates.filter((other) => other.rowId !== candidate.rowId && dominates(candidate.canonical, other.canonical)).map((row) => row.rowId)
      : [];
    map.set(candidate.rowId, {
      available,
      efficient: available ? dominatorRowIds.length === 0 : false,
      frontierRank: available ? (layers.get(candidate.rowId) ?? null) : null,
      dominatorRowIds,
      dominatedRowIds,
      unavailableReason: available ? null : 'Canonical Q/B/S components are incomplete.',
      canonical: candidate.canonical,
    });
  }
  return map;
}

function baseRowComparator(
  left: DecisionRow,
  right: DecisionRow,
  mode: PlFitMode,
): number {
  const leftFit = left.fit.modes[mode];
  const rightFit = right.fit.modes[mode];
  const leftScore = leftFit.score ?? -1;
  const rightScore = rightFit.score ?? -1;
  return rightScore - leftScore
    || (right.plScore ?? -1) - (left.plScore ?? -1)
    || compareCanonical(left.canonical, right.canonical)
    || right.sampleCount - left.sampleCount
    || left.rowId.localeCompare(right.rowId);
}

function topologicalModeSort(rows: ReadonlyArray<DecisionRow>, mode: PlFitMode): DecisionRow[] {
  const groups = {
    eligible: rows.filter((row) => row.fit.modes[mode].eligible),
    ineligible: rows.filter((row) => !row.fit.modes[mode].eligible),
  };
  const sortGroup = (groupRows: DecisionRow[]): DecisionRow[] => {
    const indegree = new Map<string, number>(groupRows.map((row) => [row.rowId, 0]));
    const outgoing = new Map<string, string[]>(groupRows.map((row) => [row.rowId, []]));
    for (const row of groupRows) {
      for (const dominatedId of row.pareto.dominatedRowIds) {
        if (!indegree.has(dominatedId)) continue;
        indegree.set(dominatedId, (indegree.get(dominatedId) ?? 0) + 1);
        outgoing.get(row.rowId)!.push(dominatedId);
      }
    }
    const ready = groupRows.filter((row) => (indegree.get(row.rowId) ?? 0) === 0).sort((a, b) => baseRowComparator(a, b, mode));
    const ordered: DecisionRow[] = [];
    while (ready.length > 0) {
      const current = ready.shift()!;
      ordered.push(current);
      for (const targetId of outgoing.get(current.rowId) ?? []) {
        indegree.set(targetId, (indegree.get(targetId) ?? 1) - 1);
        if ((indegree.get(targetId) ?? 0) === 0) {
          const row = groupRows.find((candidate) => candidate.rowId === targetId);
          if (row) {
            ready.push(row);
            ready.sort((a, b) => baseRowComparator(a, b, mode));
          }
        }
      }
    }
    if (ordered.length !== groupRows.length) {
      return [...groupRows].sort((a, b) => baseRowComparator(a, b, mode));
    }
    return ordered;
  };
  return [...sortGroup(groups.eligible), ...sortGroup(groups.ineligible)];
}

function interpolateLogBitrate(points: readonly CurvePoint[], quality: number): number | null {
  if (points.length === 0) return null;
  if (quality < points[0]!.quality - EPSILON || quality > points[points.length - 1]!.quality + EPSILON) return null;
  for (let index = 0; index < points.length - 1; index += 1) {
    const left = points[index]!;
    const right = points[index + 1]!;
    if (quality < left.quality - EPSILON || quality > right.quality + EPSILON) continue;
    if (Math.abs(right.quality - left.quality) <= EPSILON) {
      return Math.log(Math.min(left.bitrateBps, right.bitrateBps));
    }
    const t = (quality - left.quality) / (right.quality - left.quality);
    const leftLog = Math.log(left.bitrateBps);
    const rightLog = Math.log(right.bitrateBps);
    return leftLog + ((rightLog - leftLog) * t);
  }
  const tail = points[points.length - 1]!;
  return Math.abs(tail.quality - quality) <= EPSILON ? Math.log(tail.bitrateBps) : null;
}

function normalizeCurve(points: ReadonlyArray<CurvePoint>): CurvePoint[] {
  const byQuality = new Map<number, number>();
  for (const point of points) {
    if (!(point.quality > 0) || !(point.bitrateBps > 0)) continue;
    const existing = byQuality.get(point.quality);
    if (existing == null || point.bitrateBps < existing) {
      byQuality.set(point.quality, point.bitrateBps);
    }
  }
  return Array.from(byQuality.entries())
    .map(([quality, bitrateBps]) => ({ quality, bitrateBps }))
    .sort((left, right) => left.quality - right.quality);
}

function compatibleBdRateContext(left: DecisionCandidate, right: DecisionCandidate): boolean {
  return left.workloadId === right.workloadId
    && left.context.formulaVersion != null
    && left.context.formulaVersion === right.context.formulaVersion
    && left.context.benchmarkProtocolVersion != null
    && left.context.benchmarkProtocolVersion === right.context.benchmarkProtocolVersion
    && left.context.sourceSuiteVersion != null
    && left.context.sourceSuiteVersion === right.context.sourceSuiteVersion
    && left.context.qualityModelId != null
    && left.context.qualityModelId === right.context.qualityModelId
    && left.context.referenceContextVersion != null
    && left.context.referenceContextVersion === right.context.referenceContextVersion;
}

function buildCurveKey(candidate: Pick<DecisionCandidate, 'encoderName' | 'preset' | 'codecFamily' | 'workloadId' | 'hardwareContext' | 'context'>): string {
  return [
    candidate.encoderName,
    candidate.preset,
    candidate.codecFamily,
    candidate.workloadId,
    buildHardwareKey(candidate.hardwareContext),
    candidate.context.formulaVersion ?? '',
    candidate.context.benchmarkProtocolVersion ?? '',
    candidate.context.sourceSuiteVersion ?? '',
    candidate.context.qualityModelId ?? '',
    candidate.context.referenceContextVersion ?? '',
  ].join('\u241F');
}

function computeBdRate(
  subject: DecisionCandidate,
  reference: DecisionCandidate,
  curves: Map<string, CurvePoint[]>,
): BdRateStatus {
  if (subject.rowId === reference.rowId) {
    return {
      available: false,
      valuePercent: null,
      versusRowId: reference.rowId,
      versusLabel: `${reference.encoderName} ${reference.preset}`,
      method: null,
      matchedPointCount: 0,
      overlapQualityRange: null,
      unavailableReason: 'Reference curve is the selected row itself.',
    };
  }
  if (!compatibleBdRateContext(subject, reference)) {
    return {
      available: false,
      valuePercent: null,
      versusRowId: reference.rowId,
      versusLabel: `${reference.encoderName} ${reference.preset}`,
      method: null,
      matchedPointCount: 0,
      overlapQualityRange: null,
      unavailableReason: 'BD-rate requires matched workload, protocol, suite, quality model, and score context.',
    };
  }

  const subjectCurve = normalizeCurve(curves.get(buildCurveKey(subject)) ?? []);
  const referenceCurve = normalizeCurve(curves.get(buildCurveKey(reference)) ?? []);
  if (subjectCurve.length < 4 || referenceCurve.length < 4) {
    return {
      available: false,
      valuePercent: null,
      versusRowId: reference.rowId,
      versusLabel: `${reference.encoderName} ${reference.preset}`,
      method: null,
      matchedPointCount: Math.min(subjectCurve.length, referenceCurve.length),
      overlapQualityRange: null,
      unavailableReason: 'BD-rate requires at least four bitrate-quality points per matched curve.',
    };
  }

  const overlapMin = Math.max(subjectCurve[0]!.quality, referenceCurve[0]!.quality);
  const overlapMax = Math.min(subjectCurve[subjectCurve.length - 1]!.quality, referenceCurve[referenceCurve.length - 1]!.quality);
  if (!(overlapMax > overlapMin + EPSILON)) {
    return {
      available: false,
      valuePercent: null,
      versusRowId: reference.rowId,
      versusLabel: `${reference.encoderName} ${reference.preset}`,
      method: null,
      matchedPointCount: 0,
      overlapQualityRange: null,
      unavailableReason: 'BD-rate requires overlapping quality ranges between matched curves.',
    };
  }

  const qualitySamples = Array.from(new Set([
    ...subjectCurve.map((point) => point.quality),
    ...referenceCurve.map((point) => point.quality),
  ])).filter((quality) => quality >= overlapMin - EPSILON && quality <= overlapMax + EPSILON).sort((left, right) => left - right);
  if (qualitySamples.length < 2) {
    return {
      available: false,
      valuePercent: null,
      versusRowId: reference.rowId,
      versusLabel: `${reference.encoderName} ${reference.preset}`,
      method: null,
      matchedPointCount: qualitySamples.length,
      overlapQualityRange: [overlapMin, overlapMax],
      unavailableReason: 'BD-rate requires at least two overlap samples after curve matching.',
    };
  }

  let area = 0;
  for (let index = 0; index < qualitySamples.length - 1; index += 1) {
    const start = qualitySamples[index]!;
    const end = qualitySamples[index + 1]!;
    const subjectStart = interpolateLogBitrate(subjectCurve, start);
    const subjectEnd = interpolateLogBitrate(subjectCurve, end);
    const referenceStart = interpolateLogBitrate(referenceCurve, start);
    const referenceEnd = interpolateLogBitrate(referenceCurve, end);
    if ([subjectStart, subjectEnd, referenceStart, referenceEnd].some((value) => value == null)) {
      return {
        available: false,
        valuePercent: null,
        versusRowId: reference.rowId,
        versusLabel: `${reference.encoderName} ${reference.preset}`,
        method: null,
        matchedPointCount: qualitySamples.length,
        overlapQualityRange: [overlapMin, overlapMax],
        unavailableReason: 'BD-rate interpolation failed inside the overlap range.',
      };
    }
    const deltaStart = subjectStart! - referenceStart!;
    const deltaEnd = subjectEnd! - referenceEnd!;
    area += ((deltaStart + deltaEnd) / 2) * (end - start);
  }
  const averageDelta = area / (overlapMax - overlapMin);
  return {
    available: true,
    valuePercent: Number((((Math.exp(averageDelta) - 1) * 100)).toFixed(4)),
    versusRowId: reference.rowId,
    versusLabel: `${reference.encoderName} ${reference.preset}`,
    method: 'piecewise-log-linear',
    matchedPointCount: qualitySamples.length,
    overlapQualityRange: [Number(overlapMin.toFixed(4)), Number(overlapMax.toFixed(4))],
    unavailableReason: null,
  };
}

function buildCurves(candidates: ReadonlyArray<CurveCandidate>): Map<string, CurvePoint[]> {
  const curves = new Map<string, CurvePoint[]>();
  for (const candidate of candidates) {
    if (candidate.avgVmaf == null || candidate.avgVideoBitrateBps == null || candidate.avgVideoBitrateBps <= 0) continue;
    const key = buildCurveKey({
      ...candidate,
      hardwareContext: candidate.hardwareContext,
      context: candidate.context,
    });
    const list = curves.get(key) ?? [];
    list.push({ quality: candidate.avgVmaf, bitrateBps: candidate.avgVideoBitrateBps });
    curves.set(key, list);
  }
  return curves;
}

function inferRecommendationReason(row: DecisionRow, mode: PlFitMode): string | null {
  if (!row.fit.modes[mode].eligible) return 'Disqualified by hard constraints.';
  if (!row.evidence.eligibleForDefaultRecommendation) return 'Evidence remains provisional for default recommendation use.';
  return null;
}

export function buildDecisionPayload(
  candidates: ReadonlyArray<DecisionCandidate>,
  request: DecisionRequest,
  curveCandidates: ReadonlyArray<CurveCandidate> = candidates,
): DecisionPayload {
  const profiles = buildFitProfiles(request.customProfile);
  const pareto = buildParetoMap(candidates);

  const rows: DecisionRow[] = candidates.map((candidate) => {
    const modes = {} as Record<PlFitMode, FitEvaluation>;
    for (const mode of MODE_ORDER) {
      const profile = profiles[mode];
      const evaluation = evaluateConstraints(candidate, profile);
      const score = evaluation.eligible
        ? (mode === 'balanced' ? candidate.plScore : geometricWeightedScore(candidate.canonical, profile.weights))
        : null;
      modes[mode] = {
        mode,
        label: profile.label,
        eligible: evaluation.eligible,
        score,
        rank: 0,
        reasons: evaluation.reasons,
        weights: profile.weights,
        constraints: evaluation.report,
      };
    }
    const evidence = {
      evidenceTier: candidate.evidenceTier,
      provisional: candidate.evidenceTier === 'PROVISIONAL',
      eligibleForDefaultRecommendation: candidate.eligibleForDefaultRecommendation,
      confidence: buildConfidence(candidate),
    };
    return {
      ...candidate,
      realtimeRatio: deriveRealtimeRatio(candidate),
      effectiveQuality: deriveEffectiveQuality(candidate),
      hardwareKey: buildHardwareKey(candidate.hardwareContext),
      hardwareLabel: buildHardwareLabel(candidate.hardwareContext),
      fit: {
        selectedMode: request.selectedMode,
        modes,
        recommended: false,
        recommendationReason: null,
      },
      pareto: pareto.get(candidate.rowId)!,
      bdRate: {
        available: false,
        valuePercent: null,
        versusRowId: null,
        versusLabel: null,
        method: null,
        matchedPointCount: 0,
        overlapQualityRange: null,
        unavailableReason: 'No reference recommendation selected yet.',
      },
      evidence,
    };
  });

  for (const mode of MODE_ORDER) {
    const ordered = topologicalModeSort(rows, mode);
    ordered.forEach((row, index) => {
      row.fit.modes[mode].rank = index + 1;
    });
  }

  const orderedForSelectedMode = [...rows].sort((left, right) => (
    left.fit.modes[request.selectedMode].rank - right.fit.modes[request.selectedMode].rank
  ));
  const recommendation = orderedForSelectedMode.find((row) => (
    row.fit.modes[request.selectedMode].eligible && row.evidence.eligibleForDefaultRecommendation
  )) ?? null;

  if (recommendation) {
    recommendation.fit.recommended = true;
    recommendation.fit.recommendationReason = 'Best eligible PL Fit result after hard constraints, evidence gating, and Pareto ordering.';
  }
  for (const row of rows) {
    if (!row.fit.recommended) {
      row.fit.recommendationReason = inferRecommendationReason(row, request.selectedMode);
    }
  }

  const curves = buildCurves(curveCandidates);
  for (const row of rows) {
    row.bdRate = recommendation
      ? computeBdRate(row, recommendation, curves)
      : {
          available: false,
          valuePercent: null,
          versusRowId: null,
          versusLabel: null,
          method: null,
          matchedPointCount: 0,
          overlapQualityRange: null,
          unavailableReason: 'No recommendation passed the evidence gate for BD-rate comparison.',
        };
  }

  return {
    selectedMode: request.selectedMode,
    profiles,
    rows: [...rows].sort((left, right) => (
      left.fit.modes[request.selectedMode].rank - right.fit.modes[request.selectedMode].rank
    )),
    recommendation: recommendation
      ? {
          rowId: recommendation.rowId,
          label: `${recommendation.encoderName} ${recommendation.preset}`,
          reason: recommendation.fit.recommendationReason,
        }
      : {
          rowId: null,
          label: null,
          reason: 'No row satisfied both the selected hard constraints and the evidence gate.',
        },
    environmentScope: {
      selectedEnvironmentId: request.selectedEnvironmentId ?? null,
      selectedEnvironmentFingerprint: request.selectedEnvironmentFingerprint ?? null,
      exact: Boolean(request.selectedEnvironmentId || request.selectedEnvironmentFingerprint),
      available: Array.from(new Map(candidates.map((candidate) => {
        const hardware = candidate.hardwareContext;
        return [buildHardwareKey(hardware), { ...hardware, label: buildHardwareLabel(hardware) }];
      })).values()).sort((left, right) => left.label.localeCompare(right.label)),
    },
  };
}
