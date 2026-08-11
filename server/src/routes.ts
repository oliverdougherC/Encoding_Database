import { Router } from 'express';
import { z } from 'zod';
import type { Prisma } from '@prisma/client';
import { prisma } from './db.js';
import crypto from 'node:crypto';
import { BoundedTtlCache } from './cache.js';
import {
  addDerivedBenchmarkFields,
  aggregateEncoders,
  aggregateHardware,
  aggregateLeaderboards,
  buildAnalyticsWhere,
  parseAnalyticsFilters,
} from './analytics.js';

const router = Router();

type BenchmarkRow = Awaited<ReturnType<typeof prisma.benchmark.findMany>>[number];
type PrismaErrorLike = {
  code?: string;
  meta?: { target?: string[] | string };
};

type SubmissionDisposition = 'pending' | 'accepted' | 'rejected' | 'suspect';

// Public ingest: remove API key requirement; rely on rate limits, validation, and heuristics

const VALID_CONTENT_CLASSES = ['mixed', 'talkingHead', 'action', 'animation', 'screen', 'nature', 'gaming'] as const;
const VALID_RESOLUTIONS = ['480p', '720p', '1080p', '1440p', '4k'] as const;

const benchmarkSchema = z.object({
  cpuModel: z.string().min(3).max(200),
  gpuModel: z.string().max(200).optional().nullable(),
  ramGB: z.coerce.number().int().nonnegative(),
  os: z.string().min(3).max(100),
  codec: z.string().min(1).max(64),
  preset: z.string().min(1).max(64),
  crf: z.coerce.number().int().min(0).max(63).optional().nullable(),
  contentClass: z.enum(VALID_CONTENT_CLASSES).optional().nullable(),
  resolution: z.enum(VALID_RESOLUTIONS).optional().nullable(),
  passes: z.coerce.number().int().min(1).max(1).optional().nullable(),
  fps: z.coerce.number().nonnegative().max(5000),
  vmaf: z.coerce.number().min(0).max(100).optional().nullable(),
  ssim: z.coerce.number().min(0).max(1).optional().nullable(),
  psnr: z.coerce.number().min(0).max(100).optional().nullable(),
  fileSizeBytes: z.coerce.number().int().nonnegative().max(1_000 * 1024 * 1024),
  notes: z.string().max(4000).optional().nullable(),
  ffmpegVersion: z.string().max(200).optional().nullable(),
  encoderName: z.string().max(100).optional().nullable(),
  clientVersion: z.string().max(100).optional().nullable(),
  inputHash: z.string().length(64).regex(/^[0-9a-f]+$/).optional().nullable(),
  runMs: z.coerce.number().int().nonnegative().max(24 * 60 * 60 * 1000).optional().nullable(),
  // Hardware metrics (Sprint 6)
  gpuUtilAvg: z.coerce.number().min(0).max(100).optional().nullable(),
  gpuPowerAvgW: z.coerce.number().min(0).max(1000).optional().nullable(),
  gpuMemPeakMB: z.coerce.number().min(0).max(100000).optional().nullable(),
  cpuUtilAvg: z.coerce.number().min(0).max(100).optional().nullable(),
  cpuUtilMax: z.coerce.number().min(0).max(100).optional().nullable(),
  peakMemoryMB: z.coerce.number().min(0).max(500000).optional().nullable(),
  thermalThrottle: z.boolean().optional().nullable(),
  // Extended telemetry (Sprint 7)
  gpuTempMaxC: z.coerce.number().min(0).max(130).optional().nullable(),
  cpuFreqAvgMHz: z.coerce.number().min(0).max(10000).optional().nullable(),
  cpuTempMaxC: z.coerce.number().min(0).max(130).optional().nullable(),
  ffmpegCpuUtilAvg: z.coerce.number().min(0).max(10000).optional().nullable(),
  ffmpegCpuUtilMax: z.coerce.number().min(0).max(10000).optional().nullable(),
  ffmpegReadMB: z.coerce.number().min(0).max(5_000_000).optional().nullable(),
  ffmpegWriteMB: z.coerce.number().min(0).max(5_000_000).optional().nullable(),
  ffmpegCpuTimeS: z.coerce.number().min(0).max(24 * 60 * 60).optional().nullable(),
  batteryPercentStart: z.coerce.number().min(0).max(100).optional().nullable(),
  batteryPercentEnd: z.coerce.number().min(0).max(100).optional().nullable(),
  batteryPercentDrop: z.coerce.number().min(0).max(100).optional().nullable(),
  powerSource: z.enum(['ac', 'battery']).optional().nullable(),
  sampleCount: z.coerce.number().int().min(0).max(1_000_000).optional().nullable(),
  monitorDurationMs: z.coerce.number().int().min(0).max(24 * 60 * 60 * 1000).optional().nullable(),
  cpuSampleCount: z.coerce.number().int().min(0).max(1_000_000).optional().nullable(),
  gpuSampleCount: z.coerce.number().int().min(0).max(1_000_000).optional().nullable(),
  ffmpegSampleCount: z.coerce.number().int().min(0).max(1_000_000).optional().nullable(),
  batterySampleCount: z.coerce.number().int().min(0).max(1_000_000).optional().nullable(),
  telemetrySources: z.string().max(400).optional().nullable(),
  telemetryMissing: z.string().max(400).optional().nullable(),
}).strict();

const CPU_FREQ_MIN_MHZ = 100;
const CPU_FREQ_MAX_MHZ = 10_000;

export function normalizeCpuFreqMHz(value: unknown): number | null {
  const raw = Number(value);
  if (!Number.isFinite(raw) || raw <= 0) return null;

  const candidates = [
    raw,               // already MHz
    raw * 1000,        // GHz -> MHz
    raw / 1000,        // KHz -> MHz
    raw / 1_000_000,   // Hz -> MHz
  ];
  const plausible = candidates.filter((n, i, arr) => {
    if (!Number.isFinite(n)) return false;
    if (n < CPU_FREQ_MIN_MHZ || n > CPU_FREQ_MAX_MHZ) return false;
    return arr.findIndex((x) => x === n) === i;
  });
  if (plausible.length === 0) return null;

  if (raw >= CPU_FREQ_MIN_MHZ && raw <= CPU_FREQ_MAX_MHZ) {
    return raw;
  }
  if (raw > 0 && raw <= 15) {
    return raw * 1000;
  }
  return plausible.reduce((best, current) => (
    Math.abs(current - 3000) < Math.abs(best - 3000) ? current : best
  ));
}

// Type inferred from Zod schema for proper type safety
type BenchmarkSubmission = z.infer<typeof benchmarkSchema>;

export function buildSubmissionPayloadHash(data: BenchmarkSubmission): string {
  const normalizedGpuModel = (data.gpuModel && data.gpuModel.trim()) ? data.gpuModel.trim() : '';
  const contentClassValue = data.contentClass ?? 'mixed';
  const resolutionValue = data.resolution ?? '1080p';
  const significant = {
    cpuModel: data.cpuModel,
    gpuModel: normalizedGpuModel,
    ramGB: data.ramGB,
    os: data.os,
    codec: data.codec,
    preset: data.preset,
    crf: Number(data.crf ?? 24),
    contentClass: contentClassValue,
    resolution: resolutionValue,
    passes: 1,
    fps: Number(data.fps),
    vmaf: data.vmaf ?? null,
    ssim: data.ssim ?? null,
    psnr: data.psnr ?? null,
    fileSizeBytes: Number(data.fileSizeBytes),
    notes: data.notes ?? null,
    ffmpegVersion: data.ffmpegVersion ?? null,
    encoderName: data.encoderName ?? null,
    clientVersion: data.clientVersion ?? null,
    inputHash: data.inputHash ?? null,
    runMs: data.runMs ?? null,
    gpuUtilAvg: data.gpuUtilAvg ?? null,
    gpuPowerAvgW: data.gpuPowerAvgW ?? null,
    gpuMemPeakMB: data.gpuMemPeakMB ?? null,
    cpuUtilAvg: data.cpuUtilAvg ?? null,
    cpuUtilMax: data.cpuUtilMax ?? null,
    peakMemoryMB: data.peakMemoryMB ?? null,
    thermalThrottle: data.thermalThrottle ?? null,
    gpuTempMaxC: data.gpuTempMaxC ?? null,
    cpuFreqAvgMHz: data.cpuFreqAvgMHz ?? null,
    cpuTempMaxC: data.cpuTempMaxC ?? null,
    ffmpegCpuUtilAvg: data.ffmpegCpuUtilAvg ?? null,
    ffmpegCpuUtilMax: data.ffmpegCpuUtilMax ?? null,
    ffmpegReadMB: data.ffmpegReadMB ?? null,
    ffmpegWriteMB: data.ffmpegWriteMB ?? null,
    ffmpegCpuTimeS: data.ffmpegCpuTimeS ?? null,
    batteryPercentStart: data.batteryPercentStart ?? null,
    batteryPercentEnd: data.batteryPercentEnd ?? null,
    batteryPercentDrop: data.batteryPercentDrop ?? null,
    powerSource: data.powerSource ?? null,
    sampleCount: data.sampleCount ?? null,
    monitorDurationMs: data.monitorDurationMs ?? null,
    cpuSampleCount: data.cpuSampleCount ?? null,
    gpuSampleCount: data.gpuSampleCount ?? null,
    ffmpegSampleCount: data.ffmpegSampleCount ?? null,
    batterySampleCount: data.batterySampleCount ?? null,
    telemetrySources: data.telemetrySources ?? null,
    telemetryMissing: data.telemetryMissing ?? null,
  } as const;
  return crypto.createHash('sha256').update(JSON.stringify(significant)).digest('hex');
}

function getUniqueConflictTargets(error: unknown): string[] {
  const target = (error as PrismaErrorLike | null)?.meta?.target;
  if (Array.isArray(target)) {
    return target.filter((item): item is string => typeof item === 'string');
  }
  if (typeof target === 'string') return [target];
  return [];
}

function isPayloadHashConflict(error: unknown): boolean {
  const e = error as PrismaErrorLike | null;
  if (e?.code !== 'P2002') return false;
  return getUniqueConflictTargets(error).some((target) => target.toLowerCase().includes('payloadhash'));
}

function isRetryableSubmitConflict(error: unknown): boolean {
  const e = error as PrismaErrorLike | null;
  if (e?.code !== 'P2002') return false;
  if (isPayloadHashConflict(error)) return false;
  return true;
}

const MAX_SUBMIT_TRANSACTION_RETRIES = 1;

export async function runSubmitTransactionWithRetry<T>(operation: () => Promise<T>): Promise<T> {
  let attemptsRemaining = MAX_SUBMIT_TRANSACTION_RETRIES;
  // Retry a single time for non-payloadHash unique conflicts caused by concurrent create races.
  for (;;) {
    try {
      return await operation();
    } catch (error) {
      if (attemptsRemaining > 0 && isRetryableSubmitConflict(error)) {
        attemptsRemaining -= 1;
        continue;
      }
      throw error;
    }
  }
}

export function determineSubmissionStatus(input: {
  plausible: boolean;
  canonicalInput: boolean;
  maxAbsoluteZScore: number;
}): SubmissionDisposition {
  if (!input.plausible || input.maxAbsoluteZScore > 6) return 'rejected';
  if (input.maxAbsoluteZScore > 3) return 'suspect';
  return input.canonicalInput ? 'accepted' : 'pending';
}

const TELEMETRY_NOTE_REGEX = /telemetry=(\{[\s\S]*?\})(?:;|$)/;
const TELEMETRY_META_NOTE_REGEX = /telemetry_meta=(\{[\s\S]*?\})(?:;|$)/;

export function parseTelemetryFromNotes(notes: string | null | undefined): Partial<BenchmarkSubmission> {
  if (!notes) return {};
  const match = TELEMETRY_NOTE_REGEX.exec(notes);
  if (!match?.[1]) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(match[1]);
  } catch {
    return {};
  }
  if (!parsed || typeof parsed !== 'object') return {};
  const raw = parsed as Record<string, unknown>;

  const out: Partial<BenchmarkSubmission> = {};
  const putNumber = (key: keyof BenchmarkSubmission, integer = false): void => {
    const v = raw[String(key)];
    if (v == null) return;
    const n = typeof v === 'number' ? v : (typeof v === 'string' ? Number(v) : NaN);
    if (!Number.isFinite(n)) return;
    (out as Record<string, unknown>)[String(key)] = integer ? Math.round(n) : n;
  };

  putNumber('gpuUtilAvg');
  putNumber('gpuPowerAvgW');
  putNumber('gpuMemPeakMB');
  putNumber('cpuUtilAvg');
  putNumber('cpuUtilMax');
  putNumber('peakMemoryMB');
  if (typeof raw.thermalThrottle === 'boolean') out.thermalThrottle = raw.thermalThrottle;

  putNumber('gpuTempMaxC');
  putNumber('cpuFreqAvgMHz');
  putNumber('cpuTempMaxC');
  putNumber('ffmpegCpuUtilAvg');
  putNumber('ffmpegCpuUtilMax');
  putNumber('ffmpegReadMB');
  putNumber('ffmpegWriteMB');
  putNumber('ffmpegCpuTimeS');
  putNumber('batteryPercentStart');
  putNumber('batteryPercentEnd');
  putNumber('batteryPercentDrop');
  const ps = raw.powerSource;
  if (ps === 'ac' || ps === 'battery') out.powerSource = ps;
  putNumber('sampleCount', true);
  putNumber('monitorDurationMs', true);
  putNumber('cpuSampleCount', true);
  putNumber('gpuSampleCount', true);
  putNumber('ffmpegSampleCount', true);
  putNumber('batterySampleCount', true);

  return out;
}

export function parseTelemetryMetaFromNotes(notes: string | null | undefined): Partial<BenchmarkSubmission> {
  if (!notes) return {};
  const match = TELEMETRY_META_NOTE_REGEX.exec(notes);
  if (!match?.[1]) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(match[1]);
  } catch {
    return {};
  }
  if (!parsed || typeof parsed !== 'object') return {};
  const raw = parsed as Record<string, unknown>;
  const out: Partial<BenchmarkSubmission> = {};
  const sources = typeof raw.telemetrySources === 'string' ? raw.telemetrySources.trim() : '';
  if (sources) out.telemetrySources = sources.slice(0, 400);
  const missing = typeof raw.telemetryMissing === 'string' ? raw.telemetryMissing.trim() : '';
  if (missing) out.telemetryMissing = missing.slice(0, 400);
  return out;
}

function _applyTelemetryFallback(data: BenchmarkSubmission): void {
  const telemetry = parseTelemetryFromNotes(data.notes);
  const telemetryMeta = parseTelemetryMetaFromNotes(data.notes);
  const keys: Array<keyof BenchmarkSubmission> = [
    'gpuUtilAvg', 'gpuPowerAvgW', 'gpuMemPeakMB',
    'cpuUtilAvg', 'cpuUtilMax', 'peakMemoryMB', 'thermalThrottle',
    'gpuTempMaxC', 'cpuFreqAvgMHz', 'cpuTempMaxC',
    'ffmpegCpuUtilAvg', 'ffmpegCpuUtilMax',
    'ffmpegReadMB', 'ffmpegWriteMB', 'ffmpegCpuTimeS',
    'batteryPercentStart', 'batteryPercentEnd', 'batteryPercentDrop',
    'powerSource', 'sampleCount', 'monitorDurationMs',
    'cpuSampleCount', 'gpuSampleCount', 'ffmpegSampleCount', 'batterySampleCount',
  ];
  for (const key of keys) {
    if (data[key] == null && telemetry[key] != null) {
      (data[key] as BenchmarkSubmission[typeof key]) = telemetry[key] as BenchmarkSubmission[typeof key];
    }
  }
  if (data.telemetrySources == null && telemetryMeta.telemetrySources != null) {
    data.telemetrySources = telemetryMeta.telemetrySources;
  }
  if (data.telemetryMissing == null && telemetryMeta.telemetryMissing != null) {
    data.telemetryMissing = telemetryMeta.telemetryMissing;
  }
}

// Helper to log errors in structured JSON format
function logError(context: string, error: unknown): void {
  console.error(JSON.stringify({
    time: new Date().toISOString(),
    level: 'error',
    context,
    error: error instanceof Error ? error.message : String(error),
    stack: error instanceof Error ? error.stack : undefined,
  }));
}

// Simple canonical hash list for MVP (publish in README)
const CANONICAL_INPUT_HASHES = new Set<string>([
  '53a87df054e65d284bc808b8f73e62e938b815cb6aeec8379f904ad6d792aab8',
]);

type AggregateKeySource = Pick<
  Prisma.SubmissionGetPayload<Record<string, never>>,
  'cpuModel' | 'gpuModel' | 'ramGB' | 'os' | 'codec' | 'preset' | 'crf' | 'contentClass' | 'resolution' | 'passes'
>;

export function benchmarkWhereFromSubmission(submission: AggregateKeySource): Prisma.BenchmarkWhereInput {
  return {
    cpuModel: submission.cpuModel,
    gpuModel: submission.gpuModel,
    ramGB: submission.ramGB,
    os: submission.os,
    codec: submission.codec,
    preset: submission.preset,
    crf: submission.crf,
    contentClass: submission.contentClass,
    resolution: submission.resolution,
    passes: submission.passes,
  };
}

async function findBenchmarkForPayloadHash(payloadHash: string): Promise<BenchmarkRow | null> {
  // Submission is the immutable idempotency record. Benchmark.payloadHash only identifies
  // the first payload that created an aggregate and cannot resolve later retries.
  const submission = await prisma.submission.findUnique({ where: { payloadHash } });
  if (submission) {
    return prisma.benchmark.findFirst({ where: benchmarkWhereFromSubmission(submission) });
  }

  // Preserve idempotency for records written before Submission became authoritative.
  return prisma.benchmark.findUnique({ where: { payloadHash } });
}

// Method guard for /submit (reject non-POST) - must be registered before the POST handler
router.all('/submit', (req, res, next) => {
  if (req.method === 'POST') {
    return next();
  }
  res.setHeader('Allow', 'POST');
  return res.status(405).json({ error: 'Method Not Allowed' });
});

router.post('/submit', async (req, res) => {
  const parse = benchmarkSchema.safeParse(req.body);
  if (!parse.success) {
    return res.status(400).json({ error: 'Invalid payload', details: parse.error.flatten() });
  }
  const data: BenchmarkSubmission = parse.data;
  if (data.crf == null || !Number.isFinite(Number(data.crf))) {
    data.crf = 24;
  }
  if (data.passes == null) {
    data.passes = 1;
  }
  _applyTelemetryFallback(data);
  data.cpuFreqAvgMHz = normalizeCpuFreqMHz(data.cpuFreqAvgMHz);
  const contentClassValue = data.contentClass ?? 'mixed';
  const resolutionValue = data.resolution ?? '1080p';
  const passesValue: 1 = 1;
  const payloadHash = buildSubmissionPayloadHash(data);

  try {
    // Fast path: if the exact same payload was already counted, return existing (idempotency)
    const existingByHash = await findBenchmarkForPayloadHash(payloadHash).catch((err: unknown) => {
      logError('findUnique by payloadHash', err);
      return null;
    });
    if (existingByHash) {
      return res.status(200).json(existingByHash);
    }

    // Heuristics: ensure plausible values
    const isCodecOk = typeof data.codec === 'string' && data.codec.length <= 64;
    const isPresetOk = typeof data.preset === 'string' && data.preset.length <= 64;
    const isFpsOk = data.fps >= 0.1 && data.fps <= 5000; // broad cap but >0
    const isSizeOk = data.fileSizeBytes >= 10 * 1024 && data.fileSizeBytes <= 1000 * 1024 * 1024; // >=10KB and <=1GB
    const namesOk = data.cpuModel.trim().length >= 3 && data.os.trim().length >= 3;
    const inputHashOk = !!data.inputHash && CANONICAL_INPUT_HASHES.has(data.inputHash);
    // Quality scoring using robust statistics across recent accepted submissions for same key.
    // Use empty string for "no GPU" so compound unique (cpuModel, gpuModel, ...) has one row per hardware;
    // in PostgreSQL, NULL in a unique column allows multiple rows, so we normalize to '' for Benchmark.
    const gpuModelValue = (data.gpuModel && data.gpuModel.trim()) ? data.gpuModel.trim() : '';
    const key = {
      cpuModel: data.cpuModel,
      gpuModel: gpuModelValue,
      ramGB: data.ramGB,
      os: data.os,
      codec: data.codec,
      preset: data.preset,
      crf: Number(data.crf ?? 24),
      contentClass: contentClassValue,
      resolution: resolutionValue,
      passes: passesValue,
    };

    // Compute robust Z-scores via PostgreSQL (S-06): median + MAD in a single query
    let fpsZ = 0, sizeZ = 0, vmafZ = 0, ssimZ = 0, psnrZ = 0;
    try {
      const stats: Array<{
        fps_med: number | null; fps_mad: number | null;
        size_med: number | null; size_mad: number | null;
        vmaf_med: number | null; vmaf_mad: number | null;
        ssim_med: number | null; ssim_mad: number | null;
        psnr_med: number | null; psnr_mad: number | null;
        cnt: bigint | number;
      }> = await prisma.$queryRaw`
        WITH recent AS (
          SELECT "fps", "fileSizeBytes"::double precision AS size, "vmaf", "ssim", "psnr"
          FROM "Submission"
          WHERE "status" = 'accepted'
            AND "cpuModel" = ${key.cpuModel}
            AND "gpuModel" = ${key.gpuModel}
            AND "ramGB" = ${key.ramGB}
            AND "os" = ${key.os}
            AND "codec" = ${key.codec}
            AND "preset" = ${key.preset}
            AND "crf" = ${key.crf}
            AND "contentClass" = ${key.contentClass}
            AND "resolution" = ${key.resolution}
            AND "passes" = ${key.passes}
          ORDER BY "createdAt" DESC
          LIMIT 200
        )
        SELECT
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY fps) AS fps_med,
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(fps - (SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY fps) FROM recent))) AS fps_mad,
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY size) AS size_med,
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(size - (SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY size) FROM recent))) AS size_mad,
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY COALESCE(vmaf, 0)) FILTER (WHERE vmaf IS NOT NULL) AS vmaf_med,
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(COALESCE(vmaf, 0) - COALESCE((SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY COALESCE(vmaf, 0)) FROM recent WHERE vmaf IS NOT NULL), 0))) FILTER (WHERE vmaf IS NOT NULL) AS vmaf_mad,
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY COALESCE(ssim, 0)) FILTER (WHERE ssim IS NOT NULL) AS ssim_med,
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(COALESCE(ssim, 0) - COALESCE((SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY COALESCE(ssim, 0)) FROM recent WHERE ssim IS NOT NULL), 0))) FILTER (WHERE ssim IS NOT NULL) AS ssim_mad,
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY COALESCE(psnr, 0)) FILTER (WHERE psnr IS NOT NULL) AS psnr_med,
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(COALESCE(psnr, 0) - COALESCE((SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY COALESCE(psnr, 0)) FROM recent WHERE psnr IS NOT NULL), 0))) FILTER (WHERE psnr IS NOT NULL) AS psnr_mad,
          COUNT(*) AS cnt
        FROM recent
      `;
      const row = stats[0];
      if (row && Number(row.cnt) > 0) {
        const robustZ = (x: number, med: number, madVal: number): number => {
          const denom = madVal > 0 ? 1.4826 * madVal : 1;
          return (x - med) / denom;
        };
        const fpsMed = Number(row.fps_med ?? data.fps);
        const fpsMad = Number(row.fps_mad ?? 0);
        const sizeMed = Number(row.size_med ?? data.fileSizeBytes);
        const sizeMad = Number(row.size_mad ?? 0);
        fpsZ = robustZ(Number(data.fps), fpsMed, fpsMad);
        sizeZ = robustZ(Number(data.fileSizeBytes), sizeMed, sizeMad);
        if (data.vmaf != null) {
          const vmafMed = Number(row.vmaf_med ?? data.vmaf ?? 0);
          const vmafMad = Number(row.vmaf_mad ?? 0);
          vmafZ = robustZ(Number(data.vmaf), vmafMed, vmafMad);
        }
        if (data.ssim != null) {
          const ssimMed = Number(row.ssim_med ?? data.ssim ?? 0);
          const ssimMad = Number(row.ssim_mad ?? 0);
          ssimZ = robustZ(Number(data.ssim), ssimMed, ssimMad);
        }
        if (data.psnr != null) {
          const psnrMed = Number(row.psnr_med ?? data.psnr ?? 0);
          const psnrMad = Number(row.psnr_mad ?? 0);
          psnrZ = robustZ(Number(data.psnr), psnrMed, psnrMad);
        }
      }
    } catch (err) {
      logError('computeRobustZScores', err);
    }

    // Penalize extreme deviations; also check impossible combos
    const impossible = !(isCodecOk && isPresetOk && isFpsOk && isSizeOk && namesOk);
    const maxAbsoluteZScore = Math.max(Math.abs(fpsZ), Math.abs(sizeZ), Math.abs(vmafZ), Math.abs(ssimZ), Math.abs(psnrZ));
    const status = determineSubmissionStatus({
      plausible: !impossible,
      canonicalInput: inputHashOk,
      maxAbsoluteZScore,
    });
    const qualityScore = (() => {
      // Score 0..100 combining normalized robust Z deviations
      const clamp = (x: number) => Math.max(0, Math.min(100, x));
      const scoreFps = 100 * Math.exp(-0.5 * (fpsZ / 2.5) * (fpsZ / 2.5));
      const scoreSize = 100 * Math.exp(-0.5 * (sizeZ / 2.5) * (sizeZ / 2.5));
      const scoreVmaf = 100 * Math.exp(-0.5 * (vmafZ / 2.5) * (vmafZ / 2.5));
      const weighted = 0.4 * scoreFps + 0.3 * scoreSize + 0.3 * scoreVmaf;
      return clamp(weighted);
    })();

    // Composite key for aggregation (single row per hardware/codec/preset/crf)
    let createdNew = false;
    // All writes (Submission audit + Benchmark upsert) happen inside a single transaction.
    // Retry once for benchmark-key unique conflicts caused by concurrent first-time creates.
    const row = await runSubmitTransactionWithRetry(() => prisma.$transaction(async (tx: Prisma.TransactionClient) => {
      // Store raw submission record for auditability (inside tx so it rolls back on failure)
      await tx.submission.create({
        data: {
          cpuModel: data.cpuModel,
          gpuModel: (data.gpuModel && data.gpuModel.trim()) ? data.gpuModel.trim() : '',
          ramGB: data.ramGB,
          os: data.os,
          codec: data.codec,
          preset: data.preset,
          crf: Number(data.crf ?? 24),
          contentClass: contentClassValue,
          resolution: resolutionValue,
          passes: passesValue,
          fps: Number(data.fps),
          vmaf: data.vmaf == null ? null : Number(data.vmaf),
          ssim: data.ssim == null ? null : Number(data.ssim),
          psnr: data.psnr == null ? null : Number(data.psnr),
          fileSizeBytes: Number(data.fileSizeBytes),
          notes: data.notes || null,
          ffmpegVersion: data.ffmpegVersion || null,
          encoderName: data.encoderName || null,
          clientVersion: data.clientVersion || null,
          inputHash: data.inputHash || null,
          runMs: data.runMs != null ? Number(data.runMs) : null,
          gpuUtilAvg: data.gpuUtilAvg != null ? Number(data.gpuUtilAvg) : null,
          gpuPowerAvgW: data.gpuPowerAvgW != null ? Number(data.gpuPowerAvgW) : null,
          gpuMemPeakMB: data.gpuMemPeakMB != null ? Number(data.gpuMemPeakMB) : null,
          cpuUtilAvg: data.cpuUtilAvg != null ? Number(data.cpuUtilAvg) : null,
          cpuUtilMax: data.cpuUtilMax != null ? Number(data.cpuUtilMax) : null,
          peakMemoryMB: data.peakMemoryMB != null ? Number(data.peakMemoryMB) : null,
          thermalThrottle: data.thermalThrottle ?? null,
          gpuTempMaxC: data.gpuTempMaxC != null ? Number(data.gpuTempMaxC) : null,
          cpuFreqAvgMHz: data.cpuFreqAvgMHz != null ? Number(data.cpuFreqAvgMHz) : null,
          cpuTempMaxC: data.cpuTempMaxC != null ? Number(data.cpuTempMaxC) : null,
          ffmpegCpuUtilAvg: data.ffmpegCpuUtilAvg != null ? Number(data.ffmpegCpuUtilAvg) : null,
          ffmpegCpuUtilMax: data.ffmpegCpuUtilMax != null ? Number(data.ffmpegCpuUtilMax) : null,
          ffmpegReadMB: data.ffmpegReadMB != null ? Number(data.ffmpegReadMB) : null,
          ffmpegWriteMB: data.ffmpegWriteMB != null ? Number(data.ffmpegWriteMB) : null,
          ffmpegCpuTimeS: data.ffmpegCpuTimeS != null ? Number(data.ffmpegCpuTimeS) : null,
          batteryPercentStart: data.batteryPercentStart != null ? Number(data.batteryPercentStart) : null,
          batteryPercentEnd: data.batteryPercentEnd != null ? Number(data.batteryPercentEnd) : null,
          batteryPercentDrop: data.batteryPercentDrop != null ? Number(data.batteryPercentDrop) : null,
          powerSource: data.powerSource ?? null,
          sampleCount: data.sampleCount != null ? Number(data.sampleCount) : null,
          monitorDurationMs: data.monitorDurationMs != null ? Number(data.monitorDurationMs) : null,
          cpuSampleCount: data.cpuSampleCount != null ? Number(data.cpuSampleCount) : null,
          gpuSampleCount: data.gpuSampleCount != null ? Number(data.gpuSampleCount) : null,
          ffmpegSampleCount: data.ffmpegSampleCount != null ? Number(data.ffmpegSampleCount) : null,
          batterySampleCount: data.batterySampleCount != null ? Number(data.batterySampleCount) : null,
          telemetrySources: data.telemetrySources ?? null,
          telemetryMissing: data.telemetryMissing ?? null,
          payloadHash,
          status,
          qualityScore,
        },
      });

      const existing = await tx.benchmark.findFirst({
        where: key,
        orderBy: { createdAt: 'desc' },
      });
      if (!existing) {
        createdNew = true;
        // For new benchmarks, only count as sample if accepted
        const initialSamples = status === 'accepted' ? 1 : 0;
        const initialVmafSamples = (status === 'accepted' && data.vmaf != null) ? 1 : 0;
        const initialSsimSamples = (status === 'accepted' && data.ssim != null) ? 1 : 0;
        const initialPsnrSamples = (status === 'accepted' && data.psnr != null) ? 1 : 0;
        const initialFpsSum = status === 'accepted' ? Number(data.fps) : 0;
        const initialFileSizeSum = status === 'accepted' ? Number(data.fileSizeBytes) : 0;
        const initialVmafSum = (status === 'accepted' && data.vmaf != null) ? Number(data.vmaf) : 0;
        const initialSsimSum = (status === 'accepted' && data.ssim != null) ? Number(data.ssim) : 0;
        const initialPsnrSum = (status === 'accepted' && data.psnr != null) ? Number(data.psnr) : 0;
        const initialGpuUtilSamples = (status === 'accepted' && data.gpuUtilAvg != null) ? 1 : 0;
        const initialGpuUtilSum = (status === 'accepted' && data.gpuUtilAvg != null) ? Number(data.gpuUtilAvg) : 0;
        const initialGpuPowerSamples = (status === 'accepted' && data.gpuPowerAvgW != null) ? 1 : 0;
        const initialGpuPowerSum = (status === 'accepted' && data.gpuPowerAvgW != null) ? Number(data.gpuPowerAvgW) : 0;
        const initialCpuUtilSamples = (status === 'accepted' && data.cpuUtilAvg != null) ? 1 : 0;
        const initialCpuUtilSum = (status === 'accepted' && data.cpuUtilAvg != null) ? Number(data.cpuUtilAvg) : 0;
        const initialPeakMemoryMax = (status === 'accepted' && data.peakMemoryMB != null) ? Number(data.peakMemoryMB) : null;
        const initialCpuFreqSamples = (status === 'accepted' && data.cpuFreqAvgMHz != null) ? 1 : 0;
        const initialCpuFreqSum = (status === 'accepted' && data.cpuFreqAvgMHz != null) ? Number(data.cpuFreqAvgMHz) : 0;
        const initialFfmpegCpuUtilSamples = (status === 'accepted' && data.ffmpegCpuUtilAvg != null) ? 1 : 0;
        const initialFfmpegCpuUtilSum = (status === 'accepted' && data.ffmpegCpuUtilAvg != null) ? Number(data.ffmpegCpuUtilAvg) : 0;
        const initialFfmpegReadSamples = (status === 'accepted' && data.ffmpegReadMB != null) ? 1 : 0;
        const initialFfmpegReadSum = (status === 'accepted' && data.ffmpegReadMB != null) ? Number(data.ffmpegReadMB) : 0;
        const initialFfmpegWriteSamples = (status === 'accepted' && data.ffmpegWriteMB != null) ? 1 : 0;
        const initialFfmpegWriteSum = (status === 'accepted' && data.ffmpegWriteMB != null) ? Number(data.ffmpegWriteMB) : 0;
        const initialFfmpegCpuTimeSamples = (status === 'accepted' && data.ffmpegCpuTimeS != null) ? 1 : 0;
        const initialFfmpegCpuTimeSum = (status === 'accepted' && data.ffmpegCpuTimeS != null) ? Number(data.ffmpegCpuTimeS) : 0;
        const initialBatteryStartSamples = (status === 'accepted' && data.batteryPercentStart != null) ? 1 : 0;
        const initialBatteryStartSum = (status === 'accepted' && data.batteryPercentStart != null) ? Number(data.batteryPercentStart) : 0;
        const initialBatteryEndSamples = (status === 'accepted' && data.batteryPercentEnd != null) ? 1 : 0;
        const initialBatteryEndSum = (status === 'accepted' && data.batteryPercentEnd != null) ? Number(data.batteryPercentEnd) : 0;
        const initialBatteryDropSamples = (status === 'accepted' && data.batteryPercentDrop != null) ? 1 : 0;
        const initialBatteryDropSum = (status === 'accepted' && data.batteryPercentDrop != null) ? Number(data.batteryPercentDrop) : 0;
        const initialSampleCountSamples = (status === 'accepted' && data.sampleCount != null) ? 1 : 0;
        const initialSampleCountSum = (status === 'accepted' && data.sampleCount != null) ? Number(data.sampleCount) : 0;
        const initialMonitorDurationSamples = (status === 'accepted' && data.monitorDurationMs != null) ? 1 : 0;
        const initialMonitorDurationSum = (status === 'accepted' && data.monitorDurationMs != null) ? Number(data.monitorDurationMs) : 0;
        const initialCpuSampleCountSamples = (status === 'accepted' && data.cpuSampleCount != null) ? 1 : 0;
        const initialCpuSampleCountSum = (status === 'accepted' && data.cpuSampleCount != null) ? Number(data.cpuSampleCount) : 0;
        const initialGpuSampleCountSamples = (status === 'accepted' && data.gpuSampleCount != null) ? 1 : 0;
        const initialGpuSampleCountSum = (status === 'accepted' && data.gpuSampleCount != null) ? Number(data.gpuSampleCount) : 0;
        const initialFfmpegSampleCountSamples = (status === 'accepted' && data.ffmpegSampleCount != null) ? 1 : 0;
        const initialFfmpegSampleCountSum = (status === 'accepted' && data.ffmpegSampleCount != null) ? Number(data.ffmpegSampleCount) : 0;
        const initialBatterySampleCountSamples = (status === 'accepted' && data.batterySampleCount != null) ? 1 : 0;
        const initialBatterySampleCountSum = (status === 'accepted' && data.batterySampleCount != null) ? Number(data.batterySampleCount) : 0;
        return tx.benchmark.create({
          data: {
            cpuModel: key.cpuModel,
            gpuModel: gpuModelValue,
            ramGB: key.ramGB,
            os: key.os,
            codec: key.codec,
            preset: key.preset,
            crf: key.crf,
            contentClass: key.contentClass,
            resolution: key.resolution,
            passes: key.passes,
            fps: data.fps,
            vmaf: data.vmaf ?? null,
            ssim: data.ssim ?? null,
            psnr: data.psnr ?? null,
            fileSizeBytes: data.fileSizeBytes,
          notes: data.notes || null,
          gpuUtilAvg: data.gpuUtilAvg != null ? Number(data.gpuUtilAvg) : null,
          gpuPowerAvgW: data.gpuPowerAvgW != null ? Number(data.gpuPowerAvgW) : null,
          gpuMemPeakMB: data.gpuMemPeakMB != null ? Number(data.gpuMemPeakMB) : null,
          cpuUtilAvg: data.cpuUtilAvg != null ? Number(data.cpuUtilAvg) : null,
          cpuUtilMax: data.cpuUtilMax != null ? Number(data.cpuUtilMax) : null,
          peakMemoryMB: data.peakMemoryMB != null ? Number(data.peakMemoryMB) : null,
          thermalThrottle: data.thermalThrottle ?? null,
          gpuTempMaxC: data.gpuTempMaxC != null ? Number(data.gpuTempMaxC) : null,
          cpuFreqAvgMHz: data.cpuFreqAvgMHz != null ? Number(data.cpuFreqAvgMHz) : null,
          cpuTempMaxC: data.cpuTempMaxC != null ? Number(data.cpuTempMaxC) : null,
          ffmpegCpuUtilAvg: data.ffmpegCpuUtilAvg != null ? Number(data.ffmpegCpuUtilAvg) : null,
          ffmpegCpuUtilMax: data.ffmpegCpuUtilMax != null ? Number(data.ffmpegCpuUtilMax) : null,
          ffmpegReadMB: data.ffmpegReadMB != null ? Number(data.ffmpegReadMB) : null,
          ffmpegWriteMB: data.ffmpegWriteMB != null ? Number(data.ffmpegWriteMB) : null,
          ffmpegCpuTimeS: data.ffmpegCpuTimeS != null ? Number(data.ffmpegCpuTimeS) : null,
          batteryPercentStart: data.batteryPercentStart != null ? Number(data.batteryPercentStart) : null,
          batteryPercentEnd: data.batteryPercentEnd != null ? Number(data.batteryPercentEnd) : null,
          batteryPercentDrop: data.batteryPercentDrop != null ? Number(data.batteryPercentDrop) : null,
          powerSource: data.powerSource ?? null,
          sampleCount: data.sampleCount != null ? Number(data.sampleCount) : null,
          monitorDurationMs: data.monitorDurationMs != null ? Number(data.monitorDurationMs) : null,
          cpuSampleCount: data.cpuSampleCount != null ? Number(data.cpuSampleCount) : null,
          gpuSampleCount: data.gpuSampleCount != null ? Number(data.gpuSampleCount) : null,
          ffmpegSampleCount: data.ffmpegSampleCount != null ? Number(data.ffmpegSampleCount) : null,
          batterySampleCount: data.batterySampleCount != null ? Number(data.batterySampleCount) : null,
          status,
          ffmpegVersion: data.ffmpegVersion || null,
          encoderName: data.encoderName || null,
          clientVersion: data.clientVersion || null,
            inputHash: data.inputHash || null,
            runMs: data.runMs != null ? Number(data.runMs) : null,
            payloadHash,
            samples: initialSamples,
            vmafSamples: initialVmafSamples,
            ssimSamples: initialSsimSamples,
            psnrSamples: initialPsnrSamples,
            fpsSum: initialFpsSum,
            fileSizeSum: initialFileSizeSum,
            vmafSum: initialVmafSum,
            ssimSum: initialSsimSum,
            psnrSum: initialPsnrSum,
            gpuUtilSamples: initialGpuUtilSamples,
            gpuUtilSum: initialGpuUtilSum,
            gpuPowerSamples: initialGpuPowerSamples,
            gpuPowerSum: initialGpuPowerSum,
            cpuUtilSamples: initialCpuUtilSamples,
            cpuUtilSum: initialCpuUtilSum,
            peakMemoryMax: initialPeakMemoryMax,
            cpuFreqSamples: initialCpuFreqSamples,
            cpuFreqSum: initialCpuFreqSum,
            ffmpegCpuUtilSamples: initialFfmpegCpuUtilSamples,
            ffmpegCpuUtilSum: initialFfmpegCpuUtilSum,
            ffmpegReadSamples: initialFfmpegReadSamples,
            ffmpegReadSum: initialFfmpegReadSum,
            ffmpegWriteSamples: initialFfmpegWriteSamples,
            ffmpegWriteSum: initialFfmpegWriteSum,
            ffmpegCpuTimeSamples: initialFfmpegCpuTimeSamples,
            ffmpegCpuTimeSum: initialFfmpegCpuTimeSum,
            batteryStartSamples: initialBatteryStartSamples,
            batteryStartSum: initialBatteryStartSum,
            batteryEndSamples: initialBatteryEndSamples,
            batteryEndSum: initialBatteryEndSum,
            batteryDropSamples: initialBatteryDropSamples,
            batteryDropSum: initialBatteryDropSum,
            sampleCountSamples: initialSampleCountSamples,
            sampleCountSum: initialSampleCountSum,
            monitorDurationSamples: initialMonitorDurationSamples,
            monitorDurationSum: initialMonitorDurationSum,
            cpuSampleCountSamples: initialCpuSampleCountSamples,
            cpuSampleCountSum: initialCpuSampleCountSum,
            gpuSampleCountSamples: initialGpuSampleCountSamples,
            gpuSampleCountSum: initialGpuSampleCountSum,
            ffmpegSampleCountSamples: initialFfmpegSampleCountSamples,
            ffmpegSampleCountSum: initialFfmpegSampleCountSum,
            batterySampleCountSamples: initialBatterySampleCountSamples,
            batterySampleCountSum: initialBatterySampleCountSum,
          },
        });
      }

      // Only update aggregates for accepted submissions
      if (status !== 'accepted') {
        const nextStatus = existing.status === 'accepted' ? 'accepted' : (existing.status ?? status);
        return tx.benchmark.update({
          where: { id: existing.id },
          data: { status: nextStatus },
        });
      }

      // Accepted submission: atomic increment using raw SQL to prevent race conditions (B-S02)
      // and floating-point drift (B-S01). Sums accumulate exactly; averages are recomputed from sums.
      const fpsVal = Number(data.fps);
      const sizeVal = Number(data.fileSizeBytes);
      const hasVmaf = data.vmaf != null;
      const vmafVal = hasVmaf ? Number(data.vmaf) : 0;
      const hasSsim = data.ssim != null;
      const ssimVal = hasSsim ? Number(data.ssim) : 0;
      const hasPsnr = data.psnr != null;
      const psnrVal = hasPsnr ? Number(data.psnr) : 0;
      const hasGpuUtil = data.gpuUtilAvg != null;
      const gpuUtilVal = hasGpuUtil ? Number(data.gpuUtilAvg) : 0;
      const hasGpuPower = data.gpuPowerAvgW != null;
      const gpuPowerVal = hasGpuPower ? Number(data.gpuPowerAvgW) : 0;
      const hasCpuUtil = data.cpuUtilAvg != null;
      const cpuUtilVal = hasCpuUtil ? Number(data.cpuUtilAvg) : 0;
      const hasPeakMem = data.peakMemoryMB != null;
      const peakMemVal = hasPeakMem ? Number(data.peakMemoryMB) : 0;
      const hasGpuTemp = data.gpuTempMaxC != null;
      const gpuTempVal = hasGpuTemp ? Number(data.gpuTempMaxC) : 0;
      const hasCpuFreq = data.cpuFreqAvgMHz != null;
      const cpuFreqVal = hasCpuFreq ? Number(data.cpuFreqAvgMHz) : 0;
      const hasCpuTemp = data.cpuTempMaxC != null;
      const cpuTempVal = hasCpuTemp ? Number(data.cpuTempMaxC) : 0;
      const hasFfmpegCpuUtilAvg = data.ffmpegCpuUtilAvg != null;
      const ffmpegCpuUtilAvgVal = hasFfmpegCpuUtilAvg ? Number(data.ffmpegCpuUtilAvg) : 0;
      const hasFfmpegCpuUtilMax = data.ffmpegCpuUtilMax != null;
      const ffmpegCpuUtilMaxVal = hasFfmpegCpuUtilMax ? Number(data.ffmpegCpuUtilMax) : 0;
      const hasFfmpegRead = data.ffmpegReadMB != null;
      const ffmpegReadVal = hasFfmpegRead ? Number(data.ffmpegReadMB) : 0;
      const hasFfmpegWrite = data.ffmpegWriteMB != null;
      const ffmpegWriteVal = hasFfmpegWrite ? Number(data.ffmpegWriteMB) : 0;
      const hasFfmpegCpuTime = data.ffmpegCpuTimeS != null;
      const ffmpegCpuTimeVal = hasFfmpegCpuTime ? Number(data.ffmpegCpuTimeS) : 0;
      const hasBatteryStart = data.batteryPercentStart != null;
      const batteryStartVal = hasBatteryStart ? Number(data.batteryPercentStart) : 0;
      const hasBatteryEnd = data.batteryPercentEnd != null;
      const batteryEndVal = hasBatteryEnd ? Number(data.batteryPercentEnd) : 0;
      const hasBatteryDrop = data.batteryPercentDrop != null;
      const batteryDropVal = hasBatteryDrop ? Number(data.batteryPercentDrop) : 0;
      const hasPowerSource = data.powerSource != null && data.powerSource.length > 0;
      const powerSourceVal = hasPowerSource ? data.powerSource : '';
      const hasSampleCount = data.sampleCount != null;
      const sampleCountVal = hasSampleCount ? Number(data.sampleCount) : 0;
      const hasMonitorDuration = data.monitorDurationMs != null;
      const monitorDurationVal = hasMonitorDuration ? Number(data.monitorDurationMs) : 0;
      const hasCpuSampleCount = data.cpuSampleCount != null;
      const cpuSampleCountVal = hasCpuSampleCount ? Number(data.cpuSampleCount) : 0;
      const hasGpuSampleCount = data.gpuSampleCount != null;
      const gpuSampleCountVal = hasGpuSampleCount ? Number(data.gpuSampleCount) : 0;
      const hasFfmpegSampleCount = data.ffmpegSampleCount != null;
      const ffmpegSampleCountVal = hasFfmpegSampleCount ? Number(data.ffmpegSampleCount) : 0;
      const hasBatterySampleCount = data.batterySampleCount != null;
      const batterySampleCountVal = hasBatterySampleCount ? Number(data.batterySampleCount) : 0;

      await tx.$executeRaw`
        UPDATE "Benchmark"
        SET "samples" = "samples" + 1,
            "fpsSum" = "fpsSum" + ${fpsVal}::double precision,
            "fileSizeSum" = "fileSizeSum" + ${sizeVal}::double precision,
            "vmafSamples" = "vmafSamples" + ${hasVmaf ? 1 : 0},
            "vmafSum" = "vmafSum" + ${vmafVal}::double precision,
            "ssimSamples" = "ssimSamples" + ${hasSsim ? 1 : 0},
            "ssimSum" = "ssimSum" + ${ssimVal}::double precision,
            "psnrSamples" = "psnrSamples" + ${hasPsnr ? 1 : 0},
            "psnrSum" = "psnrSum" + ${psnrVal}::double precision,
            "gpuUtilSamples" = "gpuUtilSamples" + ${hasGpuUtil ? 1 : 0},
            "gpuUtilSum" = "gpuUtilSum" + ${gpuUtilVal}::double precision,
            "gpuPowerSamples" = "gpuPowerSamples" + ${hasGpuPower ? 1 : 0},
            "gpuPowerSum" = "gpuPowerSum" + ${gpuPowerVal}::double precision,
            "cpuUtilSamples" = "cpuUtilSamples" + ${hasCpuUtil ? 1 : 0},
            "cpuUtilSum" = "cpuUtilSum" + ${cpuUtilVal}::double precision,
            "cpuFreqSamples" = "cpuFreqSamples" + ${hasCpuFreq ? 1 : 0},
            "cpuFreqSum" = "cpuFreqSum" + ${cpuFreqVal}::double precision,
            "ffmpegCpuUtilSamples" = "ffmpegCpuUtilSamples" + ${hasFfmpegCpuUtilAvg ? 1 : 0},
            "ffmpegCpuUtilSum" = "ffmpegCpuUtilSum" + ${ffmpegCpuUtilAvgVal}::double precision,
            "ffmpegReadSamples" = "ffmpegReadSamples" + ${hasFfmpegRead ? 1 : 0},
            "ffmpegReadSum" = "ffmpegReadSum" + ${ffmpegReadVal}::double precision,
            "ffmpegWriteSamples" = "ffmpegWriteSamples" + ${hasFfmpegWrite ? 1 : 0},
            "ffmpegWriteSum" = "ffmpegWriteSum" + ${ffmpegWriteVal}::double precision,
            "ffmpegCpuTimeSamples" = "ffmpegCpuTimeSamples" + ${hasFfmpegCpuTime ? 1 : 0},
            "ffmpegCpuTimeSum" = "ffmpegCpuTimeSum" + ${ffmpegCpuTimeVal}::double precision,
            "batteryStartSamples" = "batteryStartSamples" + ${hasBatteryStart ? 1 : 0},
            "batteryStartSum" = "batteryStartSum" + ${batteryStartVal}::double precision,
            "batteryEndSamples" = "batteryEndSamples" + ${hasBatteryEnd ? 1 : 0},
            "batteryEndSum" = "batteryEndSum" + ${batteryEndVal}::double precision,
            "batteryDropSamples" = "batteryDropSamples" + ${hasBatteryDrop ? 1 : 0},
            "batteryDropSum" = "batteryDropSum" + ${batteryDropVal}::double precision,
            "sampleCountSamples" = "sampleCountSamples" + ${hasSampleCount ? 1 : 0},
            "sampleCountSum" = "sampleCountSum" + ${sampleCountVal}::double precision,
            "monitorDurationSamples" = "monitorDurationSamples" + ${hasMonitorDuration ? 1 : 0},
            "monitorDurationSum" = "monitorDurationSum" + ${monitorDurationVal}::double precision,
            "cpuSampleCountSamples" = "cpuSampleCountSamples" + ${hasCpuSampleCount ? 1 : 0},
            "cpuSampleCountSum" = "cpuSampleCountSum" + ${cpuSampleCountVal}::double precision,
            "gpuSampleCountSamples" = "gpuSampleCountSamples" + ${hasGpuSampleCount ? 1 : 0},
            "gpuSampleCountSum" = "gpuSampleCountSum" + ${gpuSampleCountVal}::double precision,
            "ffmpegSampleCountSamples" = "ffmpegSampleCountSamples" + ${hasFfmpegSampleCount ? 1 : 0},
            "ffmpegSampleCountSum" = "ffmpegSampleCountSum" + ${ffmpegSampleCountVal}::double precision,
            "batterySampleCountSamples" = "batterySampleCountSamples" + ${hasBatterySampleCount ? 1 : 0},
            "batterySampleCountSum" = "batterySampleCountSum" + ${batterySampleCountVal}::double precision,
            "peakMemoryMax" = CASE
              WHEN ${hasPeakMem} AND (${peakMemVal}::double precision > COALESCE("peakMemoryMax", 0))
              THEN ${peakMemVal}::double precision
              ELSE "peakMemoryMax"
            END,
            "fps" = ("fpsSum" + ${fpsVal}::double precision) / ("samples" + 1),
            "fileSizeBytes" = CAST(ROUND(("fileSizeSum" + ${sizeVal}::double precision) / ("samples" + 1)) AS BIGINT),
            "vmaf" = CASE
              WHEN "vmafSamples" + ${hasVmaf ? 1 : 0} > 0
              THEN ("vmafSum" + ${vmafVal}::double precision) / ("vmafSamples" + ${hasVmaf ? 1 : 0})
              ELSE "vmaf"
            END,
            "ssim" = CASE
              WHEN "ssimSamples" + ${hasSsim ? 1 : 0} > 0
              THEN ("ssimSum" + ${ssimVal}::double precision) / ("ssimSamples" + ${hasSsim ? 1 : 0})
              ELSE "ssim"
            END,
            "psnr" = CASE
              WHEN "psnrSamples" + ${hasPsnr ? 1 : 0} > 0
              THEN ("psnrSum" + ${psnrVal}::double precision) / ("psnrSamples" + ${hasPsnr ? 1 : 0})
              ELSE "psnr"
            END,
            "gpuUtilAvg" = CASE
              WHEN "gpuUtilSamples" + ${hasGpuUtil ? 1 : 0} > 0
              THEN ("gpuUtilSum" + ${gpuUtilVal}::double precision) / ("gpuUtilSamples" + ${hasGpuUtil ? 1 : 0})
              ELSE "gpuUtilAvg"
            END,
            "gpuPowerAvgW" = CASE
              WHEN "gpuPowerSamples" + ${hasGpuPower ? 1 : 0} > 0
              THEN ("gpuPowerSum" + ${gpuPowerVal}::double precision) / ("gpuPowerSamples" + ${hasGpuPower ? 1 : 0})
              ELSE "gpuPowerAvgW"
            END,
            "cpuUtilAvg" = CASE
              WHEN "cpuUtilSamples" + ${hasCpuUtil ? 1 : 0} > 0
              THEN ("cpuUtilSum" + ${cpuUtilVal}::double precision) / ("cpuUtilSamples" + ${hasCpuUtil ? 1 : 0})
              ELSE "cpuUtilAvg"
            END,
            "gpuTempMaxC" = CASE
              WHEN ${hasGpuTemp} AND (${gpuTempVal}::double precision > COALESCE("gpuTempMaxC", 0))
              THEN ${gpuTempVal}::double precision
              ELSE "gpuTempMaxC"
            END,
            "cpuFreqAvgMHz" = CASE
              WHEN "cpuFreqSamples" + ${hasCpuFreq ? 1 : 0} > 0
              THEN ("cpuFreqSum" + ${cpuFreqVal}::double precision) / ("cpuFreqSamples" + ${hasCpuFreq ? 1 : 0})
              ELSE "cpuFreqAvgMHz"
            END,
            "cpuTempMaxC" = CASE
              WHEN ${hasCpuTemp} AND (${cpuTempVal}::double precision > COALESCE("cpuTempMaxC", 0))
              THEN ${cpuTempVal}::double precision
              ELSE "cpuTempMaxC"
            END,
            "ffmpegCpuUtilAvg" = CASE
              WHEN "ffmpegCpuUtilSamples" + ${hasFfmpegCpuUtilAvg ? 1 : 0} > 0
              THEN ("ffmpegCpuUtilSum" + ${ffmpegCpuUtilAvgVal}::double precision) / ("ffmpegCpuUtilSamples" + ${hasFfmpegCpuUtilAvg ? 1 : 0})
              ELSE "ffmpegCpuUtilAvg"
            END,
            "ffmpegCpuUtilMax" = CASE
              WHEN ${hasFfmpegCpuUtilMax} AND (${ffmpegCpuUtilMaxVal}::double precision > COALESCE("ffmpegCpuUtilMax", 0))
              THEN ${ffmpegCpuUtilMaxVal}::double precision
              ELSE "ffmpegCpuUtilMax"
            END,
            "ffmpegReadMB" = CASE
              WHEN "ffmpegReadSamples" + ${hasFfmpegRead ? 1 : 0} > 0
              THEN ("ffmpegReadSum" + ${ffmpegReadVal}::double precision) / ("ffmpegReadSamples" + ${hasFfmpegRead ? 1 : 0})
              ELSE "ffmpegReadMB"
            END,
            "ffmpegWriteMB" = CASE
              WHEN "ffmpegWriteSamples" + ${hasFfmpegWrite ? 1 : 0} > 0
              THEN ("ffmpegWriteSum" + ${ffmpegWriteVal}::double precision) / ("ffmpegWriteSamples" + ${hasFfmpegWrite ? 1 : 0})
              ELSE "ffmpegWriteMB"
            END,
            "ffmpegCpuTimeS" = CASE
              WHEN "ffmpegCpuTimeSamples" + ${hasFfmpegCpuTime ? 1 : 0} > 0
              THEN ("ffmpegCpuTimeSum" + ${ffmpegCpuTimeVal}::double precision) / ("ffmpegCpuTimeSamples" + ${hasFfmpegCpuTime ? 1 : 0})
              ELSE "ffmpegCpuTimeS"
            END,
            "batteryPercentStart" = CASE
              WHEN "batteryStartSamples" + ${hasBatteryStart ? 1 : 0} > 0
              THEN ("batteryStartSum" + ${batteryStartVal}::double precision) / ("batteryStartSamples" + ${hasBatteryStart ? 1 : 0})
              ELSE "batteryPercentStart"
            END,
            "batteryPercentEnd" = CASE
              WHEN "batteryEndSamples" + ${hasBatteryEnd ? 1 : 0} > 0
              THEN ("batteryEndSum" + ${batteryEndVal}::double precision) / ("batteryEndSamples" + ${hasBatteryEnd ? 1 : 0})
              ELSE "batteryPercentEnd"
            END,
            "batteryPercentDrop" = CASE
              WHEN "batteryDropSamples" + ${hasBatteryDrop ? 1 : 0} > 0
              THEN ("batteryDropSum" + ${batteryDropVal}::double precision) / ("batteryDropSamples" + ${hasBatteryDrop ? 1 : 0})
              ELSE "batteryPercentDrop"
            END,
            "powerSource" = CASE
              WHEN ${hasPowerSource}
              THEN ${powerSourceVal}
              ELSE "powerSource"
            END,
            "sampleCount" = CASE
              WHEN "sampleCountSamples" + ${hasSampleCount ? 1 : 0} > 0
              THEN ("sampleCountSum" + ${sampleCountVal}::double precision) / ("sampleCountSamples" + ${hasSampleCount ? 1 : 0})
              ELSE "sampleCount"
            END,
            "monitorDurationMs" = CASE
              WHEN "monitorDurationSamples" + ${hasMonitorDuration ? 1 : 0} > 0
              THEN ("monitorDurationSum" + ${monitorDurationVal}::double precision) / ("monitorDurationSamples" + ${hasMonitorDuration ? 1 : 0})
              ELSE "monitorDurationMs"
            END,
            "cpuSampleCount" = CASE
              WHEN "cpuSampleCountSamples" + ${hasCpuSampleCount ? 1 : 0} > 0
              THEN ("cpuSampleCountSum" + ${cpuSampleCountVal}::double precision) / ("cpuSampleCountSamples" + ${hasCpuSampleCount ? 1 : 0})
              ELSE "cpuSampleCount"
            END,
            "gpuSampleCount" = CASE
              WHEN "gpuSampleCountSamples" + ${hasGpuSampleCount ? 1 : 0} > 0
              THEN ("gpuSampleCountSum" + ${gpuSampleCountVal}::double precision) / ("gpuSampleCountSamples" + ${hasGpuSampleCount ? 1 : 0})
              ELSE "gpuSampleCount"
            END,
            "ffmpegSampleCount" = CASE
              WHEN "ffmpegSampleCountSamples" + ${hasFfmpegSampleCount ? 1 : 0} > 0
              THEN ("ffmpegSampleCountSum" + ${ffmpegSampleCountVal}::double precision) / ("ffmpegSampleCountSamples" + ${hasFfmpegSampleCount ? 1 : 0})
              ELSE "ffmpegSampleCount"
            END,
            "batterySampleCount" = CASE
              WHEN "batterySampleCountSamples" + ${hasBatterySampleCount ? 1 : 0} > 0
              THEN ("batterySampleCountSum" + ${batterySampleCountVal}::double precision) / ("batterySampleCountSamples" + ${hasBatterySampleCount ? 1 : 0})
              ELSE "batterySampleCount"
            END,
            "status" = 'accepted',
            "updatedAt" = NOW()
        WHERE "id" = ${existing.id}
      `;

      // Return the updated row
      const updated = await tx.benchmark.findUnique({ where: { id: existing.id } });
      if (!updated) throw new Error('Row disappeared after atomic update');
      return updated;
    }));

    invalidateRouteCaches();
    res.status(createdNew ? 201 : 200).json(row);
  } catch (err) {
    const errCode = (err as { code?: string })?.code;
    if (errCode === 'P2002') {
      // Unique constraint violation: return the existing row idempotently
      try {
        const existing = await findBenchmarkForPayloadHash(payloadHash);
        if (existing) return res.status(200).json(existing);
      } catch (findErr) {
        logError('findExistingAfterP2002', findErr);
      }
      logError('POST /submit unique conflict', err);
      return res.status(503).json({ error: 'Conflicting submission detected. Please retry.' });
    }
    if (errCode === 'P2024' || errCode === 'P2028') {
      // P2024: connection pool timeout (maxWait exceeded)
      // P2028: transaction execution timeout (timeout exceeded)
      logError('POST /submit timeout', err);
      return res.status(503).json({ error: 'Database operation timed out. Please retry.' });
    }
    logError('POST /submit', err);
    res.status(500).json({ error: 'Failed to insert benchmark' });
  }
});

// Method guard for /query (reject non-GET/HEAD) - must be registered before the GET handler
router.all('/query', (req, res, next) => {
  if (req.method === 'GET' || req.method === 'HEAD') {
    return next();
  }
  res.setHeader('Allow', 'GET, HEAD');
  return res.status(405).json({ error: 'Method Not Allowed' });
});

// In-memory query cache with TTL
const QUERY_CACHE_TTL_MS = 30_000; // 30 seconds
const QUERY_CACHE_MAX_ENTRIES = 128;
const parsedDefaultQueryLimit = Number(process.env.QUERY_DEFAULT_LIMIT || 100);
export const DEFAULT_QUERY_LIMIT = Number.isFinite(parsedDefaultQueryLimit) && parsedDefaultQueryLimit > 0
  ? Math.min(Math.trunc(parsedDefaultQueryLimit), 500)
  : 100;
const MAX_QUERY_LIMIT = 500;
const queryCache = new BoundedTtlCache<{ rows: ReturnType<typeof addDerivedBenchmarkFields>[]; totalCount: number | null }>({
  ttlMs: QUERY_CACHE_TTL_MS,
  maxEntries: QUERY_CACHE_MAX_ENTRIES,
});
const analyticsCache = new BoundedTtlCache<unknown>({
  ttlMs: QUERY_CACHE_TTL_MS,
  maxEntries: QUERY_CACHE_MAX_ENTRIES,
});

function invalidateRouteCaches(): void {
  queryCache.clear();
  analyticsCache.clear();
}

// Whitelist of allowed sort fields to prevent injection
export const SORT_WHITELIST = new Set([
  'createdAt', 'fps', 'vmaf', 'ssim', 'psnr', 'fileSizeBytes', 'codec', 'cpuModel',
  'gpuModel', 'preset', 'crf',
  'gpuUtilAvg', 'gpuPowerAvgW', 'cpuUtilAvg',
  'gpuTempMaxC', 'cpuTempMaxC', 'ffmpegCpuUtilAvg',
  'batteryPercentDrop', 'samples', 'sampleCount', 'monitorDurationMs',
  'cpuSampleCount', 'gpuSampleCount', 'ffmpegSampleCount', 'batterySampleCount',
]);

function numberParam(query: Record<string, string | undefined>, key: string): number | undefined {
  const raw = query[key];
  if (raw == null || raw === '') return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}

function parsePositiveInt(raw: string | undefined): number | undefined {
  if (raw == null) return undefined;
  const trimmed = raw.trim();
  if (!trimmed || !/^\d+$/.test(trimmed)) return undefined;
  const parsed = Number(trimmed);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) return undefined;
  return parsed;
}

export function parseTakeParam(raw: string | undefined): number {
  const parsed = parsePositiveInt(raw);
  if (parsed == null) return DEFAULT_QUERY_LIMIT;
  return Math.min(parsed, MAX_QUERY_LIMIT);
}

export function parseSkipParam(raw: string | undefined): number | undefined {
  return parsePositiveInt(raw);
}

function applyRangeFilter(
  where: Prisma.BenchmarkWhereInput,
  query: Record<string, string | undefined>,
  field: string,
  opts?: { minKey?: string; maxKey?: string; integer?: boolean },
): void {
  const minKey = opts?.minKey ?? `${field}Min`;
  const maxKey = opts?.maxKey ?? `${field}Max`;
  let min = numberParam(query, minKey);
  let max = numberParam(query, maxKey);
  if (opts?.integer) {
    if (min != null) min = Math.trunc(min);
    if (max != null) max = Math.trunc(max);
  }
  if (min == null && max == null) return;
  if (min != null && max != null && min > max) {
    const t = min;
    min = max;
    max = t;
  }
  const range: Record<string, number> = {};
  if (min != null) range.gte = min;
  if (max != null) range.lte = max;
  (where as Record<string, unknown>)[field] = range;
}

export function getQueryCacheSize(): number {
  return queryCache.size();
}

export function buildEncoderTypeFilter(kind: 'hardware' | 'software'): Prisma.BenchmarkWhereInput {
  const suffixes = ['_videotoolbox', '_nvenc', '_qsv', '_amf', '_vaapi', '_v4l2m2m', '_omx'];
  const hardwareMatchers: Prisma.BenchmarkWhereInput[] = suffixes.flatMap((suffix) => [
    { codec: { endsWith: suffix } },
    { encoderName: { endsWith: suffix } },
  ]);
  if (kind === 'hardware') {
    return { OR: hardwareMatchers };
  }
  return { NOT: { OR: hardwareMatchers } };
}

export function buildGlobalSearchFilter(search: string): Prisma.BenchmarkWhereInput {
  const normalized = search.trim();
  if (!normalized) return {};
  const textMatch = { contains: normalized, mode: 'insensitive' as const };
  const matches: Prisma.BenchmarkWhereInput[] = [
    { cpuModel: textMatch },
    { gpuModel: textMatch },
    { os: textMatch },
    { encoderName: textMatch },
    { codec: textMatch },
    { preset: textMatch },
    { ffmpegVersion: textMatch },
    { contentClass: textMatch },
    { resolution: textMatch },
  ];
  const numericSearch = Number(normalized);
  if (Number.isFinite(numericSearch)) {
    matches.push(
      { fps: numericSearch },
      { vmaf: numericSearch },
      { ssim: numericSearch },
      { psnr: numericSearch },
      { gpuPowerAvgW: numericSearch },
    );
    if (Number.isSafeInteger(numericSearch)) {
      matches.push(
        { ramGB: numericSearch },
        { crf: numericSearch },
        { fileSizeBytes: numericSearch },
        { samples: numericSearch },
      );
    }
  }
  return { OR: matches };
}

export function buildWorkbenchWhere(query: Record<string, string | undefined>): Prisma.BenchmarkWhereInput {
  const where: Prisma.BenchmarkWhereInput = { status: 'accepted' };
  if (query.passes === '1') where.passes = 1;
  if (query.codec) where.codec = query.codec;
  if (query.codecSearch) where.codec = { contains: query.codecSearch, mode: 'insensitive' };
  if (query.preset) where.preset = { contains: query.preset, mode: 'insensitive' };
  if (query.crf && /^\d+$/.test(query.crf)) where.crf = Number(query.crf);
  if (query.cpu) where.cpuModel = { contains: query.cpu, mode: 'insensitive' };
  if (query.gpu) where.gpuModel = { contains: query.gpu, mode: 'insensitive' };
  if (query.contentClass && VALID_CONTENT_CLASSES.includes(query.contentClass as typeof VALID_CONTENT_CLASSES[number])) {
    where.contentClass = query.contentClass;
  }
  if (query.resolution && VALID_RESOLUTIONS.includes(query.resolution as typeof VALID_RESOLUTIONS[number])) {
    where.resolution = query.resolution;
  }
  if (query.encoderType === 'hardware' || query.encoderType === 'software') {
    where.AND = [buildEncoderTypeFilter(query.encoderType)];
  }
  const globalSearch = query.search?.trim();
  if (globalSearch) {
    where.AND = [
      ...(Array.isArray(where.AND) ? where.AND : where.AND ? [where.AND] : []),
      buildGlobalSearchFilter(globalSearch),
    ];
  }

  applyRangeFilter(where, query, 'fps');
  applyRangeFilter(where, query, 'vmaf');
  applyRangeFilter(where, query, 'ssim');
  applyRangeFilter(where, query, 'psnr');
  applyRangeFilter(where, query, 'fileSizeBytes', { integer: true });
  applyRangeFilter(where, query, 'runMs', { integer: true });
  applyRangeFilter(where, query, 'gpuUtilAvg');
  applyRangeFilter(where, query, 'gpuPowerAvgW');
  applyRangeFilter(where, query, 'gpuMemPeakMB');
  applyRangeFilter(where, query, 'cpuUtilAvg');
  applyRangeFilter(where, query, 'cpuUtilMax');
  applyRangeFilter(where, query, 'peakMemoryMB');
  applyRangeFilter(where, query, 'gpuTempMaxC');
  applyRangeFilter(where, query, 'cpuFreqAvgMHz');
  applyRangeFilter(where, query, 'cpuTempMaxC');
  applyRangeFilter(where, query, 'ffmpegCpuUtilAvg');
  applyRangeFilter(where, query, 'ffmpegCpuUtilMax');
  applyRangeFilter(where, query, 'ffmpegReadMB');
  applyRangeFilter(where, query, 'ffmpegWriteMB');
  applyRangeFilter(where, query, 'ffmpegCpuTimeS');
  applyRangeFilter(where, query, 'batteryPercentStart');
  applyRangeFilter(where, query, 'batteryPercentEnd');
  applyRangeFilter(where, query, 'batteryPercentDrop');
  applyRangeFilter(where, query, 'sampleCount');
  applyRangeFilter(where, query, 'monitorDurationMs');
  applyRangeFilter(where, query, 'cpuSampleCount');
  applyRangeFilter(where, query, 'gpuSampleCount');
  applyRangeFilter(where, query, 'ffmpegSampleCount');
  applyRangeFilter(where, query, 'batterySampleCount');
  return where;
}

router.get('/query', async (req, res) => {
  try {
    const query = req.query as Record<string, string | undefined>;
    if (query.powerSource != null || query.thermalThrottle != null) {
      return res.status(400).json({
        error: 'powerSource and thermalThrottle filters are unavailable for aggregated results',
        details: 'These values vary by submission and cannot truthfully filter a mixed aggregate.',
      });
    }
    const take = parseTakeParam(query.limit);
    const skip = parseSkipParam(query.skip);

    const where = buildWorkbenchWhere(query);

    // Build orderBy with whitelist validation
    let orderBy: Record<string, string> = { createdAt: 'desc' };
    if (query.sort && SORT_WHITELIST.has(query.sort)) {
      const dir = query.dir === 'asc' ? 'asc' : 'desc';
      orderBy = { [query.sort]: dir };
    }

    // Cache key includes all filter params and whether total count was requested.
    const wantTotal = query.total === '1';
    const cacheKey = JSON.stringify({ take, skip, where, orderBy, wantTotal });
    const cached = queryCache.get(cacheKey);
    if (cached) {
      if (wantTotal && cached.totalCount != null) {
        res.setHeader('X-Total-Count', String(cached.totalCount));
      }
      return res.json(cached.rows);
    }

    // Run query and optional count in parallel
    const [rawRows, totalCount] = await Promise.all([
      prisma.benchmark.findMany({
        where,
        orderBy,
        take,
        ...(typeof skip === 'number' ? { skip } : {}),
      }),
      wantTotal ? prisma.benchmark.count({ where }) : Promise.resolve(null),
    ]);

    const rows = rawRows.map((row: BenchmarkRow) => addDerivedBenchmarkFields(row));
    queryCache.set(cacheKey, { rows, totalCount });

    if (totalCount != null) {
      res.setHeader('X-Total-Count', String(totalCount));
    }

    res.json(rows);
  } catch (err) {
    logError('GET /query', err);
    res.status(500).json({ error: 'Failed to fetch benchmarks' });
  }
});

router.get('/analytics/leaderboards', async (req, res) => {
  try {
    const query = req.query as Record<string, string | undefined>;
    const filters = parseAnalyticsFilters(query);
    const cacheKey = JSON.stringify({ path: 'leaderboards', filters });
    const cached = analyticsCache.get(cacheKey);
    if (cached) return res.json(cached);

    const rows = await prisma.benchmark.findMany({ where: buildAnalyticsWhere(filters) });
    const payload = aggregateLeaderboards(rows, filters.minSamples);
    analyticsCache.set(cacheKey, payload);
    res.json(payload);
  } catch (err) {
    logError('GET /analytics/leaderboards', err);
    res.status(500).json({ error: 'Failed to fetch leaderboards analytics' });
  }
});

router.get('/analytics/hardware', async (req, res) => {
  try {
    const query = req.query as Record<string, string | undefined>;
    const filters = parseAnalyticsFilters(query);
    const cacheKey = JSON.stringify({ path: 'hardware', filters });
    const cached = analyticsCache.get(cacheKey);
    if (cached) return res.json(cached);

    const rows = await prisma.benchmark.findMany({ where: buildAnalyticsWhere(filters) });
    const payload = aggregateHardware(rows, filters.minSamples);
    analyticsCache.set(cacheKey, payload);
    res.json(payload);
  } catch (err) {
    logError('GET /analytics/hardware', err);
    res.status(500).json({ error: 'Failed to fetch hardware analytics' });
  }
});

router.get('/analytics/encoders', async (req, res) => {
  try {
    const query = req.query as Record<string, string | undefined>;
    const filters = parseAnalyticsFilters(query);
    const cacheKey = JSON.stringify({ path: 'encoders', filters });
    const cached = analyticsCache.get(cacheKey);
    if (cached) return res.json(cached);

    const rows = await prisma.benchmark.findMany({ where: buildAnalyticsWhere(filters) });
    const payload = aggregateEncoders(rows, filters.minSamples);
    analyticsCache.set(cacheKey, payload);
    res.json(payload);
  } catch (err) {
    logError('GET /analytics/encoders', err);
    res.status(500).json({ error: 'Failed to fetch encoder analytics' });
  }
});

// Test video catalog (Sprint 5)
export const TEST_VIDEO_CATALOG = [
  { name: 'sample.mp4', duration: 20.0, sha256: '53a87df054e65d284bc808b8f73e62e938b815cb6aeec8379f904ad6d792aab8', sizeBytes: 66045059 },
];

router.get('/test-videos', (_req, res) => {
  const baseUrl = 'https://github.com/oliverdougherC/Encoding_Database/releases/download/test-clips-v1';
  const catalog = TEST_VIDEO_CATALOG.map(v => ({
    ...v,
    downloadUrl: `${baseUrl}/${v.name}`,
  }));
  res.json(catalog);
});

export default router;
