export const PL_SCORE_V7_VERSION = '7.0' as const;

export type PlScoreV7Input = {
  vmafMean: number | null;
  vmafP5: number | null;
  videoBitrateBps: number | null;
  encodeFps: number | null;
  sourceFps: number | null;
};

export type PlScoreV7Context = {
  workloadId: string;
  workloadReferenceBitrateBps: number;
  scoreFormulaVersion?: typeof PL_SCORE_V7_VERSION;
  qualityExponent?: number;
  speedCurveRate?: number;
  speedSaturationRealtime?: number;
};

export type PlScoreV7Result = {
  scoreFormulaVersion: typeof PL_SCORE_V7_VERSION;
  workloadId: string;
  total: number;
  effectiveVmaf: number;
  realtimeRatio: number;
  quality: number;
  bitrate: number;
  speed: number;
};

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(max, value));
const positive = (value: number | null | undefined): value is number => typeof value === 'number' && Number.isFinite(value) && value > 0;

export function computePlScoreV7(input: PlScoreV7Input, context: PlScoreV7Context): PlScoreV7Result | null {
  const qualityExponent = context.qualityExponent ?? 2.4;
  const speedCurveRate = context.speedCurveRate ?? 1.2;
  const speedSaturationRealtime = context.speedSaturationRealtime ?? 4;
  if (!positive(input.vmafMean) || !positive(input.vmafP5) || !positive(input.videoBitrateBps)
    || !positive(input.encodeFps) || !positive(input.sourceFps) || !positive(context.workloadReferenceBitrateBps)
    || !positive(qualityExponent) || !positive(speedCurveRate) || !positive(speedSaturationRealtime)) return null;

  const effectiveVmaf = 0.85 * clamp(input.vmafMean, 0, 100) + 0.15 * clamp(input.vmafP5, 0, 100);
  const quality = Math.pow(clamp((effectiveVmaf - 20) / 80, 0, 1), qualityExponent);
  const bitrate = 1 / (1 + input.videoBitrateBps / context.workloadReferenceBitrateBps);
  const realtimeRatio = input.encodeFps / input.sourceFps;
  const speed = clamp(
    (1 - Math.exp(-speedCurveRate * realtimeRatio)) / (1 - Math.exp(-speedCurveRate * speedSaturationRealtime)),
    0,
    1,
  );
  const total = 100 * Math.pow(quality, 0.5) * Math.pow(bitrate, 0.3) * Math.pow(speed, 0.2);
  return {
    scoreFormulaVersion: PL_SCORE_V7_VERSION,
    workloadId: context.workloadId,
    total: clamp(total, 0, 100),
    effectiveVmaf,
    realtimeRatio,
    quality,
    bitrate,
    speed,
  };
}

export function parseWorkloadReferenceContexts(raw: string | undefined): ReadonlyMap<string, number> {
  if (!raw) return new Map();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return new Map();
    return new Map(Object.entries(parsed).filter((entry): entry is [string, number] => positive(entry[1] as number)));
  } catch {
    return new Map();
  }
}
