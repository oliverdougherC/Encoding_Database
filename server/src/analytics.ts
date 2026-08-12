import type { Benchmark } from '@prisma/client';
import type { Prisma } from '@prisma/client';
import { computePlScoreV7, parseWorkloadReferenceContexts, PL_SCORE_V7_VERSION } from './plScore.js';

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
  workloadId: string | null;
  contentClass: string;
  resolution: string;
  crf: number;
  passes: 1;
  minSamples: number;
  fitMode: 'balanced' | 'quality' | 'storage' | 'realtime' | 'custom';
  customQualityWeight: number | null;
  customBitrateWeight: number | null;
  customSpeedWeight: number | null;
  minimumQuality: number | null;
  minimumRealtimeRatio: number | null;
  maximumBitrateBps: number | null;
  compatibleCodecFamilies: CodecFamily[] | null;
  requireRecommendationEligibility: boolean;
  environmentId: string | null;
  environmentFingerprint: string | null;
};

export type LeaderboardAnalyticsRow = {
  encoderName: string;
  codecFamily: CodecFamily;
  preset: string;
  crf: number;
  contentClass: string;
  resolution: string;
  passes: number;
  rowId: string;
  hardwareContext: {
    cpuModel: string;
    gpuModel: string;
    ramGB: number;
    os: string;
  };
  sampleCount: number;
  avgFps: number;
  avgVmaf: number | null;
  avgVmafP5: number | null;
  avgSsim: number | null;
  avgPsnr: number | null;
  avgSizeBytes: number;
  avgVideoBitrateBps: number | null;
  avgSourceFps: number | null;
  avgPowerW: number | null;
  fpsPerWatt: number | null;
  qualityPerWatt: number | null;
  plScore: number | null;
  plScoreVersion: typeof PL_SCORE_V7_VERSION;
  plScoreComponents: { quality: number; bitrate: number; speed: number } | null;
  plScoreWorkloadId: string;
  scoreFormulaVersion: string | null;
  benchmarkProtocolVersion: string | null;
  sourceSuiteVersion: string | null;
  qualityModelId: string | null;
  plScoreContext: {
    formulaVersion: string | null;
    benchmarkProtocolVersion: string | null;
    sourceSuiteVersion: string | null;
    qualityModelId: string | null;
    referenceContextVersion: string;
    workloadReferenceBitrateBps: number;
    qualityExponent: 2.4;
    speedCurveRate: 1.2;
    speedSaturationRealtime: 4;
  } | null;
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
  vmafP5Sum: number;
  vmafP5Samples: number;
  videoBitrateSum: number;
  videoBitrateSamples: number;
  sourceFpsSum: number;
  sourceFpsSamples: number;
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

type GroupAccumulator<Key extends Record<string, string | number | null>> = Key & AggregatedMetrics;

type HardwareScope = {
  cpuModel: string;
  gpuModel: string;
  ramGB: number;
  os: string;
};

function asPositiveInt(raw: string | undefined, fallback: number): number {
  if (!raw) return fallback;
  if (!/^\d+$/.test(raw.trim())) return fallback;
  const parsed = Number(raw);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) return fallback;
  return parsed;
}

function asNonNegativeInt(raw: string | undefined, fallback: number): number {
  if (!raw) return fallback;
  if (!/^\d+$/.test(raw.trim())) return fallback;
  const parsed = Number(raw);
  if (!Number.isSafeInteger(parsed) || parsed < 0) return fallback;
  return parsed;
}

function asOptionalFinite(raw: string | undefined): number | null {
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseFitMode(raw: string | undefined): AnalyticsFilters['fitMode'] {
  if (raw === 'quality' || raw === 'storage' || raw === 'realtime' || raw === 'custom') return raw;
  return 'balanced';
}

function parseCodecFamilyList(raw: string | undefined): CodecFamily[] | null {
  if (!raw) return null;
  const values = raw.split(',').map((value) => value.trim()).filter(Boolean);
  const valid = values.filter((value): value is CodecFamily => (
    value === 'h264' || value === 'hevc' || value === 'av1' || value === 'vp9' || value === 'other'
  ));
  return valid.length > 0 ? Array.from(new Set(valid)) : null;
}

export function parseAnalyticsFilters(query: Record<string, string | undefined>): AnalyticsFilters {
  const contentClass = VALID_CONTENT_CLASSES.includes(query.contentClass as typeof VALID_CONTENT_CLASSES[number])
    ? String(query.contentClass)
    : DEFAULT_ANALYTICS_FILTERS.contentClass;
  const resolution = VALID_RESOLUTIONS.includes(query.resolution as typeof VALID_RESOLUTIONS[number])
    ? String(query.resolution)
    : DEFAULT_ANALYTICS_FILTERS.resolution;
  const crf = asNonNegativeInt(query.crf, DEFAULT_ANALYTICS_FILTERS.crf);
  const passes = query.passes === '1' ? 1 : DEFAULT_ANALYTICS_FILTERS.passes;
  const minSamples = asPositiveInt(query.minSamples, DEFAULT_ANALYTICS_FILTERS.minSamples);
  const maximumBitrateMbps = asOptionalFinite(query.maximumBitrateMbps);
  return {
    workloadId: query.workloadId?.trim() || null,
    contentClass,
    resolution,
    crf,
    passes,
    minSamples,
    fitMode: parseFitMode(query.fitMode),
    customQualityWeight: asOptionalFinite(query.customQualityWeight),
    customBitrateWeight: asOptionalFinite(query.customBitrateWeight),
    customSpeedWeight: asOptionalFinite(query.customSpeedWeight),
    minimumQuality: asOptionalFinite(query.minimumQuality),
    minimumRealtimeRatio: asOptionalFinite(query.minimumRealtimeRatio),
    maximumBitrateBps: maximumBitrateMbps == null ? null : maximumBitrateMbps * 1_000_000,
    compatibleCodecFamilies: parseCodecFamilyList(query.compatibleCodecFamilies),
    requireRecommendationEligibility: query.requireRecommendationEligibility === '1',
    environmentId: query.environmentId?.trim() || null,
    environmentFingerprint: query.environmentFingerprint?.trim() || null,
  };
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

export function buildLeaderboardCurveWhere(filters: AnalyticsFilters): Prisma.BenchmarkWhereInput {
  return {
    status: 'accepted',
    contentClass: filters.contentClass,
    resolution: filters.resolution,
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

function initMetrics(): AggregatedMetrics {
  return {
    sampleCount: 0,
    fpsSum: 0,
    sizeSum: 0,
    vmafSum: 0,
    vmafSamples: 0,
    vmafP5Sum: 0,
    vmafP5Samples: 0,
    videoBitrateSum: 0,
    videoBitrateSamples: 0,
    sourceFpsSum: 0,
    sourceFpsSamples: 0,
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
  target.vmafP5Sum += row.vmafP5Sum ?? 0;
  target.vmafP5Samples += row.vmafP5Samples ?? 0;
  target.videoBitrateSum += row.videoBitrateSum ?? 0;
  target.videoBitrateSamples += row.videoBitrateSamples ?? 0;
  target.sourceFpsSum += row.sourceFpsSum ?? 0;
  target.sourceFpsSamples += row.sourceFpsSamples ?? 0;
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

function resolveHardwareScope(row: Pick<Benchmark, 'cpuModel' | 'gpuModel' | 'ramGB' | 'os'>): HardwareScope {
  return {
    cpuModel: row.cpuModel,
    gpuModel: row.gpuModel,
    ramGB: row.ramGB,
    os: row.os,
  };
}

export function aggregateLeaderboards(rows: Benchmark[], minSamples: number): LeaderboardAnalyticsRow[] {
  const grouped = new Map<string, GroupAccumulator<{
    rowId: string;
    encoderName: string;
    codecFamily: CodecFamily;
    preset: string;
    crf: number;
    contentClass: string;
    resolution: string;
    passes: number;
    workloadId: string;
    cpuModel: string;
    gpuModel: string;
    ramGB: number;
    os: string;
    scoreFormulaVersion: string | null;
    benchmarkProtocolVersion: string | null;
    sourceSuiteVersion: string | null;
    qualityModelId: string | null;
  }>>();

  for (const row of rows) {
    const encoderName = resolveEncoderName(row);
    const hardwareScope = resolveHardwareScope(row);
    const rowId = [
      hardwareScope.cpuModel,
      hardwareScope.gpuModel,
      hardwareScope.ramGB,
      hardwareScope.os,
      encoderName,
      row.preset,
      row.crf,
      row.contentClass,
      row.resolution,
      row.passes,
      row.workloadId ?? `${row.contentClass}-${row.resolution}`,
      row.scoreFormulaVersion ?? '',
      row.benchmarkProtocolVersion ?? '',
      row.sourceSuiteVersion ?? '',
      row.metricModelId ?? '',
    ].join('\u241F');
    const key = [
      rowId,
      hardwareScope.cpuModel,
      hardwareScope.gpuModel,
      hardwareScope.ramGB,
      hardwareScope.os,
      encoderName,
      row.preset,
      row.crf,
      row.contentClass,
      row.resolution,
      row.passes,
      row.workloadId ?? `${row.contentClass}-${row.resolution}`,
      row.scoreFormulaVersion ?? '',
      row.benchmarkProtocolVersion ?? '',
      row.sourceSuiteVersion ?? '',
      row.metricModelId ?? '',
    ].join('\u241F');
    const existing = grouped.get(key) ?? {
      rowId,
      encoderName,
      codecFamily: deriveCodecFamily(encoderName),
      preset: row.preset,
      crf: row.crf,
      contentClass: row.contentClass,
      resolution: row.resolution,
      passes: row.passes,
      workloadId: row.workloadId ?? `${row.contentClass}-${row.resolution}`,
      ...hardwareScope,
      scoreFormulaVersion: row.scoreFormulaVersion ?? null,
      benchmarkProtocolVersion: row.benchmarkProtocolVersion ?? null,
      sourceSuiteVersion: row.sourceSuiteVersion ?? null,
      qualityModelId: row.metricModelId ?? null,
      ...initMetrics(),
    };
    accumulateMetrics(existing, row);
    grouped.set(key, existing);
  }

  const items = Array.from(grouped.values())
    .filter((entry) => entry.sampleCount >= minSamples)
    .map((entry) => ({
      rowId: entry.rowId,
      encoderName: entry.encoderName,
      codecFamily: entry.codecFamily,
      preset: entry.preset,
      crf: entry.crf,
      contentClass: entry.contentClass,
      resolution: entry.resolution,
      passes: entry.passes,
      hardwareContext: {
        cpuModel: entry.cpuModel,
        gpuModel: entry.gpuModel,
        ramGB: entry.ramGB,
        os: entry.os,
      },
      sampleCount: entry.sampleCount,
      avgFps: Number((entry.fpsSum / entry.sampleCount).toFixed(4)),
      avgVmaf: finalizeAverage(entry.vmafSum, entry.vmafSamples),
      avgVmafP5: finalizeAverage(entry.vmafP5Sum, entry.vmafP5Samples),
      avgSsim: finalizeAverage(entry.ssimSum, entry.ssimSamples),
      avgPsnr: finalizeAverage(entry.psnrSum, entry.psnrSamples),
      avgSizeBytes: finalizeSize(entry.sizeSum, entry.sampleCount),
      avgVideoBitrateBps: finalizeAverage(entry.videoBitrateSum, entry.videoBitrateSamples),
      avgSourceFps: finalizeAverage(entry.sourceFpsSum, entry.sourceFpsSamples),
      avgPowerW: finalizeAverage(entry.powerSum, entry.powerSamples),
      fpsPerWatt: null as number | null,
      qualityPerWatt: null as number | null,
      plScore: null as number | null,
      plScoreVersion: PL_SCORE_V7_VERSION,
      plScoreComponents: null as { quality: number; bitrate: number; speed: number } | null,
      plScoreWorkloadId: entry.workloadId,
      scoreFormulaVersion: entry.scoreFormulaVersion,
      benchmarkProtocolVersion: entry.benchmarkProtocolVersion,
      sourceSuiteVersion: entry.sourceSuiteVersion,
      qualityModelId: entry.qualityModelId,
      plScoreContext: null as LeaderboardAnalyticsRow['plScoreContext'],
    }));

  for (const item of items) {
    item.fpsPerWatt = item.avgPowerW != null && item.avgPowerW > 0 ? Number((item.avgFps / item.avgPowerW).toFixed(4)) : null;
    item.qualityPerWatt = item.avgPowerW != null && item.avgPowerW > 0 && item.avgVmaf != null
      ? Number((item.avgVmaf / item.avgPowerW).toFixed(4))
      : null;
  }

  const workloadReferences = parseWorkloadReferenceContexts(process.env.PL_V7_REFERENCE_BITRATES_JSON);
  const referenceContextVersion = process.env.PL_V7_REFERENCE_CONTEXT_VERSION?.trim() || null;
  for (const item of items) {
    const referenceBitrate = workloadReferences.get(item.plScoreWorkloadId);
    const score = referenceBitrate == null || referenceContextVersion == null ? null : computePlScoreV7({
      vmafMean: item.avgVmaf,
      vmafP5: item.avgVmafP5,
      videoBitrateBps: item.avgVideoBitrateBps,
      encodeFps: item.avgFps,
      sourceFps: item.avgSourceFps,
    }, { workloadId: item.plScoreWorkloadId, workloadReferenceBitrateBps: referenceBitrate });
    if (score) {
      item.plScore = Number(score.total.toFixed(4));
      item.plScoreComponents = { quality: score.quality, bitrate: score.bitrate, speed: score.speed };
      item.plScoreContext = {
        formulaVersion: item.scoreFormulaVersion,
        benchmarkProtocolVersion: item.benchmarkProtocolVersion,
        sourceSuiteVersion: item.sourceSuiteVersion,
        qualityModelId: item.qualityModelId,
        referenceContextVersion: referenceContextVersion!,
        workloadReferenceBitrateBps: referenceBitrate!,
        qualityExponent: 2.4,
        speedCurveRate: 1.2,
        speedSaturationRealtime: 4,
      };
    }
  }

  return items.sort((a, b) => (b.plScore ?? -1) - (a.plScore ?? -1) || b.avgFps - a.avgFps);
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
