import { Router } from 'express';
import crypto from 'node:crypto';
import { prisma } from './db.js';

const router = Router();

function requireAdmin(req: any, res: any, next: any) {
  const adminToken = String(process.env.ADMIN_TOKEN || '').trim();
  if (!adminToken) return res.status(503).json({ error: 'admin_disabled' });
  const supplied = String(req.header('X-Admin-Token') || '').trim();
  if (!supplied || supplied !== adminToken) return res.status(403).json({ error: 'forbidden' });
  return next();
}

router.use(requireAdmin);

router.post('/api-keys', async (req, res) => {
  try {
    const name = String((req.body?.name ?? '').toString()).trim() || 'beta';
    const userEmail = (req.body?.userEmail ? String(req.body.userEmail).trim() : undefined) || undefined;
    const quotaPerMinute = Number.isFinite(Number(req.body?.quotaPerMinute)) ? Number(req.body.quotaPerMinute) : undefined;
    const quotaPerDay = Number.isFinite(Number(req.body?.quotaPerDay)) ? Number(req.body.quotaPerDay) : undefined;

    let userId: string | undefined;
    if (userEmail) {
      const user = await prisma.user.upsert({
        where: { email: userEmail },
        create: { email: userEmail, role: 'user' },
        update: {},
      });
      userId = user.id;
    }

    // Generate random plaintext key and store hash only
    const plaintext = crypto.randomBytes(24).toString('base64url');
    const hash = crypto.createHash('sha256').update(plaintext).digest('hex');

    const created = await prisma.apiKey.create({
      data: {
        name,
        userId: userId ?? null,
        hash,
        status: 'active',
        ...(quotaPerMinute ? { quotaPerMinute } : {}),
        ...(quotaPerDay ? { quotaPerDay } : {}),
      },
    });
    res.status(201).json({ id: created.id, name: created.name, plaintextKey: plaintext });
  } catch (err) {
    res.status(500).json({ error: 'failed_to_create_key' });
  }
});

router.get('/api-keys', async (_req, res) => {
  const keys = await prisma.apiKey.findMany({ orderBy: { createdAt: 'desc' } });
  res.json(keys.map(k => ({ id: k.id, name: k.name, status: k.status, quotaPerMinute: k.quotaPerMinute, quotaPerDay: k.quotaPerDay, usedCount: k.usedCount, lastUsedAt: k.lastUsedAt })));
});

router.post('/api-keys/:id/revoke', async (req, res) => {
  try {
    const id = String(req.params.id);
    await prisma.apiKey.update({ where: { id }, data: { status: 'revoked' } });
    res.json({ ok: true });
  } catch {
    res.status(404).json({ error: 'not_found' });
  }
});

router.post('/api-keys/:id/ban', async (req, res) => {
  try {
    const id = String(req.params.id);
    await prisma.apiKey.update({ where: { id }, data: { status: 'banned' } });
    res.json({ ok: true });
  } catch {
    res.status(404).json({ error: 'not_found' });
  }
});

export default router;


