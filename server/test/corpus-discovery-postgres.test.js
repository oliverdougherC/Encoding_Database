import test from 'node:test';
import { randomUUID } from 'node:crypto';
import assert from 'node:assert/strict';
import { PrismaClient } from '@prisma/client';
import { loadCorpusDiscovery } from '../dist/v7/corpusDiscovery.js';
import { refreshPublicCorpusGroups, loadPublicCorpusPage } from '../dist/v7/corpusQuery.js';
import { assertIsolatedCorpusDatabase, seedCorpusFixture, removeCorpusFixture, readSettledCorpus } from './fixtures/corpus-postgres.mjs';

const url = process.env.CORPUS_TEST_DATABASE_URL;
test('PostgreSQL discovery counts unscored accepted and suspect evidence once across contexts and exact scopes', { skip: !url }, async () => {
  assertIsolatedCorpusDatabase(url);
  const db = new PrismaClient({ datasources: { db: { url } } });
  const prefix = `corpus-test-discovery-final1080p-${randomUUID()}`;
  const coverage = (kind, filters) => readSettledCorpus(async () => {
    await refreshPublicCorpusGroups(db);
    return loadCorpusDiscovery(db, kind, filters);
  });
  const readPage = (...args) => readSettledCorpus(() => loadPublicCorpusPage(...args));

  try {
    const f = await seedCorpusFixture(db, prefix);
    while (await refreshPublicCorpusGroups(db)) { /* drain only isolated fixture dirtiness */ }
    const hardware = await coverage('hardware', {workloadId:prefix});
    assert.equal(hardware.items.length, 1);
    assert.equal(hardware.items[0].acceptedCount, 12);
    assert.equal(hardware.items[0].suspectCount, 8);
    assert.equal(hardware.items[0].configurationCount, 4);
    assert.equal(hardware.items[0].encoderCount, 4);
    assert.equal(hardware.truncated, false);
    const encoders = await coverage('encoders', {workloadId:prefix});
    const suspect = encoders.items.find(row => row.encoderName === 'libsvtav1');
    assert.equal(suspect.acceptedCount, 0); assert.equal(suspect.suspectCount, 5);
    assert.equal((await coverage('encoders', {workloadId:prefix, encoderType:'hardware'})).items.length, 1);
    assert.equal((await coverage('encoders', {workloadId:prefix, encoderType:'software'})).items.length, 3);
    for (const name of ['nvenc', 'videotoolbox', 'qsv', 'vaapi', 'amf', 'v4l2m2m', 'omx', 'h264_nvenc', 'hevc_videotoolbox']) {
      await db.recipe.update({where:{id:f.recipes[1].id},data:{encoderImplementation:name}});
      while (await refreshPublicCorpusGroups(db)) {}
      const hardwareCoverage = await coverage('encoders', {workloadId:prefix,encoderType:'hardware'});
      assert.deepEqual(hardwareCoverage.items.map(row => row.encoderName), [name]);
      const hardwarePage = await readPage(db, {search:prefix,encoderType:'hardware'}, {take:100,publicReferenceContextVersions:new Set()});
      const softwarePage = await readPage(db, {search:prefix,encoderType:'software'}, {take:100,publicReferenceContextVersions:new Set()});
      assert.equal(hardwarePage.totalCount, 1, name);
      assert.equal(hardwarePage.rows[0].encoderName, name);
      assert.equal(softwarePage.totalCount, 3, name);
      assert.ok(!softwarePage.rows.some(row => row.encoderName === name));
    }

    assert.equal((await coverage('hardware', {workloadId:prefix, environmentId:'absent'})).items.length, 0);
    assert.equal((await coverage('hardware', {workloadId:prefix, environmentFingerprint:f.environment.fingerprint})).items.length, 1);
    assert.equal((await coverage('hardware', {workloadId:prefix, cpu:"' OR 1=1 --"})).items.length, 0);
    assert.equal((await coverage('encoders', {workloadId:prefix, preset:'slow'})).items.length, 1);
    for (let i=0;i<2;i++) {
      const context = await db.scoreContext.create({data:{benchmarkProtocolId:f.protocol.id, formulaVersion:'7.0',contextVersion:`${prefix}-${i}`,workloadId:prefix,qualityModelId:'fixture-model',workloadReferenceBitrateBps:1000,transformConstants:{}}});
      await db.derivedResult.create({data:{kind:'WORKLOAD',scopeKey:prefix,benchmarkProtocolId:f.protocol.id,workloadId:prefix,recipeId:f.recipes[0].id,environmentId:f.environment.id,scoreContextId:context.id,aggregatorVersion:'fixture',acceptedRunCount:999,repetitionCount:999,plTotal:99,evidenceTier:'HIGH',evidenceSummary:{},confidenceIntervals:{},dispersion:{},recomputationSpec:{}}});
    }
    while (await refreshPublicCorpusGroups(db)) {}
    assert.deepEqual(await coverage('hardware', {workloadId:prefix}), hardware, 'score contexts cannot duplicate observed evidence');
    await db.$transaction(async tx => {
      await tx.benchmarkRun.update({where:{id:`${prefix}-run-1`},data:{status:'REJECTED'}});
      // Own uncommitted dirty row cannot be consumed by a concurrent fixture refresh.
      await assert.rejects(loadCorpusDiscovery({ $transaction: fn => fn(tx) }, 'hardware', {workloadId:prefix}), {code:'CORPUS_REBUILD_PENDING'});
    });
    while (await refreshPublicCorpusGroups(db)) {}
    assert.equal((await coverage('hardware', {workloadId:prefix})).items[0].acceptedCount, 11);
    // A similarly prefixed concurrent fixture must survive this fixture's retirement.
    await seedCorpusFixture(db, `${prefix}-sibling`);
    await removeCorpusFixture(db, prefix);
    while (await refreshPublicCorpusGroups(db)) {}
    assert.equal((await coverage('hardware', {workloadId:prefix})).items.length, 0);
    assert.equal((await coverage('hardware', {workloadId:`${prefix}-sibling`})).items[0].acceptedCount, 12);
  } finally { await removeCorpusFixture(db, prefix); await removeCorpusFixture(db, `${prefix}-sibling`); await db.$disconnect(); }
});
