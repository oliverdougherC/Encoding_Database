#!/usr/bin/env node
// Explicitly invalid, non-public backup bytes. Never media/measurement evidence.
import { PrismaClient } from '@prisma/client';
import { mkdir, open, rename, copyFile, writeFile } from 'node:fs/promises';
import crypto from 'node:crypto';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
const root = process.env.BACKUP_SCALE_ROOT;
if (root !== '/scale-artifacts' || process.env.BACKUP_SCALE_ALLOW !== 'isolated-fixture-only') throw Error('Explicit isolated scale fixture acknowledgement and mount required');
const db = new PrismaClient();
try {
  const name = await db.$queryRawUnsafe('SELECT current_database() AS name');
  if (name[0]?.name !== 'backup_scale') throw Error('Refusing any database other than backup_scale');
  const templates = {};
  for (const table of ['BenchmarkRun', 'Artifact', 'QualityAnalysis']) {
    const rows = await db.$queryRawUnsafe(`SELECT to_jsonb(t) AS data FROM "${table}" t ORDER BY id LIMIT 1`);
    if (!rows.length) throw Error('Historical isolated template required');
    templates[table] = rows[0].data;
  }
  // Only this explicitly fenced fixture database is reset; foreign dimensions stay.
  await db.$executeRawUnsafe('DELETE FROM "BenchmarkRun"');
  const bytes = 256 * 1024 * 1024;
  const count = 40;
  const buffer = Buffer.alloc(1024 * 1024);
  const report = { kind: 'synthetic-high-entropy-backup-scale-never-media-or-public', startedAt: new Date().toISOString(), objectBytes: bytes, objectCount: count, retainedLogicalBytes: bytes * count, mirroredStagingBytes: bytes * count, objects: [] };
  const start = performance.now();
  for (let i = 0; i < count; i++) {
    const temporary = path.join(root, `.prepare-${i}`);
    const file = await open(temporary, 'wx');
    const hash = crypto.createHash('sha256');
    try { for (let offset = 0; offset < bytes; offset += buffer.length) { crypto.randomFillSync(buffer); hash.update(buffer); await file.writeFile(buffer); } }
    finally { await file.close(); }
    const sha256 = hash.digest('hex');
    const key = `objects/${sha256.slice(0, 2)}/${sha256}`;
    const full = path.join(root, key);
    await mkdir(path.dirname(full), { recursive: true });
    await rename(temporary, full);
    await mkdir(path.join(root, '.staging'), { recursive: true });
    await copyFile(full, path.join(root, '.staging', `backup-scale-${i}.upload`));
    const runId = `backup-scale-run-${i}`;
    const artifactId = `backup-scale-artifact-${i}`;
    const now = new Date().toISOString();
    const run = { ...templates.BenchmarkRun, id: runId, payloadHash: crypto.createHash('sha256').update(runId).digest('hex'), physicalSourceId: 'synthetic-backup-scale', campaignId: 'synthetic-backup-scale-never-public', status: 'INVALID', statusReason: 'SYNTHETIC_BACKUP_BYTES_NOT_MEDIA_OR_MEASUREMENTS', encodeWallTimeMs: null, encodeFps: null, realTimeRatio: null };
    const artifact = { ...templates.Artifact, id: artifactId, benchmarkRunId: runId, sha256, byteSize: bytes, storageState: 'RETAINED', storageKey: key, stateDetails: { synthetic: true, content: 'cryptographic random bytes, not media' }, uploadedAt: now, verifiedAt: now, retainedAt: now };
    const analysis = { ...templates.QualityAnalysis, id: `backup-scale-analysis-${i}`, benchmarkRunId: runId, artifactId, status: 'FAILED', lastError: 'SYNTHETIC_BACKUP_ONLY_NO_ANALYSIS', analysisProvenance: { synthetic: true, analysisPerformed: false }, leaseToken: null, leaseExpiresAt: null, nextRetryAt: null };
    for (const key of Object.keys(analysis)) if (key.startsWith('vmaf') || ['xpsnr', 'ssim', 'psnr', 'videoBitrateBps'].includes(key)) analysis[key] = null;
    await db.$transaction(async (tx) => {
      for (const [table, record] of [['BenchmarkRun', run], ['Artifact', artifact], ['QualityAnalysis', analysis]]) await tx.$executeRawUnsafe(`INSERT INTO "${table}" SELECT * FROM jsonb_populate_record(NULL::"${table}", $1::jsonb)`, JSON.stringify(record));
    });
    report.objects.push({ runId, artifactId, sha256, bytes, key });
    console.log(`Prepared ${i + 1}/${count}: ${bytes} random bytes with exact metadata and staging mirror`);
  }
  await db.$executeRawUnsafe('CREATE TABLE IF NOT EXISTS "BackupScaleHeartbeat" (id INTEGER PRIMARY KEY, ticks BIGINT NOT NULL, "updatedAt" TIMESTAMPTZ NOT NULL)');
  await db.$executeRawUnsafe('INSERT INTO "BackupScaleHeartbeat" VALUES (1,0,NOW()) ON CONFLICT (id) DO NOTHING');
  report.elapsedMs = performance.now() - start;
  report.completedAt = new Date().toISOString();
  await writeFile(path.join(root, '.fixture-manifest.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ status: 'prepared', logicalBytes: report.retainedLogicalBytes, stagingBytes: report.mirroredStagingBytes, elapsedMs: report.elapsedMs }));
} finally { await db.$disconnect(); }
