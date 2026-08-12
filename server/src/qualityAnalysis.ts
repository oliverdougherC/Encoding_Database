export const QUALITY_ANALYSIS_CONTRACT_VERSION = 'quality-analysis/v1' as const;
export const VMAF_MODEL_VERSION = 'v1.0.16_3d0h' as const;
export const VMAF_MODEL_FILENAME = 'vmaf_v1.0.16_3d0h.json' as const;
export const VMAF_LIBVMAF_MODEL_NAME = 'vmaf_v1.0.16_3d0h' as const;
export const VMAF_MODEL_SHA256 = 'e4cf8c147e1368b35497d772920bc92f98c1ad7853c1033d8a836947f427140e' as const;
export const QUALITY_ANALYSIS_NUMERIC_TOLERANCE = 1e-6 as const;
export const QUALITY_ANALYSIS_ROUNDING_DIGITS = 6 as const;
export const DEFAULT_VMAF_THRESHOLDS = [80, 85, 90, 95] as const;
export const CANONICAL_DISTORTED_INPUT_INDEX = 0 as const;
export const CANONICAL_REFERENCE_INPUT_INDEX = 1 as const;
export const CANONICAL_ANALYSIS_PIXEL_FORMAT = 'yuv420p10le' as const;
export const CANONICAL_VMAF_LOG_FORMAT = 'json' as const;
export const CANONICAL_VMAF_LOG_PATH = '-' as const;
export const CANONICAL_VMAF_THREADS = 1 as const;
export const CANONICAL_ANALYSIS_CONTEXT_ID = 'libvmaf-json-distorted-first-yuv420p10le-single-thread' as const;

export type SupportedDynamicRange = 'sdr';
export type SupportedResolutionClass = 'sd' | '720p' | '1080p' | '4k';
export type SupportedFrameRateClass = 'standard' | 'hfr';
export type DiagnosticMetricName = 'xpsnr' | 'ssim' | 'psnr';

export interface QualitySourceContext {
  width: number;
  height: number;
  frameRate: number;
  dynamicRange?: SupportedDynamicRange;
}

export interface CanonicalInputOrder {
  distortedInputIndex: number;
  referenceInputIndex: number;
}

export interface QualityAnalysisExecutionPlan {
  metricModelId: string;
  metricModelVersion: typeof VMAF_MODEL_VERSION;
  libvmafModelName: typeof VMAF_LIBVMAF_MODEL_NAME;
  modelFilename: typeof VMAF_MODEL_FILENAME;
  modelSha256: typeof VMAF_MODEL_SHA256;
  qualityContextId: string;
  analysisContextId: typeof CANONICAL_ANALYSIS_CONTEXT_ID;
  dynamicRange: SupportedDynamicRange;
  resolutionClass: SupportedResolutionClass;
  frameRateClass: SupportedFrameRateClass;
  analysisPixelFormat: typeof CANONICAL_ANALYSIS_PIXEL_FORMAT;
  distortedInputIndex: typeof CANONICAL_DISTORTED_INPUT_INDEX;
  referenceInputIndex: typeof CANONICAL_REFERENCE_INPUT_INDEX;
  filterGraph: string;
}

export interface MetricValueWithProvenance {
  value: number | null;
  provenance: {
    metric: DiagnosticMetricName;
    parserId: string;
    ffmpegVersion: string | null;
    averageToken: string | null;
  };
}

export interface MetricDisagreementDiagnostic {
  flagged: boolean;
  severity: 'none' | 'watch';
  spreadBands: number;
  metricBands: Partial<Record<'vmaf' | DiagnosticMetricName, string>>;
  reasons: string[];
}

export interface VmafFrameScore {
  frameIndex: number;
  timestampMs: number;
  score: number;
}

export interface ThresholdFraction {
  threshold: number;
  count: number;
  fraction: number;
}

export interface AuthoritativeQualityAnalysisRecord {
  metricModelId: string;
  qualityContextId: string;
  analysisWorkerVersion: string;
  analysisProvenance: {
    contractVersion: typeof QUALITY_ANALYSIS_CONTRACT_VERSION;
    metricModelVersion: typeof VMAF_MODEL_VERSION;
    libvmafModelName: typeof VMAF_LIBVMAF_MODEL_NAME;
    modelFilename: typeof VMAF_MODEL_FILENAME;
    modelSha256: typeof VMAF_MODEL_SHA256;
    analysisContextId: typeof CANONICAL_ANALYSIS_CONTEXT_ID;
    dynamicRange: SupportedDynamicRange;
    resolutionClass: SupportedResolutionClass;
    frameRateClass: SupportedFrameRateClass;
    distortedInputIndex: typeof CANONICAL_DISTORTED_INPUT_INDEX;
    referenceInputIndex: typeof CANONICAL_REFERENCE_INPUT_INDEX;
    analysisPixelFormat: typeof CANONICAL_ANALYSIS_PIXEL_FORMAT;
    filterGraph: string;
    ffmpegVersion: string | null;
    numericPolicy: {
      tolerance: typeof QUALITY_ANALYSIS_NUMERIC_TOLERANCE;
      roundingDigits: typeof QUALITY_ANALYSIS_ROUNDING_DIGITS;
      percentileMethod: 'nearest-rank-lower-tail';
      medianMethod: 'midpoint';
      stdDevMethod: 'population';
      harmonicMeanZeroGuard: 'score<=tolerance=>0';
      thresholdComparison: 'score+tol<threshold';
    };
    diagnosticParsers: {
      xpsnr: string;
      ssim: string;
      psnr: string;
    };
  };
  vmafMean: number;
  vmafMedian: number;
  vmafP1: number;
  vmafP5: number;
  vmafMin: number;
  vmafMax: number;
  vmafStdDev: number;
  vmafHarmonicMean: number;
  worstFrameIndex: number;
  worstFrameTimestampMs: number;
  belowThresholdFractions: Record<string, ThresholdFraction>;
  vmafDistribution: {
    frameCount: number;
    frames: VmafFrameScore[];
  };
  vpl: number;
  xpsnr: number | null;
  ssim: number | null;
  psnr: number | null;
  metricDisagreement: MetricDisagreementDiagnostic;
}

export interface ParseVmafJsonReportOptions {
  source: QualitySourceContext;
  metricModelPath: string;
  logPath?: string;
  thresholds?: ReadonlyArray<number>;
  observedInputOrder?: CanonicalInputOrder;
}

export interface BuildAuthoritativeQualityAnalysisOptions extends ParseVmafJsonReportOptions {
  analysisWorkerVersion: string;
  vmafReport: string | Record<string, unknown>;
  xpsnrReport?: string | null;
  ssimReport?: string | null;
  psnrReport?: string | null;
  ffmpegVersion?: string | null;
}

type JsonRecord = Record<string, unknown>;
type BandLabel = 'poor' | 'watch' | 'strong' | 'excellent';

const DISAGREEMENT_BAND_ORDER: Record<BandLabel, number> = {
  poor: 0,
  watch: 1,
  strong: 2,
  excellent: 3,
};

const XPSNR_PARSER_ID = 'ffmpeg-xpsnr-average-v1' as const;
const SSIM_PARSER_ID = 'ffmpeg-ssim-all-v1' as const;
const PSNR_PARSER_ID = 'ffmpeg-psnr-average-v1' as const;

function roundDeterministic(value: number): number {
  return Number(value.toFixed(QUALITY_ANALYSIS_ROUNDING_DIGITS));
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function coerceFiniteNumber(value: unknown): number | null {
  if (isFiniteNumber(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function requirePositiveFiniteNumber(value: number, field: string): number {
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${field} must be a positive finite number`);
  }
  return value;
}

function asObject(value: unknown): JsonRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : null;
}

function normalizeThresholds(values: ReadonlyArray<number> | undefined): number[] {
  const thresholds = values ?? DEFAULT_VMAF_THRESHOLDS;
  const normalized = thresholds
    .map((value) => coerceFiniteNumber(value))
    .filter((value): value is number => value != null)
    .map((value) => roundDeterministic(value))
    .filter((value, index, arr) => value >= 0 && value <= 100 && arr.indexOf(value) === index)
    .sort((a, b) => a - b);
  if (normalized.length === 0) {
    throw new Error('At least one valid threshold is required');
  }
  return normalized;
}

function inferResolutionClass(width: number, height: number): SupportedResolutionClass {
  const longer = Math.max(width, height);
  const shorter = Math.min(width, height);
  if (longer >= 3800 || shorter >= 2100) return '4k';
  if (longer >= 1900 || shorter >= 1060) return '1080p';
  if (longer >= 1200 || shorter >= 700) return '720p';
  return 'sd';
}

function inferFrameRateClass(frameRate: number): SupportedFrameRateClass {
  return frameRate > 30 ? 'hfr' : 'standard';
}

function percentileNearestRankLowerTail(sortedAscending: readonly number[], percentile: number): number {
  if (!sortedAscending.length) throw new Error('Cannot compute percentile of empty set');
  if (percentile <= 0) return sortedAscending[0]!;
  if (percentile >= 1) return sortedAscending[sortedAscending.length - 1]!;
  const rank = Math.max(1, Math.ceil(percentile * sortedAscending.length));
  return sortedAscending[Math.min(sortedAscending.length - 1, rank - 1)]!;
}

function median(sortedAscending: readonly number[]): number {
  if (!sortedAscending.length) throw new Error('Cannot compute median of empty set');
  const middle = Math.floor(sortedAscending.length / 2);
  if (sortedAscending.length % 2 === 1) return sortedAscending[middle]!;
  return (sortedAscending[middle - 1]! + sortedAscending[middle]!) / 2;
}

function populationStdDev(values: readonly number[], meanValue: number): number {
  if (!values.length) throw new Error('Cannot compute standard deviation of empty set');
  const variance = values.reduce((sum, value) => sum + ((value - meanValue) ** 2), 0) / values.length;
  return Math.sqrt(variance);
}

function harmonicMean(values: readonly number[]): number {
  if (!values.length) throw new Error('Cannot compute harmonic mean of empty set');
  if (values.some((value) => value <= QUALITY_ANALYSIS_NUMERIC_TOLERANCE)) return 0;
  const inverseSum = values.reduce((sum, value) => sum + (1 / value), 0);
  return values.length / inverseSum;
}

function buildCanonicalFilterGraph(metricModelPath: string, logPath: string): string {
  return [
    `[${CANONICAL_DISTORTED_INPUT_INDEX}:v]settb=AVTB,setpts=PTS-STARTPTS,format=pix_fmts=${CANONICAL_ANALYSIS_PIXEL_FORMAT}[distorted]`,
    `[${CANONICAL_REFERENCE_INPUT_INDEX}:v]settb=AVTB,setpts=PTS-STARTPTS,format=pix_fmts=${CANONICAL_ANALYSIS_PIXEL_FORMAT}[reference]`,
    `[distorted][reference]libvmaf=model='path=${escapeFilterValue(metricModelPath)}'`
      + `:log_fmt=${CANONICAL_VMAF_LOG_FORMAT}:log_path=${escapeFilterValue(logPath)}:n_threads=${CANONICAL_VMAF_THREADS}`,
  ].join(';');
}

function escapeFilterValue(value: string): string {
  return value.replace(/\\/g, '/').replace(/:/g, '\\:').replace(/'/g, "\\'");
}

function getFrameTimestampMs(frame: JsonRecord, frameRate: number): number {
  const timestampMs = coerceFiniteNumber(frame.timestamp_ms ?? frame.timestampMs);
  if (timestampMs != null) return Math.max(0, Math.round(timestampMs));
  const ptsTime = coerceFiniteNumber(frame.pts_time ?? frame.ptsTime);
  if (ptsTime != null) return Math.max(0, Math.round(ptsTime * 1000));
  const frameNum = coerceFiniteNumber(frame.frameNum ?? frame.frameIndex ?? frame.index);
  if (frameNum == null) throw new Error('VMAF frame entry is missing frameNum/frameIndex');
  return Math.max(0, Math.round((frameNum / frameRate) * 1000));
}

function getFrameIndex(frame: JsonRecord): number {
  const frameNum = coerceFiniteNumber(frame.frameNum ?? frame.frameIndex ?? frame.index);
  if (frameNum == null || !Number.isInteger(frameNum) || frameNum < 0) {
    throw new Error('VMAF frame entry is missing a valid non-negative frame index');
  }
  return frameNum;
}

function getFrameScore(frame: JsonRecord): number {
  const metrics = asObject(frame.metrics);
  const directScore = coerceFiniteNumber(frame.VMAF_score ?? frame.vmaf ?? frame.score);
  const nestedScore = metrics ? coerceFiniteNumber(metrics.VMAF_score ?? metrics.vmaf ?? metrics.score) : null;
  const score = directScore ?? nestedScore;
  if (score == null) throw new Error('VMAF frame entry is missing a finite VMAF score');
  return score;
}

function parseVmafPayload(report: string | Record<string, unknown>): JsonRecord {
  if (typeof report === 'string') {
    const parsed = JSON.parse(report) as unknown;
    const object = asObject(parsed);
    if (!object) throw new Error('VMAF report JSON must be an object');
    return object;
  }
  const object = asObject(report);
  if (!object) throw new Error('VMAF report payload must be an object');
  return object;
}

function classifyVmafBand(value: number): BandLabel {
  if (value >= 95) return 'excellent';
  if (value >= 90) return 'strong';
  if (value >= 80) return 'watch';
  return 'poor';
}

function classifyXpsnrBand(value: number): BandLabel {
  if (value >= 42) return 'excellent';
  if (value >= 38) return 'strong';
  if (value >= 32) return 'watch';
  return 'poor';
}

function classifyPsnrBand(value: number): BandLabel {
  if (value >= 42) return 'excellent';
  if (value >= 38) return 'strong';
  if (value >= 32) return 'watch';
  return 'poor';
}

function classifySsimBand(value: number): BandLabel {
  if (value >= 0.99) return 'excellent';
  if (value >= 0.97) return 'strong';
  if (value >= 0.94) return 'watch';
  return 'poor';
}

export function assertCanonicalInputOrder(order: CanonicalInputOrder | undefined): asserts order is CanonicalInputOrder | undefined {
  if (!order) return;
  if (order.distortedInputIndex !== CANONICAL_DISTORTED_INPUT_INDEX || order.referenceInputIndex !== CANONICAL_REFERENCE_INPUT_INDEX) {
    throw new Error(
      `Canonical VMAF input order requires distorted=${CANONICAL_DISTORTED_INPUT_INDEX} and reference=${CANONICAL_REFERENCE_INPUT_INDEX}`,
    );
  }
}

export function resolveQualityAnalysisExecutionPlan(
  source: QualitySourceContext,
  metricModelPath: string,
  logPath: string = CANONICAL_VMAF_LOG_PATH,
): QualityAnalysisExecutionPlan {
  requirePositiveFiniteNumber(source.width, 'width');
  requirePositiveFiniteNumber(source.height, 'height');
  const frameRate = requirePositiveFiniteNumber(source.frameRate, 'frameRate');
  const dynamicRange = source.dynamicRange ?? 'sdr';
  if (dynamicRange !== 'sdr') {
    throw new Error(`Unsupported dynamic range for canonical PL-v7 analysis: ${dynamicRange}`);
  }
  if (!metricModelPath.trim()) throw new Error('metricModelPath is required');

  const resolutionClass = inferResolutionClass(source.width, source.height);
  const frameRateClass = inferFrameRateClass(frameRate);
  const metricModelId = `vmaf-v1-${dynamicRange}-${resolutionClass}${frameRateClass === 'hfr' ? '-hfr' : ''}`;
  const qualityContextId = `${metricModelId}-yuv420p10le`;

  return {
    metricModelId,
    metricModelVersion: VMAF_MODEL_VERSION,
    libvmafModelName: VMAF_LIBVMAF_MODEL_NAME,
    modelFilename: VMAF_MODEL_FILENAME,
    modelSha256: VMAF_MODEL_SHA256,
    qualityContextId,
    analysisContextId: CANONICAL_ANALYSIS_CONTEXT_ID,
    dynamicRange,
    resolutionClass,
    frameRateClass,
    analysisPixelFormat: CANONICAL_ANALYSIS_PIXEL_FORMAT,
    distortedInputIndex: CANONICAL_DISTORTED_INPUT_INDEX,
    referenceInputIndex: CANONICAL_REFERENCE_INPUT_INDEX,
    filterGraph: buildCanonicalFilterGraph(metricModelPath, logPath),
  };
}

export function parseVmafJsonReport(
  report: string | Record<string, unknown>,
  options: ParseVmafJsonReportOptions,
): Omit<AuthoritativeQualityAnalysisRecord, 'analysisWorkerVersion' | 'xpsnr' | 'ssim' | 'psnr' | 'metricDisagreement' | 'analysisProvenance'> & {
  analysisExecution: QualityAnalysisExecutionPlan;
} {
  assertCanonicalInputOrder(options.observedInputOrder);
  const thresholds = normalizeThresholds(options.thresholds);
  const plan = resolveQualityAnalysisExecutionPlan(options.source, options.metricModelPath, options.logPath);
  const payload = parseVmafPayload(report);
  const framesValue = payload.frames;
  if (!Array.isArray(framesValue) || framesValue.length === 0) {
    throw new Error('Canonical PL-v7 VMAF parsing requires per-frame JSON data');
  }

  const frameRate = requirePositiveFiniteNumber(options.source.frameRate, 'frameRate');
  const frames = framesValue.map((value) => {
    const frame = asObject(value);
    if (!frame) throw new Error('VMAF frame entry must be an object');
    const score = roundDeterministic(getFrameScore(frame));
    return {
      frameIndex: getFrameIndex(frame),
      timestampMs: getFrameTimestampMs(frame, frameRate),
      score,
    };
  }).sort((a, b) => a.frameIndex - b.frameIndex);

  const values = frames.map((frame) => frame.score);
  const sortedAscending = [...values].sort((a, b) => a - b);
  const sum = values.reduce((acc, value) => acc + value, 0);
  const meanValue = sum / values.length;
  const vmafMean = roundDeterministic(meanValue);
  const vmafMedian = roundDeterministic(median(sortedAscending));
  const vmafP1 = roundDeterministic(percentileNearestRankLowerTail(sortedAscending, 0.01));
  const vmafP5 = roundDeterministic(percentileNearestRankLowerTail(sortedAscending, 0.05));
  const vmafMin = roundDeterministic(sortedAscending[0]!);
  const vmafMax = roundDeterministic(sortedAscending[sortedAscending.length - 1]!);
  const vmafStdDev = roundDeterministic(populationStdDev(values, meanValue));
  const vmafHarmonicMean = roundDeterministic(harmonicMean(values));
  const worstFrame = frames.reduce((worst, frame) => (
    frame.score < worst.score || (frame.score === worst.score && frame.frameIndex < worst.frameIndex) ? frame : worst
  ), frames[0]!);

  const belowThresholdFractions = Object.fromEntries(thresholds.map((threshold) => {
    const count = values.filter((value) => value + QUALITY_ANALYSIS_NUMERIC_TOLERANCE < threshold).length;
    return [
      threshold.toFixed(QUALITY_ANALYSIS_ROUNDING_DIGITS),
      {
        threshold,
        count,
        fraction: roundDeterministic(count / values.length),
      } satisfies ThresholdFraction,
    ];
  }));

  return {
    metricModelId: plan.metricModelId,
    qualityContextId: plan.qualityContextId,
    analysisExecution: plan,
    vmafMean,
    vmafMedian,
    vmafP1,
    vmafP5,
    vmafMin,
    vmafMax,
    vmafStdDev,
    vmafHarmonicMean,
    worstFrameIndex: worstFrame.frameIndex,
    worstFrameTimestampMs: worstFrame.timestampMs,
    belowThresholdFractions,
    vmafDistribution: {
      frameCount: frames.length,
      frames,
    },
    vpl: roundDeterministic((0.85 * vmafMean) + (0.15 * vmafP5)),
  };
}

function parseAverageMetricValue(
  report: string | null | undefined,
  regexes: readonly RegExp[],
  parserId: string,
  metric: DiagnosticMetricName,
  ffmpegVersion: string | null,
): MetricValueWithProvenance {
  if (!report) {
    return {
      value: null,
      provenance: {
        metric,
        parserId,
        ffmpegVersion,
        averageToken: null,
      },
    };
  }

  for (const regex of regexes) {
    const match = regex.exec(report);
    if (!match) continue;
    const token = match[1] ?? null;
    if (!token) continue;
    if (/^inf$/i.test(token)) {
      return {
        value: 100,
        provenance: {
          metric,
          parserId,
          ffmpegVersion,
          averageToken: token,
        },
      };
    }
    const parsed = Number(token);
    if (!Number.isFinite(parsed)) continue;
    return {
      value: roundDeterministic(parsed),
      provenance: {
        metric,
        parserId,
        ffmpegVersion,
        averageToken: token,
      },
    };
  }

  return {
    value: null,
    provenance: {
      metric,
      parserId,
      ffmpegVersion,
      averageToken: null,
    },
  };
}

export function parseXpsnrReport(report: string | null | undefined, ffmpegVersion: string | null = null): MetricValueWithProvenance {
  return parseAverageMetricValue(
    report,
    [
      /xpsnr(?:\s+[^:\n]*)?\s+average[:=]\s*([0-9]+(?:\.[0-9]+)?)/i,
      /average[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*dB/i,
    ],
    XPSNR_PARSER_ID,
    'xpsnr',
    ffmpegVersion,
  );
}

export function parseSsimReport(report: string | null | undefined, ffmpegVersion: string | null = null): MetricValueWithProvenance {
  return parseAverageMetricValue(
    report,
    [
      /All:\s*([0-9]+(?:\.[0-9]+)?)/,
      /ssim(?:\s+[^:\n]*)?\s+average[:=]\s*([0-9]+(?:\.[0-9]+)?)/i,
    ],
    SSIM_PARSER_ID,
    'ssim',
    ffmpegVersion,
  );
}

export function parsePsnrReport(report: string | null | undefined, ffmpegVersion: string | null = null): MetricValueWithProvenance {
  return parseAverageMetricValue(
    report,
    [
      /average:\s*([0-9]+(?:\.[0-9]+)?|inf)/i,
      /psnr(?:\s+[^:\n]*)?\s+average[:=]\s*([0-9]+(?:\.[0-9]+)?|inf)/i,
    ],
    PSNR_PARSER_ID,
    'psnr',
    ffmpegVersion,
  );
}

export function diagnoseMetricDisagreement(metrics: {
  vmafMean: number;
  xpsnr?: number | null;
  ssim?: number | null;
  psnr?: number | null;
}): MetricDisagreementDiagnostic {
  const metricBands: Partial<Record<'vmaf' | DiagnosticMetricName, string>> = {
    vmaf: classifyVmafBand(metrics.vmafMean),
  };
  const numericBands: number[] = [DISAGREEMENT_BAND_ORDER[classifyVmafBand(metrics.vmafMean)]];

  if (metrics.xpsnr != null) {
    const band = classifyXpsnrBand(metrics.xpsnr);
    metricBands.xpsnr = band;
    numericBands.push(DISAGREEMENT_BAND_ORDER[band]);
  }
  if (metrics.ssim != null) {
    const band = classifySsimBand(metrics.ssim);
    metricBands.ssim = band;
    numericBands.push(DISAGREEMENT_BAND_ORDER[band]);
  }
  if (metrics.psnr != null) {
    const band = classifyPsnrBand(metrics.psnr);
    metricBands.psnr = band;
    numericBands.push(DISAGREEMENT_BAND_ORDER[band]);
  }

  const spreadBands = Math.max(...numericBands) - Math.min(...numericBands);
  const reasons = spreadBands >= 2
    ? Object.entries(metricBands).map(([metric, band]) => `${metric}:${band}`)
    : [];

  return {
    flagged: spreadBands >= 2,
    severity: spreadBands >= 2 ? 'watch' : 'none',
    spreadBands,
    metricBands,
    reasons,
  };
}

export function buildAuthoritativeQualityAnalysisRecord(
  options: BuildAuthoritativeQualityAnalysisOptions,
): AuthoritativeQualityAnalysisRecord {
  const vmaf = parseVmafJsonReport(options.vmafReport, options);
  const xpsnr = parseXpsnrReport(options.xpsnrReport, options.ffmpegVersion ?? null);
  const ssim = parseSsimReport(options.ssimReport, options.ffmpegVersion ?? null);
  const psnr = parsePsnrReport(options.psnrReport, options.ffmpegVersion ?? null);
  const disagreement = diagnoseMetricDisagreement({
    vmafMean: vmaf.vmafMean,
    xpsnr: xpsnr.value,
    ssim: ssim.value,
    psnr: psnr.value,
  });

  return {
    metricModelId: vmaf.metricModelId,
    qualityContextId: vmaf.qualityContextId,
    analysisWorkerVersion: options.analysisWorkerVersion,
    analysisProvenance: {
      contractVersion: QUALITY_ANALYSIS_CONTRACT_VERSION,
      metricModelVersion: vmaf.analysisExecution.metricModelVersion,
      libvmafModelName: vmaf.analysisExecution.libvmafModelName,
      modelFilename: vmaf.analysisExecution.modelFilename,
      modelSha256: vmaf.analysisExecution.modelSha256,
      analysisContextId: vmaf.analysisExecution.analysisContextId,
      dynamicRange: vmaf.analysisExecution.dynamicRange,
      resolutionClass: vmaf.analysisExecution.resolutionClass,
      frameRateClass: vmaf.analysisExecution.frameRateClass,
      distortedInputIndex: vmaf.analysisExecution.distortedInputIndex,
      referenceInputIndex: vmaf.analysisExecution.referenceInputIndex,
      analysisPixelFormat: vmaf.analysisExecution.analysisPixelFormat,
      filterGraph: vmaf.analysisExecution.filterGraph,
      ffmpegVersion: options.ffmpegVersion ?? null,
      numericPolicy: {
        tolerance: QUALITY_ANALYSIS_NUMERIC_TOLERANCE,
        roundingDigits: QUALITY_ANALYSIS_ROUNDING_DIGITS,
        percentileMethod: 'nearest-rank-lower-tail',
        medianMethod: 'midpoint',
        stdDevMethod: 'population',
        harmonicMeanZeroGuard: 'score<=tolerance=>0',
        thresholdComparison: 'score+tol<threshold',
      },
      diagnosticParsers: {
        xpsnr: xpsnr.provenance.parserId,
        ssim: ssim.provenance.parserId,
        psnr: psnr.provenance.parserId,
      },
    },
    vmafMean: vmaf.vmafMean,
    vmafMedian: vmaf.vmafMedian,
    vmafP1: vmaf.vmafP1,
    vmafP5: vmaf.vmafP5,
    vmafMin: vmaf.vmafMin,
    vmafMax: vmaf.vmafMax,
    vmafStdDev: vmaf.vmafStdDev,
    vmafHarmonicMean: vmaf.vmafHarmonicMean,
    worstFrameIndex: vmaf.worstFrameIndex,
    worstFrameTimestampMs: vmaf.worstFrameTimestampMs,
    belowThresholdFractions: vmaf.belowThresholdFractions,
    vmafDistribution: vmaf.vmafDistribution,
    vpl: vmaf.vpl,
    xpsnr: xpsnr.value,
    ssim: ssim.value,
    psnr: psnr.value,
    metricDisagreement: disagreement,
  };
}
