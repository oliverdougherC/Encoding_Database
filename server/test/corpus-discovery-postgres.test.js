import test from 'node:test';
import assert from 'node:assert/strict';
import { PrismaClient } from '@prisma/client';
import { loadCorpusDiscovery } from '../dist/v7/corpusDiscovery.js';
import { refreshPublicCorpusGroups, loadPublicCorpusPage } from '../dist/v7/corpusQuery.js';
import { assertIsolatedCorpusDatabase, seedCorpusFixture, removeCorpusFixture } from './fixtures/corpus-postgres.mjs';

const url = process.env.CORPUS_TEST_DATABASE_URL;
test('PostgreSQL discovery counts unscored accepted and suspect evidence once across contexts and exact scopes', { skip: !url }, async () => {
  assertIsolatedCorpusDatabase(url);
  const db = new PrismaClient({ datasources: { db: { url } } });
  const prefix = `corpus-test-discovery-final1080p-${Date.now()}`;
  try {
    const f = await seedCorpusFixture(db, prefix);
    while (await refreshPublicCorpusGroups(db)) { /* drain only isolated fixture dirtiness */ }
    const hardware = await loadCorpusDiscovery(db, 'hardware', {workloadId:prefix});
    assert.equal(hardware.items.length, 1);
    assert.equal(hardware.items[0].acceptedCount, 12);
    assert.equal(hardware.items[0].suspectCount, 8);
    assert.equal(hardware.items[0].configurationCount, 4);
    assert.equal(hardware.items[0].encoderCount, 4);
    assert.equal(hardware.truncated, false);
    const encoders = await loadCorpusDiscovery(db, 'encoders', {workloadId:prefix});
    const suspect = encoders.items.find(row => row.encoderName === 'libsvtav1');
    assert.equal(suspect.acceptedCount, 0); assert.equal(suspect.suspectCount, 5);
    assert.equal((await loadCorpusDiscovery(db, 'encoders', {workloadId:prefix, encoderType:'hardware'})).items.length, 1);
    assert.equal((await loadCorpusDiscovery(db, 'encoders', {workloadId:prefix, encoderType:'software'})).items.length, 3);
    for (const name of ['nvenc', 'videotoolbox', 'qsv', 'vaapi', 'amf', 'v4l2m2m', 'omx', 'h264_nvenc', 'hevc_videotoolbox']) {
      await db.recipe.update({where:{id:f.recipes[1].id},data:{encoderImplementation:name}});
      while (await refreshPublicCorpusGroups(db)) {}
      const coverage = await loadCorpusDiscovery(db, 'encoders', {workloadId:prefix,encoderType:'hardware'});
      assert.deepEqual(coverage.items.map(row => row.encoderName), [name]);
      const hardwarePage = await loadPublicCorpusPage(db, {search:prefix,encoderType:'hardware'}, {take:100,publicReferenceContextVersions:new Set()});
      const softwarePage = await loadPublicCorpusPage(db, {search:prefix,encoderType:'software'}, {take:100,publicReferenceContextVersions:new Set()});
      assert.equal(hardwarePage.totalCount, 1, name);
      assert.equal(hardwarePage.rows[0].encoderName, name);
      assert.equal(softwarePage.totalCount, 3, name);
      assert.ok(!softwarePage.rows.some(row => row.encoderName === name));
    }

    assert.equal((await loadCorpusDiscovery(db, 'hardware', {workloadId:prefix, environmentId:'absent'})).items.length, 0);
    assert.equal((await loadCorpusDiscovery(db, 'hardware', {workloadId:prefix, environmentFingerprint:f.environment.fingerprint})).items.length, 1);
    assert.equal((await loadCorpusDiscovery(db, 'hardware', {workloadId:prefix, cpu:"' OR 1=1 --"})).items.length, 0);
    assert.equal((await loadCorpusDiscovery(db, 'encoders', {workloadId:prefix, preset:'slow'})).items.length, 1);
    for (let i=0;i<2;i++) {
      const context = await db.scoreContext.create({data:{benchmarkProtocolId:f.protocol.id, formulaVersion:'7.0',contextVersion:`${prefix}-${i}`,workloadId:prefix,qualityModelId:'fixture-model',workloadReferenceBitrateBps:1000,transformConstants:{}}});
      await db.derivedResult.create({data:{kind:'WORKLOAD',scopeKey:prefix,benchmarkProtocolId:f.protocol.id,workloadId:prefix,recipeId:f.recipes[0].id,environmentId:f.environment.id,scoreContextId:context.id,aggregatorVersion:'fixture',acceptedRunCount:999,repetitionCount:999,plTotal:99,evidenceTier:'HIGH',evidenceSummary:{},confidenceIntervals:{},dispersion:{},recomputationSpec:{}}});
    }
    while (await refreshPublicCorpusGroups(db)) {}
    assert.deepEqual(await loadCorpusDiscovery(db, 'hardware', {workloadId:prefix}), hardware, 'score contexts cannot duplicate observed evidence');
    await db.benchmarkRun.update({where:{id:`${prefix}-run-1`},data:{status:'REJECTED'}});
    await assert.rejects(loadCorpusDiscovery(db, 'hardware', {workloadId:prefix}), {code:'CORPUS_REBUILD_PENDING'});
    while (await refreshPublicCorpusGroups(db)) {}
    assert.equal((await loadCorpusDiscovery(db, 'hardware', {workloadId:prefix})).items[0].acceptedCount, 11);
    await db.benchmarkProtocol.update({where:{id:f.protocol.id},data:{state:'RETIRED'}});
    while (await refreshPublicCorpusGroups(db)) {}
    assert.equal((await loadCorpusDiscovery(db, 'hardware', {workloadId:prefix})).items.length, 0);
  } finally { await removeCorpusFixture(db, prefix); await db.$disconnect(); }
});
