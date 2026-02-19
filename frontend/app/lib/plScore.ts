import type { Benchmark } from "./types";

export type PlScoreWeights = {
  quality: number;
  size: number;
  speed: number;
};

type Range = { min: number; max: number };

export type PlScoreContext = {
  sizeBaseline: number;
  relSizeRange: Range;
  fpsRange: Range;
  fpsPerWattRange: Range;
  qualityPerWattRange: Range;
  powerRange: Range;
  cpuSpreadRange: Range;
  peakMemoryRange: Range;
};

export type PlScoreComponents = {
  quality: number;
  size: number;
  speed: number;
  efficiency: number;
  reliability: number;
  measurementConfidence: number;
};

export type PlScoreResult = PlScoreComponents & {
  core: number;
  total: number;
};

export const DEFAULT_PL_SCORE_WEIGHTS: PlScoreWeights = {
  quality: 1 / 3,
  size: 1 / 3,
  speed: 1 / 3,
};

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  if (sorted.length === 1) return sorted[0]!;
  const pos = clamp(p, 0, 1) * (sorted.length - 1);
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo]!;
  const t = pos - lo;
  return sorted[lo]! * (1 - t) + sorted[hi]! * t;
}

function robustRange(values: number[], fallbackMin: number, fallbackMax: number): Range {
  if (values.length === 0) return { min: fallbackMin, max: fallbackMax };
  const sorted = [...values].sort((a, b) => a - b);
  const minQ = percentile(sorted, 0.05);
  const maxQ = percentile(sorted, 0.95);
  if (maxQ > minQ) return { min: minQ, max: maxQ };
  const min = sorted[0]!;
  const max = sorted[sorted.length - 1]!;
  if (max > min) return { min, max };
  return { min: Math.min(min, fallbackMin), max: Math.max(max, fallbackMax) };
}

function median(values: number[]): number {
  if (values.length === 0) return 1;
  const sorted = [...values].sort((a, b) => a - b);
  return percentile(sorted, 0.5);
}

function normalizeLinear(value: number, range: Range): number {
  if (!(range.max > range.min)) return 1;
  return clamp((value - range.min) / (range.max - range.min), 0, 1);
}

function normalizeLog(value: number, range: Range): number {
  if (!(range.max > range.min) || range.min <= 0 || value <= 0) return 1;
  const lv = Math.log(value);
  const lmin = Math.log(range.min);
  const lmax = Math.log(range.max);
  if (!(lmax > lmin)) return 1;
  return clamp((lv - lmin) / (lmax - lmin), 0, 1);
}

function vmafScore(vmaf: number | null | undefined): number | null {
  if (typeof vmaf !== "number") return null;
  const v = clamp(vmaf, 0, 100);
  if (v >= 92) return 70 + 30 * Math.pow((v - 92) / 8, 0.58);
  return 70 * Math.pow(v / 92, 3.2);
}

function ssimScore(ssim: number | null | undefined): number | null {
  if (typeof ssim !== "number") return null;
  const mapped = clamp((ssim - 0.75) / 0.25, 0, 1) * 100;
  if (mapped >= 90) return 65 + 35 * Math.pow((mapped - 90) / 10, 0.55);
  return 65 * Math.pow(mapped / 90, 3.0);
}

function psnrScore(psnr: number | null | undefined): number | null {
  if (typeof psnr !== "number") return null;
  const mapped = clamp((psnr - 24) / 28, 0, 1) * 100;
  if (mapped >= 85) return 80 + 20 * Math.sqrt((mapped - 85) / 15);
  return mapped * 0.94;
}

function resolveFpsPerWatt(row: Benchmark): number | null {
  if (typeof row.fpsPerWatt === "number" && row.fpsPerWatt > 0) return row.fpsPerWatt;
  if (typeof row.fps === "number" && row.fps > 0 && typeof row.gpuPowerAvgW === "number" && row.gpuPowerAvgW > 0) {
    return row.fps / row.gpuPowerAvgW;
  }
  return null;
}

function resolveQualityPerWatt(row: Benchmark): number | null {
  if (typeof row.qualityPerWatt === "number" && row.qualityPerWatt > 0) return row.qualityPerWatt;
  if (typeof row.vmaf === "number" && row.vmaf > 0 && typeof row.gpuPowerAvgW === "number" && row.gpuPowerAvgW > 0) {
    return row.vmaf / row.gpuPowerAvgW;
  }
  return null;
}

function resolveCpuSpread(row: Benchmark): number | null {
  if (typeof row.cpuUtilAvg !== "number" || typeof row.cpuUtilMax !== "number") return null;
  return Math.max(0, row.cpuUtilMax - row.cpuUtilAvg);
}

function weightedAverage(parts: Array<{ value: number | null; weight: number }>, fallback: number): number {
  let num = 0;
  let den = 0;
  for (const part of parts) {
    if (part.value == null || !Number.isFinite(part.value)) continue;
    if (!(part.weight > 0)) continue;
    num += part.value * part.weight;
    den += part.weight;
  }
  if (!(den > 0)) return fallback;
  return num / den;
}

export function createPlScoreContext(rows: Benchmark[]): PlScoreContext {
  const fileSizes = rows.map((r) => r.fileSizeBytes).filter((v): v is number => typeof v === "number" && v > 0);
  const sizeBaseline = Math.max(1, median(fileSizes));

  const relSizes = rows
    .map((r) => (r.fileSizeBytes > 0 ? r.fileSizeBytes / sizeBaseline : null))
    .filter((v): v is number => v != null && Number.isFinite(v) && v > 0);
  const fpsValues = rows
    .map((r) => r.fps)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v) && v > 0);
  const fpsPerWattValues = rows
    .map(resolveFpsPerWatt)
    .filter((v): v is number => v != null && Number.isFinite(v) && v > 0);
  const qualityPerWattValues = rows
    .map(resolveQualityPerWatt)
    .filter((v): v is number => v != null && Number.isFinite(v) && v > 0);
  const powerValues = rows
    .map((r) => r.gpuPowerAvgW)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v) && v > 0);
  const cpuSpreadValues = rows
    .map(resolveCpuSpread)
    .filter((v): v is number => v != null && Number.isFinite(v));
  const peakMemoryValues = rows
    .map((r) => r.peakMemoryMB)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v) && v > 0);

  return {
    sizeBaseline,
    relSizeRange: robustRange(relSizes, 0.6, 1.8),
    fpsRange: robustRange(fpsValues, 8, 220),
    fpsPerWattRange: robustRange(fpsPerWattValues, 0.1, 2.8),
    qualityPerWattRange: robustRange(qualityPerWattValues, 0.1, 1.2),
    powerRange: robustRange(powerValues, 35, 320),
    cpuSpreadRange: robustRange(cpuSpreadValues, 1, 35),
    peakMemoryRange: robustRange(peakMemoryValues, 700, 16_000),
  };
}

export function computePlScoreComponentsV6(row: Benchmark, context: PlScoreContext): PlScoreComponents {
  const qualityParts: Array<{ value: number | null; weight: number }> = [
    { value: vmafScore(row.vmaf), weight: 0.55 },
    { value: ssimScore(row.ssim), weight: 0.30 },
    { value: psnrScore(row.psnr), weight: 0.15 },
  ];
  const rawQuality = weightedAverage(qualityParts, 60);
  const confidence = clamp(
    qualityParts
      .filter((p) => p.value != null)
      .reduce((acc, p) => acc + p.weight, 0),
    0,
    1,
  );
  const quality = clamp(rawQuality * (0.88 + 0.12 * confidence), 0, 100);

  const relSize = row.fileSizeBytes > 0 ? row.fileSizeBytes / context.sizeBaseline : context.relSizeRange.max;
  const size = clamp(100 * (1 - normalizeLog(relSize, context.relSizeRange)), 0, 100);
  const speed = clamp(100 * normalizeLog(Math.max(0.001, row.fps || 0), context.fpsRange), 0, 100);

  const fpsPerWatt = resolveFpsPerWatt(row);
  const qualityPerWatt = resolveQualityPerWatt(row);
  const gpuUtil = typeof row.gpuUtilAvg === "number" ? clamp(row.gpuUtilAvg, 0, 100) : null;
  const utilScore = gpuUtil == null ? null : clamp(100 - Math.abs(gpuUtil - 82) * 2.1, 0, 100);
  const powerScore =
    typeof row.gpuPowerAvgW === "number" && row.gpuPowerAvgW > 0
      ? clamp(100 * (1 - normalizeLog(row.gpuPowerAvgW, context.powerRange)), 0, 100)
      : null;

  const efficiency = clamp(
    weightedAverage(
      [
        { value: fpsPerWatt == null ? null : 100 * normalizeLog(fpsPerWatt, context.fpsPerWattRange), weight: 0.40 },
        { value: qualityPerWatt == null ? null : 100 * normalizeLog(qualityPerWatt, context.qualityPerWattRange), weight: 0.30 },
        { value: powerScore, weight: 0.20 },
        { value: utilScore, weight: 0.10 },
      ],
      50,
    ),
    0,
    100,
  );

  const cpuSpread = resolveCpuSpread(row);
  const cpuSpreadScore = cpuSpread == null ? null : clamp(100 * (1 - normalizeLinear(cpuSpread, context.cpuSpreadRange)), 0, 100);
  const memoryScore =
    typeof row.peakMemoryMB === "number" && row.peakMemoryMB > 0
      ? clamp(100 * (1 - normalizeLog(row.peakMemoryMB, context.peakMemoryRange)), 0, 100)
      : null;
  const cpuAvgScore =
    typeof row.cpuUtilAvg === "number"
      ? clamp(100 - Math.max(0, row.cpuUtilAvg - 82) * 2.2, 30, 100)
      : null;
  let reliability = weightedAverage(
    [
      { value: cpuSpreadScore, weight: 0.45 },
      { value: memoryScore, weight: 0.30 },
      { value: cpuAvgScore, weight: 0.25 },
    ],
    68,
  );
  if (row.thermalThrottle === true) reliability -= 22;
  reliability = clamp(reliability, 0, 100);

  return {
    quality,
    size,
    speed,
    efficiency,
    reliability,
    measurementConfidence: confidence,
  };
}

export function scorePlBenchmarkV6(
  row: Benchmark,
  context: PlScoreContext,
  weights: PlScoreWeights = DEFAULT_PL_SCORE_WEIGHTS,
): PlScoreResult {
  const components = computePlScoreComponentsV6(row, context);
  const wSum = Math.max(0.0001, weights.quality + weights.size + weights.speed);
  const wq = weights.quality / wSum;
  const ws = weights.size / wSum;
  const wv = weights.speed / wSum;
  const core = clamp(wq * components.quality + ws * components.size + wv * components.speed, 0, 100);
  const confidenceAdj = (components.measurementConfidence - 0.7) * 6;
  const total = clamp(core * 0.78 + components.efficiency * 0.14 + components.reliability * 0.08 + confidenceAdj, 0, 100);
  return {
    ...components,
    core,
    total,
  };
}
