import { Router } from 'express';
import { z } from 'zod';
import { prisma } from './db.js';

const router = Router();

// Optional API key guard: enabled when process.env.API_KEY is set
function requireApiKey(req: any, res: any, next: any) {
  const expected = process.env.API_KEY;
  if (!expected) return next();
  const provided = req.headers['x-api-key'] as string | undefined;
  if (provided && provided === expected) return next();
  return res.status(401).json({ error: 'Unauthorized' });
}

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
});

router.post('/submit', requireApiKey, async (req, res) => {
  const parse = benchmarkSchema.safeParse(req.body);
  if (!parse.success) {
    return res.status(400).json({ error: 'Invalid payload', details: parse.error.flatten() });
  }
  const data = parse.data;
  try {
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


