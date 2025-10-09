import type express from 'express';
import crypto from 'node:crypto';
import { prisma } from './db.js';

type KeyCounters = {
  minuteWindowStart: number; // ms
  minuteCount: number;
  dayWindowStart: number; // ms
  dayCount: number;
};

const perMinuteDefault = Math.max(1, Number(process.env.SUBMIT_PER_KEY_PER_MINUTE || 30));
const perDayDefault = Math.max(1, Number(process.env.SUBMIT_PER_KEY_PER_DAY || 1000));
const headerName = String(process.env.API_KEY_HEADER || 'X-API-Key');

const counters = new Map<string, KeyCounters>(); // key: apiKey.id

function nowMs(): number { return Date.now(); }

function getOrInitCounters(keyId: string): KeyCounters {
  const existing = counters.get(keyId);
  if (existing) return existing;
  const base: KeyCounters = {
    minuteWindowStart: nowMs(),
    minuteCount: 0,
    dayWindowStart: startOfDayMs(nowMs()),
    dayCount: 0,
  };
  counters.set(keyId, base);
  return base;
}

function startOfDayMs(t: number): number {
  const d = new Date(t);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export async function requireApiKey(req: express.Request, res: express.Response, next: express.NextFunction) {
  try {
    const plaintext = String(req.header(headerName) || '').trim();
    if (!plaintext) return res.status(401).json({ error: 'missing_api_key' });
    const hash = crypto.createHash('sha256').update(plaintext).digest('hex');

    const apiKey = await prisma.apiKey.findFirst({ where: { hash } });
    if (!apiKey || apiKey.status !== 'active') {
      return res.status(403).json({ error: 'invalid_or_revoked' });
    }

    // Quotas
    const limits = {
      perMinute: Number.isFinite(apiKey.quotaPerMinute) ? Math.max(1, apiKey.quotaPerMinute) : perMinuteDefault,
      perDay: Number.isFinite(apiKey.quotaPerDay) ? Math.max(1, apiKey.quotaPerDay) : perDayDefault,
    } as const;
    const c = getOrInitCounters(apiKey.id);
    const now = nowMs();

    // Rotate minute window every 60s
    if (now - c.minuteWindowStart >= 60_000) {
      c.minuteWindowStart = now;
      c.minuteCount = 0;
    }
    // Rotate day window at midnight
    const sod = startOfDayMs(now);
    if (c.dayWindowStart !== sod) {
      c.dayWindowStart = sod;
      c.dayCount = 0;
    }

    if (c.minuteCount + 1 > limits.perMinute) {
      return res.status(429).json({ error: 'rate_limited_per_minute' });
    }
    if (c.dayCount + 1 > limits.perDay) {
      return res.status(429).json({ error: 'rate_limited_per_day' });
    }

    c.minuteCount += 1;
    c.dayCount += 1;
    counters.set(apiKey.id, c);

    // Best-effort update usage metadata asynchronously (do not block request)
    prisma.apiKey.update({
      where: { id: apiKey.id },
      data: {
        usedCount: { increment: 1 } as any,
        lastUsedAt: new Date(),
      },
    }).catch(() => {});

    (req as any).apiKey = apiKey;
    return next();
  } catch (err) {
    return res.status(500).json({ error: 'auth_failed' });
  }
}


