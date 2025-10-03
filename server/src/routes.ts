import { Router } from 'express';
import { z } from 'zod';
import { prisma } from './db.js';

const router = Router();

// Public ingest: remove API key requirement; rely on rate limits, validation, and heuristics

const benchmarkSchema = z.object({
  cpuModel: z.string().min(1),
  gpuModel: z.string().optional().nullable(),
  ramGB: z.coerce.number().int().nonnegative(),
  os: z.string().min(1),
  codec: z.string().min(1),
  preset: z.string().min(1),
  fps: z.coerce.number().nonnegative(),
  vmaf: z.coerce.number().min(0).max(100).optional().nullable(),
  fileSizeBytes: z.coerce.number().int().nonnegative(),
  notes: z.string().optional().nullable(),
  // Submission metadata (optional for MVP)
  ffmpegVersion: z.string().optional().nullable(),
  encoderName: z.string().optional().nullable(),
  clientVersion: z.string().optional().nullable(),
  inputHash: z.string().length(64).optional().nullable(), // sha256 hex
  runMs: z.coerce.number().int().nonnegative().optional().nullable(),
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
  const data = parse.data;
  try {
    // Heuristics: ensure plausible values
    const isCodecOk = typeof data.codec === 'string' && data.codec.length <= 64;
    const isPresetOk = typeof data.preset === 'string' && data.preset.length <= 64;
    const isFpsOk = data.fps >= 0 && data.fps <= 5000; // broad cap
    const isSizeOk = data.fileSizeBytes >= 0 && data.fileSizeBytes <= 1000 * 1024 * 1024; // <= 1GB
    const inputHashOk = !data.inputHash || CANONICAL_INPUT_HASHES.has(data.inputHash);
    const status: 'pending' | 'accepted' = (isCodecOk && isPresetOk && isFpsOk && isSizeOk && inputHashOk) ? 'accepted' : 'pending';

    const created = await prisma.benchmark.create({ data: {
      cpuModel: data.cpuModel,
      gpuModel: data.gpuModel ?? null,
      ramGB: data.ramGB,
      os: data.os,
      codec: data.codec,
      preset: data.preset,
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
    }});
    res.status(201).json(created);
  } catch (err) {
    res.status(500).json({ error: 'Failed to insert benchmark' });
  }
});

router.get('/query', async (_req, res) => {
  try {
    const rows = await prisma.benchmark.findMany({ orderBy: { createdAt: 'desc' } });
    res.json(rows);
  } catch (err) {
    res.status(500).json({ error: 'Failed to fetch benchmarks' });
  }
});

export default router;


