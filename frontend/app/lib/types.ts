/** Shared Benchmark type for server and client. */
export type Benchmark = {
  id: string;
  createdAt: string;
  cpuModel: string;
  gpuModel: string | null;
  ramGB: number;
  os: string;
  codec: string;
  codecFamily?: "h264" | "hevc" | "av1" | "vp9" | "other";
  crf?: number | null;
  preset: string;
  fps: number;
  vmaf: number | null;
  vmafP5?: number | null;
  ssim: number | null;
  psnr: number | null;
  fileSizeBytes: number;
  videoBitrateBps?: number | null;
  sourceFps?: number | null;
  notes: string | null;
  ffmpegVersion?: string | null;
  encoderName?: string | null;
  clientVersion?: string | null;
  inputHash?: string | null;
  contentClass?: string | null;
  resolution?: string | null;
  passes?: number | null;
  runMs?: number | null;
  scoreFormulaVersion?: string | null;
  benchmarkProtocolVersion?: string | null;
  sourceSuiteVersion?: string | null;
  workloadId?: string | null;
  metricModelId?: string | null;
  status?: string | null;
  samples: number;
  vmafSamples?: number;
  ssimSamples?: number;
  psnrSamples?: number;
  gpuUtilAvg?: number | null;
  gpuPowerAvgW?: number | null;
  gpuMemPeakMB?: number | null;
  cpuUtilAvg?: number | null;
  cpuUtilMax?: number | null;
  peakMemoryMB?: number | null;
  thermalThrottle?: boolean | null;
  sampleCount?: number | null;
  monitorDurationMs?: number | null;
  cpuSampleCount?: number | null;
  gpuSampleCount?: number | null;
  ffmpegSampleCount?: number | null;
  batterySampleCount?: number | null;
  fpsPerWatt?: number | null;
  qualityPerWatt?: number | null;
};

export type AnalyticsFilters = {
  contentClass: string;
  resolution: string;
  crf: number;
  minSamples: number;
};

export type PlFitMode = "balanced" | "quality" | "storage" | "realtime" | "custom";
export type EvidenceTier = "PROVISIONAL" | "LOW" | "MEDIUM" | "HIGH";

export type DecisionWeights = {
  quality: number;
  bitrate: number;
  speed: number;
};

export type FitProfile = {
  mode: PlFitMode;
  label: string;
  weights: DecisionWeights;
  constraints: {
    minimumQuality?: number | null;
    minimumRealtimeRatio?: number | null;
    maximumBitrateBps?: number | null;
    compatibleCodecFamilies?: Array<"h264" | "hevc" | "av1" | "vp9" | "other"> | null;
    requireRecommendationEligibility?: boolean;
  };
};

export type ConstraintStatus = {
  passed: boolean;
  required: number | string | readonly string[] | boolean | null;
  actual: number | string | boolean | readonly string[] | null;
  reason: string | null;
};

export type FitEvaluation = {
  mode: PlFitMode;
  label: string;
  eligible: boolean;
  score: number | null;
  rank: number;
  reasons: string[];
  weights: DecisionWeights;
  constraints: {
    minimumQuality: ConstraintStatus;
    minimumRealtimeRatio: ConstraintStatus;
    maximumBitrateBps: ConstraintStatus;
    compatibility: ConstraintStatus;
    recommendationEligibility: ConstraintStatus;
  };
};

export type LeaderboardDecisionRow = {
  rowId: string;
  encoderName: string;
  codecFamily: "h264" | "hevc" | "av1" | "vp9" | "other";
  preset: string;
  rateControl: {
    requestedMode: string;
    effectiveMode: string;
    qualityValue: number | null;
    targetBitrateKbps: number | null;
    maxBitrateKbps: number | null;
    bufferSizeKbits: number | null;
    label: string;
  };
  contentClass: string;
  resolution: string;
  passes: number;
  workloadId: string;
  hardwareKey: string;
  hardwareLabel: string;
  realtimeRatio: number | null;
  effectiveQuality: number | null;
  scoreFormulaVersion: string | null;
  benchmarkProtocolVersion: string | null;
  sourceSuiteVersion: string | null;
  qualityModelId: string | null;
  hardwareContext: {
    environmentId: string;
    environmentFingerprint: string;
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
  plScoreVersion: "7.0";
  plScoreComponents: { quality: number; bitrate: number; speed: number } | null;
  plScoreWorkloadId: string;
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
  evidence: {
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
  };
  pareto: {
    available: boolean;
    efficient: boolean;
    frontierRank: number | null;
    dominatorRowIds: string[];
    dominatedRowIds: string[];
    unavailableReason: string | null;
    canonical: {
      quality: number | null;
      bitrate: number | null;
      speed: number | null;
    };
  };
  bdRate: {
    available: boolean;
    valuePercent: number | null;
    versusRowId: string | null;
    versusLabel: string | null;
    method: "piecewise-log-linear" | null;
    matchedPointCount: number;
    overlapQualityRange: [number, number] | null;
    unavailableReason: string | null;
  };
  fit: {
    selectedMode: PlFitMode;
    modes: Record<PlFitMode, FitEvaluation>;
    recommended: boolean;
    recommendationReason: string | null;
  };
};

export type LeaderboardAnalyticsResponse = {
  selectedMode: PlFitMode;
  profiles: Record<PlFitMode, FitProfile>;
  rows: LeaderboardDecisionRow[];
  recommendation: {
    rowId: string | null;
    label: string | null;
    reason: string | null;
  };
  environmentScope: {
    selectedEnvironmentId: string | null;
    selectedEnvironmentFingerprint: string | null;
    exact: boolean;
    available: Array<{
      environmentId: string;
      environmentFingerprint: string;
      cpuModel: string;
      gpuModel: string;
      ramGB: number;
      os: string;
      label: string;
    }>;
  };
};

export type HardwareAnalyticsRow = {
  cpuModel: string;
  gpuModel: string;
  encoderName: string;
  codecFamily: "h264" | "hevc" | "av1" | "vp9" | "other";
  preset: string;
  rateControl: LeaderboardDecisionRow['rateControl'];
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
  codecFamily: "h264" | "hevc" | "av1" | "vp9" | "other";
  preset: string;
  rateControl: LeaderboardDecisionRow['rateControl'];
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
