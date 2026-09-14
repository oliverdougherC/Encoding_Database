#!/usr/bin/env node
// Isolated metadata scale proof only. No encoded pixels or calibration evidence.
import { PrismaClient, Prisma } from '@prisma/client';
import { mkdir, writeFile } from 'node:fs/promises';
import { performance } from 'node:perf_hooks';
import { execFileSync } from 'node:child_process';
import { assertIsolatedCorpusDatabase, seedCorpusFixture } from '../test/fixtures/corpus-postgres.mjs';
import { buildPublicCorpusPageSql, loadPublicCorpusPage, refreshPublicCorpusGroups } from '../dist/v7/corpusQuery.js';
const url = process.env.CORPUS_TEST_DATABASE_URL;
if (!url) throw new Error('CORPUS_TEST_DATABASE_URL is required');
assertIsolatedCorpusDatabase(url);
const db = new PrismaClient({ datasources: { db: { url } } });
const output = process.argv[2] ?? '.test-reports/corpus-scale';
const prefix = process.env.CORPUS_SCALE_PREFIX ?? `corpus-scale-${Date.now()}`;
if (!/^corpus-scale-[0-9]+$/.test(prefix)) throw new Error('Invalid isolated fixture prefix');
const count = 100000;
try {
  if (!process.env.CORPUS_SCALE_PREFIX) {
  const f = await seedCorpusFixture(db, prefix);
  await db.$executeRaw(Prisma.sql`
    INSERT INTO "Environment"
    SELECT (jsonb_populate_record(NULL::"Environment", to_jsonb(e) || jsonb_build_object(
      'id', ${prefix} || '-env-' || i, 'fingerprint', md5(${prefix} || '-env-' || i),
      'cpuModel', 'Scale CPU ' || (i % 50), 'gpuModel', CASE WHEN i % 3 = 0 THEN NULL ELSE 'Scale GPU ' || (i % 10) END))).*
    FROM "Environment" e CROSS JOIN generate_series(0, 249) i WHERE e.id = ${f.environment.id}`);
  await db.$executeRaw(Prisma.sql`
    INSERT INTO "BenchmarkRun"
    SELECT (jsonb_populate_record(NULL::"BenchmarkRun", to_jsonb(r) || jsonb_build_object(
      'id', ${prefix} || '-bulk-run-' || i, 'payloadHash', md5(${prefix} || '-bulk-run-' || i),
      'environmentId', ${prefix} || '-env-' || (i % 250), 'recipeId', ${prefix} || '-recipe-' || ((i / 250) % 4),
      'workloadId', ${prefix} || '-workload-' || ((i / 1000) % 7),
      'createdAt', '2026-01-01T00:00:00Z'::timestamptz + i * interval '1 second',
      'physicalSourceId', 'source-' || (i % 1000), 'campaignId', 'campaign-' || i,
      'status', CASE WHEN i % 5 = 0 THEN 'SUSPECT' ELSE 'ACCEPTED' END,
      'encodeFps', 24.0 + (i % 1000) / 10.0, 'repetitionGroupId', 'repetition-' || (i / 3)))).*
    FROM "BenchmarkRun" r CROSS JOIN generate_series(1, ${count}::int) i WHERE r.id = ${prefix + '-run-1'}`);
  await db.$executeRaw(Prisma.sql`
    INSERT INTO "Artifact"
    SELECT (jsonb_populate_record(NULL::"Artifact", to_jsonb(a) || jsonb_build_object(
      'id', ${prefix} || '-bulk-artifact-' || i, 'benchmarkRunId', ${prefix} || '-bulk-run-' || i,
      'sha256', md5(${prefix} || '-bytes-' || i), 'byteSize', 1000000 + (i % 10000) * 100,
      'storageState', CASE WHEN i % 5 = 0 THEN 'VERIFIED' ELSE 'RETAINED' END))).*
    FROM "Artifact" a CROSS JOIN generate_series(1, ${count}::int) i WHERE a.id = ${prefix + '-artifact-1'}`);
  await db.$executeRaw(Prisma.sql`
    INSERT INTO "QualityAnalysis"
    SELECT (jsonb_populate_record(NULL::"QualityAnalysis", to_jsonb(a) || jsonb_build_object(
      'id', ${prefix} || '-bulk-analysis-' || i, 'benchmarkRunId', ${prefix} || '-bulk-run-' || i,
      'artifactId', ${prefix} || '-bulk-artifact-' || i, 'vmafMean', 70.0 + (i % 300) / 10.0,
      'vmafP5', 60.0 + (i % 300) / 10.0, 'videoBitrateBps', 1000000 + i * 100,
      'status', CASE WHEN i % 5 = 0 THEN 'SUSPECT' ELSE 'COMPLETE' END))).*
    FROM "QualityAnalysis" a CROSS JOIN generate_series(1, ${count}::int) i WHERE a.id = ${prefix + '-analysis-1'}`);
  await db.$executeRawUnsafe('ANALYZE');
  }
  const backfillStarted = performance.now();
  let backfilledIdentities = 0;
  for (;;) {
    const refreshed = await refreshPublicCorpusGroups(db, 256);
    backfilledIdentities += refreshed;
    if (!refreshed) break;
  }
  const backfillMs = performance.now() - backfillStarted;
  await mkdir(output, { recursive: true });
  const sql = buildPublicCorpusPageSql({ sort: 'fps', dir: 'desc', search: prefix }, 25, 0, []);
  const plan = await db.$transaction(async tx => {
    await tx.$executeRaw`SELECT set_config('jit', 'off', true), set_config('max_parallel_workers_per_gather', '0', true)`;
    return tx.$queryRaw(Prisma.sql`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ${sql}`);
  }, { timeout: 30000 });
  await writeFile(`${output}/query-plan.json`, JSON.stringify(plan, null, 2));
  const first = await loadPublicCorpusPage(db, { search: prefix, sort: 'fps' }, { take: 25, publicReferenceContextVersions: new Set() });
  const samples = [];
  let peakRss = process.memoryUsage().rss;
  const started = performance.now();
  const monitor = setInterval(() => { peakRss = Math.max(peakRss, process.memoryUsage().rss); }, 20);
  const failures = [];
  const seenGroups = new Set();
  await Promise.all(Array.from({ length: 25 }, async (_, browser) => {
    for (let request = 0; request < 4; request++) {
      const start = performance.now();
      try {
        const page = await loadPublicCorpusPage(db, { search: prefix, sort: ['fps', 'vmaf', 'samples', 'createdAt'][request], dir: browser % 2 ? 'asc' : 'desc' },
          { take: 25, skip: browser * 25, publicReferenceContextVersions: new Set() });
        if (page.rows.length !== 25 || page.totalCount !== first.totalCount || new Set(page.rows.map(r => r.id)).size !== 25) throw new Error('Missing, duplicate or inconsistent page');
        page.rows.forEach(r => seenGroups.add(r.id));
        samples.push(performance.now() - start);
      } catch (error) { failures.push(String(error)); }
    }
  }));
  clearInterval(monitor);
  samples.sort((a, b) => a - b);
  const report = { schema: 'encodingdb-isolated-corpus-scale/v1', sourceSha: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
    sourceDirty: execFileSync('git', ['status', '--porcelain', '--untracked-files=no'], { encoding: 'utf8' }).trim().length > 0, fixtureOnly: true, backfillMs, backfilledIdentities, prefix, metadataRuns: count + 20, groups: first.totalCount, concurrentBrowsers: 25,
    predeclaredP95TargetMs: 1000, requests: samples.length + failures.length, successes: samples.length, failures, elapsedMs: performance.now() - started,
    p50Ms: samples[Math.floor(samples.length * .5)], p95Ms: samples[Math.floor(samples.length * .95)], maxMs: samples.at(-1),
    peakNodeRssBytes: peakRss, uniqueGroupsInspected: seenGroups.size,
    limits: { pageRows: 100, statementTimeoutMs: 15000, transactionTimeoutMs: 30000 },
    limitations: ['Metadata-only isolated PostgreSQL fixture; no media throughput, human review or production readiness claim.', 'Actual HTTP and sustained ingestion/restart tests are separate operations gates.'] };
  await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (failures.length || report.p95Ms > 1000) process.exitCode = 1;
} finally { await db.$disconnect(); }
