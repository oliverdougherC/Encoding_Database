import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import express from 'express';
import routes from '../dist/routes.js';
import { prisma } from '../dist/db.js';

process.env.DATABASE_URL ||= 'postgresql://app:app@localhost:5432/benchmarks?schema=public';
after(() => prisma.$disconnect());

async function withServer(fn) {
  const app = express(); app.use(routes);
  const server = await new Promise(resolve => { const s = app.listen(0, '127.0.0.1', () => resolve(s)); });
  try { await fn(`http://127.0.0.1:${server.address().port}`); }
  finally { await new Promise(resolve => server.close(resolve)); }
}

test('coverage directory exposes accepted unscored final1080p corpus without a selected environment', async t => {
  let transactionUsed = false;
  const originalFind = prisma.derivedResult.findMany;
  const originalTransaction = prisma.$transaction;
  let derivedCalls = 0;
  t.after(() => { prisma.derivedResult.findMany = originalFind; prisma.$transaction = originalTransaction; });
  prisma.derivedResult.findMany = async () => { derivedCalls++; return []; };
  prisma.$transaction = async fn => {
    transactionUsed = true;
    return fn({ $executeRaw: async () => 0, $queryRaw: async sql => {
      if ((sql.sql ?? sql.join('')).includes('PublicCorpusDirtyGroup')) return [{ pending: false }];
      return [{ cpuModel: 'Fixture CPU', gpuModel: '', encoderCount: 2n, codecFamilies: ['h264'], acceptedCount: 7n, suspectCount: 2n, configurationCount: 4n }];
    } });
  };
  await withServer(async base => {
    const res = await fetch(`${base}/analytics/hardware?mode=coverage`);
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.kind, 'hardware');
    assert.equal(body.items[0].acceptedCount, 7);
    assert.equal(body.items[0].suspectCount, 2);
    assert.equal(body.items[0].configurationCount, 4);
    assert.deepEqual(body.items[0].browseFilters, { cpu: 'Fixture CPU' });
    assert.equal(body.items[0].score, undefined);
    assert.equal(body.items[0].avgFps, undefined);
    assert.equal(transactionUsed, true);
    assert.equal(derivedCalls, 0);
  });
});

test('coverage rejects malformed/unsupported filters before querying and leaves legacy routes unchanged', async t => {
  const originalFind = prisma.derivedResult.findMany;
  const originalTransaction = prisma.$transaction;
  t.after(() => { prisma.derivedResult.findMany = originalFind; prisma.$transaction = originalTransaction; });
  let derivedCalls = 0;
  prisma.derivedResult.findMany = async () => { derivedCalls++; return []; };
  prisma.$transaction = async () => { throw new Error('Malformed request reached database'); };
  await withServer(async base => {
    for (const path of ['mode=coverage&cpu[]=a', 'mode=coverage&minSamples=1', 'mode=coverage&encoderType=alien', 'mode=coverage&mode=coverage', 'mode=unknown', 'mode=coverage&cpu='+ 'x'.repeat(201)]) {
      assert.equal((await fetch(`${base}/analytics/encoders?${path}`)).status, 400, path);
    }
    for (const name of ['hardware', 'encoders']) {
      const response = await fetch(`${base}/analytics/${name}`);
      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), []);
    }
    assert.equal(derivedCalls, 2);
  });
});

test('coverage separates suspect-only observations, preserves bounded completeness and rejects stale read model', async t => {
  const original = prisma.$transaction;
  t.after(() => { prisma.$transaction = original; });
  let pending = false;
  prisma.$transaction = async fn => fn({ $executeRaw: async () => 0, $queryRaw: async sql => {
    if ((sql.sql ?? sql.join('')).includes('PublicCorpusDirtyGroup')) return [{ pending }];
    return Array.from({length:501}, (_,i) => ({ encoderName: `encoder-${i}`, codecFamily: 'h264', acceptedCount: 0n, suspectCount: 2n, configurationCount: 1n }));
  } });
  await withServer(async base => {
    const response = await fetch(`${base}/analytics/encoders?mode=coverage`);
    const body = await response.json();
    assert.equal(body.kind, 'encoders'); assert.equal(body.items.length, 500); assert.equal(body.truncated, true);
    assert.equal(body.items[0].acceptedCount, 0); assert.equal(body.items[0].suspectCount, 2);
    assert.deepEqual(body.items[0].browseFilters, {search:'encoder-0'});
    assert.equal(body.items[0].plScore, undefined);
    pending = true;
    const busy = await fetch(`${base}/analytics/encoders?mode=coverage`);
    assert.equal(busy.status, 503); assert.equal(busy.headers.get('retry-after'), '2');
  });
});

test('coverage SQL parameters scopes safely without score-context duplication or implicit mixed workload', async () => {
  const { buildCorpusDiscoverySql, parseDiscoveryFilters } = await import('../dist/v7/corpusDiscovery.js');
  const payload = "' OR 1=1 --";
  const sql = buildCorpusDiscoverySql('hardware', parseDiscoveryFilters({ mode:'coverage', workloadId:'film-grain-1080p24-final', environmentId:'env-1', cpu:payload, encoderType:'software' }));
  assert.ok(sql.values.includes('%'+payload+'%'));
  assert.ok(sql.values.includes('film-grain-1080p24-final'));
  assert.ok(sql.values.includes('env-1'));
  assert.ok(!sql.sql.includes(payload));
  assert.match(sql.sql, /PublicCorpusGroup/);
  assert.doesNotMatch(sql.sql, /DerivedResult|ScoreContext|mixed-1080p|acceptedRunCount/);
  assert.ok(sql.sql.indexOf('GROUP BY') < sql.sql.indexOf('LIMIT'));
  assert.equal(sql.values.at(-1), 501);
});

test('native family names and FFmpeg suffix names are hardware in both corpus query paths', async () => {
  const { buildCorpusDiscoverySql } = await import('../dist/v7/corpusDiscovery.js');
  const { buildPublicCorpusPageSql } = await import('../dist/v7/corpusQuery.js');
  const { buildPublicCorpusWhere } = await import('../dist/v7/corpus.js');
  const families = ['nvenc','videotoolbox','qsv','amf','vaapi','v4l2m2m','omx'];
  const matchers = buildPublicCorpusWhere({encoderType:'hardware'}).AND[0].OR;
  for (const family of families) {
    assert.ok(matchers.some(row => row.recipe.encoderImplementation.in?.includes(family)), `native ${family} must be hardware`);
    assert.ok(matchers.some(row => row.recipe.encoderImplementation.endsWith === '_'+family));
  }
  for (const sql of [buildCorpusDiscoverySql('encoders',{encoderType:'hardware'}),buildPublicCorpusPageSql({encoderType:'hardware'},10,0,[])]) {
    for (const family of families) assert.ok(sql.values.flat().includes(family), `SQL must match native ${family}`);
  }
});
