import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import compression from 'compression';
import morgan from 'morgan';
import { v4 as uuidv4 } from 'uuid';
import rateLimit from 'express-rate-limit';
import routes from './routes.js';
import { prisma } from './db.js';
import crypto from 'node:crypto';

const app = express();

// Trust proxy when behind nginx/reverse proxy
app.set('trust proxy', 1);
// Hide implementation header
app.disable('x-powered-by');

// Security headers
app.use(helmet());

// Compression
app.use(compression());

// Request ID and logging
app.use((req, _res, next) => {
  (req as any).requestId = req.headers['x-request-id'] || uuidv4();
  next();
});
morgan.token('id', (req: any) => req.requestId as string);
app.use(morgan((tokens: any, req, res) => {
  const call = (name: string, arg?: string) => {
    const fn = tokens[name] as ((req: any, res: any, arg?: string) => string) | undefined;
    try { return fn ? fn(req, res, arg) : ''; } catch { return ''; }
  };
  const record = {
    time: new Date().toISOString(),
    level: 'info',
    id: call('id'),
    method: call('method'),
    url: call('url'),
    status: Number(call('status') || 0),
    length: call('res', 'content-length'),
    responseMs: Number(call('response-time') || 0),
    userAgent: call('req', 'user-agent'),
    remoteAddr: call('remote-addr'),
  } as const;
  return JSON.stringify(record);
}));

// CORS configuration (defaults assume hosting behind Nginx Proxy Manager at encodingdb.platinumlabs.dev)
const corsOriginEnv = process.env.CORS_ORIGIN || 'https://encodingdb.platinumlabs.dev';
const allowedOrigins = corsOriginEnv.split(',').map(v => v.trim()).filter(Boolean);
const isProd = process.env.NODE_ENV === 'production';
const isWildcard = corsOriginEnv === '*';
if (isProd && isWildcard) {
  console.error('CORS_ORIGIN is "*" in production. Please set explicit origins.');
}
const corsOptions = isWildcard
  ? (isProd
      ? {
          origin: (origin: string | undefined, callback: (err: Error | null, allowed?: boolean) => void) => {
            // In production, reject wildcard; only allow explicit list (which will be empty → deny)
            if (!origin) return callback(null, false);
            if (allowedOrigins.includes(origin)) return callback(null, true);
            return callback(new Error('Not allowed by CORS'));
          },
          credentials: true,
        }
      : { origin: true })
  : {
      origin: (origin: string | undefined, callback: (err: Error | null, allowed?: boolean) => void) => {
        if (!origin) return callback(null, true);
        if (allowedOrigins.includes(origin)) return callback(null, true);
        return callback(new Error('Not allowed by CORS'));
      },
      credentials: true,
    };
app.use(cors(corsOptions));

// Body parser with limit and raw body capture (for HMAC verification)
const bodyLimit = process.env.BODY_LIMIT || '1mb';
app.use(express.json({
  limit: bodyLimit,
  verify: (req, _res, buf) => {
    (req as any).rawBody = Buffer.from(buf);
  },
}));

// Optional HMAC verification for ingest endpoint
const ingestSecret = process.env.INGEST_HMAC_SECRET || '';
const maxSkewSeconds = Number(process.env.INGEST_MAX_SKEW_SECONDS || 300);
const seenSignatures = new Map<string, number>();
let warnedNoSecret = false;

function isReplay(sig: string, nowMs: number): boolean {
  const exp = seenSignatures.get(sig);
  if (exp && exp > nowMs) return true;
  return false;
}

function rememberSignature(sig: string, nowMs: number): void {
  const ttl = maxSkewSeconds * 1000;
  seenSignatures.set(sig, nowMs + ttl);
  // Best-effort cleanup to avoid unbounded growth
  if (seenSignatures.size > 5000) {
    const cutoff = nowMs;
    for (const [k, v] of seenSignatures.entries()) {
      if (v <= cutoff) seenSignatures.delete(k);
    }
  }
}

// In-memory submit token store
type TokenMeta = { ip: string; expMs: number; used: boolean };
const tokenStore = new Map<string, TokenMeta>();
const submitTokenTtlSeconds = Number(process.env.SUBMIT_TOKEN_TTL_SECONDS || 60);
const ingestMode = (process.env.INGEST_MODE || 'public').toLowerCase(); // public | signed | hybrid
const powEnabled = String(process.env.POW_ENABLED || '0') === '1';
const powDifficulty = Math.max(0, Number(process.env.POW_DIFFICULTY || 0)); // leading zero hex chars approx

function normalizeIp(ip: string | undefined): string {
  if (!ip) return '';
  // Normalize IPv4-mapped IPv6 addresses like ::ffff:1.2.3.4
  return ip.replace(/^::ffff:/i, '');
}

// Token endpoint - short-lived, one-time token bound to IP
function issueSubmitToken(req: express.Request, res: express.Response) {
  const token = crypto.randomBytes(16).toString('hex');
  const expMs = Date.now() + submitTokenTtlSeconds * 1000;
  tokenStore.set(token, { ip: normalizeIp(req.ip), expMs, used: false });
  res.json({ token, exp: Math.floor(expMs / 1000), pow: powEnabled ? { difficulty: powDifficulty } : { difficulty: 0 } });
}
app.get('/submit-token', (req, res) => issueSubmitToken(req, res));
// Alternate path under /submit/ to ease proxy rules that already forward /submit/*
app.get('/submit/token', (req, res) => issueSubmitToken(req, res));

app.use('/submit', (req, res, next) => {
  // Helper: validate HMAC if secret provided
  const validateHmac = (): true | { code: number; error: string } => {
    if (!ingestSecret) return { code: 401, error: 'missing_secret' };
    const tsHeader = String(req.headers['x-timestamp'] || '');
    const sigHeader = String(req.headers['x-signature'] || '');
    const raw: Buffer | undefined = (req as any).rawBody;
    if (!tsHeader || !sigHeader || !raw) {
      return { code: 401, error: 'missing_signature' };
    }
    const now = Date.now();
    const ts = Number(tsHeader);
    if (!Number.isFinite(ts)) {
      return { code: 401, error: 'invalid_timestamp' };
    }
    const skew = Math.abs(now - ts * 1000);
    if (skew > maxSkewSeconds * 1000) {
      return { code: 401, error: 'timestamp_out_of_range' };
    }
    if (isReplay(sigHeader, now)) {
      return { code: 409, error: 'replay_detected' };
    }
    try {
      const expected = crypto
        .createHmac('sha256', ingestSecret)
        .update(`${tsHeader}.`)
        .update((req as any).rawBody)
        .digest('hex');
      const a = Buffer.from(sigHeader, 'hex');
      const b = Buffer.from(expected, 'hex');
      if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
        return { code: 401, error: 'invalid_signature' };
      }
      rememberSignature(sigHeader, now);
      return true;
    } catch {
      return { code: 401, error: 'signature_verification_failed' };
    }
  };

  // Helper: validate token (+ optional PoW)
  const validateToken = (): true | { code: number; error: string } => {
    const token = String(req.headers['x-ingest-token'] || '');
    if (!token) return { code: 401, error: 'missing_token' };
    const meta = tokenStore.get(token);
    if (!meta) return { code: 401, error: 'invalid_token' };
    const now = Date.now();
    if (meta.used) return { code: 409, error: 'token_used' };
    if (meta.expMs < now) return { code: 401, error: 'token_expired' };
    const reqIp = normalizeIp(req.ip);
    if (meta.ip && reqIp && meta.ip !== reqIp) {
      return { code: 401, error: 'ip_mismatch' };
    }
    if (powEnabled && powDifficulty > 0) {
      const nonce = String(req.headers['x-ingest-nonce'] || '');
      if (!nonce) return { code: 401, error: 'missing_nonce' };
      const h = crypto.createHash('sha256').update(`${token}.${nonce}`).digest('hex');
      const requiredPrefix = '0'.repeat(Math.max(0, Math.floor(powDifficulty)));
      if (!h.startsWith(requiredPrefix)) return { code: 401, error: 'invalid_pow' };
    }
    // mark used (one-time)
    meta.used = true;
    tokenStore.set(token, meta);
    return true;
  };

  // Decide based on ingest mode
  if (ingestMode === 'signed') {
    const ok = validateHmac();
    if (ok === true) return next();
    return res.status(ok.code).json({ error: ok.error });
  }
  if (ingestMode === 'public') {
    // Best-effort tokens: if provided, validate; otherwise accept unsigned to prioritize UX
    const hasToken = Boolean(req.headers['x-ingest-token']);
    if (hasToken) {
      const ok = validateToken();
      if (ok === true) return next();
      return res.status(ok.code).json({ error: ok.error });
    }
    return next();
  }
  // hybrid
  const okH = ingestSecret ? validateHmac() : { code: 401, error: 'no_hmac' };
  if (okH === true) return next();
  const hasToken = Boolean(req.headers['x-ingest-token']);
  if (hasToken) {
    const okT = validateToken();
    if (okT === true) return next();
    return res.status(okT.code).json({ error: okT.error });
  }
  // Fall back to unsigned acceptance for maximum compatibility
  return next();
});

// Basic rate limiting (skip health endpoints)
const windowMs = Number(process.env.RATE_LIMIT_WINDOW_MS || 60_000);
const maxReqs = Number(process.env.RATE_LIMIT_MAX || 300);
app.use(rateLimit({
  windowMs,
  max: maxReqs,
  standardHeaders: true,
  legacyHeaders: false,
  skip: (req) => req.path.startsWith('/health'),
}));

// Stricter limiter for public submissions
const submitWindowMs = Number(process.env.SUBMIT_RATE_WINDOW_MS || 60_000);
const submitMax = Number(process.env.SUBMIT_RATE_MAX || 30);
app.use('/submit', rateLimit({
  windowMs: submitWindowMs,
  max: submitMax,
  standardHeaders: true,
  legacyHeaders: false,
}));

// Health endpoints
app.get('/health/live', (_req, res) => {
  res.json({ status: 'ok' });
});

app.get('/health/ready', async (_req, res) => {
  try {
    await prisma.$queryRaw`SELECT 1`;
    res.json({ status: 'ok' });
  } catch (err) {
    res.status(503).json({ status: 'degraded', error: 'db_unreachable' });
  }
});

app.get('/health', (_req, res) => {
  res.json({ status: 'ok' });
});

// Routes
app.use(routes);

// 404 handler
app.use((req, res) => {
  res.status(404).json({ error: 'Not Found' });
});

// Error handler
// eslint-disable-next-line @typescript-eslint/no-unused-vars
app.use((err: any, req: express.Request, res: express.Response, _next: express.NextFunction) => {
  if (err && (err.type === 'entity.too.large' || err.status === 413)) {
    return res.status(413).json({ error: 'Payload Too Large' });
  }
  if (err instanceof SyntaxError) {
    return res.status(400).json({ error: 'Invalid JSON' });
  }
  console.error(JSON.stringify({
    time: new Date().toISOString(),
    level: 'error',
    id: (req as any).requestId,
    message: 'Unhandled error',
    error: err && err.message ? err.message : String(err),
  }));
  res.status(500).json({ error: 'Internal Server Error' });
});

 

const port = process.env.PORT || 3001;
const server = app.listen(port, () => {
  console.log(`server listening on ${port}`);
});

// Graceful shutdown
async function shutdown(signal: string) {
  console.log(`\n${signal} received. Shutting down...`);
  server.close(async () => {
    try {
      await prisma.$disconnect();
    } finally {
      process.exit(0);
    }
  });
  // Force exit if not closed in time
  setTimeout(() => {
    console.error(JSON.stringify({ time: new Date().toISOString(), level: 'error', message: 'Forced shutdown' }));
    process.exit(1);
  }, 10_000).unref();
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

// Crash guards
process.on('unhandledRejection', (reason) => {
  console.error('Unhandled Rejection', reason);
  shutdown('unhandledRejection');
});
process.on('uncaughtException', (error) => {
  console.error('Uncaught Exception', error);
  shutdown('uncaughtException');
});

// Tune server timeouts
server.headersTimeout = 65_000; // allow a bit over common proxy timeouts
server.requestTimeout = 60_000;
