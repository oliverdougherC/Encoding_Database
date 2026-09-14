#!/usr/bin/env node
// Controlled synthetic metadata arrivals; never a client/media certification.
import { PrismaClient, Prisma } from '@prisma/client';
import { mkdir, appendFile, writeFile } from 'node:fs/promises';
import { performance } from 'node:perf_hooks';
import { execFileSync } from 'node:child_process';
import { loadPublicCorpusPage } from '../dist/v7/corpusQuery.js';
import { assertIsolatedCorpusDatabase } from '../test/fixtures/corpus-postgres.mjs';
const executionSourceSha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
const url = process.env.CORPUS_TEST_DATABASE_URL;
assertIsolatedCorpusDatabase(url);
const prefix = process.env.CORPUS_SCALE_PREFIX;
if (!/^corpus-scale-[0-9]+$/.test(prefix ?? '')) throw new Error('Existing isolated CORPUS_SCALE_PREFIX required');
const seconds = Number(process.argv[2] ?? 600);
if (!Number.isInteger(seconds) || seconds < 1 || seconds > 3600) throw new Error('Duration must be 1..3600 seconds');
const output = process.argv[3] ?? '.test-reports/corpus-arrivals';
const db = new PrismaClient({ datasources: { db: { url } } });
const campaign = `${prefix}-arrival-${Date.now()}`;
const started = performance.now();
let count = 0;
let stopping = false;
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => { stopping = true; });
const latencies = [];
await mkdir(output, { recursive: true });
try {
  const template = await db.benchmarkRun.findUniqueOrThrow({ where: { id: `${prefix}-run-1` }, include: { qualityAnalyses: true } });
  const groupId = [template.benchmarkProtocolId, template.workloadId, template.recipeId, template.environmentId, template.qualityAnalyses[0].metricModelId].join('::');
  const beforeRow = (await loadPublicCorpusPage(db, {}, { id: groupId, take: 1, publicReferenceContextVersions: new Set() })).rows[0];
  while (!stopping && performance.now() - started < seconds * 1000) {
    const before = performance.now();
    const id = `${campaign}-${count}`;
    await db.$transaction(async tx => {
      await tx.$executeRaw(Prisma.sql`
        INSERT INTO "BenchmarkRun"
        SELECT (jsonb_populate_record(NULL::"BenchmarkRun", to_jsonb(r) || jsonb_build_object(
          'id', ${id}, 'payloadHash', encode(sha256(convert_to(${id}, 'UTF8')), 'hex'),
          'campaignId', ${campaign}, 'repetitionGroupId', ${id}, 'createdAt', clock_timestamp(), 'updatedAt', clock_timestamp()))).*
        FROM "BenchmarkRun" r WHERE r.id = ${prefix + '-run-1'}`);
      await tx.$executeRaw(Prisma.sql`
        INSERT INTO "Artifact"
        SELECT (jsonb_populate_record(NULL::"Artifact", to_jsonb(a) || jsonb_build_object(
          'id', ${id + '-artifact'}, 'benchmarkRunId', ${id}, 'sha256', encode(sha256(convert_to(${id + '-synthetic-object'}, 'UTF8')), 'hex'),
          'createdAt', clock_timestamp(), 'updatedAt', clock_timestamp(), 'uploadedAt', clock_timestamp()))).*
        FROM "Artifact" a WHERE a.id = ${prefix + '-artifact-1'}`);
      await tx.$executeRaw(Prisma.sql`
        INSERT INTO "QualityAnalysis"
        SELECT (jsonb_populate_record(NULL::"QualityAnalysis", to_jsonb(a) || jsonb_build_object(
          'id', ${id + '-analysis'}, 'benchmarkRunId', ${id}, 'artifactId', ${id + '-artifact'},
          'createdAt', clock_timestamp(), 'updatedAt', clock_timestamp(), 'completedAt', clock_timestamp()))).*
        FROM "QualityAnalysis" a WHERE a.id = ${prefix + '-analysis-1'}`);
    });
    count++;
    latencies.push(performance.now() - before);
    await appendFile(`${output}/arrivals.jsonl`, `${JSON.stringify({ runId: id, artifactId: `${id}-artifact`, analysisId: `${id}-analysis` })}\n`);
    await new Promise(resolve => setTimeout(resolve, Math.max(0, 1000 - (performance.now() - before))));
  }
  const verified = await db.benchmarkRun.count({ where: { campaignId: campaign, artifacts: { some: { role: 'ENCODED' } }, qualityAnalyses: { some: { status: 'COMPLETE' } } } });
  if (verified !== count) throw new Error(`Arrival identity mismatch: ${verified}/${count}`);
  latencies.sort((a, b) => a - b);
  const afterRow = (await loadPublicCorpusPage(db, {}, { id: groupId, take: 1, publicReferenceContextVersions: new Set() })).rows[0];
  if (afterRow.sampleCounts.accepted !== beforeRow.sampleCounts.accepted + count || afterRow.sampleCounts.independentSources !== beforeRow.sampleCounts.independentSources) {
    throw new Error('Arrival public membership or independent-source accounting mismatch');
  }
  const report = { groupId, acceptedBefore: beforeRow.sampleCounts.accepted, acceptedAfter: afterRow.sampleCounts.accepted,
    independentSourcesBefore: beforeRow.sampleCounts.independentSources, independentSourcesAfter: afterRow.sampleCounts.independentSources, schema: 'encodingdb-isolated-metadata-arrivals/v1', fixtureOnly: true, sourceSha: executionSourceSha,
    campaign, requestedDurationSeconds: seconds, elapsedMs: performance.now() - started, stoppedEarly: stopping,
    targetArrivalsPerSecond: 1, createdRuns: count, verifiedRunArtifactAnalysisChains: verified,
    writeP95Ms: latencies[Math.floor(latencies.length * .95)],
    limitations: ['Synthetic database metadata arrivals exercise summary invalidation under browsing; no encoded media, client upload, worker or calibration proof.'] };
  await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally { await db.$disconnect(); }
