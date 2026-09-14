import assert from 'node:assert/strict';
import test from 'node:test';
import { PrismaClient } from '@prisma/client';
import { buildPublicCorpusRows, buildPublicCorpusWhere, sortPublicCorpusRows, buildPublicCorpusOrderBy } from '../dist/v7/corpus.js';
import { isPublicCorpusBusyError, loadPublicCorpusPage, publicCorpusReadiness } from '../dist/v7/corpusQuery.js';
import { assertIsolatedCorpusDatabase, seedCorpusFixture, removeCorpusFixture } from './fixtures/corpus-postgres.mjs';

test('bounded query exhaustion reports recoverable capacity only', () => {
  assert.equal(isPublicCorpusBusyError({ code: 'P2010', meta: { code: '57014' } }), true);
  assert.equal(isPublicCorpusBusyError({ code: 'P2024' }), true);
  assert.equal(isPublicCorpusBusyError({ code: 'P2010', meta: { code: '42P01' } }), false);
});

const url = process.env.CORPUS_TEST_DATABASE_URL;
test('PostgreSQL corpus matches complete-history reference, bounds pages, and follows review/reanalysis', { skip: !url }, async () => {
  assertIsolatedCorpusDatabase(url);
  const db = new PrismaClient({ datasources: { db: { url } } });
  try {
    await removeCorpusFixture(db);
    const fixture = await seedCorpusFixture(db, `corpus-test-${Date.now()}`);
    const queries = [{}, { encoderType: 'hardware' }, { encoderType: 'software' }, { preset: 'slow' },
      { search: 'libx264' }, { cpu: '100%_literal' }, { gpu: 'not present' }, { search: "' OR 1=1 --" }];
    for (const query of queries) {
      const runs = await db.benchmarkRun.findMany({ where: { AND: [buildPublicCorpusWhere(query), { id: { startsWith: fixture.prefix } }] },
        include: { benchmarkProtocol: true, recipe: true, environment: true, artifacts: true, qualityAnalyses: true } });
      const reference = buildPublicCorpusRows({ runs, publicReferenceContextVersions: new Set() });
      for (const sort of ['fps', 'vmaf', 'fileSizeBytes', 'videoBitrateBps', 'samples', 'cpuModel', 'gpuModel', 'codec', 'preset', 'createdAt']) {
        for (const dir of ['asc', 'desc']) {
          const expected = sortPublicCorpusRows(reference, buildPublicCorpusOrderBy(sort, dir));
          const actual = await loadPublicCorpusPage(db, { ...query, sort, dir, search: query.search ?? fixture.prefix }, { take: 2, skip: 1, publicReferenceContextVersions: new Set() });
          assert.equal(actual.totalCount, expected.length, JSON.stringify({ query, sort, dir }));
          assert.deepEqual(actual.rows, expected.slice(1, 3), JSON.stringify({ query, sort, dir }));
        }
      }
    }
    const all = await loadPublicCorpusPage(db, { search: fixture.prefix }, { take: 100, publicReferenceContextVersions: new Set() });
    const detail = await loadPublicCorpusPage(db, {}, { take: 1, id: all.rows[0].id, publicReferenceContextVersions: new Set() });
    assert.deepEqual(detail.rows, [all.rows[0]]);
    assert.deepEqual((await loadPublicCorpusPage(db, { search: fixture.prefix }, { take: 5, skip: 100, publicReferenceContextVersions: new Set() })), { rows: [], totalCount: 4 });
    // A public score may be shown only for the current exact accepted member set.
    const context = await db.scoreContext.create({ data: {
      id: `${fixture.prefix}-context`, benchmarkProtocolId: fixture.protocol.id, formulaVersion: '7.0', contextVersion: `${fixture.prefix}-production`,
      workloadId: fixture.prefix, qualityModelId: 'fixture-model', workloadReferenceBitrateBps: 1000, transformConstants: {},
    } });
    const accepted = await db.benchmarkRun.findMany({ where: { benchmarkProtocolId: fixture.protocol.id, recipeId: fixture.recipes[1].id, status: 'ACCEPTED' }, include: { qualityAnalyses: true } });
    const derived = await db.derivedResult.create({ data: {
      id: `${fixture.prefix}-derived`, kind: 'WORKLOAD', scopeKey: fixture.prefix, benchmarkProtocolId: fixture.protocol.id,
      workloadId: fixture.prefix, recipeId: fixture.recipes[1].id, environmentId: fixture.environment.id, scoreContextId: context.id,
      aggregatorVersion: 'fixture-policy', acceptedRunCount: accepted.length, repetitionCount: accepted.length,
      plTotal: 75, evidenceTier: 'HIGH', evidenceSummary: { eligibleForDefaultRecommendation: true }, confidenceIntervals: {}, dispersion: {}, recomputationSpec: {},
      members: { create: accepted.map(run => ({ benchmarkRunId: run.id, qualityAnalysisId: run.qualityAnalyses[0].id })) },
    } });
    const scoredId = `${fixture.protocol.id}::${fixture.prefix}::${fixture.recipes[1].id}::${fixture.environment.id}::fixture-model`;
    const readScore = async () => (await loadPublicCorpusPage(db, {}, { take: 1, id: scoredId, publicReferenceContextVersions: new Set([context.contextVersion]) })).rows[0];
    assert.equal((await readScore()).pl.total, 75);
    assert.equal((await readScore()).status.evidenceTier, 'HIGH');
    await db.derivedResult.update({ where: { id: derived.id }, data: { invalidatedAt: new Date(), invalidationReason: 'isolated regression' } });
    assert.equal((await readScore()).pl.total, null);
    await db.derivedResult.update({ where: { id: derived.id }, data: { invalidatedAt: null } });
    await db.qualityAnalysis.update({ where: { id: accepted[0].qualityAnalyses[0].id }, data: { status: 'PENDING' } });
    assert.equal((await readScore()).pl.total, null, 'stale selected analysis cannot preserve an old public score');

    const beforeConcurrentChange = await readScore();
    let changedDuringHydration = false;
    const concurrentClient = db.$extends({ query: { benchmarkRun: { async findMany({ args, query }) {
      if (!changedDuringHydration) {
        changedDuringHydration = true;
        await db.benchmarkRun.update({ where: { id: accepted[1].id }, data: { status: 'REJECTED' } });
      }
      return query(args);
    } } } });
    const during = await loadPublicCorpusPage(concurrentClient, {}, { take: 1, id: scoredId, publicReferenceContextVersions: new Set([context.contextVersion]) });
    assert.equal(changedDuringHydration, true);
    assert.deepEqual(during.rows, [beforeConcurrentChange], 'page and hydration must share the pre-change snapshot');
    assert.equal((await readScore()).sampleCounts.accepted, beforeConcurrentChange.sampleCounts.accepted - 1);

    const target = await db.qualityAnalysis.findUniqueOrThrow({ where: { id: `${fixture.prefix}-analysis-3` }, include: { artifact: true } });
    const review = decision => db.evidenceReview.create({ data: {
      analysisId: target.id, benchmarkRunId: target.benchmarkRunId, artifactId: target.artifact.id,
      artifactSha256: target.artifact.sha256, metricModelId: target.metricModelId, analysisWorkerVersion: target.analysisWorkerVersion,
      reviewerId: 'isolated-test-reviewer', rationale: 'Automated lifecycle fixture; not human approval', evidenceLinks: [], decision,
    } });
    const rowId = `${fixture.protocol.id}::${fixture.prefix}::${fixture.recipes[3].id}::${fixture.environment.id}::fixture-model`;
    const read = async () => (await loadPublicCorpusPage(db, {}, { take: 1, id: rowId, publicReferenceContextVersions: new Set() })).rows[0];
    assert.equal((await read()).sampleCounts.accepted, 0);
    await review('EXPECTED');
    assert.equal((await read()).sampleCounts.accepted, 1);
    assert.equal((await read()).fps, 31);
    await review('INVESTIGATE');
    assert.equal((await read()).sampleCounts.suspect, 4);
    await review('REVOKE');
    assert.equal((await read()).sampleCounts.suspect, 5);
    await review('REJECT');
    assert.equal((await read()).sampleCounts.suspect, 4);
    await review('REVOKE');
    assert.equal((await read()).sampleCounts.suspect, 5);
    await db.qualityAnalysis.update({ where: { id: target.id }, data: { status: 'PENDING' } });
    assert.equal((await publicCorpusReadiness(db)).ready, false, 'source mutation durably queues its exact identity');
    const restarted = new PrismaClient({ datasources: { db: { url } } });
    try {
      const recovered = await loadPublicCorpusPage(restarted, {}, { take: 1, id: rowId, publicReferenceContextVersions: new Set() });
      assert.equal(recovered.rows[0].sampleCounts.suspect, 4);
      assert.equal((await publicCorpusReadiness(restarted)).ready, true);
    } finally { await restarted.$disconnect(); }

    assert.equal((await read()).sampleCounts.suspect, 4);
  } finally {
    await removeCorpusFixture(db);
    await db.$disconnect();
  }
});
