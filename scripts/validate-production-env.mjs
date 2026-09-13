#!/usr/bin/env node

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '..');
const serverRoot = path.join(repoRoot, 'server');

function parseArgs(argv) {
  const flags = new Map();
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) throw new Error(`Unexpected argument ${token}`);
    const next = argv[index + 1];
    if (next && !next.startsWith('--')) {
      flags.set(token, next);
      index += 1;
    } else {
      flags.set(token, 'true');
    }
  }
  return flags;
}

export function parseEnvText(raw) {
  const entries = {};
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const index = trimmed.indexOf('=');
    if (index === -1) continue;
    const key = trimmed.slice(0, index).trim();
    const value = trimmed.slice(index + 1).trim().replace(/^['"]|['"]$/g, '');
    entries[key] = value;
  }
  return entries;
}

export function buildReferenceContextBindings(context, referenceContextPath) {
  return {
    PL_V7_REFERENCE_CONTEXT_VERSION: context.contextVersion,
    PL_V7_REFERENCE_BITRATES_JSON: JSON.stringify(Object.fromEntries(
      [...context.workloads]
        .map((workload) => [workload.workloadId, workload.workloadReferenceBitrateBps])
        .sort(([left], [right]) => left.localeCompare(right)),
    )),
    PL_V7_REFERENCE_CONTEXT_PATH: referenceContextPath,
  };
}

export function validateProductionEnv({ env, referenceContext = null, referenceContextPath = null }) {
  const errors = [];
  const warnings = [];

  const requireNonEmpty = (key) => {
    if (!String(env[key] || '').trim()) errors.push(`${key} must be set`);
  };
  const placeholderPattern = /(change[_-]?me|replace[_-]?me|example\.(com|invalid)|mydomain\.com|localhost)/i;
  const requirePositiveNumber = (key, { allowZero = false } = {}) => {
    const raw = String(env[key] || '').trim();
    const value = Number(raw);
    if (!raw || !Number.isFinite(value) || (allowZero ? value < 0 : value <= 0)) {
      errors.push(`${key} must be ${allowZero ? 'a non-negative' : 'a positive'} number`);
    }
  };

  const ingestMode = String(env.INGEST_MODE || 'public').trim().toLowerCase();
  if (!['public', 'hybrid', 'signed'].includes(ingestMode)) {
    errors.push('INGEST_MODE must be one of public, hybrid, or signed');
  }
  if (ingestMode === 'signed') {
    requireNonEmpty('INGEST_HMAC_SECRET');
  } else if (ingestMode === 'public') {
    warnings.push('INGEST_MODE=public accepts unsigned submissions');
  }

  for (const key of ['POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB']) requireNonEmpty(key);
  const databaseUrl = String(env.DATABASE_URL || '').trim();
  if (databaseUrl && placeholderPattern.test(databaseUrl)) {
    errors.push('DATABASE_URL contains a placeholder or local-only value');
  }
  const databasePassword = String(env.POSTGRES_PASSWORD || '').trim();
  if (databasePassword && (databasePassword.length < 16 || placeholderPattern.test(databasePassword))) {
    errors.push('POSTGRES_PASSWORD must be a non-placeholder value of at least 16 characters');
  }

  for (const key of ['ARTIFACT_UPLOAD_SECRET', 'ARTIFACT_STORAGE_ROOT', 'TRUST_PROXY', 'CORS_ORIGIN', 'INTERNAL_API_BASE_URL', 'APP_URL']) {
    requireNonEmpty(key);
  }

  const artifactSecret = String(env.ARTIFACT_UPLOAD_SECRET || '').trim();
  if (artifactSecret && (artifactSecret.length < 32 || placeholderPattern.test(artifactSecret) || /dev-only/i.test(artifactSecret))) {
    errors.push('ARTIFACT_UPLOAD_SECRET must be a non-placeholder value of at least 32 characters');
  }
  const trustProxy = String(env.TRUST_PROXY || '').trim();
  const validTrustProxy = /^(true|false|[1-9][0-9]*)$/i.test(trustProxy)
    || (trustProxy.split(',').every((entry) => /^[0-9a-f:.]+\/\d{1,3}$/i.test(entry.trim())));
  if (trustProxy && !validTrustProxy) {
    errors.push('TRUST_PROXY must be true, false, a positive hop count, or a CIDR list');
  }
  for (const key of ['CORS_ORIGIN', 'APP_URL']) {
    const value = String(env[key] || '').trim();
    if (value && (!value.startsWith('https://') || placeholderPattern.test(value))) {
      errors.push(`${key} must be a non-placeholder HTTPS URL`);
    }
  }
  const internalApiUrl = String(env.INTERNAL_API_BASE_URL || '').trim();
  if (internalApiUrl && (placeholderPattern.test(internalApiUrl) || !/^https?:\/\//i.test(internalApiUrl))) {
    errors.push('INTERNAL_API_BASE_URL must be an explicit non-placeholder HTTP(S) URL');
  }
  for (const key of [
    'BODY_LIMIT', 'RATE_LIMIT_WINDOW_MS', 'RATE_LIMIT_MAX', 'SUBMIT_RATE_WINDOW_MS', 'SUBMIT_RATE_MAX',
    'ARTIFACT_MAX_BYTES', 'ARTIFACT_UPLOAD_TTL_MS', 'ARTIFACT_AUTH_RATE_WINDOW_MS',
    'ARTIFACT_AUTH_RATE_MAX', 'ARTIFACT_UPLOAD_RATE_WINDOW_MS', 'ARTIFACT_UPLOAD_RATE_MAX',
    'ARTIFACT_UPLOAD_CONCURRENCY_MAX', 'ARTIFACT_PENDING_UPLOAD_MAX', 'ARTIFACT_PENDING_ANALYSIS_MAX',
    'ARTIFACT_STORAGE_RESERVE_BYTES', 'ARTIFACT_ANALYSIS_CONCURRENCY_MAX', 'ARTIFACT_ANALYSIS_POLL_MS',
    'ARTIFACT_ANALYSIS_LEASE_MS', 'ARTIFACT_ANALYSIS_RETRY_BACKOFF_MS', 'ARTIFACT_ANALYSIS_MAX_ATTEMPTS',
    'V7_PENDING_UPLOAD_ALERT_SECONDS', 'V7_PENDING_ANALYSIS_ALERT_SECONDS', 'V7_ORPHAN_STAGING_ALERT_SECONDS',
  ]) {
    if (key === 'BODY_LIMIT') continue;
    requirePositiveNumber(key);
  }
  requirePositiveNumber('ARTIFACT_STORAGE_QUOTA_BYTES', { allowZero: true });
  if (!/^\d+(?:kb|mb|gb)$/i.test(String(env.BODY_LIMIT || '').trim())) {
    errors.push('BODY_LIMIT must use an explicit kb, mb, or gb value');
  }
  if (!['0', '1'].includes(String(env.POW_ENABLED || '').trim())) errors.push('POW_ENABLED must be 0 or 1');
  requirePositiveNumber('POW_DIFFICULTY', { allowZero: true });
  if (String(env.ARTIFACT_VALIDATE_MEDIA_BEFORE_PUBLISH || '').trim() !== '1') {
    errors.push('ARTIFACT_VALIDATE_MEDIA_BEFORE_PUBLISH must be 1 in production');
  }

  if (String(env.CORS_ORIGIN || '').trim() === '*') {
    errors.push('CORS_ORIGIN must not be "*" in production');
  }
  if (String(env.ALLOW_TEST_ONLY_REFERENCE_CONTEXTS || '0').trim() === '1') {
    errors.push('ALLOW_TEST_ONLY_REFERENCE_CONTEXTS must stay 0 in production');
  }
  if (!String(env.ARTIFACT_VOLUME_NAME || '').trim()) {
    warnings.push('ARTIFACT_VOLUME_NAME is unset; named-volume backup automation will require an explicit flag');
  }

  if (referenceContext) {
    if (referenceContext.activation?.stage !== 'PRODUCTION' || referenceContext.activation?.productionActivationAllowed !== true) {
      errors.push('Reference context must be production-activated');
    }
    const expected = buildReferenceContextBindings(referenceContext, referenceContextPath ?? '');
    for (const [key, value] of Object.entries(expected)) {
      if (String(env[key] || '').trim() !== String(value)) {
        errors.push(`${key} does not match ${referenceContextPath ?? 'the reference context'}`);
      }
    }
  } else if ([
    env.PL_V7_REFERENCE_CONTEXT_PATH,
    env.PL_V7_REFERENCE_CONTEXT_VERSION,
    env.PL_V7_REFERENCE_BITRATES_JSON,
  ].some((value) => String(value || '').trim())) {
    errors.push('PL v7 reference-context settings must all remain blank until a validated production context is supplied');
  }

  return {
    ok: errors.length === 0,
    errors,
    warnings,
  };
}

async function loadReferenceContextFromFile(filePath) {
  try {
    const module = await import(path.join(serverRoot, 'dist', 'v7', 'referenceContext.js'));
    return module.parseReferenceContext(readFileSync(filePath, 'utf8'));
  } catch {
    return JSON.parse(readFileSync(filePath, 'utf8'));
  }
}

async function main() {
  const flags = parseArgs(process.argv.slice(2));
  const envFile = path.resolve(process.cwd(), flags.get('--env-file') ?? path.join(repoRoot, '.env'));
  const env = parseEnvText(readFileSync(envFile, 'utf8'));
  let referenceContext = null;
  let referenceContextPath = null;

  if (flags.has('--reference-context')) {
    referenceContextPath = path.resolve(process.cwd(), flags.get('--reference-context'));
    referenceContext = await loadReferenceContextFromFile(referenceContextPath);
  }

  const result = validateProductionEnv({ env, referenceContext, referenceContextPath });
  process.stdout.write(`${JSON.stringify({
    envFile,
    referenceContextPath,
    ...result,
  }, null, 2)}\n`);
  if (!result.ok) process.exitCode = 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    process.stderr.write(`validate-production-env failed: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
