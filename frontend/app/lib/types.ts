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
  ssim: number | null;
  psnr: number | null;
  fileSizeBytes: number;
  notes: string | null;
  ffmpegVersion?: string | null;
  encoderName?: string | null;
  clientVersion?: string | null;
  inputHash?: string | null;
  runMs?: number | null;
  status?: string | null;
  samples?: number;
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

export type LeaderboardAnalyticsRow = {
  encoderName: string;
  codecFamily: "h264" | "hevc" | "av1" | "vp9" | "other";
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
  codecFamily: "h264" | "hevc" | "av1" | "vp9" | "other";
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
  codecFamily: "h264" | "hevc" | "av1" | "vp9" | "other";
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
