import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

const CPU_MODELS = [
  'AMD Ryzen 9 7950X',
  'AMD Ryzen 7 7800X3D',
  'AMD Ryzen 5 7600',
  'Intel Core i9-14900K',
  'Intel Core i7-14700K',
  'Intel Core i5-13600K',
  'Apple M3 Max',
  'Apple M2 Pro',
  'Intel Xeon Gold 6226R',
  'AMD EPYC 7543',
];

const GPU_MODELS = [
  '',
  'NVIDIA GeForce RTX 4090',
  'NVIDIA GeForce RTX 4070',
  'NVIDIA GeForce RTX 3060',
  'AMD Radeon RX 7900 XTX',
  'AMD Radeon RX 6800',
  'Intel Arc A770',
  'Intel Iris Xe',
  'Apple M3 Max GPU',
];

const OPERATING_SYSTEMS = [
  'Windows 11 23H2',
  'Ubuntu 24.04 LTS',
  'Fedora 41',
  'macOS 15.1',
];

const CODECS = [
  'libx264',
  'libx265',
  'libsvtav1',
  'h264_qsv',
  'hevc_qsv',
  'h264_videotoolbox',
  'hevc_videotoolbox',
  'h264_nvenc',
  'hevc_nvenc',
  'av1_nvenc',
  'h264_amf',
  'hevc_amf',
];

const PRESETS = [
  'ultrafast',
  'veryfast',
  'faster',
  'fast',
  'medium',
  'slow',
  'veryslow',
  'p3',
  'p4',
  'p5',
  'p6',
  'p7',
  'balanced',
  'quality',
  'speed',
  'hq',
];

const CRFS = [18, 22, 26, 30];

const FPS_CODEC_FACTOR: Record<string, number> = {
  libx264: 1.0,
  libx265: 0.57,
  libsvtav1: 0.46,
  h264_qsv: 1.72,
  hevc_qsv: 1.22,
  h264_videotoolbox: 1.58,
  hevc_videotoolbox: 1.18,
  h264_nvenc: 2.05,
  hevc_nvenc: 1.35,
  av1_nvenc: 0.88,
  h264_amf: 1.52,
  hevc_amf: 1.08,
};

const QUALITY_CODEC_BONUS: Record<string, number> = {
  libx264: 0.6,
  libx265: 2.0,
  libsvtav1: 2.3,
  h264_qsv: -0.2,
  hevc_qsv: 0.9,
  h264_videotoolbox: -0.4,
  hevc_videotoolbox: 0.7,
  h264_nvenc: -0.4,
  hevc_nvenc: 1.1,
  av1_nvenc: 1.8,
  h264_amf: -0.1,
  hevc_amf: 0.8,
};

const SIZE_CODEC_FACTOR: Record<string, number> = {
  libx264: 1.0,
  libx265: 0.75,
  libsvtav1: 0.69,
  h264_qsv: 0.99,
  hevc_qsv: 0.81,
  h264_videotoolbox: 1.06,
  hevc_videotoolbox: 0.87,
  h264_nvenc: 1.05,
  hevc_nvenc: 0.84,
  av1_nvenc: 0.72,
  h264_amf: 1.04,
  hevc_amf: 0.86,
};

const FPS_PRESET_FACTOR: Record<string, number> = {
  ultrafast: 1.35,
  veryfast: 1.24,
  faster: 1.20,
  fast: 1.16,
  medium: 1.0,
  slow: 0.8,
  veryslow: 0.64,
  p3: 1.18,
  p4: 1.08,
  p5: 1.0,
  p6: 0.9,
  p7: 0.82,
  balanced: 1.0,
  quality: 0.86,
  speed: 1.18,
  hq: 0.88,
};

const SINGLE_SAMPLE_SPEED_FACTOR = 1.0;
const BASE_SAMPLE_SIZE_MB = 92;

function jitter(seed: number): number {
  const x = Math.sin(seed * 12.9898) * 43758.5453123;
  return x - Math.floor(x);
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function round4(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

function pickBySeed<T>(items: readonly T[], seed: number, salt: number): T {
  const noise = jitter(seed * (salt + 1.73) + salt * 31.4159);
  const index = Math.floor(noise * items.length) % items.length;
  return items[index]!;
}

function readBooleanEnv(name: string): boolean {
  const value = String(process.env[name] || '').trim().toLowerCase();
  return value === '1' || value === 'true' || value === 'yes' || value === 'on';
}

function readCountEnv(name: string, fallback: number): number {
  const raw = Number(process.env[name]);
  if (!Number.isFinite(raw) || raw <= 0) return fallback;
  return Math.floor(raw);
}

function cpuToRam(cpuModel: string): number {
  if (cpuModel.includes('EPYC') || cpuModel.includes('Xeon')) return 64;
  if (cpuModel.includes('i9') || cpuModel.includes('7950X') || cpuModel.includes('M3 Max')) return 32;
  if (cpuModel.includes('i7') || cpuModel.includes('7800X3D') || cpuModel.includes('M2 Pro')) return 24;
  return 16;
}

function gpuToSpeedFactor(gpuModel: string): number {
  if (!gpuModel) return 0.72;
  if (gpuModel.includes('4090')) return 2.3;
  if (gpuModel.includes('4070')) return 1.85;
  if (gpuModel.includes('3060')) return 1.45;
  if (gpuModel.includes('7900')) return 1.95;
  if (gpuModel.includes('6800')) return 1.55;
  if (gpuModel.includes('A770')) return 1.4;
  if (gpuModel.includes('Iris')) return 0.95;
  if (gpuModel.includes('Apple')) return 1.35;
  return 1.0;
}

function gpuToPowerBase(gpuModel: string): number {
  if (!gpuModel) return 18;
  if (gpuModel.includes('4090')) return 285;
  if (gpuModel.includes('4070')) return 195;
  if (gpuModel.includes('3060')) return 148;
  if (gpuModel.includes('7900')) return 305;
  if (gpuModel.includes('6800')) return 215;
  if (gpuModel.includes('A770')) return 188;
  if (gpuModel.includes('Iris')) return 42;
  if (gpuModel.includes('Apple')) return 60;
  return 130;
}

function buildRow(index: number) {
  const seed = index + 1;
  const cpuModel = pickBySeed(CPU_MODELS, seed, 3);
  const gpuModel = pickBySeed(GPU_MODELS, seed, 5);
  const os = OPERATING_SYSTEMS[(index * 7 + 1) % OPERATING_SYSTEMS.length]!;
  const codec = CODECS[(index * 11 + 3) % CODECS.length]!;
  const preset = PRESETS[(index * 13 + 5) % PRESETS.length]!;
  const crf = CRFS[(index * 17 + 2) % CRFS.length]!;
  const passes = 1;

  const gpuSpeed = gpuToSpeedFactor(gpuModel);
  const codecSpeed = FPS_CODEC_FACTOR[codec] ?? 1;
  const presetSpeed = FPS_PRESET_FACTOR[preset] ?? 1;
  const crfSpeed = 1 + (crf - 24) * 0.018;
  const baseFps = 36 * gpuSpeed * codecSpeed * presetSpeed * SINGLE_SAMPLE_SPEED_FACTOR * crfSpeed;
  const fps = round2(clamp(baseFps * (0.9 + jitter(seed) * 0.2), 4, 420));

  const qualityBase = 95 - (crf - 18) * 1.5 + (QUALITY_CODEC_BONUS[codec] ?? 0) + (jitter(seed + 7) - 0.5) * 2.4;
  const vmaf = round2(clamp(qualityBase, 50, 99.5));
  const ssim = round4(clamp(0.81 + (vmaf - 60) * 0.0044 + (jitter(seed + 11) - 0.5) * 0.008, 0.72, 0.999));
  const psnr = round2(clamp(24 + (vmaf - 60) * 0.42 + (jitter(seed + 13) - 0.5) * 1.8, 20, 56));

  const sizeBase = BASE_SAMPLE_SIZE_MB * (SIZE_CODEC_FACTOR[codec] ?? 1);
  const crfScale = 1 - (crf - 24) * 0.04;
  const sizeMb = sizeBase * crfScale * (0.9 + jitter(seed + 17) * 0.2);
  const fileSizeBytes = Math.max(120_000, Math.round(sizeMb * 1024 * 1024));

  const samples = 3 + Math.floor(jitter(seed + 19) * 10);
  const gpuUtilAvg = gpuModel ? round2(clamp(48 + jitter(seed + 23) * 42, 15, 99)) : null;
  const gpuPowerAvgW = gpuModel ? round2(gpuToPowerBase(gpuModel) * (0.78 + jitter(seed + 29) * 0.34)) : null;
  const gpuMemPeakMB = gpuModel ? Math.round(1200 + jitter(seed + 31) * 6800) : null;
  const cpuUtilAvg = round2(clamp(35 + jitter(seed + 37) * 58, 10, 100));
  const cpuUtilMax = round2(clamp(cpuUtilAvg + 6 + jitter(seed + 41) * 26, cpuUtilAvg, 100));
  const peakMemoryMB = Math.round(900 + jitter(seed + 43) * 5200);
  const thermalThrottle = jitter(seed + 47) > 0.94;

  return {
    cpuModel,
    gpuModel,
    ramGB: cpuToRam(cpuModel),
    os,
    codec,
    preset,
    crf,
    passes,
    fps,
    vmaf,
    ssim,
    psnr,
    fileSizeBytes,
    notes: `Dummy benchmark row #${index + 1}`,
    gpuUtilAvg,
    gpuPowerAvgW,
    gpuMemPeakMB,
    cpuUtilAvg,
    cpuUtilMax,
    peakMemoryMB,
    thermalThrottle,
    samples,
    vmafSamples: samples,
    fpsSum: round2(fps * samples),
    fileSizeSum: round2(fileSizeBytes * samples),
    vmafSum: round2(vmaf * samples),
    ssimSamples: samples,
    ssimSum: round4(ssim * samples),
    psnrSamples: samples,
    psnrSum: round2(psnr * samples),
    gpuUtilSamples: gpuUtilAvg == null ? 0 : samples,
    gpuUtilSum: gpuUtilAvg == null ? 0 : round2(gpuUtilAvg * samples),
    gpuPowerSamples: gpuPowerAvgW == null ? 0 : samples,
    gpuPowerSum: gpuPowerAvgW == null ? 0 : round2(gpuPowerAvgW * samples),
    cpuUtilSamples: samples,
    cpuUtilSum: round2(cpuUtilAvg * samples),
    peakMemoryMax: peakMemoryMB,
    status: 'accepted',
    ffmpegVersion: 'n7.0.2',
    encoderName: codec,
    clientVersion: 'dummy-seed-1.0',
    inputHash: '53a87df054e65d284bc808b8f73e62e938b815cb6aeec8379f904ad6d792aab8',
    runMs: Math.round((1000 / Math.max(fps, 1)) * 300),
    payloadHash: `dummy_${index + 1}`,
  };
}

async function main(): Promise<void> {
  const enabled = readBooleanEnv('SEED_DUMMY_BENCHMARKS');
  if (!enabled) {
    console.log('[seed:dummy] Disabled (set SEED_DUMMY_BENCHMARKS=1 to enable).');
    return;
  }

  const targetCount = Math.min(readCountEnv('SEED_DUMMY_BENCHMARKS_COUNT', 480), 5_000);
  const rows: Array<ReturnType<typeof buildRow>> = [];
  for (let i = 0; i < targetCount; i += 1) {
    rows.push(buildRow(i));
  }

  const result = await prisma.benchmark.createMany({
    data: rows,
    skipDuplicates: true,
  });

  const total = await prisma.benchmark.count();
  console.log(`[seed:dummy] Inserted ${result.count} rows (target ${targetCount}).`);
  console.log(`[seed:dummy] Benchmark total in DB: ${total}.`);
}

main()
  .catch((error: unknown) => {
    console.error('[seed:dummy] Failed to seed dummy data:', error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
