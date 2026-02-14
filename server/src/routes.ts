import { Router } from 'express';
import { z } from 'zod';
import { prisma } from './db.js';
import crypto from 'node:crypto';

const router = Router();

// Public ingest: remove API key requirement; rely on rate limits, validation, and heuristics

const benchmarkSchema = z.object({
  cpuModel: z.string().min(3).max(200),
  gpuModel: z.string().max(200).optional().nullable(),
  ramGB: z.coerce.number().int().nonnegative(),
  os: z.string().min(3).max(100),
  codec: z.string().min(1).max(64),
  preset: z.string().min(1).max(64),
  crf: z.coerce.number().int().min(0).max(63).optional().nullable(),
  fps: z.coerce.number().nonnegative().max(5000),
  vmaf: z.coerce.number().min(0).max(100).optional().nullable(),
  fileSizeBytes: z.coerce.number().int().nonnegative().max(1_000 * 1024 * 1024),
  notes: z.string().max(500).optional().nullable(),
  // Submission metadata (optional for MVP)
  ffmpegVersion: z.string().max(200).optional().nullable(),
  encoderName: z.string().max(100).optional().nullable(),
  clientVersion: z.string().max(100).optional().nullable(),
  inputHash: z.string().length(64).regex(/^[0-9a-f]+$/).optional().nullable(), // sha256 hex
  runMs: z.coerce.number().int().nonnegative().max(24 * 60 * 60 * 1000).optional().nullable(),
}).strict();

// Type inferred from Zod schema for proper type safety
type BenchmarkSubmission = z.infer<typeof benchmarkSchema>;

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
  // sha256 of sample.mp4 (to be documented)
]);

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
  // Enforce default CRF=24 when missing/null to ensure consistent records
  if (data.crf == null || !Number.isFinite(Number(data.crf))) {
    data.crf = 24;
  }
  // Compute deduplication hash based on significant fields (outside try so it's visible in catch)
  const significant = {
    cpuModel: data.cpuModel,
    gpuModel: data.gpuModel ?? null,
    ramGB: data.ramGB,
    os: data.os,
    codec: data.codec,
    preset: data.preset,
    crf: Number(data.crf),
    fps: data.fps,
    vmaf: data.vmaf ?? null,
    fileSizeBytes: data.fileSizeBytes,
    inputHash: data.inputHash ?? null,
  } as const;
  const payloadHash = crypto.createHash('sha256').update(JSON.stringify(significant)).digest('hex');

  try {
    // Fast path: if the exact same payload was already counted, return existing (idempotency)
    const existingByHash = await prisma.benchmark.findUnique({ where: { payloadHash } }).catch((err) => {
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
    };

    // Fetch recent samples for robust baseline (best-effort; tolerate missing table)
    let recentSubs: Array<{ fps: number; fileSizeBytes: bigint | number; vmaf: number | null }> = [];
    try {
      recentSubs = await prisma.submission.findMany({
        where: {
          status: 'accepted',
          cpuModel: key.cpuModel,
          gpuModel: gpuModelValue || null, // Use null for empty string in queries
          ramGB: key.ramGB,
          os: key.os,
          codec: key.codec,
          preset: key.preset,
          crf: key.crf,
        },
        orderBy: { createdAt: 'desc' },
        take: 200,
        select: { fps: true, fileSizeBytes: true, vmaf: true },
      });
    } catch (err) {
      logError('fetchRecentSubmissions', err);
    }
    function median(values: number[]): number {
      const v = [...values].sort((a, b) => a - b);
      const n = v.length;
      if (n === 0) return 0;
      const m = Math.floor(n / 2);
      if (n % 2 === 1) {
        return v[m] ?? 0;
      }
      // For even n, both indices exist (n >= 2). Use nullish coalescing to satisfy TS strict index checks.
      const a = v[m - 1] ?? 0;
      const b = v[m] ?? 0;
      return (a + b) / 2;
    }
    function mad(values: number[], med: number): number { const dev = values.map(x=>Math.abs(x-med)); return median(dev); }
    function robustZ(x: number, med: number, madVal: number): number { const denom = madVal > 0 ? 1.4826 * madVal : 1; return (x - med) / denom; }

    // Build arrays for metrics to check
    const fpsArr = recentSubs.map(r => Number(r.fps)).filter(n => Number.isFinite(n) && n > 0);
    const sizeArr = recentSubs.map(r => Number(r.fileSizeBytes)).filter(n => Number.isFinite(n) && n > 0);
    const vmafArr = recentSubs.map(r => Number(r.vmaf ?? 0)).filter(n => Number.isFinite(n) && n >= 0);

    const fpsMed = fpsArr.length ? median(fpsArr) : Number(data.fps);
    const fpsMad = fpsArr.length ? mad(fpsArr, fpsMed) : 0;
    const sizeMed = sizeArr.length ? median(sizeArr) : Number(data.fileSizeBytes);
    const sizeMad = sizeArr.length ? mad(sizeArr, sizeMed) : 0;
    const vmafMed = vmafArr.length ? median(vmafArr) : Number(data.vmaf ?? 0);
    const vmafMad = vmafArr.length ? mad(vmafArr, vmafMed) : 0;

    const fpsZ = robustZ(Number(data.fps), fpsMed, fpsMad);
    const sizeZ = robustZ(Number(data.fileSizeBytes), sizeMed, sizeMad);
    const vmafZ = data.vmaf == null ? 0 : robustZ(Number(data.vmaf), vmafMed, vmafMad);

    // Penalize extreme deviations; also check impossible combos
    const impossible = !(isCodecOk && isPresetOk && isFpsOk && isSizeOk && namesOk);
    const extreme = Math.max(Math.abs(fpsZ), Math.abs(sizeZ), Math.abs(vmafZ)) > 6; // conservative threshold
    const suspect = Math.max(Math.abs(fpsZ), Math.abs(sizeZ), Math.abs(vmafZ)) > 3;  // softer threshold
    const baselineOk = inputHashOk || (isCodecOk && isPresetOk && isFpsOk && isSizeOk && namesOk);
    const status: 'pending' | 'accepted' | 'rejected' | 'suspect' = impossible ? 'rejected' : (extreme ? 'rejected' : (suspect ? 'suspect' : (baselineOk ? 'accepted' : 'pending')));
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
    // Store raw submission record for auditability
    try {
      await prisma.submission.create({
        data: {
          cpuModel: data.cpuModel,
          gpuModel: data.gpuModel || null, // Store null for empty/missing gpuModel
          ramGB: data.ramGB,
          os: data.os,
          codec: data.codec,
          preset: data.preset,
          crf: Number(data.crf ?? 24),
          fps: Number(data.fps),
          vmaf: data.vmaf == null ? null : Number(data.vmaf),
          fileSizeBytes: Number(data.fileSizeBytes),
          notes: data.notes || null,
          ffmpegVersion: data.ffmpegVersion || null,
          encoderName: data.encoderName || null,
          clientVersion: data.clientVersion || null,
          inputHash: data.inputHash || null,
          runMs: data.runMs != null ? Number(data.runMs) : null,
          payloadHash,
          status,
          qualityScore,
        },
      });
    } catch (err) {
      // Log audit failures but don't block the benchmark aggregation
      logError('createSubmissionAudit', err);
    }
    const row = await prisma.$transaction(async (tx) => {
      // Transaction inherits global defaults (maxWait 5s, timeout 15s)
      const existing = await tx.benchmark.findUnique({ where: { cpuModel_gpuModel_ramGB_os_codec_preset_crf: key } });
      if (!existing) {
        createdNew = true;
        // For new benchmarks, only count as sample if accepted
        const initialSamples = status === 'accepted' ? 1 : 0;
        const initialVmafSamples = (status === 'accepted' && data.vmaf != null) ? 1 : 0;
        return tx.benchmark.create({
          data: {
            cpuModel: key.cpuModel,
            gpuModel: gpuModelValue, // Use '' for no GPU so compound unique matches findUnique(key)
            ramGB: key.ramGB,
            os: key.os,
            codec: key.codec,
            preset: key.preset,
            crf: key.crf,
            fps: data.fps,
            vmaf: data.vmaf ?? null,
            fileSizeBytes: data.fileSizeBytes,
            notes: data.notes || null,
            status,
            ffmpegVersion: data.ffmpegVersion || null,
            encoderName: data.encoderName || null,
            clientVersion: data.clientVersion || null,
            inputHash: data.inputHash || null,
            runMs: data.runMs != null ? Number(data.runMs) : null,
            payloadHash,
            samples: initialSamples,
            vmafSamples: initialVmafSamples,
          },
        });
      }

      // Only update aggregates for accepted submissions
      if (status !== 'accepted') {
        // Non-accepted submissions don't change aggregates, just update status if needed
        const nextStatus = existing.status === 'accepted' ? 'accepted' : (existing.status ?? status);
        return tx.benchmark.update({
          where: { cpuModel_gpuModel_ramGB_os_codec_preset_crf: key },
          data: { status: nextStatus },
        });
      }

      // Accepted submission: update running averages
      const prevSamples = existing.samples ?? 0;
      const nextSamples = prevSamples + 1;
      const prevFps = existing.fps ?? 0;
      const prevFileSize = existing.fileSizeBytes ?? 0;
      const nextFps = (prevFps * prevSamples + Number(data.fps)) / nextSamples;
      const nextFileSize = Math.round((prevFileSize * prevSamples + Number(data.fileSizeBytes)) / nextSamples);

      const prevVmafSamples = existing.vmafSamples ?? 0;
      let nextVmafSamples = prevVmafSamples;
      let nextVmaf: number | null = existing.vmaf ?? null;
      if (data.vmaf != null) {
        const prevVmafTotal = (existing.vmaf ?? 0) * prevVmafSamples;
        nextVmafSamples = prevVmafSamples + 1;
        nextVmaf = (prevVmafTotal + Number(data.vmaf)) / nextVmafSamples;
      }

      return tx.benchmark.update({
        where: { cpuModel_gpuModel_ramGB_os_codec_preset_crf: key },
        data: {
          fps: nextFps,
          fileSizeBytes: nextFileSize,
          vmaf: nextVmaf,
          samples: nextSamples,
          vmafSamples: nextVmafSamples,
          status: 'accepted',
        },
      });
    });

    res.status(createdNew ? 201 : 200).json(row);
  } catch (err) {
    const errCode = (err as { code?: string })?.code;
    if (errCode === 'P2002') {
      // Unique constraint violation: return the existing row idempotently
      try {
        const existing = await prisma.benchmark.findUnique({ where: { payloadHash } });
        if (existing) return res.status(200).json(existing);
      } catch (findErr) {
        logError('findExistingAfterP2002', findErr);
      }
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

router.get('/query', async (req, res) => {
  try {
    const query = req.query as { limit?: string; skip?: string };
    const rawLimit = Number(query.limit);
    const rawSkip = Number(query.skip);
    const take = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, 500) : undefined;
    const skip = Number.isFinite(rawSkip) && rawSkip > 0 ? rawSkip : undefined;

    const rows = await prisma.benchmark.findMany({
      where: { status: 'accepted' },
      orderBy: { createdAt: 'desc' },
      ...(typeof take === 'number' ? { take } : {}),
      ...(typeof skip === 'number' ? { skip } : {}),
    });
    res.json(rows);
  } catch (err) {
    logError('GET /query', err);
    res.status(500).json({ error: 'Failed to fetch benchmarks' });
  }
});

export default router;


