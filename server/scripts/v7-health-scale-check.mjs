#!/usr/bin/env node
import { PrismaClient } from '@prisma/client';
import { mkdir, writeFile } from 'node:fs/promises';
import { performance } from 'node:perf_hooks';
import { collectV7EvidenceHealth, createV7EvidenceHealthMonitor } from '../dist/v7/operationalHealth.js';

const database = new URL(process.env.DATABASE_URL || '');
if (!['127.0.0.1', 'localhost', '[::1]'].includes(database.hostname) || !database.pathname.includes('operations') && !database.pathname.includes('corpus')) throw Error('isolated loopback operations/corpus database required');
const root = process.env.HEALTH_SCALE_STORAGE_ROOT;
const output = process.env.HEALTH_SCALE_OUTPUT;
if (!root || !output) throw Error('HEALTH_SCALE_STORAGE_ROOT and HEALTH_SCALE_OUTPUT required');
await mkdir(root, { recursive: true });
const db = new PrismaClient();
try {
  const artifactCount = await db.artifact.count();
  if (artifactCount < 100_000) throw Error('at least100000 metadata artifacts required');
  const options = { storageRoot: root, batchSize: 256 };
  const began = performance.now();
  const cold = await collectV7EvidenceHealth(db, options);
  const coldMilliseconds = performance.now() - began;
  const monitor = createV7EvidenceHealthMonitor(db, options);
  const burstStart = performance.now();
  const burst = await Promise.all(Array.from({ length: 25 }, () => monitor()));
  const burstMilliseconds = performance.now() - burstStart;
  const warmStart = performance.now();
  for (let i = 0; i < 1000; i++) await monitor();
  const warm1000Milliseconds = performance.now() - warmStart;
  const evidence = { capturedAt: new Date().toISOString(), scope: '100k isolated synthetic metadata; missing objects expected; no media throughput claim', artifactCount, coldMilliseconds, burstMilliseconds, warm1000Milliseconds, rssBytes: process.memoryUsage().rss, cold, burstSameSnapshot: burst.every((value) => value.capturedAt === burst[0].capturedAt) };
  if (cold.integrityScan.checkedThisBatch > 256 || !evidence.burstSameSnapshot) throw Error('bounded/single-flight scan contract failed');
  await writeFile(output, JSON.stringify(evidence, null, 2) + '\n', { flag: 'wx' });
  console.log(JSON.stringify({ artifactCount, coldMilliseconds, burstMilliseconds, warm1000Milliseconds, rssBytes: evidence.rssBytes }));
} finally { await db.$disconnect(); }
