#!/usr/bin/env node
// Rebuilds disposable summaries only; raw runs/artifacts/analyses/reviews stay intact.
import { PrismaClient } from '@prisma/client';
import { refreshPublicCorpusGroups } from '../dist/v7/corpusQuery.js';
if (!process.env.DATABASE_URL) throw new Error('DATABASE_URL is required');
if (process.argv.slice(2).some(arg => arg !== '--enqueue-all')) throw new Error('Usage: rebuild-corpus.mjs [--enqueue-all]');
const db = new PrismaClient();
try {
  if (process.argv.includes('--enqueue-all')) {
    await db.$executeRaw`
      INSERT INTO "PublicCorpusDirtyGroup" ("baseKey", "benchmarkProtocolId", "workloadId", "recipeId", "environmentId")
      SELECT DISTINCT concat_ws('::', "benchmarkProtocolId", "workloadId", "recipeId", "environmentId"), "benchmarkProtocolId", "workloadId", "recipeId", "environmentId" FROM "BenchmarkRun"
      ON CONFLICT ("baseKey") DO NOTHING`;
  }
  let rebuilt = 0;
  const started = Date.now();
  for (let batch = 0; batch < 10000; batch++) {
    const count = await refreshPublicCorpusGroups(db, 256);
    rebuilt += count;
    if (!count) {
      console.log(JSON.stringify({ schema: 'encodingdb-corpus-backfill/v1', ready: true, rebuiltIdentities: rebuilt, elapsedMs: Date.now() - started }));
      break;
    }
    if (batch === 9999) throw new Error('Corpus backfill remains pending after the bounded batch budget; rerun to resume');
  }
} finally { await db.$disconnect(); }
