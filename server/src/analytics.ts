import type { Benchmark } from '@prisma/client';
import type { Prisma } from '@prisma/client';

export const DEFAULT_ANALYTICS_FILTERS = {
  contentClass: 'mixed',
  resolution: '1080p',
  crf: 24,
  passes: 1,
  minSamples: 3,
} as const;

const VALID_CONTENT_CLASSES = ['mixed', 'talkingHead', 'action', 'animation', 'screen', 'nature', 'gaming'] as const;
const VALID_RESOLUTIONS = ['480p', '720p', '1080p', '1440p', '4k'] as const;

export type CodecFamily = 'h264' | 'hevc' | 'av1' | 'vp9' | 'other';

export type AnalyticsFilters = {
  contentClass: string;
  resolution: string;
  crf: number;
  passes: 1;
  minSamples: number;
};

export type LeaderboardAnalyticsRow = {
  encoderName: string;
  codecFamily: CodecFamily;
  preset: string;
  crf: number;
  contentClass: string;
  resolution: string;
  passes: number;
  sampleCount: number;
  avgFps: number;
  avgVmaf: number | null;
  avgSsim: number | null;
  avgPsnr: number | null;
  avgSizeBytes: number;
  avgPowerW: number | null;
  fpsPerWatt: number | null;
  qualityPerWatt: number | null;
  plScore: number;
};

export type HardwareAnalyticsRow = {
  cpuModel: string;
  gpuModel: string;
  encoderName: string;
  codecFamily: CodecFamily;
  preset: string;
  crf: number;
  contentClass: string;
  resolution: string;
  passes: number;
  sampleCount: number;
  avgFps: number;
  avgVmaf: number | null;
  avgPowerW: number | null;
  fpsPerWatt: number | null;
  score: number;
};

export type EncoderAnalyticsRow = {
  encoderName: string;
  codecFamily: CodecFamily;
  preset: string;
  crf: number;
  contentClass: string;
  resolution: string;
  passes: number;
  sampleCount: number;
  avgFps: number;
  avgVmaf: number | null;
  avgSsim: number | null;
  avgPsnr: number | null;
  avgSizeBytes: number;
};

type AggregatedMetrics = {
  sampleCount: number;
  fpsSum: number;
  sizeSum: number;
  vmafSum: number;
  vmafSamples: number;
  ssimSum: number;
  ssimSamples: number;
  psnrSum: number;
  psnrSamples: number;
  powerSum: number;
  powerSamples: number;
  cpuUtilSum: number;
  cpuUtilSamples: number;
  peakMemoryMax: number | null;
  thermalThrottle: boolean;
};

type ScoreRow = {
  fps: number;
  fileSizeBytes: number;
  vmaf: number | null;
  ssim: number | null;
  psnr: number | null;
  gpuPowerAvgW: number | null;
  cpuUtilAvg: number | null;
  cpuUtilMax: number | null;
  peakMemoryMB: number | null;
  thermalThrottle: boolean | null;
  fpsPerWatt?: number | null;
  qualityPerWatt?: number | null;
};

type ScoreRange = { min: number; max: number };

type PlScoreContext = {
  sizeBaseline: number;
  relSizeRange: ScoreRange;
  fpsRange: ScoreRange;
  fpsPerWattRange: ScoreRange;
  qualityPerWattRange: ScoreRange;
  powerRange: ScoreRange;
  cpuSpreadRange: ScoreRange;
  peakMemoryRange: ScoreRange;
};

type GroupAccumulator<Key extends Record<string, string | number>> = Key & AggregatedMetrics;

function asPositiveInt(raw: string | undefined, fallback: number): number {
  if (!raw) return fallback;
  if (!/^\d+$/.test(raw.trim())) return fallback;
  const parsed = Number(raw);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) return fallback;
  return parsed;
}

export function parseAnalyticsFilters(query: Record<string, string | undefined>): AnalyticsFilters {
  const contentClass = VALID_CONTENT_CLASSES.includes(query.contentClass as typeof VALID_CONTENT_CLASSES[number])
    ? String(query.contentClass)
    : DEFAULT_ANALYTICS_FILTERS.contentClass;
  const resolution = VALID_RESOLUTIONS.includes(query.resolution as typeof VALID_RESOLUTIONS[number])
    ? String(query.resolution)
    : DEFAULT_ANALYTICS_FILTERS.resolution;
  const crf = asPositiveInt(query.crf, DEFAULT_ANALYTICS_FILTERS.crf);
  const passes = query.passes === '1' ? 1 : DEFAULT_ANALYTICS_FILTERS.passes;
  const minSamples = asPositiveInt(query.minSamples, DEFAULT_ANALYTICS_FILTERS.minSamples);
  return { contentClass, resolution, crf, passes, minSamples };
}

export function buildAnalyticsWhere(filters: AnalyticsFilters): Prisma.BenchmarkWhereInput {
  return {
    status: 'accepted',
    contentClass: filters.contentClass,
    resolution: filters.resolution,
    crf: filters.crf,
    passes: filters.passes,
  };
}

export function resolveEncoderName(row: Pick<Benchmark, 'codec' | 'encoderName'>): string {
  const encoderName = row.encoderName?.trim();
  return encoderName || row.codec;
}

export function deriveCodecFamily(value: string | null | undefined): CodecFamily {
  const codec = String(value || '').toLowerCase();
  if (codec.includes('av1')) return 'av1';
  if (codec.includes('265') || codec.includes('hevc') || codec.includes('x265')) return 'hevc';
  if (codec.includes('264') || codec.includes('avc') || codec.includes('x264')) return 'h264';
  if (codec.includes('vp9') || codec.includes('libvpx')) return 'vp9';
  return 'other';
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  if (sorted.length === 1) return sorted[0] ?? 0;
  const pos = clamp(p, 0, 1) * (sorted.length - 1);
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo] ?? 0;
  const t = pos - lo;
  return (sorted[lo] ?? 0) * (1 - t) + (sorted[hi] ?? 0) * t;
}

function median(values: number[]): number {
  if (values.length === 0) return 1;
  return percentile([...values].sort((a, b) => a - b), 0.5);
}

function robustRange(values: number[], fallbackMin: number, fallbackMax: number): ScoreRange {
  if (values.length === 0) return { min: fallbackMin, max: fallbackMax };
  const sorted = [...values].sort((a, b) => a - b);
  const minQ = percentile(sorted, 0.05);
  const maxQ = percentile(sorted, 0.95);
  if (maxQ > minQ) return { min: minQ, max: maxQ };
  const min = sorted[0] ?? fallbackMin;
  const max = sorted[sorted.length - 1] ?? fallbackMax;
  if (max > min) return { min, max };
  return { min: Math.min(min, fallbackMin), max: Math.max(max, fallbackMax) };
}

function normalizeLinear(value: number, range: ScoreRange): number {
  if (!(range.max > range.min)) return 1;
  return clamp((value - range.min) / (range.max - range.min), 0, 1);
}

function normalizeLog(value: number, range: ScoreRange): number {
  if (!(range.max > range.min) || range.min <= 0 || value <= 0) return 1;
  const lv = Math.log(value);
  const lmin = Math.log(range.min);
  const lmax = Math.log(range.max);
  if (!(lmax > lmin)) return 1;
  return clamp((lv - lmin) / (lmax - lmin), 0, 1);
}

function vmafScore(vmaf: number | null): number | null {
  if (typeof vmaf !== 'number') return null;
  const v = clamp(vmaf, 0, 100);
  if (v >= 92) return 70 + 30 * Math.pow((v - 92) / 8, 0.58);
  return 70 * Math.pow(v / 92, 3.2);
}

function ssimScore(ssim: number | null): number | null {
  if (typeof ssim !== 'number') return null;
  const mapped = clamp((ssim - 0.75) / 0.25, 0, 1) * 100;
  if (mapped >= 90) return 65 + 35 * Math.pow((mapped - 90) / 10, 0.55);
  return 65 * Math.pow(mapped / 90, 3.0);
}

function psnrScore(psnr: number | null): number | null {
  if (typeof psnr !== 'number') return null;
  const mapped = clamp((psnr - 24) / 28, 0, 1) * 100;
  if (mapped >= 85) return 80 + 20 * Math.sqrt((mapped - 85) / 15);
  return mapped * 0.94;
}

function resolveFpsPerWatt(row: ScoreRow): number | null {
  if (typeof row.fpsPerWatt === 'number' && row.fpsPerWatt > 0) return row.fpsPerWatt;
  if (row.fps > 0 && row.gpuPowerAvgW != null && row.gpuPowerAvgW > 0) {
    return row.fps / row.gpuPowerAvgW;
  }
  return null;
}

function resolveQualityPerWatt(row: ScoreRow): number | null {
  if (typeof row.qualityPerWatt === 'number' && row.qualityPerWatt > 0) return row.qualityPerWatt;
  if (row.vmaf != null && row.vmaf > 0 && row.gpuPowerAvgW != null && row.gpuPowerAvgW > 0) {
    return row.vmaf / row.gpuPowerAvgW;
  }
  return null;
}

function weightedAverage(parts: Array<{ value: number | null; weight: number }>, fallback: number): number {
  let num = 0;
  let den = 0;
  for (const part of parts) {
    if (part.value == null || !Number.isFinite(part.value) || !(part.weight > 0)) continue;
    num += part.value * part.weight;
    den += part.weight;
  }
  if (!(den > 0)) return fallback;
  return num / den;
}

function resolveCpuSpread(row: ScoreRow): number | null {
  if (row.cpuUtilAvg == null || row.cpuUtilMax == null) return null;
  return Math.max(0, row.cpuUtilMax - row.cpuUtilAvg);
}

function createPlScoreContext(rows: ScoreRow[]): PlScoreContext {
  const fileSizes = rows.map((row) => row.fileSizeBytes).filter((value) => value > 0);
  const sizeBaseline = Math.max(1, median(fileSizes));
  const relSizes = rows
    .map((row) => row.fileSizeBytes > 0 ? row.fileSizeBytes / sizeBaseline : null)
    .filter((value): value is number => value != null && value > 0);
  const fpsValues = rows.map((row) => row.fps).filter((value) => value > 0);
  const fpsPerWattValues = rows
    .map(resolveFpsPerWatt)
    .filter((value): value is number => value != null && value > 0);
  const qualityPerWattValues = rows
    .map(resolveQualityPerWatt)
    .filter((value): value is number => value != null && value > 0);
  const powerValues = rows
    .map((row) => row.gpuPowerAvgW)
    .filter((value): value is number => value != null && value > 0);
  const cpuSpreadValues = rows
    .map(resolveCpuSpread)
    .filter((value): value is number => value != null && Number.isFinite(value));
  const peakMemoryValues = rows
    .map((row) => row.peakMemoryMB)
    .filter((value): value is number => value != null && value > 0);
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

function computePlScore(row: ScoreRow, context: PlScoreContext): number {
  const qualityParts = [
    { value: vmafScore(row.vmaf), weight: 0.55 },
    { value: ssimScore(row.ssim), weight: 0.30 },
    { value: psnrScore(row.psnr), weight: 0.15 },
  ];
  const rawQuality = weightedAverage(qualityParts, 60);
  const confidence = clamp(
    qualityParts.filter((part) => part.value != null).reduce((sum, part) => sum + part.weight, 0),
    0,
    1,
  );
  const quality = clamp(rawQuality * (0.88 + 0.12 * confidence), 0, 100);
  const relSize = row.fileSizeBytes > 0 ? row.fileSizeBytes / context.sizeBaseline : context.relSizeRange.max;
  const size = clamp(100 * (1 - normalizeLog(relSize, context.relSizeRange)), 0, 100);
  const speed = clamp(100 * normalizeLog(Math.max(0.001, row.fps), context.fpsRange), 0, 100);
  const fpsPerWatt = resolveFpsPerWatt(row);
  const qualityPerWatt = resolveQualityPerWatt(row);
  const powerScore = row.gpuPowerAvgW != null && row.gpuPowerAvgW > 0
    ? clamp(100 * (1 - normalizeLog(row.gpuPowerAvgW, context.powerRange)), 0, 100)
    : null;
  const efficiency = clamp(weightedAverage([
    { value: fpsPerWatt == null ? null : 100 * normalizeLog(fpsPerWatt, context.fpsPerWattRange), weight: 0.40 },
    { value: qualityPerWatt == null ? null : 100 * normalizeLog(qualityPerWatt, context.qualityPerWattRange), weight: 0.30 },
    { value: powerScore, weight: 0.20 },
  ], 50), 0, 100);
  const cpuSpread = resolveCpuSpread(row);
  const cpuSpreadScore = cpuSpread == null ? null : clamp(100 * (1 - normalizeLinear(cpuSpread, context.cpuSpreadRange)), 0, 100);
  const memoryScore = row.peakMemoryMB != null && row.peakMemoryMB > 0
    ? clamp(100 * (1 - normalizeLog(row.peakMemoryMB, context.peakMemoryRange)), 0, 100)
    : null;
  let reliability = weightedAverage([
    { value: cpuSpreadScore, weight: 0.45 },
    { value: memoryScore, weight: 0.30 },
  ], 68);
  if (row.thermalThrottle === true) reliability -= 22;
  reliability = clamp(reliability, 0, 100);
  const core = clamp((quality + size + speed) / 3, 0, 100);
  const confidenceAdj = (confidence - 0.7) * 6;
  return clamp(core * 0.78 + efficiency * 0.14 + reliability * 0.08 + confidenceAdj, 0, 100);
}

function initMetrics(): AggregatedMetrics {
  return {
    sampleCount: 0,
    fpsSum: 0,
    sizeSum: 0,
    vmafSum: 0,
    vmafSamples: 0,
    ssimSum: 0,
    ssimSamples: 0,
    psnrSum: 0,
    psnrSamples: 0,
    powerSum: 0,
    powerSamples: 0,
    cpuUtilSum: 0,
    cpuUtilSamples: 0,
    peakMemoryMax: null,
    thermalThrottle: false,
  };
}

function accumulateMetrics(target: AggregatedMetrics, row: Benchmark): void {
  target.sampleCount += Math.max(0, row.samples);
  target.fpsSum += row.fpsSum;
  target.sizeSum += row.fileSizeSum;
  target.vmafSum += row.vmafSum;
  target.vmafSamples += row.vmafSamples;
  target.ssimSum += row.ssimSum;
  target.ssimSamples += row.ssimSamples;
  target.psnrSum += row.psnrSum;
  target.psnrSamples += row.psnrSamples;
  target.powerSum += row.gpuPowerSum;
  target.powerSamples += row.gpuPowerSamples;
  target.cpuUtilSum += row.cpuUtilSum;
  target.cpuUtilSamples += row.cpuUtilSamples;
  if (row.peakMemoryMax != null) {
    target.peakMemoryMax = target.peakMemoryMax == null
      ? row.peakMemoryMax
      : Math.max(target.peakMemoryMax, row.peakMemoryMax);
  }
  if (row.thermalThrottle === true) {
    target.thermalThrottle = true;
  }
}

function finalizeAverage(sum: number, count: number): number | null {
  if (!(count > 0)) return null;
  return sum / count;
}

function finalizeSize(sum: number, count: number): number {
  if (!(count > 0)) return 0;
  return Math.round(sum / count);
}

export function aggregateLeaderboards(rows: Benchmark[], minSamples: number): LeaderboardAnalyticsRow[] {
  const grouped = new Map<string, GroupAccumulator<{
    encoderName: string;
    codecFamily: CodecFamily;
    preset: string;
    crf: number;
    contentClass: string;
    resolution: string;
    passes: number;
  }>>();

  for (const row of rows) {
    const encoderName = resolveEncoderName(row);
    const key = [
      encoderName,
      row.preset,
      row.crf,
      row.contentClass,
      row.resolution,
      row.passes,
    ].join('\u241F');
    const existing = grouped.get(key) ?? {
      encoderName,
      codecFamily: deriveCodecFamily(encoderName),
      preset: row.preset,
      crf: row.crf,
      contentClass: row.contentClass,
      resolution: row.resolution,
      passes: row.passes,
      ...initMetrics(),
    };
    accumulateMetrics(existing, row);
    grouped.set(key, existing);
  }

  const items = Array.from(grouped.values())
    .filter((entry) => entry.sampleCount >= minSamples)
    .map((entry) => ({
      encoderName: entry.encoderName,
      codecFamily: entry.codecFamily,
      preset: entry.preset,
      crf: entry.crf,
      contentClass: entry.contentClass,
      resolution: entry.resolution,
      passes: entry.passes,
      sampleCount: entry.sampleCount,
      avgFps: Number((entry.fpsSum / entry.sampleCount).toFixed(4)),
      avgVmaf: finalizeAverage(entry.vmafSum, entry.vmafSamples),
      avgSsim: finalizeAverage(entry.ssimSum, entry.ssimSamples),
      avgPsnr: finalizeAverage(entry.psnrSum, entry.psnrSamples),
      avgSizeBytes: finalizeSize(entry.sizeSum, entry.sampleCount),
      avgPowerW: finalizeAverage(entry.powerSum, entry.powerSamples),
      fpsPerWatt: null as number | null,
      qualityPerWatt: null as number | null,
      plScore: 0,
    }));

  for (const item of items) {
    item.fpsPerWatt = item.avgPowerW != null && item.avgPowerW > 0 ? Number((item.avgFps / item.avgPowerW).toFixed(4)) : null;
    item.qualityPerWatt = item.avgPowerW != null && item.avgPowerW > 0 && item.avgVmaf != null
      ? Number((item.avgVmaf / item.avgPowerW).toFixed(4))
      : null;
  }

  const context = createPlScoreContext(items.map((item) => ({
    fps: item.avgFps,
    fileSizeBytes: item.avgSizeBytes,
    vmaf: item.avgVmaf,
    ssim: item.avgSsim,
    psnr: item.avgPsnr,
    gpuPowerAvgW: item.avgPowerW,
    cpuUtilAvg: null,
    cpuUtilMax: null,
    peakMemoryMB: null,
    thermalThrottle: false,
    fpsPerWatt: item.fpsPerWatt,
    qualityPerWatt: item.qualityPerWatt,
  })));

  for (const item of items) {
    item.plScore = Number(computePlScore({
      fps: item.avgFps,
      fileSizeBytes: item.avgSizeBytes,
      vmaf: item.avgVmaf,
      ssim: item.avgSsim,
      psnr: item.avgPsnr,
      gpuPowerAvgW: item.avgPowerW,
      cpuUtilAvg: null,
      cpuUtilMax: null,
      peakMemoryMB: null,
      thermalThrottle: false,
      fpsPerWatt: item.fpsPerWatt,
      qualityPerWatt: item.qualityPerWatt,
    }, context).toFixed(4));
  }

  return items.sort((a, b) => b.plScore - a.plScore || b.avgFps - a.avgFps);
}

export function aggregateHardware(rows: Benchmark[], minSamples: number): HardwareAnalyticsRow[] {
  const grouped = new Map<string, GroupAccumulator<{
    cpuModel: string;
    gpuModel: string;
    encoderName: string;
    codecFamily: CodecFamily;
    preset: string;
    crf: number;
    contentClass: string;
    resolution: string;
    passes: number;
  }>>();

  for (const row of rows) {
    const encoderName = resolveEncoderName(row);
    const key = [
      row.cpuModel,
      row.gpuModel,
      encoderName,
      row.preset,
      row.crf,
      row.contentClass,
      row.resolution,
      row.passes,
    ].join('\u241F');
    const existing = grouped.get(key) ?? {
      cpuModel: row.cpuModel,
      gpuModel: row.gpuModel,
      encoderName,
      codecFamily: deriveCodecFamily(encoderName),
      preset: row.preset,
      crf: row.crf,
      contentClass: row.contentClass,
      resolution: row.resolution,
      passes: row.passes,
      ...initMetrics(),
    };
    accumulateMetrics(existing, row);
    grouped.set(key, existing);
  }

  const items = Array.from(grouped.values())
    .filter((entry) => entry.sampleCount >= minSamples)
    .map((entry) => {
      const avgFps = entry.sampleCount > 0 ? entry.fpsSum / entry.sampleCount : 0;
      const avgVmaf = finalizeAverage(entry.vmafSum, entry.vmafSamples);
      const avgPowerW = finalizeAverage(entry.powerSum, entry.powerSamples);
      const fpsPerWatt = avgPowerW != null && avgPowerW > 0 ? avgFps / avgPowerW : null;
      return {
        cpuModel: entry.cpuModel,
        gpuModel: entry.gpuModel,
        encoderName: entry.encoderName,
        codecFamily: entry.codecFamily,
        preset: entry.preset,
        crf: entry.crf,
        contentClass: entry.contentClass,
        resolution: entry.resolution,
        passes: entry.passes,
        sampleCount: entry.sampleCount,
        avgFps: Number(avgFps.toFixed(4)),
        avgVmaf: avgVmaf == null ? null : Number(avgVmaf.toFixed(4)),
        avgPowerW: avgPowerW == null ? null : Number(avgPowerW.toFixed(4)),
        fpsPerWatt: fpsPerWatt == null ? null : Number(fpsPerWatt.toFixed(4)),
        score: 0,
      };
    });

  let maxFps = 1;
  let maxVmaf = 1;
  let maxEff = 1;
  for (const item of items) {
    if (item.avgFps > maxFps) maxFps = item.avgFps;
    if (item.avgVmaf != null && item.avgVmaf > maxVmaf) maxVmaf = item.avgVmaf;
    if (item.fpsPerWatt != null && item.fpsPerWatt > maxEff) maxEff = item.fpsPerWatt;
  }

  for (const item of items) {
    const speedScore = item.avgFps / maxFps;
    const qualityScore = item.avgVmaf != null ? item.avgVmaf / maxVmaf : 0.5;
    const effScore = item.fpsPerWatt != null ? item.fpsPerWatt / maxEff : 0.3;
    item.score = Number((0.4 * speedScore + 0.35 * qualityScore + 0.25 * effScore).toFixed(4));
  }

  return items.sort((a, b) => b.score - a.score || b.avgFps - a.avgFps);
}

export function aggregateEncoders(rows: Benchmark[], minSamples: number): EncoderAnalyticsRow[] {
  const grouped = new Map<string, GroupAccumulator<{
    encoderName: string;
    codecFamily: CodecFamily;
    preset: string;
    crf: number;
    contentClass: string;
    resolution: string;
    passes: number;
  }>>();

  for (const row of rows) {
    const encoderName = resolveEncoderName(row);
    const key = [
      encoderName,
      row.preset,
      row.crf,
      row.contentClass,
      row.resolution,
      row.passes,
    ].join('\u241F');
    const existing = grouped.get(key) ?? {
      encoderName,
      codecFamily: deriveCodecFamily(encoderName),
      preset: row.preset,
      crf: row.crf,
      contentClass: row.contentClass,
      resolution: row.resolution,
      passes: row.passes,
      ...initMetrics(),
    };
    accumulateMetrics(existing, row);
    grouped.set(key, existing);
  }

  return Array.from(grouped.values())
    .filter((entry) => entry.sampleCount >= minSamples)
    .map((entry) => ({
      encoderName: entry.encoderName,
      codecFamily: entry.codecFamily,
      preset: entry.preset,
      crf: entry.crf,
      contentClass: entry.contentClass,
      resolution: entry.resolution,
      passes: entry.passes,
      sampleCount: entry.sampleCount,
      avgFps: Number((entry.fpsSum / entry.sampleCount).toFixed(4)),
      avgVmaf: finalizeAverage(entry.vmafSum, entry.vmafSamples),
      avgSsim: finalizeAverage(entry.ssimSum, entry.ssimSamples),
      avgPsnr: finalizeAverage(entry.psnrSum, entry.psnrSamples),
      avgSizeBytes: finalizeSize(entry.sizeSum, entry.sampleCount),
    }))
    .sort((a, b) => a.encoderName.localeCompare(b.encoderName) || a.preset.localeCompare(b.preset));
}

export function addDerivedBenchmarkFields(row: Benchmark): Benchmark & {
  codecFamily: CodecFamily;
  fpsPerWatt: number | null;
  qualityPerWatt: number | null;
} {
  const encoderName = resolveEncoderName(row);
  const fpsPerWatt = row.fps > 0 && row.gpuPowerAvgW != null && row.gpuPowerAvgW > 0
    ? Math.round((row.fps / row.gpuPowerAvgW) * 100) / 100
    : null;
  const qualityPerWatt = row.vmaf != null && row.gpuPowerAvgW != null && row.gpuPowerAvgW > 0
    ? Math.round((row.vmaf / row.gpuPowerAvgW) * 100) / 100
    : null;
  return {
    ...row,
    encoderName,
    codecFamily: deriveCodecFamily(encoderName),
    fpsPerWatt,
    qualityPerWatt,
  };
}
