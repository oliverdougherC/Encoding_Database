import { Router } from 'express';
import { z } from 'zod';
import { prisma } from './db.js';
import crypto from 'node:crypto';

const router = Router();

// Public ingest: remove API key requirement; rely on rate limits, validation, and heuristics

const benchmarkSchema = z.object({
  cpuModel: z.string().min(3),
  gpuModel: z.string().optional().nullable(),
  ramGB: z.coerce.number().int().nonnegative(),
  os: z.string().min(3),
  codec: z.string().min(1),
  preset: z.string().min(1),
  crf: z.coerce.number().int().min(0).max(63).optional().nullable(),
  fps: z.coerce.number().nonnegative().max(5000),
  vmaf: z.coerce.number().min(0).max(100).optional().nullable(),
  fileSizeBytes: z.coerce.number().int().nonnegative().max(1_000 * 1024 * 1024),
  notes: z.string().optional().nullable(),
  // Submission metadata (optional for MVP)
  ffmpegVersion: z.string().max(200).optional().nullable(),
  encoderName: z.string().max(100).optional().nullable(),
  clientVersion: z.string().max(100).optional().nullable(),
  inputHash: z.string().length(64).regex(/^[0-9a-f]+$/).optional().nullable(), // sha256 hex
  runMs: z.coerce.number().int().nonnegative().max(24 * 60 * 60 * 1000).optional().nullable(),
});

// Simple canonical hash list for MVP (publish in README)
const CANONICAL_INPUT_HASHES = new Set<string>([
  // sha256 of sample.mp4 (to be documented)
]);

router.post('/submit', async (req, res) => {
  const parse = benchmarkSchema.safeParse(req.body);
  if (!parse.success) {
    return res.status(400).json({ error: 'Invalid payload', details: parse.error.flatten() });
  }
  const data = parse.data as any;
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
    inputHash: (data as any).inputHash ?? null,
  } as const;
  const payloadHash = crypto.createHash('sha256').update(JSON.stringify(significant)).digest('hex');

  try {
    // Fast path: if already inserted, return existing (idempotency)
    const existing = await prisma.benchmark.findUnique({ where: { payloadHash } }).catch(() => null);
    if (existing) {
      return res.status(200).json(existing);
    }

    // Heuristics: ensure plausible values
    const isCodecOk = typeof data.codec === 'string' && data.codec.length <= 64;
    const isPresetOk = typeof data.preset === 'string' && data.preset.length <= 64;
    const isFpsOk = data.fps >= 0.1 && data.fps <= 5000; // broad cap but >0
    const isSizeOk = data.fileSizeBytes >= 10 * 1024 && data.fileSizeBytes <= 1000 * 1024 * 1024; // >=10KB and <=1GB
    const namesOk = data.cpuModel.trim().length >= 3 && data.os.trim().length >= 3;
    const inputHashOk = !!data.inputHash && CANONICAL_INPUT_HASHES.has(data.inputHash);
    const status: 'pending' | 'accepted' = (inputHashOk || (isCodecOk && isPresetOk && isFpsOk && isSizeOk && namesOk)) ? 'accepted' : 'pending';

    const created = await prisma.benchmark.create({ data: {
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
      notes: data.notes ?? null,
      status,
      ffmpegVersion: (data as any).ffmpegVersion ?? null,
      encoderName: (data as any).encoderName ?? null,
      clientVersion: (data as any).clientVersion ?? null,
      inputHash: (data as any).inputHash ?? null,
      runMs: (data as any).runMs ?? null,
      payloadHash,
    }});
    res.status(201).json(created);
  } catch (err) {
    if ((err as any)?.code === 'P2002') {
      // Unique constraint violation: return the existing row idempotently
      try {
        const existing = await prisma.benchmark.findUnique({ where: { payloadHash } });
        if (existing) return res.status(200).json(existing);
      } catch {}
    }
    res.status(500).json({ error: 'Failed to insert benchmark' });
  }
});

router.get('/query', async (req, res) => {
  try {
    const rawLimit = Number((req.query as any).limit);
    const rawSkip = Number((req.query as any).skip);
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
    res.status(500).json({ error: 'Failed to fetch benchmarks' });
  }
});

export default router;


