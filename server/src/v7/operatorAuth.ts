import crypto from 'node:crypto';
import type { Request, Response, NextFunction } from 'express';

/** Operator identities are deployment configuration, never contributor supplied. */
export function operatorIdentity(_req: Request): string {
  const identity = process.env.V7_OPERATOR_ID?.trim();
  if (!identity) throw new Error('V7_OPERATOR_ID is not configured');
  return identity;
}

export function requireOperator(req: Request, res: Response, next: NextFunction): void {
  const expected = process.env.V7_OPERATOR_TOKEN;
  const supplied = req.get('authorization')?.replace(/^Bearer /, '');
  if (!expected || !process.env.V7_OPERATOR_ID?.trim()) {
    res.status(503).json({ error: 'Operator interface is not configured' });
    return;
  }
  const left = crypto.createHash('sha256').update(supplied ?? '').digest();
  const right = crypto.createHash('sha256').update(expected).digest();
  if (!supplied || !crypto.timingSafeEqual(left, right)) {
    res.status(401).json({ error: 'Operator authentication required' });
    return;
  }
  next();
}
