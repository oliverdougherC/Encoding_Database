/** Canonical, fixed PL Score v7 utility. Personalized rankings belong to PL Fit. */
export const PL_SCORE_V7_WEIGHTS = {
  quality: 0.5,
  bitrate: 0.3,
  speed: 0.2,
} as const;

export type PlScoreV7Context = {
  scoreFormulaVersion: `7.${number}`;
  benchmarkProtocolVersion: string;
  sourceSuiteVersion: string;
  workloadId: string;
  workloadReferenceBitrateBps: number;
  vmafModelId: string;
  qualityExponent: number;
  speedCurveRate: number;
  speedSaturationRealtime: number;
};

export type PlScoreV7Input = {
  vmafMean: number | null | undefined;
  vmafP5: number | null | undefined;
  videoBitrateBps: number | null | undefined;
  encodeFps: number | null | undefined;
  sourceFps: number | null | undefined;
};

export type PlScoreV7Result = {
  version: PlScoreV7Context["scoreFormulaVersion"];
  workloadId: string;
  effectiveVmaf: number;
  realtimeRatio: number;
  components: { quality: number; bitrate: number; speed: number };
  total: number;
};

export const DEFAULT_PL_SCORE_V7_POLICY = {
  scoreFormulaVersion: "7.0",
  qualityExponent: 2.4,
  speedCurveRate: 1.2,
  speedSaturationRealtime: 4,
} as const;

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function finitePositive(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

/** Returns null rather than inventing a canonical score when any required v7 input is absent. */
export function scorePlBenchmarkV7(input: PlScoreV7Input, context: PlScoreV7Context): PlScoreV7Result | null {
  if (
    !finitePositive(input.vmafMean) ||
    !finitePositive(input.vmafP5) ||
    !finitePositive(input.videoBitrateBps) ||
    !finitePositive(input.encodeFps) ||
    !finitePositive(input.sourceFps) ||
    !finitePositive(context.workloadReferenceBitrateBps) ||
    !finitePositive(context.qualityExponent) ||
    !finitePositive(context.speedCurveRate) ||
    !finitePositive(context.speedSaturationRealtime)
  ) return null;

  const effectiveVmaf = 0.85 * clamp(input.vmafMean, 0, 100) + 0.15 * clamp(input.vmafP5, 0, 100);
  const normalizedQuality = clamp((effectiveVmaf - 20) / 80, 0, 1);
  const quality = Math.pow(normalizedQuality, context.qualityExponent);

  const bitrateRatio = input.videoBitrateBps / context.workloadReferenceBitrateBps;
  const bitrate = 1 / (1 + bitrateRatio);

  const realtimeRatio = input.encodeFps / input.sourceFps;
  const numerator = 1 - Math.exp(-context.speedCurveRate * realtimeRatio);
  const denominator = 1 - Math.exp(-context.speedCurveRate * context.speedSaturationRealtime);
  const speed = clamp(numerator / denominator, 0, 1);

  const total = 100
    * Math.pow(quality, PL_SCORE_V7_WEIGHTS.quality)
    * Math.pow(bitrate, PL_SCORE_V7_WEIGHTS.bitrate)
    * Math.pow(speed, PL_SCORE_V7_WEIGHTS.speed);

  return {
    version: context.scoreFormulaVersion,
    workloadId: context.workloadId,
    effectiveVmaf,
    realtimeRatio,
    components: { quality, bitrate, speed },
    total: clamp(total, 0, 100),
  };
}

/** Equal-content-class geometric aggregation. Missing/invalid class coverage yields no General PL. */
export function computeGeneralPlV7(classScores: readonly number[], requiredClassCount: number): number | null {
  if (!Number.isInteger(requiredClassCount) || requiredClassCount <= 0 || classScores.length !== requiredClassCount) return null;
  if (classScores.some((score) => !Number.isFinite(score) || score <= 0 || score > 100)) return null;
  return 100 * Math.exp(classScores.reduce((sum, score) => sum + Math.log(score / 100), 0) / classScores.length);
}
